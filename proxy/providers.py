"""FO-008: LLM-провайдеры — цепочки фолбэка, circuit breaker, токенная экономика.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 1; наряд #68, стоп-гейт SG-F2).
Единый HTTP-клиент — requests (блокирующий код). Модуль не знает о Flask-роутах.
"""
import os
import threading
import time
import uuid
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests as http_requests

from proxy.core import (
    log,
    get_secret,
    _query,
    _log_error,
    _write_llm_trace,
    DB_PATH,
    CFG_DIR,
    DEPT_NAMES,
)

# FO-016 (#82): полный конвейер компакции — budget + prune + summarize +
# offload — в proxy/compaction.py. Импорт односторонний: compaction НЕ
# импортирует providers (разрыв цикла — summarize_fn передаётся параметром).
from proxy.compaction import (  # noqa: F401
    compact_context,
    get_context_budget,
    PROVIDER_CONTEXT_LIMITS,
    TOOL_OUTPUT_DIR,
    restore_tool_output,
    cleanup_tool_output_files,
    estimate_tokens as _estimate_tokens,
)

# ──────────────────────────── PROVIDERS ────────────────────────────
PROVIDERS = {
    "zai": {"url": "https://api.z.ai/api/paas/v4/chat/completions", "env_key": "ZAI_API_KEY", "format": "openai", "timeout": 120},
    "deepseek": {"url": "https://api.deepseek.com/v1/chat/completions", "env_key": "DEEPSEEK_API_KEY", "format": "openai", "timeout": 120},
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "env_key": "GROQ_API_KEY", "format": "openai", "timeout": 120},
    "grok": {"url": "https://api.x.ai/v1/chat/completions", "env_key": "GROK_API_KEY", "format": "openai", "timeout": 120},
    "anthropic": {"url": "https://api.anthropic.com/v1/messages", "env_key": "ANTHROPIC_API_KEY", "format": "anthropic", "timeout": 120},
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "env_key": "OPENAI_API_KEY", "format": "openai", "timeout": 120},
    "apodex": {"url": "https://api.apodex.ai/v1/chat/completions", "env_key": "APODEX_API_KEY", "format": "openai", "timeout": 300},
    "nvidia": {"url": "https://integrate.api.nvidia.com/v1/chat/completions", "env_key": "NVIDIA_API_KEY", "format": "openai", "timeout": 120},
    "cerebras": {"url": "https://api.cerebras.ai/v1/chat/completions", "env_key": "CEREBRAS_API_KEY", "format": "openai", "timeout": 120},
    "kimi": {"url": "https://api.moonshot.ai/v1/chat/completions", "env_key": "KIMI_API_KEY", "format": "openai", "timeout": 120},
}

TOKEN_COSTS = {
    "zai": {"input": 0.5, "output": 1.5}, "deepseek": {"input": 0.14, "output": 0.28},
    "groq": {"input": 0.0, "output": 0.0}, "grok": {"input": 3.0, "output": 15.0},
    "anthropic": {"input": 3.0, "output": 15.0}, "openai": {"input": 2.5, "output": 10.0},
    "apodex": {"input": 2.0, "output": 8.0},
    "nvidia": {"input": 0.0, "output": 0.0},
    "cerebras": {"input": 0.0, "output": 0.0},
    "kimi": {"input": 0.6, "output": 2.5},
}

# Some providers count prompt + max_tokens against a per-minute token budget
# and reject the request outright (Groq answers 413). Cap the ask per provider.
PROVIDER_MAX_TOKENS = {
    "groq": 2048,
}

# ──────────────────────────── CIRCUIT BREAKER ────────────────────────────
class CircuitBreaker:
    """Per-provider circuit breaker: opens after N consecutive failures,
    resets after reset_after_ms. Half-open allows 1 probe request."""
    def __init__(self, threshold=3, reset_after_ms=60000, half_open_requests=1):
        self.threshold = threshold
        self.reset_after_ms = reset_after_ms
        self.half_open_requests = half_open_requests
        self._state = {}  # provider -> {failures: int, opens_at: float, half_open_remaining: int}
        self._lock = threading.Lock()

    def _get(self, provider):
        if provider not in self._state:
            self._state[provider] = {"failures": 0, "opens_at": 0, "half_open_remaining": self.half_open_requests}
        return self._state[provider]

    def can_call(self, provider):
        with self._lock:
            s = self._get(provider)
            if s["failures"] < self.threshold:
                return True
            # Circuit is open
            if time.time() * 1000 < s["opens_at"] + self.reset_after_ms:
                return False
            # Reset period elapsed -> half-open
            s["half_open_remaining"] = self.half_open_requests
            return True

    def record_success(self, provider):
        with self._lock:
            s = self._get(provider)
            s["failures"] = 0
            s["opens_at"] = 0

    def record_failure(self, provider):
        with self._lock:
            s = self._get(provider)
            s["failures"] += 1
            if s["failures"] >= self.threshold:
                s["opens_at"] = time.time() * 1000
                log.warning(f"CircuitBreaker OPEN for {provider} ({s['failures']} consecutive failures)")

    def status(self):
        with self._lock:
            result = {}
            for p, s in self._state.items():
                if s["failures"] < self.threshold:
                    result[p] = "closed"
                elif time.time() * 1000 < s["opens_at"] + self.reset_after_ms:
                    result[p] = "open"
                else:
                    result[p] = "half-open"
            return result

_breaker = CircuitBreaker(threshold=3, reset_after_ms=60000)

# ──────────────────────────── COMBO CHAINS ────────────────────────────
# Each combo is an ordered list of (provider, [models]) tuples.
# call_llm walks the chain: for each provider, try each model until one works.
COMBO_CHAINS = {
    "fosved-free": [
        ("groq", ["openai/gpt-oss-20b"]),
        ("cerebras", ["gpt-oss-120b"]),
        ("deepseek", ["deepseek-chat"]),
    ],
    "fosved-standard": [
        ("kimi", ["kimi-k3"]),
        ("deepseek", ["deepseek-chat"]),
        ("zai", ["glm-4.6", "glm-4-plus"]),
        ("groq", ["openai/gpt-oss-20b"]),
        ("cerebras", ["gpt-oss-120b"]),
    ],
    "fosved-deep": [
        ("kimi", ["kimi-k3"]),
        ("deepseek", ["deepseek-chat"]),
        ("zai", ["glm-4.6"]),
        ("groq", ["openai/gpt-oss-20b"]),
        ("cerebras", ["gpt-oss-120b"]),
        ("anthropic", ["claude-sonnet-4-20250514"]),
    ],
    "fosved-fusion": [
        ("kimi", ["kimi-k3"]),
        ("deepseek", ["deepseek-chat"]),
        ("zai", ["glm-4.6"]),
        ("groq", ["openai/gpt-oss-20b"]),
        ("cerebras", ["gpt-oss-120b"]),
        ("anthropic", ["claude-sonnet-4-20250514"]),
    ],
}

# Map task types to combos (same logic as old TASK_COMBOS, but native)
_TASK_COMBO_MAP = {
    'status': 'fosved-free', 'help': 'fosved-free', 'rate': 'fosved-free',
    'good': 'fosved-free', 'fix': 'fosved-free', 'remember': 'fosved-free',
    'learning': 'fosved-free', 'audit': 'fosved-free', 'voice_confirm': 'fosved-free',
    'dept_standard': 'fosved-standard', 'chain': 'fosved-standard', 'debrief': 'fosved-standard',
    'osp_deep': 'fosved-deep', 'osp_full': 'fosved-deep', 'lz_deep': 'fosved-deep',
    'chain_heavy': 'fosved-deep', 'admin_analyze': 'fosved-deep',
    'osp_fusion': 'fosved-fusion', 'redteam': 'fosved-fusion', 'counter_forecast': 'fosved-fusion',
}


_FREE_DEPTS = {'yana'}


def _combo_for_task(dept, command='', depth=2):
    """Select combo based on task type, dept, and analysis depth."""
    if command in _TASK_COMBO_MAP:
        return _TASK_COMBO_MAP[command]
    if depth >= 4:
        return 'fosved-fusion'
    elif depth >= 3:
        return 'fosved-deep'
    elif dept in _FREE_DEPTS:
        return 'fosved-free'
    else:
        return 'fosved-standard'

# ──────────────────────────── TOKEN COMPRESSION ────────────────────────────
_COMPRESSION_MAX_TOKENS = 64000  # ~128K chars (conservative estimate: 1 token ~ 2 chars for Russian)
_COMPRESSION_KEEP_SYSTEM = True


def _compaction_summarize(summary_prompt):
    """Дешёвая модель для summarize-компакции (race-пул: groq → cerebras).
    Передаётся в compact_context как summarize_fn (разрыв цикла импортов)."""
    try:
        res = _call_single_provider("groq", "openai/gpt-oss-20b", summary_prompt,
                                    dept="system", max_tokens=1024, is_internal=True)
        if res and res.get("reply"):
            return res
    except Exception as e:
        log.warning(f"compaction: groq summarize failed: {e}")
    try:
        return _call_single_provider("cerebras", "gpt-oss-120b", summary_prompt,
                                     dept="system", max_tokens=1024, is_internal=True)
    except Exception as e:
        log.warning(f"compaction: cerebras summarize failed: {e}")
        return None


def _compress_messages(messages, dept='yana'):
    """DEPRECATED (FO-016): совместимость для старых импортов.
    Раньше — rolling summary по порогу 64k; теперь полный конвейер
    compact_context (budget + offload + prune + summarize).
    Returns (compressed_messages, tokens_saved_estimate)."""
    msgs, stats = compact_context(messages, dept, summarize_fn=_compaction_summarize)
    return msgs, max(stats["tokens_before"] - stats["tokens_after"], 0)


def _call_single_provider(provider_name, model, messages, dept='yana', max_tokens=4096, is_internal=False):
    """Call a single provider+model. Returns result dict or None.
    This is the low-level primitive used by both combo chains and direct calls."""
    prov = PROVIDERS.get(provider_name)
    if not prov:
        return None
    api_key = get_secret(prov["env_key"])
    if not api_key:
        return None
    if not _breaker.can_call(provider_name):
        log.debug(f"CircuitBreaker: skipping {provider_name} (open)")
        return None

    _trace_start = time.monotonic()
    _trace_id = uuid.uuid4().hex[:16]
    _trace_ok = False
    _trace_err = None

    try:
        # FO-018: температура департамента из departments/<dept>.md (дефолт 0.7 — прежний хардкод)
        try:
            from proxy.departments import temperature_for
            _dept_temp = temperature_for(dept)
        except Exception:
            _dept_temp = 0.7
        if prov["format"] == "openai":
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": messages, "temperature": _dept_temp, "max_tokens": max_tokens}
        else:  # anthropic
            sys_msg = ""
            user_msgs = []
            for m in messages:
                if m["role"] == "system":
                    sys_msg = m["content"]
                else:
                    user_msgs.append(m)
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
            body = {"model": model, "max_tokens": max_tokens, "system": sys_msg, "messages": user_msgs}

        resp = http_requests.post(prov["url"], headers=headers, json=body, timeout=prov["timeout"])
        resp.raise_for_status()
        data = resp.json()

        if prov["format"] == "openai":
            reply = data["choices"][0]["message"]["content"]
            t_in = data.get("usage", {}).get("prompt_tokens", 0)
            t_out = data.get("usage", {}).get("completion_tokens", 0)
        else:
            reply = data["content"][0]["text"]
            t_in = data.get("usage", {}).get("input_tokens", 0)
            t_out = data.get("usage", {}).get("output_tokens", 0)

        _breaker.record_success(provider_name)
        _trace_ok = True

        if not is_internal:
            costs = TOKEN_COSTS.get(provider_name, {"input": 1, "output": 1})
            cost = t_in * costs["input"] / 1_000_000 + t_out * costs["output"] / 1_000_000
            now = datetime.utcnow().isoformat()
            try:
                _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
                       (provider_name, model, t_in, t_out, round(cost, 6), dept, now))
            except Exception as e:
                _log_error(f"token_usage insert failed: {e}", dept=dept, kind="metrics_loss")
            finally:
                from proxy.budget import invalidate as budget_invalidate
                budget_invalidate()  # FO-024: счётчик дня — по каждой записи
            log.info(f"LLM ok: provider={provider_name} model={model} dept={dept} "
                     f"t_in={t_in} t_out={t_out} reply_chars={len(reply)} reply_head={reply[:120]!r}")

        # FO-004: write JSONL trace (OTel GenAI semantic conventions)
        _write_llm_trace({
            "trace_id": _trace_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "gen_ai.system": provider_name,
            "gen_ai.request.model": model,
            "gen_ai.response.model": data.get("model", model),
            "gen_ai.usage.input_tokens": t_in,
            "gen_ai.usage.output_tokens": t_out,
            "latency_ms": round((time.monotonic() - _trace_start) * 1000),
            "dept": dept,
            "ok": True,
            "is_internal": is_internal,
            "reply_chars": len(reply) if reply else 0,
        })

        return {"reply": reply, "provider": provider_name, "model": model, "tokens_in": t_in, "tokens_out": t_out}
    except Exception as e:
        _breaker.record_failure(provider_name)
        log.warning(f"LLM fail: provider={provider_name} model={model} err={e}")
        _trace_err = str(e)[:200]
        # FO-004: trace the failure too
        _write_llm_trace({
            "trace_id": _trace_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "gen_ai.system": provider_name,
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": 0,
            "gen_ai.usage.output_tokens": 0,
            "latency_ms": round((time.monotonic() - _trace_start) * 1000),
            "dept": dept,
            "ok": False,
            "error": _trace_err,
            "is_internal": is_internal,
        })
        return None

# ──────────────────────────── CONFIG LOADING ────────────────────────────
_cfg_cache = {"priority_provider": "zai", "priority_model": None, "overrides": {}}

def _load_cfg():
    try:
        p = CFG_DIR / "priority_provider.txt"
        if p.exists(): _cfg_cache["priority_provider"] = p.read_text().strip().split()[0]
    except Exception as e: log.warning(f"[config] priority_provider read failed: {e}")
    try:
        p = CFG_DIR / "priority_model.txt"
        if p.exists(): _cfg_cache["priority_model"] = p.read_text().strip()
    except Exception as e: log.warning(f"[config] priority_model read failed: {e}")
    for dept in DEPT_NAMES:
        try:
            p = CFG_DIR / f"override_{dept}.txt"
            if p.exists(): _cfg_cache["overrides"][dept] = p.read_text().strip()
        except Exception as e: log.warning(f"[config] override_{dept} read failed: {e}")

_load_cfg()

def call_llm(dept, messages, model_override=None, combo=None, command='', depth=2, chat_id=None):
    """Call LLM via native combo chain with circuit breaker and context compaction.
    
    Flow:
    0. FO-024: budget enforcement (soft 80% alert / hard 100% econom / stop 120%)
    1. FO-016: compact context if over budget (offload → prune → summarize)
    2. Select combo chain (or use model_override for direct single-provider call)
    3. Walk the chain: for each (provider, [models]), try each model until one works
    4. Circuit breaker skips providers with recent consecutive failures
    5. If combo chain exhausted, fall back to legacy priority-provider ordering
    """
    # 0. FO-024: enforcement бюджета ДО любой точки расхода. admin и аварийные
    # команды не стопятся (см. proxy/budget.py). stop → честный отказ департаменту.
    try:
        from proxy.budget import enforce as budget_enforce
        bstate = budget_enforce(dept, command=command)
    except Exception as e:  # бюджет не должен ронять вызовы LLM
        _log_error(f"budget enforce failed: {e}", dept=dept, kind="budget_enforce")
        bstate = {"state": "unknown"}
    if bstate.get("state") == "stop":
        return {"reply": ("[Budget] Суточный бюджет департамента исчерпан (>120%). "
                          "Вызовы остановлены до ролловера дня (UTC). "
                          "Аварийные команды (/status /budget /admin) живы."),
                "provider": None, "model": None, "tokens_in": 0, "tokens_out": 0,
                "budget_state": "stop"}

    # 1. FO-016: компакция контекста (наряд #82) — offload → prune → summarize.
    # Бюджет = флор окон провайдеров combo-цепи − резерв ответа (compaction.py);
    # полные метрики конвейера — в трейсах FO-004 (event=compaction).
    combo_pre = combo if combo is not None else _combo_for_task(dept, command=command, depth=depth)
    chain_pre = COMBO_CHAINS.get(combo_pre, COMBO_CHAINS["fosved-standard"])
    messages, comp_stats = compact_context(messages, dept, chain=chain_pre,
                                           summarize_fn=_compaction_summarize,
                                           chat_id=chat_id)
    compression_saved = max(comp_stats["tokens_before"] - comp_stats["tokens_after"], 0)

    # FO-018: модель департамента из departments/<dept>.md (если не задан явный override)
    if model_override is None:
        try:
            from proxy.departments import model_for
            model_override = model_for(dept)
        except Exception as e:
            log.warning(f"[departments] model_for({dept}) failed, combo as usual: {e}")

    # FO-024 (hard ≥100%): эконом-режим — модель = последний элемент fallback-цепи
    # (самая дешёвая, зеркало GetModelFallbackChain), heavy-модели deny.
    if bstate.get("state") == "hard":
        model_override = bstate.get("econom_model") or model_override
        log.info(f"[budget] hard≥100% dept={dept}: econom model={model_override}")

    # 2. If model_override is set, do direct single-provider call
    if model_override:
        # Determine provider from model name
        provider = _cfg_cache["priority_provider"]
        for prov_name in PROVIDERS:
            if model_override.startswith("claude"):
                provider = "anthropic"; break
            elif model_override.startswith("deepseek"):
                provider = "deepseek"; break
            elif model_override.startswith("grok"):
                provider = "grok"; break
            elif model_override.startswith("gpt"):
                provider = "openai"; break
            elif model_override.startswith("glm"):
                provider = "zai"; break
            elif model_override.startswith("llama") or model_override.startswith("mixtral") or model_override.startswith("gemma"):
                provider = "groq"; break
            elif model_override.startswith("apodex"):
                provider = "apodex"; break
            elif model_override.startswith("nvidia/"):
                provider = "nvidia"; break
            elif model_override.startswith("gpt-oss") or model_override.startswith("zai-glm"):
                provider = "cerebras"; break
        result = _call_single_provider(provider, model_override, messages, dept=dept)
        if result and result.get("reply"):
            if compression_saved > 0:
                result["compression_saved"] = compression_saved
            return result
        # If direct call failed, fall through to combo chain
        log.warning(f"Direct call failed for {provider}/{model_override}, falling back to combo chain")

    # 3. Select combo
    if combo is None:
        combo = _combo_for_task(dept, command=command, depth=depth)

    # 4. Walk combo chain — race first 2 providers in parallel, then sequential fallback
    chain = COMBO_CHAINS.get(combo, COMBO_CHAINS["fosved-standard"])
    # Parallel race: launch first 2 (provider, model) pairs concurrently
    race_entries = []
    for prov_name, models in chain:
        if not _breaker.can_call(prov_name):
            continue
        for model in models:
            max_tok = 16384 if dept in {"yana", "admin", "osp", "lz", "expert", "engineering"} else 8192
            cap = PROVIDER_MAX_TOKENS.get(prov_name)
            if cap:
                max_tok = min(max_tok, cap)
            race_entries.append((prov_name, model, max_tok))
            if len(race_entries) >= 2:
                break
        if len(race_entries) >= 2:
            break

    if len(race_entries) >= 2:
        def _race_call(entry):
            prov_name, model, max_tok = entry
            return _call_single_provider(prov_name, model, messages, dept=dept, max_tokens=max_tok)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {pool.submit(_race_call, e): e for e in race_entries}
                for fut in as_completed(futures, timeout=30):
                    try:
                        result = fut.result(timeout=25)
                        if result and result.get("reply"):
                            if compression_saved > 0:
                                result["compression_saved"] = compression_saved
                            result["combo"] = combo
                            log.info(f"Race winner: {result.get('provider')}/{result.get('model')}")
                            return result
                    except Exception:
                        continue
        except Exception:
            pass  # Fall through to sequential

    # Sequential fallback for remaining chain entries (skip already-raced)
    raced_set = {(p, m) for p, m, _ in race_entries}
    for prov_name, models in chain:
        if not _breaker.can_call(prov_name):
            continue
        for model in models:
            if (prov_name, model) in raced_set:
                continue
            max_tok = 16384 if dept in {"yana", "admin", "osp", "lz", "expert", "engineering"} else 8192
            cap = PROVIDER_MAX_TOKENS.get(prov_name)
            if cap:
                max_tok = min(max_tok, cap)
            result = _call_single_provider(prov_name, model, messages, dept=dept, max_tokens=max_tok)
            if result and result.get("reply"):
                if compression_saved > 0:
                    result["compression_saved"] = compression_saved
                result["combo"] = combo
                return result

    # 5. Fallback: legacy priority-provider ordering (all providers, priority first)
    log.warning(f"Combo chain '{combo}' exhausted, falling back to legacy ordering")
    priority = _cfg_cache["priority_provider"]
    fallback_model = _cfg_cache["overrides"].get(dept) or _cfg_cache["priority_model"] or "glm-4.6"
    order = [p for p in [priority] + [k for k in PROVIDERS if k != priority] if p in PROVIDERS]
    last_err = None
    for prov_name in order:
        if not _breaker.can_call(prov_name):
            continue
        use_model = fallback_model
        # Auto-adapt model to provider
        if prov_name == "anthropic" and use_model.startswith("gpt"):
            use_model = "claude-sonnet-4-20250514"
        elif prov_name == "deepseek" and not use_model.startswith("deepseek"):
            use_model = "deepseek-chat"
        elif prov_name == "groq" and not any(m in use_model for m in ("openai/gpt-oss", "llama", "mixtral", "gemma")):
            use_model = "openai/gpt-oss-20b"
        elif prov_name == "nvidia" and not use_model.startswith("nvidia/"):
            use_model = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        elif prov_name == "cerebras" and not use_model.startswith("gpt-oss"):
            use_model = "gpt-oss-120b"
        fb_max = PROVIDER_MAX_TOKENS.get(prov_name, 4096)
        result = _call_single_provider(prov_name, use_model, messages, dept=dept, max_tokens=fb_max)
        if result and result.get("reply"):
            if compression_saved > 0:
                result["compression_saved"] = compression_saved
            return result
        last_err = f"{prov_name}/{use_model}"

    return {"reply": f"[Oshibka] Vse providery nedostupny (combo={combo}): {last_err}", "provider": None, "model": None, "tokens_in": 0, "tokens_out": 0}

# ──────────────────────────── IMAGE GENERATION ─────────────────────────────

_ZAI_CONFIG_PATHS = ['/etc/.z-ai-config', os.path.expanduser('~/.z-ai-config'), '.z-ai-config']
_ZAI_CONFIG = None


def _load_zai_config():
    """Load z-ai SDK config (baseUrl, apiKey, headers) from file."""
    global _ZAI_CONFIG
    if _ZAI_CONFIG is not None:
        return _ZAI_CONFIG
    for p in _ZAI_CONFIG_PATHS:
        try:
            with open(p, 'r') as f:
                cfg = json.load(f)
                _ZAI_CONFIG = cfg
                log.info(f"z-ai config loaded from {p}")
                return cfg
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    log.warning("z-ai config not found in any search path")
    return None


def _zai_headers():
    """Build headers dict for z-ai API calls."""
    cfg = _load_zai_config()
    if not cfg:
        return None
    h = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {cfg.get('apiKey', '')}",
        'X-Z-AI-From': 'Z',
    }
    if cfg.get('chatId'):
        h['X-Chat-Id'] = cfg['chatId']
    if cfg.get('userId'):
        h['X-User-Id'] = cfg['userId']
    if cfg.get('token'):
        h['X-Token'] = cfg['token']
    return h


_IMG_DIR = os.path.join(DB_PATH, 'generated_images')
_ALLOWED_SIZES = ('1024x1024', '768x1344', '864x1152', '1344x768', '1152x864', '1440x720', '720x1440')


def _generate_image(prompt, size='1024x1024'):
    """Call z-ai image generation API and return (local_path, error)."""
    if size not in _ALLOWED_SIZES:
        size = '1024x1024'
    headers = _zai_headers()
    if not headers:
        return None, 'z-ai config not found'
    cfg = _load_zai_config()
    url = f"{cfg['baseUrl']}/images/generations"
    payload = {'prompt': prompt, 'size': size}
    try:
        # Step 1: request generation
        log.info(f"Image generation request: {prompt[:80]}...")
        resp = http_requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        images = data.get('data', [])
        if not images:
            return None, 'API returned no images'
        image_url = images[0].get('url', '')
        if not image_url:
            return None, 'API returned no image URL'
        # Step 2: download the generated image
        img_resp = http_requests.get(image_url, timeout=60)
        img_resp.raise_for_status()
        # Step 3: save locally
        os.makedirs(_IMG_DIR, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        fname = f"img_{ts}_{uuid.uuid4().hex[:6]}.jpg"
        fpath = os.path.join(_IMG_DIR, fname)
        with open(fpath, 'wb') as f:
            f.write(img_resp.content)
        log.info(f"Image saved: {fpath} ({len(img_resp.content)} bytes)")
        return fpath, None
    except Exception as e:
        log.error(f"Image generation failed: {e}")
        return None, str(e)
