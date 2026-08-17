#!/usr/bin/env python3
"""llm_proxy.py — Fosved Office v2 LLM Proxy Server
Flask server on port 4000 with native circuit breaker, combo chains, token compression,
7-provider direct failover, dept routing, dashboards, SQLite,
TTS/STT, archive, scheduler, learning, audit, and search endpoints."""

import sys, json, os, re, sqlite3, subprocess, threading, time, logging, hashlib, uuid
import doc_extract
import html as html_lib
from datetime import datetime, timedelta
from pathlib import Path

# ── FosvedMemory ──────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from fosved_memory import FosvedMemory
_MEMORY_DB = os.path.join(os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')), 'memory.db')
os.makedirs(os.path.dirname(_MEMORY_DB), exist_ok=True)
memory = FosvedMemory(_MEMORY_DB)
log_mem = logging.getLogger("fosved.memory")
log_mem.info(f"FosvedMemory loaded: {len(memory.TYPES)} types, db={_MEMORY_DB}")

from flask import Flask, request, jsonify, Response
import requests as http_requests
try:
    from auto_enricher import auto_enrich as _auto_enrich_fn
    _has_enricher = True
except Exception as _e:
    log.warning(f"auto_enricher import failed, rich post-processor disabled: {_e}")
    _auto_enrich_fn = None
    _has_enricher = False


def auto_enrich(text, dept='yana', accent_color='#6366f1'):
    """Safe wrapper — returns raw text if enricher unavailable."""
    if _auto_enrich_fn is None:
        return text or ''
    try:
        return _auto_enrich_fn(text, dept=dept, accent_color=accent_color)
    except Exception as e:
        log.warning(f"auto_enrich error: {e}")
        return text or ''

# ──────────────────────────── APP & CONFIG ────────────────────────────
app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("llm_proxy")

# ── Auth middleware (before_request) ──────────────────────────
@app.before_request
def auth_middleware():
    path = request.path
    # Protect API, admin, memory, miniapp-action endpoints
    if any(path.startswith(p) for p in PROTECTED_PREFIXES):
        # Internal requests from mlog (localhost) are allowed to /memory/
        # without Bearer — mlog http_post() has no custom-header support.
        # External traffic is blocked by reverse_proxy (SEC-1) and firewall.
        if path.startswith("/memory/") and request.remote_addr in ("127.0.0.1", "::1"):
            return None
        if not _check_bearer():
            return jsonify({"error": "unauthorized"}), 401
    return None

PORT = int(os.environ.get("PORT_PROXY", 4000))
DB_PATH = os.environ.get("DATABASE_PATH", "./data")
Path(DB_PATH).mkdir(parents=True, exist_ok=True)
DB_FILE = os.path.join(DB_PATH, "fosved.db")

BASE_DIR = Path(__file__).parent
LIB_DIR = BASE_DIR / "library"
CFG_DIR = BASE_DIR / "config"

db_lock = threading.Lock()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ARCHIVE_CHANNEL_ID = os.environ.get("TELEGRAM_ARCHIVE_CHANNEL_ID", "")
WHISPER_API_KEY = os.environ.get("WHISPER_API_KEY", "")
WHISPER_PROVIDER = os.environ.get("WHISPER_PROVIDER", "groq")
API_SECRET = os.environ.get("API_SECRET", "")  # Bearer token for protected endpoints
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")  # X-Telegram-Bot-Api-Secret-Token

# ── Auth helpers ──────────────────────────────────────────────
PROTECTED_PREFIXES = ('/api/', '/admin-ua/', '/memory/', '/webhook/miniapp-action')

def _check_bearer():
    """Return True if request bears valid API_SECRET, or if API_SECRET is empty (open mode)."""
    if not API_SECRET:
        return True
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {API_SECRET}'

def _verify_webhook_secret():
    """Verify Telegram webhook secret token header."""
    if not WEBHOOK_SECRET:
        return True  # no secret configured — open mode
    return request.headers.get('X-Telegram-Bot-Api-Secret-Token', '') == WEBHOOK_SECRET


def _verify_init_data(init_data, max_age_seconds=86400):
    """Validate Telegram Mini App initData signature and owner identity.

    Returns True when the signature matches the bot token, the payload is
    fresh, and the user is the owner. Disabled (returns True) when the bot
    token is not configured, so a misconfigured environment stays usable.
    """
    if not TELEGRAM_BOT_TOKEN:
        return True
    if not init_data:
        return False
    try:
        import hmac as _hmac
        from urllib.parse import parse_qsl

        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            return False

        check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = _hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = _hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, received_hash):
            return False

        auth_date = int(pairs.get("auth_date", "0"))
        if max_age_seconds and (time.time() - auth_date) > max_age_seconds:
            return False

        owner = os.environ.get("OWNER_TELEGRAM_ID", "")
        if owner:
            user = json.loads(pairs.get("user", "{}"))
            if str(user.get("id", "")) != str(owner):
                return False
        return True
    except Exception as e:
        log.warning(f"initData verification failed: {e}")
        return False


# SEC-4: Telegram delivers initData to the WebApp JS object, not to the URL.
# When the signature is absent we serve this bootstrap page: its script reads
# initData from Telegram and re-requests the same URL with the header set.
_TG_BOOTSTRAP_PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Загрузка</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
body{margin:0;padding:40px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
background:#17212b;color:#e9edf2;text-align:center}
.msg{margin-top:24px;font-size:15px;color:#8fa3b8}
</style></head><body>
<div class="msg" id="s">Загрузка…</div>
<script>
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  var initData = tg && tg.initData ? tg.initData : "";
  if (!initData) {
    document.getElementById("s").textContent =
      "Эта страница открывается только из Telegram.";
    return;
  }
  if (tg.expand) { tg.expand(); }
  fetch(window.location.href, {
    headers: { "X-Telegram-Init-Data": initData }
  }).then(function (r) {
    if (!r.ok) { throw new Error("HTTP " + r.status); }
    return r.text();
  }).then(function (html) {
    document.open();
    document.write(html);
    document.close();
  }).catch(function (e) {
    document.getElementById("s").textContent = "Не удалось загрузить: " + e.message;
  });
})();
</script>
</body></html>"""


def require_telegram(view):
    """Allow the request only from inside Telegram (valid initData)."""
    from functools import wraps

    @wraps(view)
    def wrapper(*args, **kwargs):
        init_data = (request.args.get("tgWebAppData")
                     or request.headers.get("X-Telegram-Init-Data", ""))
        if not _verify_init_data(init_data):
            # No signature at all: browser navigation from a web_app button.
            # Serve the bootstrap page so its script can supply initData.
            if not init_data:
                return Response(_TG_BOOTSTRAP_PAGE, status=200, mimetype="text/html")
            # Signature present but invalid, stale, or from another user: refuse.
            log.warning("SEC-4: initData present but rejected")
            return Response(
                "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
                "<title>Доступ закрыт</title></head><body style='font-family:sans-serif;"
                "padding:40px;background:#17212b;color:#e9edf2'>"
                "<h2>Доступ закрыт</h2><p>Эта страница открывается только из Telegram.</p>"
                "</body></html>",
                status=403, mimetype="text/html")
        return view(*args, **kwargs)

    return wrapper

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
        ("groq", ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]),
        ("cerebras", ["gpt-oss-120b"]),
        ("deepseek", ["deepseek-chat"]),
    ],
    "fosved-standard": [
        ("kimi", ["kimi-k3"]),
        ("deepseek", ["deepseek-chat"]),
        ("zai", ["glm-4.6", "glm-4-plus"]),
        ("groq", ["llama-3.3-70b-versatile"]),
        ("cerebras", ["gpt-oss-120b"]),
    ],
    "fosved-deep": [
        ("kimi", ["kimi-k3"]),
        ("deepseek", ["deepseek-chat"]),
        ("zai", ["glm-4.6"]),
        ("groq", ["llama-3.3-70b-versatile"]),
        ("cerebras", ["gpt-oss-120b"]),
        ("anthropic", ["claude-sonnet-4-20250514"]),
    ],
    "fosved-fusion": [
        ("kimi", ["kimi-k3"]),
        ("deepseek", ["deepseek-chat"]),
        ("zai", ["glm-4.6"]),
        ("groq", ["llama-3.3-70b-versatile"]),
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


def _estimate_tokens(messages):
    """Rough token estimate: ~2 chars per token for mixed Russian/English."""
    total = 0
    for m in messages:
        total += len(m.get("content", "")) // 2
    return total


def _compress_messages(messages, dept='yana'):
    """Rolling summary compression: if messages exceed threshold,
    summarize older messages into a single system-context message.
    Returns (compressed_messages, tokens_saved_estimate)."""
    est = _estimate_tokens(messages)
    if est <= _COMPRESSION_MAX_TOKENS:
        return messages, 0

    # Separate system prompts from conversation
    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo = [m for m in messages if m.get("role") != "system"]

    if len(convo) <= 4:
        return messages, 0  # Too few messages to compress meaningfully

    # Keep last 6 messages, compress the rest
    keep_count = 6
    to_compress = convo[:-keep_count]
    to_keep = convo[-keep_count:]

    # Build a summary request using a cheap model
    compress_text = "\n".join(
        f"{'User' if m['role']=='user' else 'Assistant'}: {m['content'][:500]}"
        for m in to_compress[-20:]  # Last 20 of old messages, truncated
    )
    if not compress_text.strip():
        return messages, 0

    summary_prompt = [
        {"role": "system", "content": "Summarize the following conversation history into a concise context paragraph (max 300 words). Preserve key facts, decisions, names, numbers. Output ONLY the summary, nothing else."},
        {"role": "user", "content": compress_text}
    ]

    try:
        # Use cheap provider for compression
        summary_result = _call_single_provider("groq", "llama-3.3-70b-versatile", summary_prompt, dept="system", max_tokens=1024, is_internal=True)
        if summary_result and summary_result.get("reply"):
            summary_msg = {"role": "system", "content": f"[Earlier conversation summary]: {summary_result['reply'][:2000]}"}
            compressed = system_msgs + [summary_msg] + to_keep
            saved = est - _estimate_tokens(compressed)
            log.info(f"Token compression: {est} -> {_estimate_tokens(compressed)} (saved ~{saved} tokens, {len(to_compress)} messages compressed)")
            return compressed, saved
    except Exception as e:
        log.warning(f"Token compression failed, sending uncompressed: {e}")

    return messages, 0


def _call_single_provider(provider_name, model, messages, dept='yana', max_tokens=4096, is_internal=False):
    """Call a single provider+model. Returns result dict or None.
    This is the low-level primitive used by both combo chains and direct calls."""
    prov = PROVIDERS.get(provider_name)
    if not prov:
        return None
    api_key = os.environ.get(prov["env_key"])
    if not api_key:
        return None
    if not _breaker.can_call(provider_name):
        log.debug(f"CircuitBreaker: skipping {provider_name} (open)")
        return None

    try:
        if prov["format"] == "openai":
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": max_tokens}
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

        if not is_internal:
            costs = TOKEN_COSTS.get(provider_name, {"input": 1, "output": 1})
            cost = t_in * costs["input"] / 1_000_000 + t_out * costs["output"] / 1_000_000
            now = datetime.utcnow().isoformat()
            try:
                _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
                       (provider_name, model, t_in, t_out, round(cost, 6), dept, now))
            except Exception:
                pass
            log.info(f"LLM ok: provider={provider_name} model={model} dept={dept} "
                     f"t_in={t_in} t_out={t_out} reply_chars={len(reply)} reply_head={reply[:120]!r}")

        return {"reply": reply, "provider": provider_name, "model": model, "tokens_in": t_in, "tokens_out": t_out}
    except Exception as e:
        _breaker.record_failure(provider_name)
        log.warning(f"LLM fail: provider={provider_name} model={model} err={e}")
        return None

# ──────────────────────────── DEPT COLORS & NAMES ────────────────────────────
DEPT_COLORS = {
    'yana': {'start': '#293133', 'end': '#1a2024', 'accent': '#3d4a4d'},
    'osp': {'start': '#b91c1c', 'end': '#7f1d1d', 'accent': '#dc2626'},
    'lz': {'start': '#0e7490', 'end': '#164e63', 'accent': '#0891b2'},
    'expert': {'start': '#3730a3', 'end': '#1e1b4b', 'accent': '#4f46e5'},
    'marketing': {'start': '#c2410c', 'end': '#7c2d12', 'accent': '#ea580c'},
    'finance': {'start': '#15803d', 'end': '#14532d', 'accent': '#16a34a'},
    'legal': {'start': '#475569', 'end': '#1e293b', 'accent': '#64748b'},
    'dev': {'start': '#1d4ed8', 'end': '#1e3a8a', 'accent': '#2563eb'},
    'design': {'start': '#be185d', 'end': '#831843', 'accent': '#ec4899'},
    'qa': {'start': '#4d7c0f', 'end': '#365314', 'accent': '#65a30d'},
    'visual': {'start': '#7e22ce', 'end': '#581c87', 'accent': '#a855f7'},
    'engineering': {'start': '#44403c', 'end': '#292524', 'accent': '#78716c'},
    'kavalnya': {'start': '#b45309', 'end': '#78350f', 'accent': '#d97706'},
    'admin': {'start': '#1e40af', 'end': '#1e3a5f', 'accent': '#3b82f6'},
}

DEPT_NAMES = {
    'yana': 'Yana — Шеф де кабинета', 'osp': 'ОСП · Стратегическое планирование',
    'lz': 'ЛЗ · Лаборатория знаний', 'expert': 'Эксперт · Подготовка к встрече',
    'marketing': 'Маркетинг', 'finance': 'Финансы', 'legal': 'Юрист',
    'dev': 'Dev · Разработка', 'design': 'Дизайн · UI/UX', 'qa': 'QA · Тестирование',
    'visual': 'Визуал · Инфографика', 'engineering': 'Инженерия · Расчёты',
    'kavalnya': 'Кавальня · Методология', 'admin': 'Админ · Система',
}

DEPT_HASHTAGS = {
    'osp': '#OSP #analytics #strategy',
    'lz': '#LZ #technology #politics #economics #geopolitics #research',
    'expert': '#Expert #briefing #meeting #negotiations',
    'marketing': '#Marketing #audience',
    'finance': '#Finance #cashflow',
    'legal': '#Legal #contracts',
    'dev': '#Dev #code #architecture',
    'design': '#Design #UX',
    'qa': '#QA #testing',
    'visual': '#Visual #infographic',
    'engineering': '#Engineering #calculations',
    'kavalnya': '#Kavalnya #methodology',
    'yana': '#Yana #cabinet',
    'admin': '#Admin #system',
}

def html_lib_escape(s):
    """Safe HTML escape for report templates."""
    return html_lib.escape(str(s)) if s else ''

# ── Text formatting helpers for Telegram ────────────────────────────

# Emoji used as section markers — kept in visual text, stripped for TTS
_MARKER_EMOJI = re.compile(
    r'[\U0001F4C5\U0001F324\U0001F3E2\U0001F30D\U0001F50D\U000026A1'  # 📅🌤🏢🌍🔍⚡
    r'\U0001F4CC\U0001F4AC\U0001F527\U00002705\U0000274C'                # 📌💬🔧✅❌
    r'\U0001F5E3\U0001F4CB\U0001F4CA\U0001F4C8\U0001F4C9'                # 🗣📋📊📈📉
    r'\U00002B50\U0001F680\U0001F389\U0001F514\U000023F0'                # ⭐🚀🎉🔔⏰
    r'\U0001F4E6\U0001F4DD\U0001F3AF\U0001F4A1\U0001F517'                # 📦📝🎯💡🔗
    r'\U0001F4C1\U0001F4C4\U0001F4C2\U0001F504\U00002699'                # 📁📄📂🔄⚙
    r'\U0001F4D6\U0001F3DB\U0001F3E0\U0001F310\U0001F30F'                # 📖🏛🏠🌐🌍
    r'\U0001F6E1\U00002696\U00002764\U00002753\U00002139'                # 🛡⚛❓❗
    r'\U0001F534\U0001F7E0\U0001F7E1\U0001F7E2\U0001F535\U0001F7E3'  # 🔴🟠🟡🟢🔵🟣
    r'\U000025B6\U000025AA\U000025CF\U000025CB\U00002500\U00002501'  # ▸▪●○──━
    r'\U000025C6\U00002666\U00002737\U0000203C\U000000A9\U00002122]'  # ◆♠✳‼©®
    r'[\U0001F300-\U0001F9FF]'                                            # catch-all: common emoji
)

# All emoji (broadest match) — for TTS
_ALL_EMOJI = re.compile(
    r'[\U00002600-\U000027BF]'   # Misc symbols, dingbats
    r'|[\U0001F000-\U0001FAFF]'  # All emoji blocks
    r'|[\U0000FE00-\U0000FE0F]'  # Variation selectors
    r'|[\U0000200D]'             # Zero-width joiner
    r'|[\U0001F900-\U0001F9FF]'  # Supplemental symbols
    r'|[\U0001FA00-\U0001FA6F]'  # Chess, symbols
    r'|[\U0001FA70-\U0001FAFF]'  # Symbols extended
)


def _clean_text_for_tts(text):
    """Strip emoji, Markdown syntax, special chars for clean edge-tts voice output.
    
    Keeps: letters (all scripts), digits, basic sentence punctuation (. , - : ;).
    Removes: emoji, *, _ `, #, ▸ ◦ ───, quotes (" " « »), ‑, •, etc.
    """
    if not text:
        return ""
    t = _ALL_EMOJI.sub(' ', text)            # remove all emoji
    t = re.sub(r'[*_`#~|>]', ' ', t)          # remove Markdown syntax chars
    t = re.sub(r'[«»""\u201C\u201D\u201E\u2018\u2019]', '', t)  # remove all quotes
    t = re.sub(r'───+|──+|─+', '', t)         # remove decorative lines
    t = re.sub(r'[▸◦▪●○◆◇▪▸►←→↑↓]', '', t)  # remove bullet/arrow chars
    t = re.sub(r'[═─━─]', '', t)              # remove box-drawing lines
    t = re.sub(r'[✓✗✘✔✖]', '', t)            # remove check/cross marks
    t = re.sub(r'\s{2,}', ' ', t)             # collapse whitespace
    t = re.sub(r'(?<=\S)\s*[.!?]\s*[.!?]+', '.', t)  # collapse multiple sentence ends
    t = t.strip()
    return t


def _escape_mdv2(text):
    """Escape text for Telegram MarkdownV2 parse_mode.
    
    Characters that MUST be escaped: _ * [ ] ( ) ~ ` > # + - = | { } . !
    Inside inline code or code blocks, no escaping needed.
    Strategy: find code blocks/spans first, escape around them.
    
    For safety, this uses a simple approach: escape everything except
    emoji (which Telegram renders natively) and content inside backticks.
    """
    if not text:
        return ""
    
    # Split by backtick-delimited code spans
    parts = re.split(r'(`[^`]+`)', text)
    escaped_parts = []
    for part in parts:
        if part.startswith('`') and part.endswith('`'):
            # Code span — keep as-is
            escaped_parts.append(part)
        else:
            # Escape MarkdownV2 special chars, but preserve emoji and newlines
            # MDV2 special: _ * [ ] ( ) ~ ` > # + - = | { } . !
            escaped = re.sub(r'(?<!\\)([_*\[\]\(\)~`>#\+\-=|{}\.!])', r'\\\1', part)
            # Un-escape emoji (they were incorrectly escaped)
            escaped = _ALL_EMOJI.sub(lambda m: m.group(), escaped)
            # Un-escape escaped newlines
            escaped = escaped.replace('\\\n', '\n')
            # Fix double-escaped backslashes before emoji
            escaped = re.sub(r'\\(\\[\U0001F000-\U0001FAFF\U00002600-\U000027BF])', r'\1', escaped)
            escaped_parts.append(escaped)
    
    return ''.join(escaped_parts)


def _tg_send_formatted(chat_id, text, dept=None):
    """Send message with MarkdownV2 formatting for Yana/Admin, plain for others.
    
    Tries MarkdownV2 first; if Telegram rejects it (400), falls back to plain text.
    This ensures messages always get delivered even if formatting is imperfect.
    """
    if not text:
        return None
    
    # Use MarkdownV2 for formatted departments
    if dept in ("yana", "admin"):
        mdv2_text = _escape_mdv2(text)
        msg_id = _tg_send_message(chat_id, mdv2_text, parse_mode="MarkdownV2")
        if msg_id is not None:
            return msg_id
        # Fallback: Telegram rejected formatting, send plain
        log.warning(f"MarkdownV2 rejected for dept={dept}, falling back to plain text")
    
    return _tg_send_message(chat_id, text)


# ──────────────────────────── DEPT DETECTION ────────────────────────────
COMMAND_DEPT = {
    '/yana': 'yana', '/osp': 'osp', '/lz': 'lz', '/expert': 'expert',
    '/marketing': 'marketing', '/finance': 'finance', '/legal': 'legal',
    '/dev': 'dev', '/design': 'design', '/qa': 'qa', '/visual': 'visual',
    '/engineering': 'engineering', '/forge': 'kavalnya',
    '/analyze': 'osp', '/scan': 'lz', '/deep': 'osp',
    '/quickanalyze': 'osp', '/wargame': 'osp',
    '/market-research': 'marketing', '/segment': 'marketing',
    '/competitors': 'marketing', '/campaign': 'marketing',
    '/calc': 'engineering', '/simulate': 'engineering',
    '/admin': 'admin',
}

RUSSIAN_KEYWORDS = {
    'osp': ['проанализируй', 'прогноз', 'стратегия', 'анализ', 'сценари', 'вероятност', 'деconstruct', 'деконстру', 'тополог', 'силовой потенциал', 'препарирован'],
    'lz': ['технолог', 'монитор', 'тренд', 'прорыв', 'наука', 'исследован', 'обзор', 'что такое', 'как работает', 'лаборатори',
           'политик', 'экономик', 'геополитик', 'санкци', 'макро', 'режим', 'нарратив', 'событие', 'кризис',
           'конфликт', 'выбор', 'инфляци', 'рецесси', 'ставк', 'ценн', 'войн', 'мирн', 'дипломат',
           'cantillon', 'нарратив vs', 'narrative', 'регим', 'цикл', 'kondratieff', 'хайп', 'инфлекци',
           'осинт', 'osint', 'разведк', 'мониторинг', 'свеж', 'новост', 'событи', 'в мире', 'в рф'],
    'expert': ['встреч', 'брифинг', 'подготов к', 'эксперт', 'подготовь', 'вопросы для', 'комбат-вопрос', 'подготов',
              'переговор', 'byd', 'geely', 'chery', 'zeekr', 'lixiang', 'nio', 'xpeng', 'vinfast',
              'авто', 'автомобиль', 'автопром', 'конкурент', 'соперник',
              'toyota', 'bmw', 'mercedes', 'vw ', 'volkswagen', 'honda', 'hyundai', 'kia',
              'платформ', 'ev ', 'электромобиль', 'завод', 'производств', 'сборк', 'локализац',
              'cto', 'ceo', 'cfo', 'директор', 'руководств', 'встреча с', 'митинг', 'переговоры'],
    'marketing': ['реклам', 'аудитори', 'конверси', 'маркетинг', 'позицио', 'воронк', 'smm', 'бренд', 'контент', 'сегмент'],
    'finance': ['бюджет', 'cashflow', 'налог', 'финанс', 'расход', 'доход', 'инвестиц', 'кредит', 'курс валют', 'кассовый разрыв'],
    'legal': ['договор', 'иск', 'gdpr', 'юридическ', 'nda', 'право', 'суд', 'комплаенс', 'контракт', 'закон'],
    'dev': ['код', 'архитектур', 'api', 'программ', 'деплой', 'сервер', 'git', 'баг', 'рефактор', 'бэкенд', 'фронтенд'],
    'design': ['дизайн', 'wireframe', 'макет', 'ui', 'ux', 'интерфейс', 'прототип', 'фиго', 'компонент'],
    'qa': ['тест', 'баг', 'качеств', 'проверк', 'регресси', 'автотест', 'e2e', 'покрыти'],
    'visual': ['инфографик', 'визуализац', 'график', 'презентац', 'диаграмм', 'иллюстрац', 'дашборд'],
    'engineering': ['расчёт', 'нагрузк', 'конструкц', 'инженер', 'снип', 'гидравлик', 'прочност', 'сварк', 'фундамент'],
    'kavalnya': ['новый отдел', 'полигон', 'методолог', 'создать отдел', 'наряд', 'дефектив', 'assess', 'debrief'],
    'admin': ['оптимизир', 'почини', 'рефакторинг', 'deploy', 'админ', 'инфраструктур', 'здравствуй', 'перезагруз', 'конфиг'],
}

# ── Keyword weights for scoring: higher = more specific/less generic ──
# 'анализ' is generic (weight 1) while 'встреч' is specific (weight 4), 'byd' is very specific (weight 5)
KEYWORD_WEIGHTS = {
    'osp': {'проанализируй': 3, 'прогноз': 2, 'стратегия': 2, 'анализ': 1, 'сценари': 2, 'вероятност': 2, 'деconstruct': 3, 'деконстру': 3, 'тополог': 3, 'силовой потенциал': 3, 'препарирован': 2},
    'lz': {'политик': 3, 'экономик': 3, 'геополитик': 4, 'санкци': 4, 'макро': 3, 'режим': 3, 'нарратив': 3, 'событие': 2, 'кризис': 3,
           'конфликт': 3, 'инфляци': 3, 'рецесси': 3, 'ставк': 2, 'войн': 3, 'дипломат': 3,
           'cantillon': 4, 'осинт': 3, 'osint': 3, 'разведк': 3, 'мониторинг': 2, 'свеж': 2, 'новост': 2, 'в мире': 2, 'в рф': 3},
    'expert': {'встреч': 4, 'встреча с': 5, 'брифинг': 4, 'подготов к': 3, 'эксперт': 3, 'подготовь': 3, 'вопросы для': 3, 'комбат-вопрос': 4, 'подготов': 2,
              'переговор': 4, 'переговоры': 4, 'byd': 5, 'geely': 5, 'chery': 5, 'zeekr': 5, 'lixiang': 5, 'nio': 5, 'xpeng': 5, 'vinfast': 5,
              'cto': 4, 'ceo': 4, 'cfo': 4, 'директор': 3, 'авто': 3, 'автомобиль': 3, 'автопром': 4, 'конкурент': 3, 'платформ': 3, 'ev ': 4,
              'электромобиль': 4, 'завод': 2, 'производств': 2, 'сборк': 2, 'локализац': 3},
}

def detect_dept(text):
    text_lower = text.lower().strip()
    # Phase 1: Explicit command prefix (exact match, no scoring needed)
    for cmd, dept in sorted(COMMAND_DEPT.items(), key=lambda x: -len(x[0])):
        if text_lower.startswith(cmd) and (len(text_lower) == len(cmd) or text_lower[len(cmd)] in ' \n/'):
            return dept

    # Phase 2: Weighted keyword scoring across ALL departments
    # Each dept scores points for matching keywords; highest score wins.
    # This fixes the OSP-before-Expert ordering bug where 'анализ' (weight 1)
    # hijacked queries containing 'встреч' (weight 4) or 'byd' (weight 5).
    scores = {}
    for dept, kws in RUSSIAN_KEYWORDS.items():
        score = 0
        matched = []
        weights = KEYWORD_WEIGHTS.get(dept, {})
        for kw in kws:
            if kw in text_lower:
                w = weights.get(kw, 1)  # default weight = 1 for unweighted keywords
                score += w
                matched.append(kw)
        if score > 0:
            scores[dept] = (score, matched)

    if scores:
        # Sort by score descending; on tie, prefer expert > osp > others
        _PRIORITY = {'expert': 0, 'osp': 1, 'lz': 2, 'finance': 3, 'marketing': 4, 'legal': 5,
                     'dev': 6, 'engineering': 7, 'design': 8, 'qa': 9, 'visual': 10, 'kavalnya': 11, 'admin': 12}
        best = sorted(scores.items(), key=lambda x: (-x[1][0], _PRIORITY.get(x[0], 99)))[0]
        best_dept = best[0]
        best_score = best[1][0]
        best_keywords = best[1][1]
        log.info(f"[detect_dept] scored: { {d: s[0] for d, s in scores.items()} } → {best_dept} (score={best_score}, kw={best_keywords})")
        return best_dept

    return 'yana'

# ──────────────────────────── CONDENSED PROMPTS ────────────────────────────
CONDENSED_PROMPTS = {
    'yana': "You are Yana, Chief of Cabinet. Route tasks to departments. Be empathetic, concise. Default language: Russian.",
    'osp': "You are OSP, Strategic Analysis Dept. Use 5-level topology (Leaves/Branches/Stem/Roots/Fruits). Mark claims [FACT]/[INTERPRETATION]/[SPECULATION]. Sherman Kent scale. Language: Russian.",
    'lz': "You are LZ, World Intelligence Lab. Monitor tech + politics + economics + geopolitics + events. Structure: Signal->Impact->Opportunity. Cantillon, narrative-vs-flows, macro regime. Cite sources. Language: Russian.",
    'expert': "You are Expert, Meeting & Negotiation Preparator. Prepare briefings for meetings/interviews/negotiations. Profile counterparty, combat questions, leverage points, BATNA, red flags, decision points. Mark: [ФАКТ] confirmed, [ОЦЕНКА] expert assessment, [РИСК] potential problem. Language: Russian.",
    'marketing': "You are Marketing. Audience analysis, positioning, campaigns, conversion. Segment personas, A/B logic. ROI-focused. Language: Russian.",
    'finance': "You are Finance. Budgets, cashflow, taxes, P&L. Precise numbers, scenarios, risk buffers. Tables preferred. Language: Russian.",
    'legal': "You are Legal. Contracts, compliance, GDPR, NDA, IP. Flag risks, cite articles. Practical actionable advice. Language: Russian.",
    'dev': "You are Dev. Architecture, APIs, deployment, code review. Modern stack, clean code principles. Code blocks with explanations. Language: Russian.",
    'design': "You are Design. UI/UX, wireframes, design systems, user flows. Accessibility, mobile-first, consistency. Language: Russian.",
    'qa': "You are QA. Testing strategies, bug triage, quality metrics. Test cases, regression plans, coverage. Language: Russian.",
    'visual': "You are Visual. Infographics, data visualization, charts, presentations. Color theory, layout, clarity. Language: Russian.",
    'engineering': "You are Engineering. Structural calculations, load analysis, SNiP compliance. Safety factors, materials, drawings. Language: Russian.",
    'kavalnya': "You are Kavalnya. Methodology, department creation, polygon exercises. Frameworks, KPIs, org design. Language: Russian.",
    'admin': "You are Admin, System Agent. Health checks, config management, system diagnostics. Technical, precise, actionable. Language: Russian.",
}

FORMAT_INSTRUCTION = """

## ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО)

Отвечай РАЗВЁРНУТО (минимум 1000 символов). Структура:

1. Используй секции: "Слой 1 — ...", "Слой 2 — ..." и т.д. (минимум 3 слоя)
2. Маркируй каждое утверждение значками:
   - ✓ — подтверждённые данные, цифры, даты (факты)
   - ◈ — твой анализ и интерпретация на основе фактов
   - ⚡ — гипотезы, предположения, спекуляция
3. Завершай секцией "Вердикт" с ключевыми выводами
4. Если применимо — добавь "Индикаторы для наблюдения"
5. Язык: русский
6. Не будь кратким. Препарируй тему глубоко.
"""

# FORMAT_INSTRUCTION (layered analysis with ✓/◈/⚡) only for expert dept
# OSP format now comes from deconstruct skill (always loaded via LoadOspSkills in app.mlog)
_ANALYTICAL_DEPTS = {"expert"}

def get_dept_prompt(dept, combo=None):
    fmt = FORMAT_INSTRUCTION if dept in _ANALYTICAL_DEPTS else ""
    if combo and 'free' in combo:
        return CONDENSED_PROMPTS.get(dept, CONDENSED_PROMPTS['yana']) + fmt
    try:
        f = LIB_DIR / f"{dept}.md"
        if f.exists():
            return f.read_text(encoding="utf-8") + fmt
    except Exception:
        pass
    return CONDENSED_PROMPTS.get(dept, CONDENSED_PROMPTS['yana']) + fmt

# ──────────────────────────── CONFIG LOADING ────────────────────────────
_cfg_cache = {"priority_provider": "zai", "priority_model": None, "overrides": {}}

def _load_cfg():
    try:
        p = CFG_DIR / "priority_provider.txt"
        if p.exists(): _cfg_cache["priority_provider"] = p.read_text().strip().split()[0]
    except Exception: pass
    try:
        p = CFG_DIR / "priority_model.txt"
        if p.exists(): _cfg_cache["priority_model"] = p.read_text().strip()
    except Exception: pass
    for dept in DEPT_NAMES:
        try:
            p = CFG_DIR / f"override_{dept}.txt"
            if p.exists(): _cfg_cache["overrides"][dept] = p.read_text().strip()
        except Exception: pass

_load_cfg()

# ──────────────────────────── SQLITE SETUP ────────────────────────────
def _db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with db_lock:
        c = _db()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS miniapp_responses (id TEXT PRIMARY KEY, dept TEXT, title TEXT, query TEXT, raw_text TEXT DEFAULT '', html TEXT, confidence TEXT, created_at TEXT DEFAULT (datetime('now')), archived INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS miniapp_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, note_text TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS dept_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, metric_name TEXT, metric_value TEXT, period TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS token_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, provider TEXT, model TEXT, input_tokens TEXT, output_tokens TEXT, cost_usd TEXT, request_type TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT (datetime('now')), action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS dialog_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, dept TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS adapt_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, original_query TEXT, original_response TEXT, correction TEXT, corr_type TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS error_patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, error_type TEXT, query_text TEXT, correction TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS channel_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, dept TEXT, title TEXT, channel_message_id TEXT, archived_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT, file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS knowledge_edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT, edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS admin_findings (id INTEGER PRIMARY KEY AUTOINCREMENT, severity TEXT, category TEXT, file TEXT, issue TEXT, fix TEXT, status TEXT DEFAULT 'open', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS admin_proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, status TEXT DEFAULT 'pending', narad_id TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS admin_night_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_data TEXT, review_data TEXT, health_score INTEGER, findings_count INTEGER, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS lz_monitors (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, frequency TEXT DEFAULT 'daily', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS news_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, url TEXT, category TEXT DEFAULT 'general', language TEXT DEFAULT 'ru', published TIMESTAMP, collected TIMESTAMP DEFAULT CURRENT_TIMESTAMP, relevance_score REAL DEFAULT 0, hash TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS idx_news_category ON news_cache (category, collected DESC);
        CREATE INDEX IF NOT EXISTS idx_news_hash ON news_cache (hash);
        """)
        for col_sql, col_name in [
            ("ALTER TABLE token_usage ADD COLUMN compression_saved INTEGER DEFAULT 0", "compression_saved"),
            ("ALTER TABLE token_usage ADD COLUMN combo TEXT DEFAULT ''", "combo"),
            ("ALTER TABLE miniapp_responses ADD COLUMN archived INTEGER DEFAULT 0", "archived"),
        ]:
            try:
                c.execute(col_sql)
            except Exception:
                pass
        c.commit(); c.close()

init_db()

def _query(sql, params=(), fetch=False):
    with db_lock:
        try:
            c = _db()
            cur = c.execute(sql, params)
            if fetch:
                rows = cur.fetchall(); c.close(); return rows
            c.commit(); c.close()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return [] if fetch else None
            raise

def _get_setting(key, default=""):
    """Read a value from system_settings (shared kv with Metalogos)."""
    try:
        rows = _query("SELECT value FROM system_settings WHERE key = ?", (key,), fetch=True)
        if rows:
            return rows[0]["value"]
    except Exception as e:
        log.error(f"_get_setting({key}) failed: {e}")
    return default

def _log_audit(action, details_dict, dept="system"):
    _query("INSERT INTO audit_log (action,actor,dept,details,status) VALUES (?,'proxy',?,?,'ok')",
           (action, dept, json.dumps(details_dict, ensure_ascii=False)))

# ──────────────────────────── OSINT (Aliens Eye) ────────────────────────────
OSINT_DISCLAIMER = "⚠ OSINT-данные собраны из открытых источников. Результаты не гарантируют принадлежность аккаунтов конкретному лицу. Используйте для легитимных целей в рамках законодательства."
_osint_last_time = {}  # rate limiting: chat_id -> timestamp
OSINT_RATE_LIMIT = 60  # seconds between scans

def categorize_platform(site_name):
    """Категоризация платформы по типу."""
    categories = {
        'social': ['twitter', 'facebook', 'instagram', 'tiktok', 'snapchat', 'threads', 'mastodon', 'bluesky', 'x.com'],
        'professional': ['linkedin', 'xing', 'angellist', 'crunchbase'],
        'tech': ['github', 'gitlab', 'bitbucket', 'stackoverflow', 'hackernews', 'dev.to', 'codepen'],
        'media': ['youtube', 'twitch', 'vimeo', 'soundcloud', 'spotify', 'medium', 'substack'],
        'messaging': ['telegram', 'discord', 'slack', 'signal', 'whatsapp'],
        'commerce': ['amazon', 'ebay', 'etsy', 'shopify', 'aliexpress'],
        'gaming': ['steam', 'xbox', 'playstation', 'epic', 'roblox', 'minecraft'],
        'forum': ['reddit', 'quora', '4chan', 'hackforums'],
        'dating': ['tinder', 'bumble', 'okcupid'],
        'darknet': ['onion', 'tor', 'i2p'],
    }
    site_lower = site_name.lower()
    for category, platforms in categories.items():
        if any(p in site_lower for p in platforms):
            return category
    return 'other'


def scan_osint(username, level='basic', timeout=120, tor=False, sites=None):
    """Scan username across 840+ platforms via Aliens Eye."""
    cmd = ['aliens_eye', username, '--format', 'json', '--plain', '-l', level]
    if tor:
        cmd.extend(['--tor'])
    if sites:
        cmd.extend(['--site', ','.join(sites)])
    cmd.extend(['--no-nsfw'])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, 'NO_COLOR': '1'}
        )
        if result.returncode != 0:
            return {'error': f'Aliens Eye exited with code {result.returncode}', 'stderr': result.stderr[:500]}

        data = json.loads(result.stdout)
        results_list = data.get('results', [])
        found = [p for p in results_list if p.get('status') == 'Found']
        maybe = [p for p in results_list if p.get('status') == 'Maybe']

        return {
            'username': username,
            'found': len(found),
            'maybe': len(maybe),
            'total_scanned': len(results_list),
            'scan_time': data.get('elapsed', '?'),
            'platforms': [{
                'name': p.get('site', ''),
                'url': p.get('url', ''),
                'confidence': p.get('confidence', 0),
                'category': categorize_platform(p.get('site', ''))
            } for p in found],
            'uncertain': [{
                'name': p.get('site', ''),
                'url': p.get('url', ''),
                'confidence': p.get('confidence', 0)
            } for p in maybe],
        }
    except subprocess.TimeoutExpired:
        return {'error': f'Timeout after {timeout}s', 'username': username}
    except json.JSONDecodeError:
        return {'error': 'Failed to parse Aliens Eye output', 'raw': result.stdout[:500]}
    except FileNotFoundError:
        return {'error': 'aliens_eye binary not found. Install: pip3 install aliens-eye'}
    except Exception as e:
        return {'error': str(e)}


# ──────────────────────────── HTML STRIP FOR ARCHIVE ────────────────────────────
def strip_html_for_archive(html_content):
    """Convert HTML badges to text markers and strip all tags for Telegram."""
    text = html_content
    # Convert badge spans with known classes to text markers
    badge_map = {
        'badge-fact': '✓',
        'badge-int': '◈',
        'badge-interp': '◈',
        'badge-spec': '⚡',
        'badge-verified': '[FACT verified]',
        'badge-unverified': '[FACT unverified]',
        'badge-conflicting': '[CONFLICT]',
    }
    for cls, marker in badge_map.items():
        # Match <span class="badge badge-xxx">content</span>
        pattern = r'<span[^>]*class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"[^>]*>(.*?)</span>'
        text = re.sub(pattern, marker + r' \1 ', text, flags=re.IGNORECASE | re.DOTALL)
    # Also match class="badge badge-xxx" without space (single class)
    for cls, marker in badge_map.items():
        pattern2 = r'<span[^>]*class="' + re.escape(cls) + r'"[^>]*>(.*?)</span>'
        text = re.sub(pattern2, marker + r' \1 ', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove all remaining HTML tags
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ──────────────────────────── LLM CALL (combo chains + compression) ────────────────────────────
def call_llm(dept, messages, model_override=None, combo=None, command='', depth=2):
    """Call LLM via native combo chain with circuit breaker and token compression.
    
    Flow:
    1. Apply token compression if messages are too long
    2. Select combo chain (or use model_override for direct single-provider call)
    3. Walk the chain: for each (provider, [models]), try each model until one works
    4. Circuit breaker skips providers with recent consecutive failures
    5. If combo chain exhausted, fall back to legacy priority-provider ordering
    """
    # 1. Token compression
    messages, compression_saved = _compress_messages(messages, dept)

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

    # 4. Walk combo chain
    chain = COMBO_CHAINS.get(combo, COMBO_CHAINS["fosved-standard"])
    for prov_name, models in chain:
        if not _breaker.can_call(prov_name):
            continue
        for model in models:
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
        elif prov_name == "groq" and not any(m in use_model for m in ("llama", "mixtral", "gemma")):
            use_model = "llama-3.3-70b-versatile"
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

# ──────────────────────────── TELEGRAM HELPERS ────────────────────────────
def _tg_send_message(chat_id, text, parse_mode=None):
    """Send a text message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send message")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = http_requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
    except Exception as e:
        log.error(f"Telegram sendMessage failed: {e}")
    return None

def _tg_send_voice(chat_id, voice_path):
    """Send a voice file via Telegram Bot API using multipart upload."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send voice")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"
    try:
        with open(voice_path, "rb") as f:
            resp = http_requests.post(url, data={"chat_id": chat_id}, files={"voice": f}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
    except Exception as e:
        log.error(f"Telegram sendVoice failed: {e}")
    return None

def _tg_send_report_with_button(chat_id, text, button_text="Otkryt otchet", button_url=None):
    """Send text with an inline button via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send report")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    reply_markup = {
        "inline_keyboard": [[{"text": button_text, "url": button_url or "https://t.me/FosvedMiniApp"}]]
    }
    payload = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
    try:
        resp = http_requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
    except Exception as e:
        log.error(f"Telegram sendReport failed: {e}")
    return None

def _tg_get_file(file_id):
    """Get file path from Telegram Bot API given a file_id."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
    try:
        resp = http_requests.get(url, params={"file_id": file_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok") and data.get("result", {}).get("file_path"):
            return data["result"]["file_path"]
    except Exception as e:
        log.error(f"Telegram getFile failed: {e}")
    return None

def _tg_download_file(file_path):
    """Download a file from Telegram Bot API given its file_path."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    try:
        resp = http_requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        log.error(f"Telegram file download failed: {e}")
    return None

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


def _tg_send_photo(chat_id, photo_path, caption=None):
    """Send a photo via Telegram Bot API using multipart upload."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send photo")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            payload = {'chat_id': chat_id}
            if caption:
                payload['caption'] = caption[:1000]
            resp = http_requests.post(url, data=payload, files={'photo': f}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get('ok'):
            return data['result'].get('message_id')
    except Exception as e:
        log.error(f"Telegram sendPhoto failed: {e}")
    return None


def _tg_send_document(chat_id, file_path, caption=None):
    """Send a document via Telegram Bot API using multipart upload."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send document")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
            resp = http_requests.post(url, data=data, files={"document": f}, timeout=60)
            resp.raise_for_status()
            j = resp.json()
            if j.get("ok"):
                return j["result"].get("message_id")
            log.error(f"sendDocument not ok: {j}")
    except Exception as e:
        log.error(f"Telegram sendDocument failed: {e}")
    return None


def _safe_filename_part(s, maxlen=40):
    """Make a filesystem/Telegram-safe filename fragment from arbitrary text."""
    s = (s or "").strip()
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_ ":
            out.append(ch)
        else:
            out.append(" ")
    cleaned = " ".join("".join(out).split())
    cleaned = cleaned.replace(" ", "_")
    return cleaned[:maxlen] or "report"


# ──────────────────────────── MEMORIZE HELPER ────────────────────────────
def _memorize(dept, topic, content):
    """Save a finding to dialog_history as a system memorization entry."""
    now = datetime.utcnow().isoformat()
    entry = f"[MEMORY] {topic}: {content}"
    _query("INSERT INTO dialog_history (dept, chat_id, role, content, created_at) VALUES (?, '0', 'system', ?, ?)",
           (dept, entry, now))

# ──────────────────────────── HTML HELPERS ────────────────────────────
def _html_base(title, bg="#0F0F0F"):
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<title>{title}</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',system-ui,sans-serif;background:{bg};color:#F8F7F4;min-height:100vh}}
h1,h2,h3{{font-family:'Cormorant Garamond',serif;font-weight:700}}
.badge{{font-family:'DM Mono',monospace;font-size:0.85rem;padding:1px 6px;border-radius:4px;display:inline-block;letter-spacing:-1px}}
.badge-fact{{background:#dcfce7;color:#16a34a}} .badge-interp{{background:#dbeafe;color:#2563eb}}
.badge-int{{background:#dbeafe;color:#2563eb}} .badge-spec{{background:#fef9c3;color:#ca8a04}}
.badge-verified{{background:#d1fae5;color:#059669}} .badge-unverified{{background:#fef3c7;color:#d97706}}
.badge-conflicting{{background:#fee2e2;color:#dc2626}}
.card{{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:20px}}
.kpi{{text-align:center;padding:16px}} .kpi .num{{font-size:2rem;font-weight:700;font-family:'DM Mono',monospace}}
.kpi .lbl{{font-size:0.75rem;color:#999;margin-top:4px;text-transform:uppercase;letter-spacing:1px}}
.gold{{color:#C9A84C}} .status-red{{color:#E24B4A}} .status-yellow{{color:#EF9F27}} .status-green{{color:#639922}} .status-blue{{color:#185FA5}}
table{{width:100%;border-collapse:collapse;margin:12px 0}} th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid #2a2a2a;font-size:0.85rem}}
th{{color:#999;font-weight:500;text-transform:uppercase;font-size:0.7rem;letter-spacing:1px}}
a{{color:#C9A84C;text-decoration:none}} a:hover{{text-decoration:underline}}
.grid{{display:grid;gap:16px}} .grid-3{{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}}
.grid-4{{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}}
.header-grad{{padding:32px 40px;border-radius:16px;margin:20px 24px;color:#fff}}
.section{{padding:0 24px;margin-top:24px}} .section h2{{margin-bottom:16px;font-size:1.4rem}}
.mono{{font-family:'DM Mono',monospace}}
</style></head><body>"""

def _dept_header(dept, title_extra=""):
    c = DEPT_COLORS.get(dept, DEPT_COLORS['admin'])
    name = DEPT_NAMES.get(dept, dept)
    return f'<div class="header-grad" style="background:linear-gradient(135deg,{c["start"]},{c["end"]})">' \
           f'<h1>{name} {title_extra}</h1><p style="color:{c["accent"]};font-size:0.9rem;margin-top:8px">Department Dashboard</p></div>'

def _status_icon(level):
    colors = {"high": "#639922", "medium": "#EF9F27", "low": "#E24B4A"}
    return f'<span style="color:{colors.get(level,"#999")};font-size:1.5rem">{"&#x1F7E2;" if level=="high" else "&#x1F7E1;" if level=="medium" else "&#x1F534;"}</span>'

def _dept_kpis(dept):
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).isoformat()
    rows_m = _query("SELECT COUNT(*) as c, COALESCE(AVG(CAST(metric_value AS REAL)),0) as avg_r FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
    rows_t = _query("SELECT COALESCE(SUM(input_tokens),0) as ti, COALESCE(SUM(output_tokens),0) as to2 FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
    rows_d = _query("SELECT COUNT(*) as c FROM dialog_history WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
    m = rows_m[0] if rows_m else {"c": 0, "avg_r": 0}
    t = rows_t[0] if rows_t else {"ti": 0, "to2": 0}
    d = rows_d[0] if rows_d else {"c": 0}
    return f"""<div class="grid grid-4" style="margin:20px 24px">
<div class="card kpi"><div class="num gold">{m['c']}</div><div class="lbl">Reiting / ned</div></div>
<div class="card kpi"><div class="num" style="color:#16a34a">{m['avg_r']:.1f}</div><div class="lbl">Sr. otsenka</div></div>
<div class="card kpi"><div class="num status-blue">{(t['ti']+t['to2']):,}</div><div class="lbl">Tokeny / ned</div></div>
<div class="card kpi"><div class="num">{d['c']}</div><div class="lbl">Dialogi / ned</div></div></div>"""

# ══════════════════════════════════════════════════════════════════════
#  ROUTES — ORIGINAL ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return jsonify({"status": "ok", "circuit_breaker": _breaker.status(), "combos": list(COMBO_CHAINS.keys())})

@app.get("/now-time")
def now_time_endpoint():
    """Return current date/time in human-readable form for Yana prompt injection.
    Timezone: Europe/Minsk (UTC+3 year-round) — configured via TZ env var."""
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo("Europe/Minsk")
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    weekdays_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    human = (f"{now.day} {months_ru[now.month-1]} {now.year}, "
             f"{weekdays_ru[now.weekday()]}, "
             f"{now.strftime('%H:%M')}")
    return jsonify({"time": human, "iso": now.isoformat(), "unix": now.timestamp()})

# ── Weather cache (30 min) ──
_weather_cache = {"text": "", "ts": 0.0}

@app.get("/now-weather")
def now_weather_endpoint():
    """Return current weather for Minsk. Cached 30 min."""
    import time as _time
    now = _time.time()
    if _weather_cache["text"] and (now - _weather_cache["ts"]) < 1800:
        return jsonify({"weather": _weather_cache["text"]})
    try:
        r1 = http_requests.get("https://wttr.in/Minsk?format=%C+%t+%w+%h&lang=ru", timeout=10)
        r2 = http_requests.get("https://wttr.in/Minsk?format=3&lang=ru", timeout=10)
        parts = []
        if r1.ok:
            parts.append(r1.text.strip())
        if r2.ok:
            parts.append(r2.text.strip())
        weather = " | ".join(parts) if parts else "Погода недоступна"
    except Exception:
        weather = "Погода недоступна"
    _weather_cache["text"] = weather
    _weather_cache["ts"] = now
    return jsonify({"weather": weather})

@app.post("/detect-dept")
def detect_dept_endpoint():
    d = request.get_json(force=True)
    text = d.get("text", "")
    dept = detect_dept(text)
    return jsonify({"dept": dept})

@app.post("/ask")
def ask():
    d = request.get_json(force=True)
    dept = d.get("dept", "yana")
    messages = d.get("messages", [])
    model_ov = d.get("model")
    # DEBUG: log system prompt to find FORMAT_INSTRUCTION source
    for m in messages:
        if m.get("role") == "system":
            sys_text = m.get("content", "")
            has_format = "ФОРМАТ ОТВЕТА" in sys_text or "Слой 1" in sys_text
            log.info(f"ASK dept={dept} sys_len={len(sys_text)} has_format={has_format} first200={sys_text[:200]}")
            if has_format:
                # Find exactly where FORMAT_INSTRUCTION appears
                idx = sys_text.find("ФОРМАТ ОТВЕТА")
                if idx < 0: idx = sys_text.find("Слой 1")
                log.info(f"FORMAT found at char {idx}, context: ...{sys_text[max(0,idx-50):idx+100]}...")
    if not messages:
        return jsonify({"reply": "[Oshibka] Net soobshenii", "provider": None, "model": None, "tokens_in": 0, "tokens_out": 0}), 400
    result = call_llm(dept, messages, model_ov)
    if dept == "osp" and "reply" in result:
        import re as _re
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        try:
            _tz = _ZI("Europe/Minsk")
        except Exception:
            _tz = _ZI("UTC")
        _today = _dt.now(_tz).strftime("%Y-%m-%d")
        _reply = result["reply"]
        _reply = _re.sub(
            r'(Дата препарирования:\s*)\d{4}-\d{2}-\d{2}',
            r'\g<1>' + _today, _reply
        )
        _reply = _re.sub(
            r'(Сейчас:\s*)\d{4}-\d{2}-\d{2}',
            r'\g<1>' + _today, _reply
        )
        _reply = _re.sub(
            r'(Темпоральная якорная точка:\s*Сейчас:\s*)\d{4}-\d{2}-\d{2}',
            r'\g<1>' + _today, _reply
        )
        result["reply"] = _reply
    return jsonify(result)

@app.post("/rate_cmd")
def rate_cmd():
    d = request.get_json(force=True)
    dept, rating = d.get("dept", "yana"), d.get("rating", 0)
    _query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES (?,'satisfaction',?,?,?)", (dept, str(rating), 'daily', datetime.utcnow().isoformat()))
    return jsonify({"status": "ok"})

@app.post("/context_cmd")
def context_cmd():
    d = request.get_json(force=True)
    dept, chat_id = d.get("dept", "yana"), d.get("chat_id", "0")
    rows = _query("SELECT role,content,created_at FROM dialog_history WHERE dept=? AND chat_id=? ORDER BY id DESC LIMIT 20", (dept, chat_id), fetch=True)
    corrs = _query("SELECT original_query,correction,created_at FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 10", (dept,), fetch=True)
    ctx = {"dialog": [{"role": r["role"], "content": r["content"], "ts": r["created_at"]} for r in reversed(rows)]}
    ctx["corrections"] = [{"original": r["original_query"], "corrected": r["correction"], "ts": r["created_at"]} for r in corrs]
    return jsonify(ctx)

@app.post("/voice-set")
def voice_set():
    d = request.get_json(force=True)
    _log_audit("voice_set", d)
    return jsonify({"status": "ok"})

@app.post("/archive/digest")
def archive_digest():
    d = request.get_json(force=True)
    _log_audit("digest", d)
    return jsonify({"status": "ok", "digest_id": hashlib.md5(json.dumps(d).encode()).hexdigest()[:8]})

def _build_action_bar(dept, doc_id, existing_notes_html=""):
    """Build action bar HTML + JS for Mini App reports."""
    osp_buttons = ""
    osp_menus = ""
    if dept == "osp":
        osp_buttons = '''
<button class="action-btn primary" onclick="doAction('journalist')"><span class="icon">✏️</span>Журналист</button>
<button class="action-btn" onclick="toggleMenu('depthMenu')"><span class="icon">🔍</span>Погружение</button>
<button class="action-btn" onclick="toggleMenu('controlMenu')"><span class="icon">📌</span>На контроль</button>
<button class="action-btn danger" onclick="doAction('counter_forecast')"><span class="icon">⚡</span>Контр-прогноз</button>'''
        osp_menus = '''
<div class="depth-menu" id="depthMenu">
  <div class="depth-option" onclick="doDepth(1)"><div class="depth-dot" style="background:#94a3b8"></div><div><b>Быстрая оценка</b><br><span style="font-size:11px;color:#64748b">2-3 слоя</span></div></div>
  <div class="depth-option" onclick="doDepth(2)"><div class="depth-dot" style="background:#3b82f6"></div><div><b>Стандартный</b><br><span style="font-size:11px;color:#64748b">5-7 слоёв, ACH</span></div></div>
  <div class="depth-option" onclick="doDepth(3)"><div class="depth-dot" style="background:#f59e0b"></div><div><b>Глубокое</b><br><span style="font-size:11px;color:#64748b">8-10 слоёв, premortem</span></div></div>
  <div class="depth-option" onclick="doDepth(4)"><div class="depth-dot" style="background:#dc2626"></div><div><b>Полное + Red Team</b><br><span style="font-size:11px;color:#64748b">12+ слоёв, контр-анализ</span></div></div>
</div>
<div class="control-menu" id="controlMenu">
  <div class="control-option" onclick="doControl('daily')">📅 Ежедневно</div>
  <div class="control-option" onclick="doControl('weekly')">📆 Еженедельно</div>
  <div class="control-option" onclick="doControl('monthly')">🗓 Ежемесячно</div>
</div>'''

    return f'''
{osp_menus}
<div class="action-bar{' osp-bar' if dept == 'osp' else ''}">
{osp_buttons}
<button class="action-btn" onclick="doAction('archive')"><span class="icon">📥</span>В архив</button>
<button class="action-btn" onclick="copyText()"><span class="icon">📋</span>Копировать</button>
<button class="action-btn" onclick="window.print()"><span class="icon">📄</span>PDF</button>
<button class="action-btn" onclick="shareReport()"><span class="icon">📤</span>Поделиться</button>
</div>
<div class="notes-section">
<div class="notes-title">Важные замечания</div>
<div class="notes-list" id="notesList">{existing_notes_html}</div>
<div class="notes-input">
<input type="text" id="noteInput" placeholder="Добавить замечание..." onkeydown="if(event.key==='Enter')addNote()"/>
<button onclick="addNote()">+</button>
</div>
</div>
<script>
var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
var docId = "{doc_id}";
var _apiSecret = '{{API_SECRET}}';
if(tg) tg.ready();

function copyText(){{
  var body = document.querySelector('.report-body');
  if(body) navigator.clipboard.writeText(body.innerText).then(function(){{ alert('Скопировано') }});
}}
function shareReport(){{
  if(navigator.share) navigator.share({{title:document.title, url:location.href}});
  else if(tg) tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(location.href));
  else alert('Ссылка: '+location.href);
}}
function addNote(){{
  var input=document.getElementById('noteInput');
  var text=input.value.trim();
  if(!text)return;
  var list=document.getElementById('notesList');
  var now=new Date().toLocaleTimeString('ru-RU',{{hour:'2-digit',minute:'2-digit'}});
  list.innerHTML+='<div class="note-item"><span>'+text+'</span><span class="note-time">'+now+'</span></div>';
  input.value='';
  fetch('/miniapp/note',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{doc_id:docId,note_text:text}})}});
}}
function doAction(action){{
  fetch('/webhook/miniapp-action',{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+_apiSecret}},body:JSON.stringify({{action:action,doc_id:docId}})}}).then(function(r){{if(r.ok)alert(action+' выполнен');else alert('Ошибка: '+r.status)}}).catch(function(){{alert('Сетевая ошибка')}});
}}
function toggleMenu(id){{
  var m=document.getElementById(id);
  if(m)m.style.display=m.style.display==='none'?'block':'none';
}}
function doDepth(level){{
  document.getElementById('depthMenu').style.display='none';
  doAction('deepen_to_'+level);
}}
function doControl(freq){{
  document.getElementById('controlMenu').style.display='none';
  doAction('control_'+freq);
}}
</script>'''


@app.get("/miniapp/<doc_id>")
@app.get("/miniapp/<doc_id>/")
@require_telegram
def miniapp_get(doc_id):
    try:
        return _miniapp_get_inner(doc_id)
    except Exception as e:
        log.error(f"miniapp_get crash for {doc_id}: {e}", exc_info=True)
        return f"<h1>Ошибка рендеринга</h1><p>{html_lib_escape(str(e))}</p><p>ID: {html_lib_escape(doc_id)}</p>", 500

def _miniapp_get_inner(doc_id):
    rows = _query("SELECT html,title,created_at,dept,raw_text FROM miniapp_responses WHERE id=?", (doc_id,), fetch=True)
    if not rows:
        return "<h1>Not found</h1>", 404
    r = rows[0]
    dept = r["dept"] or "admin"
    # Load notes for this doc
    notes_rows = _query("SELECT note_text, created_at FROM miniapp_notes WHERE doc_id=? ORDER BY id", (doc_id,), fetch=True) or []
    notes_html = "".join(f'<div class="note-item"><span>{html_lib_escape(n["note_text"])}</span><span class="note-time">{(n["created_at"] or "")[-8:-3]}</span></div>' for n in notes_rows)
    action_bar = _build_action_bar(dept, doc_id, notes_html)
    # Rich post-processor: enrich any non-trivial raw_text
    raw = r["raw_text"] or ""
    if raw and len(raw) > 100 and _has_enricher:
        accent = DEPT_COLORS.get(dept, {}).get("accent", "#6366f1")
        try:
            enriched_body = auto_enrich(raw, dept=dept, accent_color=accent)
        except Exception as e:
            log.warning(f"miniapp enrich failed for {doc_id}: {e}")
            enriched_body = None
        if enriched_body and len(enriched_body) > len(raw) * 0.5:
            # Rebuild full HTML with enriched body
            css_path = BASE_DIR / "report_css.txt"
            css = css_path.read_text() if css_path.exists() else ""
            c = DEPT_COLORS.get(dept, DEPT_COLORS["admin"])
            name = DEPT_NAMES.get(dept, dept)
            title = r["title"] or doc_id
            created = r["created_at"] or ""
            disclaimer = ""
            if dept == "finance":
                disclaimer = '<div class="disclaimer-rich">Не является финансовой консультацией. Обратитесь к лицензированному специалисту.</div>'
            elif dept == "legal":
                disclaimer = '<div class="disclaimer-rich">Не является юридической консультацией. Обратитесь к лицензированному юристу.</div>'
            elif dept == "engineering":
                disclaimer = '<div class="disclaimer-rich">Требует review лицензированного инженера. Не использовать для строительства без проверки.</div>'
            html = f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>{css}
body {{ font-family:'DM Sans',sans-serif; color:#1e293b; background:#F8F7F4; margin:0; }}
</style></head><body>
<div class="report-container">
<div class="report-header" style="background:linear-gradient(135deg,{c['start']},{c['end']})">
  <h1>{html_lib_escape(name)}</h1>
  <div class="subtitle">{html_lib_escape(title)}</div>
</div>
<div class="report-meta"><span>ID: {html_lib_escape(doc_id)}</span><span>{html_lib_escape(created)}</span></div>
<div class="report-body">{enriched_body}</div>
{disclaimer}
{action_bar}
</div></body></html>'''
            html = html.replace('{{API_SECRET}}', API_SECRET)
            return Response(html, mimetype="text/html")
    # Fallback: return stored HTML with action bar injected
    stored_html = r["html"] or ""
    if not stored_html:
        # No stored HTML at all — render raw_text as plain HTML
        raw_fallback = r["raw_text"] or "Отчёт пуст"
        stored_html = f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script></head><body>
<div style="padding:16px;font-family:sans-serif;color:#1e293b;white-space:pre-wrap">{html_lib_escape(raw_fallback)}</div>
{action_bar}</body></html>'''
    if "</body>" in stored_html:
        stored_html = stored_html.replace("</body>", f"{action_bar}</body>")
    stored_html = stored_html.replace('{{API_SECRET}}', API_SECRET)
    return Response(stored_html, mimetype="text/html")


ARCHIVE_MONTHS_RU = {
    "01": "Январь", "02": "Февраль", "03": "Март", "04": "Апрель",
    "05": "Май", "06": "Июнь", "07": "Июль", "08": "Август",
    "09": "Сентябрь", "10": "Октябрь", "11": "Ноябрь", "12": "Декабрь",
}


def _browse_page(title, crumbs, items, back_href, tg_suffix=""):
    """Render one level of the archive browser.

    tg_suffix is appended to all internal links so tgWebAppData survives
    navigation inside the Telegram Mini App.
    """
    rows = []
    for it in items:
        e_name = html_lib.escape(str(it.get("name", "")))
        e_sub = html_lib.escape(str(it.get("sub", "")))
        raw_href = str(it.get("href", ""))
        # Append tg_suffix: use ? if no query string yet, & otherwise
        if tg_suffix and "?" not in raw_href:
            full_href = raw_href + "?" + tg_suffix
        else:
            full_href = raw_href + ("&" + tg_suffix if tg_suffix else "")
        e_href = html_lib.escape(full_href, quote=True)
        sub = f'<span class="sub">{e_sub}</span>' if it.get("sub") else ""
        rows.append(
            f'<a class="row" href="{e_href}"><span class="name">{e_name}</span>{sub}</a>'
        )
    body = "".join(rows) or '<div class="empty">Пусто</div>'
    # Append tg_suffix to back link too
    if back_href:
        if tg_suffix and "?" not in back_href:
            back_full = back_href + "?" + tg_suffix
        else:
            back_full = back_href + ("&" + tg_suffix if tg_suffix else "")
        back = f'<a class="back" href="{html_lib.escape(back_full, quote=True)}">← Назад</a>'
    else:
        back = ""
    e_title = html_lib.escape(str(title))
    e_crumbs = html_lib.escape(str(crumbs))
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e_title}</title>
<style>
body{{margin:0;padding:16px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
background:#17212b;color:#e9edf2}}
h1{{font-size:18px;margin:0 0 4px}}
.crumbs{{font-size:13px;color:#8fa3b8;margin-bottom:16px}}
.row{{display:flex;justify-content:space-between;align-items:center;gap:12px;
padding:14px 12px;margin-bottom:8px;background:#1f2b38;border-radius:10px;
text-decoration:none;color:#e9edf2}}
.row:active{{background:#26374a}}
.name{{font-size:15px;overflow:hidden;text-overflow:ellipsis}}
.sub{{font-size:13px;color:#8fa3b8;white-space:nowrap}}
.empty{{color:#8fa3b8;padding:20px 0}}
.back{{display:inline-block;margin-bottom:14px;color:#5aa9e6;text-decoration:none;font-size:14px}}
</style></head><body>
{back}<h1>{e_title}</h1><div class="crumbs">{e_crumbs}</div>{body}
</body></html>"""


@app.get("/archive/browse")
@require_telegram
def archive_browse():
    """Browse archived reports: year -> month -> dept -> documents."""
    year = (request.args.get("year") or "").strip()
    month = (request.args.get("month") or "").strip()
    dept = (request.args.get("dept") or "").strip()
    # Preserve tgWebAppData across navigation inside Mini App
    tg = request.args.get("tgWebAppData", "")
    tg_suffix = ("tgWebAppData=" + html_lib.escape(tg, quote=True)) if tg else ""
    try:
        if not year:
            rows = _query(
                "SELECT substr(created_at,1,4) AS y, COUNT(*) AS n FROM miniapp_responses "
                "WHERE created_at IS NOT NULL AND created_at != '' GROUP BY y ORDER BY y DESC",
                (), fetch=True) or []
            items = [{"name": r["y"], "sub": f'{r["n"]} шт.',
                      "href": f'/archive/browse?year={r["y"]}'} for r in rows]
            return _browse_page("Архив", "Годы", items, "", tg_suffix)

        if not month:
            rows = _query(
                "SELECT substr(created_at,6,2) AS m, COUNT(*) AS n FROM miniapp_responses "
                "WHERE substr(created_at,1,4) = ? GROUP BY m ORDER BY m DESC",
                (year,), fetch=True) or []
            items = [{"name": ARCHIVE_MONTHS_RU.get(r["m"], r["m"]), "sub": f'{r["n"]} шт.',
                      "href": f'/archive/browse?year={year}&month={r["m"]}'} for r in rows]
            return _browse_page(year, "Месяцы", items, "/archive/browse", tg_suffix)

        if not dept:
            rows = _query(
                "SELECT dept, COUNT(*) AS n FROM miniapp_responses "
                "WHERE substr(created_at,1,4) = ? AND substr(created_at,6,2) = ? "
                "GROUP BY dept ORDER BY n DESC",
                (year, month), fetch=True) or []
            items = [{"name": r["dept"] or "—", "sub": f'{r["n"]} шт.',
                      "href": f'/archive/browse?year={year}&month={month}&dept={r["dept"]}'}
                     for r in rows]
            return _browse_page(f'{ARCHIVE_MONTHS_RU.get(month, month)} {year}', "Отделы",
                                items, f"/archive/browse?year={year}", tg_suffix)

        rows = _query(
            "SELECT id, title, created_at FROM miniapp_responses "
            "WHERE substr(created_at,1,4) = ? AND substr(created_at,6,2) = ? AND dept = ? "
            "ORDER BY created_at DESC",
            (year, month, dept), fetch=True) or []
        items = [{"name": (r["title"] or r["id"])[:80], "sub": (r["created_at"] or "")[:10],
                  "href": f'/miniapp/{r["id"]}'} for r in rows]
        return _browse_page(f'{dept} · {ARCHIVE_MONTHS_RU.get(month, month)} {year}',
                            "Отчёты", items,
                            f"/archive/browse?year={year}&month={month}", tg_suffix)
    except Exception as e:
        log.error(f"archive_browse error: {e}")
        return _browse_page("Архив", "Ошибка", [], "/archive/browse", tg_suffix), 500


@app.post("/miniapp/note")
def miniapp_note():
    d = request.get_json(force=True)
    _query("INSERT INTO miniapp_notes (doc_id,note_text,created_at) VALUES (?,?,?)",
           (d.get("doc_id", ""), d.get("note_text", ""), datetime.utcnow().isoformat()))
    return jsonify({"status": "ok"})

@app.post("/webhook/miniapp-action")
def miniapp_action():
    """Handle Mini App action bar button clicks (Journalist, Depth, Control, Counter)."""
    d = request.get_json(force=True)
    action = d.get("action", "")
    doc_id = d.get("doc_id", "")
    if not doc_id:
        return jsonify({"status": "error", "msg": "no doc_id"}), 400
    
    rows = _query("SELECT raw_text, title, dept FROM miniapp_responses WHERE id=?", (doc_id,), fetch=True)
    if not rows:
        return jsonify({"status": "error", "msg": "doc not found"}), 404
    r = rows[0]
    raw = r["raw_text"] or ""
    title = r["title"] or ""
    dept = r["dept"] or "osp"
    
    if action == "journalist":
        prompt = f"""Ты — журналист-аналитик. Перепиши следующий аналитический отчёт в формат журналистской статьи.
Без служебных реквизитов, без бейджей [ФАКТ]/[ИНТЕРПРЕТАЦИЯ]/[СПЕКУЛЯЦИЯ].
Живой язык, понятный обычному читателю. Лид-абзац + контекст + основная часть + вывод.
1000-1500 слов. Заголовок — яркий, журналистский."""
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": prompt + "\n\nИсходный отчёт:\n" + raw}]
        result = call_llm("osp", messages)
        return jsonify({"status": "ok", "reply": result.get("reply", ""), "action": "journalist"})
    
    elif action.startswith("deepen_to_"):
        level = action.split("_")[-1]
        depth_map = {"1": "Быстрая оценка. 2-3 слоя.", "2": "Стандартный анализ. 5-7 слоёв. ACH 3 гипотезы.",
                     "3": "Глубокое. 8-10 слоёв. ACH 5 гипотез. Premortem. Кантильоновский анализ.",
                     "4": "Полное + Red Team. 12+ слоёв. ACH, premortem, кантильон, source triangulation. Контраргументы."}
        instruction = depth_map.get(level, "Стандартный анализ.")
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": instruction + "\n\nПредыдущий анализ:\n" + raw + "\n\nУглуби до уровня " + level}]
        result = call_llm("osp", messages)
        return jsonify({"status": "ok", "reply": result.get("reply", ""), "action": "deepen", "level": level})
    
    elif action.startswith("control_"):
        freq = action.split("_", 1)[1]
        _query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES ('osp','control_watch',?,?,?)",
               (doc_id, freq, datetime.utcnow().isoformat()))
        return jsonify({"status": "ok", "action": "control", "frequency": freq, "doc_id": doc_id})
    
    elif action == "counter_forecast":
        prompt = """Ты — контр-аналитик. Построй максимально противоположный прогноз:
- Найди слабые места исходного прогноза
- Построй альтернативный сценарий
- Используй те же факты, но с противоположной интерпретацией
- Оцени вероятность контр-сценария
- Укажи индикаторы реализации контр-сценария
- Формат: ACH с минимум 3 контр-гипотезами"""
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": prompt + "\n\nИсходный анализ:\n" + raw}]
        result = call_llm("osp", messages)
        return jsonify({"status": "ok", "reply": result.get("reply", ""), "action": "counter_forecast"})
    
    elif action == "archive":
        _query("UPDATE miniapp_responses SET archived=1 WHERE id=?", (doc_id,))
        return jsonify({"status": "ok", "action": "archive", "doc_id": doc_id})
    
    elif action == "crisis_protocol":
        prompt = """Ты — кризис-аналитик. Проанализируй данный отчёт с точки зрения кризисных рисков:
- Выдели все потенциальные кризисы и точки перелома
- Оцени вероятность и сроки наступления каждого (30/60/90/180 дней)
- Для каждого кризиса укажи индикаторы-предвестники
- Построй дерево решений: что делать при реализации каждого сценария
- Выдели критический путь: какой кризис наиболее вероятен и наиболее опасен
- Формат: структурированный отчёт с заголовками"""
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": prompt + "\n\nОтчёт:\n" + raw}]
        result = call_llm("osp", messages)
        return jsonify({"status": "ok", "reply": result.get("reply", ""), "action": "crisis_protocol"})
    
    return jsonify({"status": "error", "msg": f"unknown action: {action}"}), 400

@app.post("/enrich")
def enrich_endpoint():
    """Rich post-processor endpoint for Metalogos. Accepts raw markdown, returns enriched HTML."""
    d = request.get_json(force=True)
    raw_text = d.get("text", "")
    dept = d.get("dept", "admin")
    accent = DEPT_COLORS.get(dept, {}).get("accent", "#6366f1")
    enriched = auto_enrich(raw_text, dept=dept, accent_color=accent)
    return jsonify({"enriched": enriched, "has_metrics": "metric-card" in enriched})

@app.post("/tg-send")
def tg_send():
    """Send Telegram message with auto-split for texts >4096 chars."""
    d = request.get_json(force=True)
    chat_id = d.get("chat_id", "")
    text = d.get("text", "")
    if not chat_id or not text:
        return jsonify({"status": "error", "msg": "missing chat_id or text"})
    TG_MAX = 4096
    if len(text) <= TG_MAX:
        msg_id = _tg_send_message(chat_id, text)
        return jsonify({"status": "ok", "msg_id": msg_id, "parts": 1})
    # Split at last newline before 4096
    parts = []
    while len(text) > TG_MAX:
        cut = text.rfind("\n", 0, TG_MAX)
        if cut < TG_MAX // 2:
            cut = TG_MAX
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    msg_ids = []
    for i, part in enumerate(parts):
        mid = _tg_send_message(chat_id, part)
        if mid:
            msg_ids.append(mid)
    return jsonify({"status": "ok", "msg_ids": msg_ids, "parts": len(parts)})

@app.post("/tg-send-report-file")
def tg_send_report_file():
    """Send a stored report as an .html document to the owner chat."""
    d = request.get_json(force=True)
    doc_id = d.get("doc_id", "")
    chat_id = d.get("chat_id", "")
    caption = d.get("caption", "")
    if not doc_id or not chat_id:
        return jsonify({"status": "error", "message": "doc_id and chat_id are required"}), 400
    try:
        rows = _query("SELECT dept, title, html, created_at FROM miniapp_responses WHERE id = ?",
                      (doc_id,), fetch=True)
        if not rows:
            return jsonify({"status": "error", "message": "doc not found"}), 404
        r = rows[0]
        html = r["html"] or ""
        dept = r["dept"] or "report"
        title = r["title"] or ""
        created = (r["created_at"] or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
        fname = f"{created}_{_safe_filename_part(dept, 20)}_{_safe_filename_part(title)}.html"
        fpath = os.path.join("/tmp", fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)
        msg_id = _tg_send_document(chat_id, fpath, caption)
        try:
            os.remove(fpath)
        except Exception:
            pass
        if not msg_id:
            # Attachment failed: fall back to plain text so the owner is not left with silence
            fallback_text = caption or f"Отчёт готов: {title or doc_id}"
            text_msg_id = _tg_send_message(chat_id, fallback_text)
            _log_audit("report_file_fallback", {"doc_id": doc_id, "dept": dept,
                                                "msg_id": text_msg_id})
            if text_msg_id:
                return jsonify({"status": "ok", "msg_id": text_msg_id, "mode": "text"})
            return jsonify({"status": "error", "message": "sendDocument and sendMessage failed"}), 502
        _log_audit("report_file_sent", {"doc_id": doc_id, "dept": dept, "msg_id": msg_id})
        return jsonify({"status": "ok", "msg_id": msg_id})
    except Exception as e:
        log.error(f"tg_send_report_file error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.get("/dept-dashboard/<slug>")
@require_telegram
def dept_dashboard(slug):
    dept = slug.lower()
    if dept not in DEPT_NAMES:
        return "<h1>Unknown department</h1>", 404
    rows_corr = _query("SELECT original_query,correction,created_at FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 5", (dept,), fetch=True)
    override = _cfg_cache["overrides"].get(dept, "default")
    html = _html_base(f"Dashboard — {DEPT_NAMES[dept]}")
    html += _dept_header(dept)
    html += _dept_kpis(dept)
    html += '<div class="section"><h2>Poslednie korrektirovki</h2>'
    if rows_corr:
        html += '<table><tr><th>Original</th><th>Korrektirovka</th><th>Data</th></tr>'
        for r in rows_corr:
            html += f'<tr><td>{r["original_query"][:80]}</td><td>{r["correction"][:80]}</td><td class="mono">{r["created_at"][:16]}</td></tr>'
        html += '</table>'
    else:
        html += '<p style="color:#666">Net korrektirovok</p>'
    html += '</div>'
    html += '<div class="section"><h2>Konfiguratsiya</h2>'
    html += f'<div class="card"><p>Model: <span class="mono gold">{override}</span></p>'
    html += f'<p>Provider: <span class="mono gold">{_cfg_cache["priority_provider"]}</span></p></div></div>'
    html += '</body></html>'
    return Response(html, mimetype="text/html")

@app.get("/office-dashboard")
@require_telegram
def office_dashboard():
    now = datetime.utcnow()
    today = now.isoformat()[:10]
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()
    r_today = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (today,), fetch=True)
    r_week = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (week_ago,), fetch=True)
    r_month = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (month_ago,), fetch=True)
    r_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (month_ago,), fetch=True)
    n_today = r_today[0]["c"] if r_today else 0
    n_week = r_week[0]["c"] if r_week else 0
    n_month = r_month[0]["c"] if r_month else 0
    cost_month = r_cost[0]["t"] if r_cost else 0

    html = _html_base("Fosved Office — Panel upravleniya")
    html += '<div class="header-grad" style="background:linear-gradient(135deg,#1a1a2e,#16213e)"><h1>Fosved Office v2</h1>'
    html += f'<p style="color:#C9A84C;margin-top:8px">Obzor za {today} &nbsp;|&nbsp; Provider: <span class="mono">{_cfg_cache["priority_provider"]}</span> &nbsp;|&nbsp; Model: <span class="mono">{_cfg_cache["priority_model"] or "auto"}</span></p></div>'
    html += f"""<div class="grid grid-4" style="margin:20px 24px">
<div class="card kpi"><div class="num gold">{n_today}</div><div class="lbl">Vyzovov segodnya</div></div>
<div class="card kpi"><div class="num status-blue">{n_week}</div><div class="lbl">Za nedelyu</div></div>
<div class="card kpi"><div class="num">{n_month}</div><div class="lbl">Za mesyats</div></div>
<div class="card kpi"><div class="num status-green">${cost_month:.2f}</div><div class="lbl">Stoimost / mes</div></div></div>"""

    html += '<div class="section"><h2>Departamenty</h2><div class="grid grid-3">'
    depts = [d for d in DEPT_NAMES if d != "admin"]
    for dept in depts:
        c = DEPT_COLORS[dept]
        r_d = _query("SELECT COUNT(*) as c FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        r_m = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        calls = r_d[0]["c"] if r_d else 0
        rating = r_m[0]["a"] if r_m else 0
        level = "high" if calls > 10 else "medium" if calls > 0 else "low"
        ov = _cfg_cache["overrides"].get(dept)
        html += f"""<div class="card" style="border-left:4px solid {c['accent']}">
<h3 style="font-size:1rem">{_status_icon(level)} {DEPT_NAMES[dept]}</h3>
<p class="mono" style="margin-top:8px;font-size:0.8rem;color:#999">Vyzovy: {calls} &nbsp; Otsenka: {rating:.1f}/5</p>
<p class="mono" style="font-size:0.7rem;color:#666;margin-top:4px">Model: {ov or 'default'}</p>
<a href="/dept-dashboard/{dept}" style="font-size:0.75rem;display:inline-block;margin-top:8px">Otkryt -&gt;</a></div>"""
    html += '</div></div>'

    audit_rows = _query("SELECT action,details,timestamp FROM audit_log ORDER BY id DESC LIMIT 10", fetch=True)
    html += '<div class="section"><h2>Zhurnal</h2><table><tr><th>Deistvie</th><th>Detali</th><th>Vremya</th></tr>'
    for r in audit_rows:
        det = r["details"][:100] if r["details"] else ""
        html += f'<tr><td class="mono">{r["action"]}</td><td style="color:#999;font-size:0.8rem">{det}</td><td class="mono" style="font-size:0.8rem">{r["timestamp"][:19]}</td></tr>'
    html += '</table></div>'

    prov_rows = _query("SELECT provider,COUNT(*) as c,COALESCE(SUM(cost_usd),0) as cost FROM token_usage WHERE created_at>=? GROUP BY provider", (month_ago,), fetch=True)
    html += '<div class="section"><h2>Providery (mesyats)</h2><table><tr><th>Provider</th><th>Vyzovy</th><th>Stoimost</th></tr>'
    for r in prov_rows:
        html += f'<tr><td class="mono gold">{r["provider"]}</td><td>{r["c"]}</td><td class="mono">${r["cost"]:.2f}</td></tr>'
    html += '</table></div></body></html>'
    return Response(html, mimetype="text/html")

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: TTS ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/tts")
def tts_endpoint():
    """Text-to-speech via edge-tts, send voice to Telegram."""
    d = request.get_json(force=True)
    text = d.get("text", "")
    voice = d.get("voice", "ru-RU-SvetlanaNeural")
    chat_id = d.get("chat_id", "")

    if not text:
        return jsonify({"status": "error", "message": "text is required"}), 400
    if not chat_id:
        return jsonify({"status": "error", "message": "chat_id is required"}), 400

    timestamp = int(time.time())
    tmp_path = f"/tmp/tts_{timestamp}_{uuid.uuid4().hex[:6]}.mp3"

    try:
        # Run edge-tts subprocess
        rate = d.get("rate", "+20%")
        cmd = [
            "edge-tts",
            "--voice", voice,
            "--rate", rate,
            "--text", text,
            "--write-media", tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error(f"edge-tts failed: {result.stderr}")
            _log_audit("tts_error", {"voice": voice, "error": result.stderr[:500]})
            return jsonify({"status": "error", "message": "edge-tts synthesis failed", "detail": result.stderr[:500]}), 500

        # Send voice to Telegram
        msg_id = _tg_send_voice(chat_id, tmp_path)

        _log_audit("tts", {"chat_id": chat_id, "voice": voice, "text_len": len(text), "tg_msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except FileNotFoundError:
        _log_audit("tts_error", {"error": "edge-tts not installed"})
        return jsonify({"status": "error", "message": "edge-tts binary not found"}), 500
    except subprocess.TimeoutExpired:
        _log_audit("tts_error", {"error": "timeout"})
        return jsonify({"status": "error", "message": "TTS synthesis timeout"}), 500
    except Exception as e:
        log.error(f"TTS error: {e}")
        _log_audit("tts_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        # Clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: STT (WHISPER) ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/stt")
def stt_endpoint():
    """Speech-to-text via Whisper (Groq preferred, OpenAI fallback)."""
    d = request.get_json(force=True)
    file_id = d.get("file_id", "")

    if not file_id:
        return jsonify({"status": "error", "message": "file_id is required"}), 400

    provider = WHISPER_PROVIDER
    audio_data = None

    try:
        # Step 1: Get file path from Telegram
        file_path = _tg_get_file(file_id)
        if not file_path:
            _log_audit("stt_error", {"error": "could not get file path from Telegram", "file_id": file_id})
            return jsonify({"status": "error", "message": "Failed to get file from Telegram"}), 400

        # Step 2: Download audio from Telegram
        audio_data = _tg_download_file(file_path)
        if not audio_data:
            _log_audit("stt_error", {"error": "could not download file from Telegram", "file_path": file_path})
            return jsonify({"status": "error", "message": "Failed to download audio from Telegram"}), 400

        # Step 3: Transcribe via Whisper
        if provider == "groq":
            api_key = os.environ.get("GROQ_API_KEY", WHISPER_API_KEY)
            url = "https://api.groq.com/openai/v1/audio/transcriptions"
            model = "whisper-large-v3"
        else:
            api_key = os.environ.get("OPENAI_API_KEY", WHISPER_API_KEY)
            url = "https://api.openai.com/v1/audio/transcriptions"
            model = "whisper-1"

        # Prepare multipart form
        files = {
            "file": ("audio.ogg", bytes(audio_data), "audio/ogg"),
        }
        data = {"model": model}
        headers = {"Authorization": f"Bearer {api_key}"}

        resp = http_requests.post(url, headers=headers, files=files, data=data, timeout=60)
        resp.raise_for_status()
        resp_data = resp.json()
        transcribed_text = resp_data.get("text", "")

        _log_audit("stt", {"file_id": file_id, "provider": provider, "model": model, "text_len": len(transcribed_text)})

        return jsonify({"status": "ok", "text": transcribed_text, "provider": provider})

    except Exception as e:
        log.error(f"STT error (provider={provider}): {e}")
        # Try fallback provider if primary failed
        if provider == "groq" and audio_data:
            try:
                fallback_key = os.environ.get("OPENAI_API_KEY", "")
                if not fallback_key:
                    raise ValueError("No OpenAI API key for fallback")
                files = {"file": ("audio.ogg", bytes(audio_data), "audio/ogg")}
                data = {"model": "whisper-1"}
                headers = {"Authorization": f"Bearer {fallback_key}"}
                resp = http_requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=60)
                resp.raise_for_status()
                resp_data = resp.json()
                transcribed_text = resp_data.get("text", "")
                _log_audit("stt", {"file_id": file_id, "provider": "openai", "model": "whisper-1", "text_len": len(transcribed_text), "fallback": True})
                return jsonify({"status": "ok", "text": transcribed_text, "provider": "openai"})
            except Exception as fallback_err:
                log.error(f"STT fallback also failed: {fallback_err}")

        _log_audit("stt_error", {"error": str(e)[:500], "file_id": file_id})
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/extract-document")
def extract_document():
    """Download a Telegram document and return its plain text."""
    d = request.get_json(force=True)
    file_id = d.get("file_id", "")
    file_name = d.get("file_name", "")
    if not file_id:
        return jsonify({"status": "error", "message": "file_id is required"}), 400
    tmp = None
    try:
        file_path = _tg_get_file(file_id)
        if not file_path:
            return jsonify({"status": "error",
                            "message": "не удалось получить файл из Telegram"}), 200
        blob = _tg_download_file(file_path)
        if not blob:
            return jsonify({"status": "error",
                            "message": "не удалось скачать файл (возможно, больше 20 МБ)"}), 200
        suffix = os.path.splitext(file_name or file_path)[1] or ""
        tmp = os.path.join("/tmp", f"doc_{int(time.time() * 1000)}{suffix}")
        with open(tmp, "wb") as f:
            f.write(blob)
        text, truncated = doc_extract.extract_text(tmp, file_name)
        _log_audit("document_extracted", {"file_name": file_name,
                                          "chars": len(text), "truncated": truncated})
        return jsonify({"status": "ok", "text": text,
                        "chars": len(text), "truncated": truncated})
    except ValueError as e:
        _log_audit("document_extract_error", {"file_name": file_name, "error": str(e)[:200]})
        return jsonify({"status": "error", "message": str(e)}), 200
    except Exception as e:
        log.error(f"extract_document failed: {e}")
        return jsonify({"status": "error", "message": "внутренняя ошибка извлечения"}), 500
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: ARCHIVE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.post("/archive/publish")
def archive_publish():
    """Publish a document to the Telegram archive channel."""
    d = request.get_json(force=True)
    doc_id = d.get("doc_id", "")
    dept = d.get("dept", "")
    title = d.get("title", "")
    content = d.get("content", "")

    if not content:
        return jsonify({"status": "error", "message": "content is required"}), 400
    if not TELEGRAM_ARCHIVE_CHANNEL_ID:
        return jsonify({"status": "error", "message": "TELEGRAM_ARCHIVE_CHANNEL_ID not set"}), 500

    try:
        # Compact archive record: date, dept, description, link + .html attachment
        plain = strip_html_for_archive(content)
        summary = " ".join(plain.split())[:200]
        if len(" ".join(plain.split())) > 200:
            summary = summary + "..."

        day = datetime.utcnow().strftime("%Y-%m-%d")
        hashtags = DEPT_HASHTAGS.get(dept, "")
        link = f"{RENDER_URL}/miniapp/{doc_id}" if doc_id else ""

        lines = [f"{day} | {dept}"]
        if title:
            lines.append(title[:150])
        if summary:
            lines.append("")
            lines.append(summary)
        if link:
            lines.append("")
            lines.append(f"Открыть: {link}")
        if hashtags:
            lines.append("")
            lines.append(hashtags)
        record = "\n".join(lines)[:1024]

        # Attach the stored HTML as a document (archive stays readable without our service)
        msg_id = None
        archive_format = _get_setting("archive_format") or "compact"
        html_doc = ""
        if doc_id and archive_format == "compact":
            rows = _query("SELECT html FROM miniapp_responses WHERE id = ?", (doc_id,), fetch=True)
            if rows:
                html_doc = rows[0]["html"] or ""

        if html_doc:
            fname = f"{day}_{_safe_filename_part(dept, 20)}_{_safe_filename_part(title)}.html"
            fpath = os.path.join("/tmp", fname)
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(html_doc)
                msg_id = _tg_send_document(TELEGRAM_ARCHIVE_CHANNEL_ID, fpath, record)
            finally:
                try:
                    os.remove(fpath)
                except Exception:
                    pass

        # Fallback: no HTML stored, or document upload failed
        if not msg_id:
            msg_id = _tg_send_message(TELEGRAM_ARCHIVE_CHANNEL_ID, record)

        # Record in channel_archive table
        now = datetime.utcnow().isoformat()
        _query("INSERT INTO channel_archive (doc_id, dept, title, channel_message_id, archived_at) VALUES (?,?,?,?,?)",
               (doc_id, dept, title, str(msg_id) if msg_id else "", now))

        _log_audit("archive_publish", {"doc_id": doc_id, "dept": dept, "title": title, "msg_id": msg_id, "chars": len(record)})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"archive_publish error: {e}")
        _log_audit("archive_publish_error", {"error": str(e)[:500], "doc_id": doc_id})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/archive/daily-digest")
def archive_daily_digest():
    """Collect today's stats and send a digest to the archive channel."""
    try:
        if not TELEGRAM_ARCHIVE_CHANNEL_ID:
            return jsonify({"status": "error", "message": "TELEGRAM_ARCHIVE_CHANNEL_ID not set"}), 500

        now = datetime.utcnow()
        today = now.isoformat()[:10]
        today_start = today + "T00:00:00"

        # Collect today's stats
        tasks_rows = _query("SELECT dept, COUNT(*) as c FROM dialog_history WHERE created_at>=? AND role='user' GROUP BY dept", (today_start,), fetch=True)
        reports_rows = _query("SELECT dept, COUNT(*) as c FROM miniapp_responses WHERE created_at>=? GROUP BY dept", (today_start,), fetch=True)
        corrections_rows = _query("SELECT dept, COUNT(*) as c FROM adapt_corrections WHERE created_at>=? GROUP BY dept", (today_start,), fetch=True)

        # Build digest text
        lines = []
        lines.append(f"DAILY DIGEST - {today}")
        lines.append("=" * 40)
        lines.append("")

        # Task breakdown
        total_tasks = sum(r["c"] for r in tasks_rows)
        lines.append(f"TASKS: {total_tasks} total")
        for r in sorted(tasks_rows, key=lambda x: -x["c"]):
            dept_name = DEPT_NAMES.get(r["dept"], r["dept"])
            lines.append(f"  {dept_name}: {r['c']}")
        lines.append("")

        # Reports
        total_reports = sum(r["c"] for r in reports_rows)
        lines.append(f"REPORTS: {total_reports} total")
        for r in sorted(reports_rows, key=lambda x: -x["c"]):
            dept_name = DEPT_NAMES.get(r["dept"], r["dept"])
            lines.append(f"  {dept_name}: {r['c']}")
        lines.append("")

        # Corrections
        total_corrections = sum(r["c"] for r in corrections_rows)
        lines.append(f"CORRECTIONS: {total_corrections} total")
        for r in sorted(corrections_rows, key=lambda x: -x["c"]):
            dept_name = DEPT_NAMES.get(r["dept"], r["dept"])
            lines.append(f"  {dept_name}: {r['c']}")

        digest_text = "\n".join(lines)

        msg_id = _tg_send_message(TELEGRAM_ARCHIVE_CHANNEL_ID, digest_text)
        _log_audit("archive_daily_digest", {"date": today, "tasks": total_tasks, "reports": total_reports, "corrections": total_corrections, "msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"archive_daily_digest error: {e}")
        _log_audit("archive_daily_digest_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: SCHEDULER ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

def _collect_metrics_for_period(start_iso, end_iso=None):
    """Collect metrics for a given time period."""
    conditions = "created_at >= ?"
    params = [start_iso]
    if end_iso:
        conditions += " AND created_at < ?"
        params.append(end_iso)

    tasks = _query(f"SELECT dept, COUNT(*) as c FROM dialog_history WHERE {conditions} AND role='user' GROUP BY dept", params, fetch=True)
    reports = _query(f"SELECT dept, COUNT(*) as c FROM miniapp_responses WHERE {conditions} GROUP BY dept", params, fetch=True)
    corrections = _query(f"SELECT dept, COUNT(*) as c FROM adapt_corrections WHERE {conditions} GROUP BY dept", params, fetch=True)
    ratings = _query(f"SELECT dept, COALESCE(AVG(CAST(metric_value AS REAL)),0) as avg_r, COUNT(*) as c FROM dept_metrics WHERE {conditions} GROUP BY dept", params, fetch=True)
    tokens = _query(f"SELECT dept, COALESCE(SUM(input_tokens),0) as ti, COALESCE(SUM(output_tokens),0) as to2, COALESCE(SUM(cost_usd),0) as cost FROM token_usage WHERE {conditions} GROUP BY dept", params, fetch=True)

    return {
        "tasks": {r["dept"]: r["c"] for r in tasks},
        "reports": {r["dept"]: r["c"] for r in reports},
        "corrections": {r["dept"]: r["c"] for r in corrections},
        "ratings": {r["dept"]: {"avg": r["avg_r"], "count": r["c"]} for r in ratings},
        "tokens": {r["dept"]: {"in": r["ti"], "out": r["to2"], "cost": r["cost"]} for r in tokens},
    }

def _format_metrics_text(metrics):
    """Format metrics dict as readable text for LLM prompt."""
    lines = []
    lines.append("METRICS:")
    all_depts = set(list(metrics["tasks"].keys()) + list(metrics["reports"].keys()) + list(metrics["corrections"].keys()) + list(metrics["ratings"].keys()))
    for dept in sorted(all_depts):
        name = DEPT_NAMES.get(dept, dept)
        parts = [f"{name}:"]
        if dept in metrics["tasks"]:
            parts.append(f"tasks={metrics['tasks'][dept]}")
        if dept in metrics["reports"]:
            parts.append(f"reports={metrics['reports'][dept]}")
        if dept in metrics["corrections"]:
            parts.append(f"corrections={metrics['corrections'][dept]}")
        if dept in metrics["ratings"]:
            r = metrics["ratings"][dept]
            parts.append(f"avg_rating={r['avg']:.1f} (n={r['count']})")
        if dept in metrics["tokens"]:
            t = metrics["tokens"][dept]
            parts.append(f"tokens={t['in']+t['out']} cost=${t['cost']:.2f}")
        lines.append("  " + " ".join(parts))
    return "\n".join(lines)

@app.post("/scheduler/morning-brief")
def scheduler_morning_brief():
    """
    Generate and send a morning brief to the owner.
    Яна делает отчёт в 7:20: дата, время, прогноз погоды, как работает офис, важные мировые события.
    """
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        # Minsk time for display (UTC+3 year-round)
        from datetime import timezone, timedelta as _td
        msk = timezone(_td(hours=3))
        now_msk = datetime.now(msk)
        date_str = now_msk.strftime("%d.%m.%Y")
        time_str = now_msk.strftime("%H:%M")
        weekday = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"][now_msk.weekday()]

        # ── 1. Weather (wttr.in — free, no API key) ──
        weather_text = ""
        try:
            weather_resp = http_requests.get("https://wttr.in/Minsk?format=%C+%t+%w+%h+%P&lang=ru", timeout=10)
            if weather_resp.ok:
                weather_text = weather_resp.text.strip()
            else:
                weather_text = "Погода недоступна"
        except Exception:
            weather_text = "Не удалось получить прогноз погоды"

        # Extended forecast
        weather_ext = ""
        try:
            weather_ext_resp = http_requests.get("https://wttr.in/Minsk?format=3&lang=ru", timeout=10)
            if weather_ext_resp.ok:
                weather_ext = weather_ext_resp.text.strip()
        except Exception:
            pass

        # ── 2. Office metrics ──
        yesterday = (now - timedelta(days=1)).isoformat()[:10] + "T00:00:00"
        today = now.isoformat()[:10] + "T00:00:00"
        metrics = _collect_metrics_for_period(yesterday, today)
        metrics_text = _format_metrics_text(metrics)

        # Dialog count (24h)
        dialog_rows = _query("SELECT COUNT(*) as cnt FROM dialog_history WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        dialog_24h = dialog_rows[0]["cnt"] if dialog_rows else 0

        # Active departments (24h)
        dept_rows = _query("SELECT DISTINCT dept FROM dialog_history WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        active_depts = [r["dept"] for r in dept_rows] if dept_rows else []

        # Pending narads
        narad_rows = _query("SELECT COUNT(*) as cnt FROM narads WHERE status = 'pending'", fetch=True)
        narads_pending = narad_rows[0]["cnt"] if narad_rows else 0

        # Recent corrections
        corr_rows = _query("SELECT COUNT(*) as cnt FROM adapt_corrections WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        corrections_24h = corr_rows[0]["cnt"] if corr_rows else 0

        # ── 3. LZ daily findings (from memory) ──
        lz_findings = ""
        try:
            lz_mem = memory.recall("LZ Daily", type_filter="observation", limit=3)
            if lz_mem:
                lz_findings = "\n".join([f"  - {f['content'][:120]}" for f in lz_mem])
        except Exception:
            pass

        # ── 4. Build prompt ──
        dept_prompt = get_dept_prompt("yana")
        user_prompt = f"""Составь утренний отчёт для хозяина офиса.

Дата: {date_str} ({weekday})
Время: {time_str} (Минск)

=== ПОГОДА (Минск) ===
{weather_text}
{weather_ext}

=== КАК РАБОТАЕТ ОФИС (последние 24ч) ===
Диалогов: {dialog_24h}
Активные отделы: {', '.join(active_depts) if active_depts else 'нет активности'}
Нерешённых нарядов: {narads_pending}
Коррекций за сутки: {corrections_24h}
{metrics_text}

=== НАХОДКИ ЛАБОРАТОРИИ ЗНАНИЙ ===
{lz_findings if lz_findings else 'За последние сутки нет новых находок'}

{get_night_news_digest()}

=== ТВОЯ ЗАДАЧА ===
Напиши утренний отчёт на русском. Структура:
1. 📅 Дата, время, день недели
2. 🌤 Прогноз погоды в Минске
3. 🏢 Статус офиса — кратко, что происходит
4. 🌍 Важные мировые события — что актуально (на основе своих знаний)
5. 🔍 Ключевые находки ЛЗ (если есть)
6. ⚡ Что требует внимания хозяина

ФОРМАТИРОВАНИЕ (Telegram MarkdownV2):
▸ Заголовки секций: *Жирный текст*
▸ Ключевые цифры и термины: *выделить жирным*
▸ Подчёркивания важных пунктов: __подчёркнуто__
▸ Статусы: ✅ зелёный, ⚠️ жёлтый, ❌ красный
▸ НЕ используй кавычки " " или « » — они озвучиваются TTS
▸ Эмодзи только как маркеры секций (📅🌤🏢🌍🔍⚡), не ставь эмодзи в середине предложений
▸ НЕ ставь # заголовки — Telegram их не рендерит

Будь лаконичной но информативной. 7-12 предложений максимум."""

        messages = [
            {"role": "system", "content": dept_prompt + "\n\nТы — Яна, управляющая офисом. Ты составляешь утренний отчёт для хозяина. Отчёт должен быть информативным, структурированным, на русском языке. Упоминай находки Лаборатории Знаний если они есть. Форматирование: *жирный* для заголовков и ключевых слов, __подчёркнуто__ для важных пунктов, эмодзи только как маркеры секций. НЕ используй кавычки."},
            {"role": "user", "content": user_prompt},
        ]

        result = call_llm("yana", messages)
        brief = result["reply"]

        msg_id = _tg_send_formatted(owner_id, brief, dept="yana")
        _log_audit("scheduler_morning_brief", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "brief": brief, "msg_id": msg_id})

    except Exception as e:
        log.error(f"morning_brief error: {e}")
        _log_audit("scheduler_morning_brief_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/admin-morning-reply")
def scheduler_admin_morning_reply():
    """
    Админ делает свой ответ на утренний отчёт Яны (7:25).
    Анализирует отчёт Яны, добавляет своё видение, приоритеты, замечания.
    """
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        # ── 1. Get Yana's last morning brief from dialog_history ──
        yana_rows = _query(
            "SELECT content, created_at FROM dialog_history WHERE dept='yana' AND role='assistant' "
            "AND created_at > datetime('now', '-2 hours') ORDER BY id DESC LIMIT 1",
            fetch=True
        )
        yana_brief = yana_rows[0]["content"] if yana_rows else ""

        if not yana_brief:
            # Fallback: just send a status
            msg_id = _tg_send_message(owner_id, "⏰ Утренний ответ Админа: не найден свежий отчёт Яны для комментирования.")
            return jsonify({"status": "ok", "msg_id": msg_id, "note": "no_yana_brief"})

        # ── 2. Get admin prompt ──
        admin_prompt = get_dept_prompt("admin")

        # ── 3. Get LZ daily findings for admin context ──
        lz_context = ""
        try:
            lz_mem = memory.recall("LZ Daily", type_filter="observation", limit=5)
            if lz_mem:
                lz_context = "\n".join([f"  - {f['content'][:200]}" for f in lz_mem])
        except Exception:
            pass

        # ── 4. Get pending issues ──
        issues_context = ""
        try:
            narad_rows = _query("SELECT COUNT(*) as cnt FROM narads WHERE status = 'pending'", fetch=True)
            if narad_rows:
                issues_context = f"Нерешённых нарядов: {narad_rows[0]['cnt']}"
        except Exception:
            pass

        # ── 5. Build admin prompt ──
        messages = [
            {"role": "system", "content": admin_prompt + "\n\nТы — Админ Фосвед Офиса. Ты прочитал утренний отчёт Яны и должен дать свой ответ. Твой ответ — это директива на день. Упомяни находки Лаборатории Знаний, если они релевантны. Форматирование: *жирный* для приоритетов и ключевых слов, __подчёркнуто__ для указаний, эмодзи только как маркеры секций. НЕ используй кавычки."},
            {"role": "user", "content": f"""Яна прислала утренний отчёт:

{yana_brief}

{f"=== НАХОДКИ ЛЗ ===\n{lz_context}" if lz_context else ""}
{f"=== СТАТУС ===\n{issues_context}" if issues_context else ""}

Твоя задача: напиши краткий ответ на отчёт Яны на русском. Структура:
1. 📌 Приоритеты на сегодня — 2-3 главных задачи
2. 💬 Замечания по отчёту Яны (если есть)
3. 🔧 Указания отделам
4. 🔍 Что из находок ЛЗ стоит изучить и применить

ФОРМАТИРОВАНИЕ (Telegram MarkdownV2):
▸ Заголовки: *Жирный текст*
▸ Приоритеты и указания: __подчёркнуто__
▸ Статусы: ✅ ⚠️ ❌
▸ НЕ используй кавычки — они озвучиваются TTS
▸ Эмодзи только как маркеры секций (📌💬🔧🔍), не в середине предложений

Будь кратким, по-деловому. 5-8 предложений."""},
        ]

        result = call_llm("admin", messages)
        reply = result["reply"]

        msg_id = _tg_send_formatted(owner_id, reply, dept="admin")
        _log_audit("scheduler_admin_morning_reply", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "reply": reply, "msg_id": msg_id})

    except Exception as e:
        log.error(f"admin_morning_reply error: {e}")
        _log_audit("scheduler_admin_morning_reply_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/evening-summary")
def scheduler_evening_summary():
    """Generate and send an evening summary, plus publish daily digest to archive."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10] + "T00:00:00"

        metrics = _collect_metrics_for_period(today)
        metrics_text = _format_metrics_text(metrics)

        dept_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are generating an evening summary for the office owner. Review the day's performance, highlight achievements and issues. Format in Russian."},
            {"role": "user", "content": f"Sformirui vechernii itog za segodnyashnii den'.\n\n{metrics_text}\n\nOzhidai: korotkii itog na 5-8 punktov s rekomendatsiyami."},
        ]

        result = call_llm("yana", messages)
        summary = result["reply"]

        # Send to owner
        msg_id = _tg_send_message(owner_id, summary)

        # Publish daily digest to archive channel
        if TELEGRAM_ARCHIVE_CHANNEL_ID:
            tasks_total = sum(metrics["tasks"].values())
            reports_total = sum(metrics["reports"].values())
            corrections_total = sum(metrics["corrections"].values())
            digest_lines = [
                f"DAILY DIGEST - {now.isoformat()[:10]}",
                "=" * 40,
                f"Tasks: {tasks_total}",
                f"Reports: {reports_total}",
                f"Corrections: {corrections_total}",
            ]
            digest_text = "\n".join(digest_lines)
            _tg_send_message(TELEGRAM_ARCHIVE_CHANNEL_ID, digest_text)

        _log_audit("scheduler_evening_summary", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"evening_summary error: {e}")
        _log_audit("scheduler_evening_summary_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/weekly-digest")
def scheduler_weekly_digest():
    """Generate a weekly digest per department and send via Telegram."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        metrics = _collect_metrics_for_period(week_ago)
        metrics_text = _format_metrics_text(metrics)

        dept_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are generating a weekly digest for the office owner. Summarize per-department performance, trends, and recommendations. Format in Russian."},
            {"role": "user", "content": f"Sformirui ezhenedelnyi digest za proshlou nedelyu.\n\n{metrics_text}\n\nOzhidai: detalnyi digest po departamentam s rekomendatsiyami."},
        ]

        result = call_llm("yana", messages)
        digest = result["reply"]

        # Send via SendReport (if > 800 chars, use Mini App button)
        if len(digest) > 800:
            msg_id = _tg_send_report_with_button(owner_id, digest)
        else:
            msg_id = _tg_send_message(owner_id, digest)

        _log_audit("scheduler_weekly_digest", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id, "chars": len(digest)})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"weekly_digest error: {e}")
        _log_audit("scheduler_weekly_digest_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/monthly-review")
def scheduler_monthly_review():
    """Generate a monthly review per department."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        month_ago = (now - timedelta(days=30)).isoformat()

        metrics = _collect_metrics_for_period(month_ago)
        metrics_text = _format_metrics_text(metrics)

        dept_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are generating a monthly review for the office owner. Analyze per-department performance: tasks completed, average ratings, correction frequency. Identify trends and action items. Format in Russian."},
            {"role": "user", "content": f"Sformirui ezhemesyachnyi obzor za proshlyi mesyats.\n\n{metrics_text}\n\nOzhidai: analiz po departamentam s planom deistvii."},
        ]

        result = call_llm("yana", messages)
        review = result["reply"]

        msg_id = _tg_send_report_with_button(owner_id, review)

        _log_audit("scheduler_monthly_review", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"monthly_review error: {e}")
        _log_audit("scheduler_monthly_review_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/control-check")
def scheduler_control_check():
    """Check control predictions against current reality."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        # Get all control_* keys from system_settings
        controls = _query("SELECT key, value FROM system_settings WHERE key LIKE 'control_%'", fetch=True)

        if not controls:
            _tg_send_message(owner_id, "No control predictions found in system_settings.")
            _log_audit("scheduler_control_check", {"owner_id": owner_id, "found": 0})
            return jsonify({"status": "ok", "checked": 0})

        results = []
        osp_prompt = get_dept_prompt("osp")

        for ctrl in controls:
            key = ctrl["key"]
            value = ctrl["value"]
            try:
                ctrl_data = json.loads(value) if isinstance(value, str) else value
            except (json.JSONDecodeError, TypeError):
                ctrl_data = {"raw": value}

            frequency = ctrl_data.get("frequency", "daily")
            topic = ctrl_data.get("topic", key)
            original_prediction = ctrl_data.get("prediction", ctrl_data.get("original", str(value)))

            # For daily controls, compare prediction with current reality via LLM
            if frequency == "daily":
                messages = [
                    {"role": "system", "content": osp_prompt + "\n\nYou are performing a control check. Compare the original prediction with the current situation. Be brief, 2-3 sentences. Format in Russian."},
                    {"role": "user", "content": f"Control check: {topic}\n\nOriginal prediction: {original_prediction}\n\nAnalyze: did the prediction match reality? What changed?\n\nOzhidai: korotkii analiz 2-3 predlozheniya."},
                ]
                check_result = call_llm("osp", messages)
                analysis = check_result["reply"]
                results.append({"key": key, "topic": topic, "frequency": frequency, "analysis": analysis})

        # Format and send results
        if results:
            lines = [f"CONTROL CHECK - {datetime.utcnow().isoformat()[:10]}", "=" * 40, ""]
            for r in results:
                lines.append(f"[{r['topic']}]")
                lines.append(f"  {r['analysis']}")
                lines.append("")
            check_text = "\n".join(lines)
        else:
            check_text = "No daily control predictions to check."

        msg_id = _tg_send_message(owner_id, check_text)
        _log_audit("scheduler_control_check", {"owner_id": owner_id, "checked": len(controls), "daily": len(results), "msg_id": msg_id})

        return jsonify({"status": "ok", "checked": len(controls), "daily": len(results), "msg_id": msg_id})

    except Exception as e:
        log.error(f"control_check error: {e}")
        _log_audit("scheduler_control_check_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/self-learn")
def scheduler_self_learn():
    """Self-learning: call LLM to identify improvement areas and memorize findings."""
    try:
        # Get recent corrections and error patterns for context
        corrs = _query("SELECT dept, original_query, correction, created_at FROM adapt_corrections ORDER BY id DESC LIMIT 20", fetch=True)
        patterns = _query("SELECT dept, error_type, query_text, created_at FROM error_patterns ORDER BY id DESC LIMIT 20", fetch=True)

        context_parts = []
        if corrs:
            context_parts.append("Recent corrections:")
            for c in corrs[-10:]:
                context_parts.append(f"  [{c['dept']}] {c['original_query'][:100]} -> {c['correction'][:100]}")
        if patterns:
            context_parts.append("\nRecent error patterns:")
            for p in patterns[-10:]:
                context_parts.append(f"  [{p['dept']}] {p['error_type']}: {p['query_text'][:100]}")

        context = "\n".join(context_parts) if context_parts else "No recent data available."

        yana_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": yana_prompt + "\n\nYou are performing self-learning analysis. Based on recent corrections and error patterns, identify ONE specific improvement topic that would reduce errors. Be practical and specific. Output format: TOPIC: <topic> | INSIGHT: <insight> | ACTION: <action>. Format in Russian."},
            {"role": "user", "content": f"Proanalizirui nedavnie oshibki i predlozhi odnu konkretnuyu temu dlya samousovershenstvovaniya.\n\n{context}\n\nFormat: TOPIC: <tema> | INSIGHT: <vyvod> | ACTION: <deistvie>"},
        ]

        result = call_llm("yana", messages)
        finding = result["reply"]

        # Memorize finding
        _memorize("yana", "self_learn", finding)

        _log_audit("scheduler_self_learn", {"provider": result["provider"], "finding": finding[:200]})

        return jsonify({"status": "ok", "finding": finding})

    except Exception as e:
        log.error(f"self_learn error: {e}")
        _log_audit("scheduler_self_learn_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: LEARNING ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.post("/learning/fix")
def learning_fix():
    """Process a user correction: classify error type and save to learning tables."""
    d = request.get_json(force=True)
    text = d.get("text", "")
    dept = d.get("dept", "yana")

    if not text:
        return jsonify({"status": "error", "message": "text is required"}), 400

    try:
        # Call LLM to classify the error type
        dept_prompt = get_dept_prompt(dept)
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are a quality control classifier. Analyze the user's correction text and classify the error type. Also suggest how to fix it going forward. Output JSON only: {\"error_type\": \"TOO_GENERAL|WRONG_FACTS|WRONG_DEPT|BAD_FORMAT|MISSING_CONTEXT|OTHER\", \"suggestion\": \"your suggestion\"}. Language: Russian."},
            {"role": "user", "content": f"Klassifitsirui etu korrektsiyu:\n\n{text}\n\nVerni tolko JSON."},
        ]

        result = call_llm(dept, messages)
        reply = result["reply"]

        # Parse JSON from LLM response
        try:
            # Try to extract JSON from the response (may be wrapped in markdown code block)
            json_match = re.search(r'\{[^}]+\}', reply, re.DOTALL)
            if json_match:
                classification = json.loads(json_match.group())
            else:
                classification = {"error_type": "OTHER", "suggestion": reply}
        except json.JSONDecodeError:
            classification = {"error_type": "OTHER", "suggestion": reply}

        error_type = classification.get("error_type", "OTHER")
        suggestion = classification.get("suggestion", "")

        now = datetime.utcnow().isoformat()

        # Save to error_patterns table
        _query("INSERT INTO error_patterns (dept, error_type, query_text, created_at) VALUES (?,?,?,?)",
               (dept, error_type, text[:2000], now))

        # Save to adapt_corrections table
        _query("INSERT INTO adapt_corrections (dept, original_query, correction, created_at, corr_type) VALUES (?,?,?,?,?)",
               (dept, text[:2000], suggestion[:2000], now, error_type))

        _log_audit("learning_fix", {"dept": dept, "error_type": error_type, "text_len": len(text)})

        return jsonify({"status": "ok", "error_type": error_type, "suggestion": suggestion})

    except Exception as e:
        log.error(f"learning_fix error: {e}")
        _log_audit("learning_fix_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/learning/good")
def learning_good():
    """Save a positive example for learning."""
    d = request.get_json(force=True)
    dept = d.get("dept", "yana")
    query = d.get("query", "")
    response = d.get("response", "")

    if not query or not response:
        return jsonify({"status": "error", "message": "query and response are required"}), 400

    now = datetime.utcnow().isoformat()
    _query("INSERT INTO adapt_corrections (dept, original_query, correction, created_at, corr_type) VALUES (?,?,?,?,?)",
           (dept, query[:2000], response[:2000], now, "positive"))

    _log_audit("learning_good", {"dept": dept, "query_len": len(query), "response_len": len(response)})

    return jsonify({"status": "ok"})

@app.post("/learning/stats")
def learning_stats():
    """Return learning statistics."""
    try:
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        # Corrections count (7d)
        corr_rows = _query("SELECT COUNT(*) as c FROM adapt_corrections WHERE created_at>=? AND corr_type != 'positive'", (week_ago,), fetch=True)
        corrections_7d = corr_rows[0]["c"] if corr_rows else 0

        # Positive examples count
        pos_rows = _query("SELECT COUNT(*) as c FROM adapt_corrections WHERE corr_type = 'positive'", fetch=True)
        positive_total = pos_rows[0]["c"] if pos_rows else 0

        # Error pattern breakdown
        pattern_rows = _query("SELECT error_type, COUNT(*) as c FROM error_patterns GROUP BY error_type ORDER BY c DESC", fetch=True)
        error_breakdown = {}
        for r in pattern_rows:
            error_breakdown[r["error_type"]] = r["c"]

        # Per-dept corrections (7d)
        dept_rows = _query("SELECT dept, COUNT(*) as c FROM adapt_corrections WHERE created_at>=? AND corr_type != 'positive' GROUP BY dept ORDER BY c DESC", (week_ago,), fetch=True)
        dept_corrections = {}
        for r in dept_rows:
            dept_corrections[r["dept"]] = r["c"]

        return jsonify({
            "status": "ok",
            "corrections_7d": corrections_7d,
            "positive_examples": positive_total,
            "error_breakdown": error_breakdown,
            "dept_corrections": dept_corrections,
        })

    except Exception as e:
        log.error(f"learning_stats error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/learning/debrief")
def learning_debrief():
    """Analyze error patterns for a specific department."""
    d = request.get_json(force=True)
    dept = d.get("dept", "yana")

    try:
        # Get recent corrections for department
        corrs = _query("SELECT original_query, correction, corr_type, created_at FROM adapt_corrections WHERE dept=? AND corr_type != 'positive' ORDER BY id DESC LIMIT 20", (dept,), fetch=True)

        if not corrs:
            return jsonify({"status": "ok", "analysis": "No corrections found for this department."})

        # Format corrections for LLM analysis
        corr_text_parts = []
        for c in corrs:
            corr_text_parts.append(f"[{c['corr_type']}] {c['original_query'][:200]} -> {c['correction'][:200]} ({c['created_at'][:10]})")
        corr_text = "\n".join(corr_text_parts)

        dept_prompt = get_dept_prompt(dept)
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are analyzing error patterns for department quality improvement. Identify recurring themes, root causes, and propose 3 actionable improvements. Format in Russian."},
            {"role": "user", "content": f"Proanalizirui patterny oshibok departamenta {DEPT_NAMES.get(dept, dept)}:\n\n{corr_text}\n\nSformirui analiz s vyvodami i 3 konkretnymi predlozheniyami po uluchsheniyu."},
        ]

        result = call_llm(dept, messages)
        analysis = result["reply"]

        _log_audit("learning_debrief", {"dept": dept, "corrections_analyzed": len(corrs), "provider": result["provider"]})

        return jsonify({"status": "ok", "analysis": analysis})

    except Exception as e:
        log.error(f"learning_debrief error: {e}")
        _log_audit("learning_debrief_error", {"error": str(e)[:500], "dept": dept})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: AUDIT RECENT ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.get("/audit/recent")
@require_telegram
def audit_recent():
    """Return recent audit log entries."""
    try:
        limit = request.args.get("limit", 20, type=int)
        limit = min(limit, 200)

        rows = _query("SELECT id, action, details, timestamp FROM audit_log ORDER BY id DESC LIMIT ?", (limit,), fetch=True)

        entries = []
        for r in rows:
            entry = {
                "id": r["id"],
                "action": r["action"],
                "created": r["timestamp"],
            }
            try:
                entry["details"] = json.loads(r["details"]) if r["details"] else {}
            except (json.JSONDecodeError, TypeError):
                entry["details"] = {"raw": r["details"]}
            entries.append(entry)

        return jsonify({"status": "ok", "entries": entries, "count": len(entries)})

    except Exception as e:
        log.error(f"audit_recent error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: SEARCH ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/search")
def search_endpoint():
    """Search miniapp_responses (raw_text and title) for query text."""
    d = request.get_json(force=True)
    query = d.get("query", "")

    if not query:
        return jsonify({"status": "error", "message": "query is required"}), 400

    try:
        search_term = f"%{query}%"
        rows = _query(
            "SELECT id, dept, title, created_at FROM miniapp_responses WHERE (raw_text LIKE ? OR title LIKE ?) ORDER BY id DESC LIMIT 50",
            (search_term, search_term),
            fetch=True
        )

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "dept": r["dept"],
                "title": r["title"],
                "created": r["created_at"],
            })

        return jsonify({"status": "ok", "results": results, "count": len(results)})

    except Exception as e:
        log.error(f"search error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-4: LZ DEEP RESEARCH (APODEX)
# ══════════════════════════════════════════════════════════════════════

def _send_chat_action_loop(chat_id, action="typing", interval=5):
    """Send typing/action indicator to Telegram in a loop. Returns a stop event."""
    stop = threading.Event()

    def _loop():
        while not stop.is_set():
            try:
                _tg_send_chat_action(chat_id, action)
            except Exception:
                pass
            stop.wait(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return stop

def _tg_send_chat_action(chat_id, action):
    """Send a chat action to Telegram (typing, upload_photo, etc.)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
    try:
        http_requests.post(url, json={"chat_id": chat_id, "action": action}, timeout=10)
    except Exception:
        pass

@app.post("/lz/deep-research")
def lz_deep_research():
    """Apodex-powered deep research endpoint with typing indicator refresh."""
    d = request.get_json(force=True)
    query_text = d.get("query", "")
    dept = d.get("dept", "lz")
    provider = d.get("provider", "apodex")
    model = d.get("model", "apodex-1.0-mini")
    system_context = d.get("system_context", "")
    chat_id = d.get("chat_id", "")

    if not query_text:
        return jsonify({"status": "error", "message": "query is required"}), 400

    stop_typing = None
    if chat_id:
        stop_typing = _send_chat_action_loop(chat_id, "typing", 5)

    try:
        # Build LZ prompt for deep research
        lz_prompt = system_context or get_dept_prompt("lz")

        # If no specific system context, build one
        if not system_context:
            lz_prompt = f"""{lz_prompt}

You are performing DEEP RESEARCH with verification via Apodex.
Requirements:
1. Find minimum 10 independent sources
2. Verify each fact — indicate source and confidence level
3. Mark: [FACT verified], [FACT unverified], [INTERPRETATION], [SPECULATION]
4. Identify contradictions between sources
5. Build timeline if applicable
6. Rate disruption potential (1-10)
7. State what could NOT be found/verified
8. Language: Russian
9. Format: layers (like OSP), with evidence graph at end"""

        messages = [
            {"role": "system", "content": lz_prompt},
            {"role": "user", "content": query_text}
        ]

        # Call Apodex (or fallback to default provider)
        apodex_key = os.environ.get("APODEX_API_KEY", "")
        if apodex_key and provider == "apodex":
            headers = {"Authorization": f"Bearer {apodex_key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "max_tokens": 16384,
                "messages": messages
            }
            resp = http_requests.post(
                "https://platform.apodex.ai/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=300  # 5 minutes for deep research
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            used_provider = "apodex"
            used_model = model
            t_in = data.get("usage", {}).get("prompt_tokens", 0)
            t_out = data.get("usage", {}).get("completion_tokens", 0)
        else:
            # Fallback to standard LLM
            result = call_llm(dept, messages)
            answer = result.get("reply", "Deep research failed.")
            used_provider = result.get("provider", "fallback")
            used_model = result.get("model", "unknown")
            t_in = result.get("tokens_in", 0)
            t_out = result.get("tokens_out", 0)

        # Track token usage
        costs = TOKEN_COSTS.get(used_provider, {"input": 1, "output": 1})
        cost = t_in * costs["input"] / 1_000_000 + t_out * costs["output"] / 1_000_000
        now = datetime.utcnow().isoformat()
        _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
               (used_provider, used_model, t_in, t_out, round(cost, 6), dept, now))

        _log_audit("lz_deep_research", {
            "dept": dept, "provider": used_provider, "model": used_model,
            "query": query_text[:100], "tokens_in": t_in, "tokens_out": t_out,
            "verified": used_provider == "apodex"
        })

        return jsonify({
            "response": answer,
            "provider": used_provider,
            "model": used_model,
            "verified": used_provider == "apodex",
            "tokens_in": t_in,
            "tokens_out": t_out
        })

    except Exception as e:
        log.error(f"lz_deep_research error: {e}")
        _log_audit("lz_deep_research_error", {"error": str(e)[:500], "query": query_text[:100]})
        return jsonify({"response": f"Deep research error: {str(e)}", "provider": None, "verified": False}), 500
    finally:
        if stop_typing:
            stop_typing.set()

# ══════════════════════════════════════════════════════════════════════
#  MEGA-4: EVIDENCE GRAPH BADGES (added to HTML base)
# ══════════════════════════════════════════════════════════════════════

# Apodex verified/unverified/conflicting badges are handled in strip_html_for_archive
# Evidence CSS is injected via _html_base extension

def _evidence_badges_css():
    """Return CSS for Apodex evidence badges."""
    return """
.badge-verified{background:#05966922;color:#059669;border:1px solid #05966944;border-radius:4px;font-family:'DM Mono',monospace;font-size:0.7rem;padding:2px 8px;display:inline-block}
.badge-unverified{background:#d9770622;color:#d97706;border:1px solid #d9770644;border-radius:4px;font-family:'DM Mono',monospace;font-size:0.7rem;padding:2px 8px;display:inline-block}
.badge-conflicting{background:#dc262622;color:#dc2626;border:1px solid #dc262644;border-radius:4px;font-family:'DM Mono',monospace;font-size:0.7rem;padding:2px 8px;display:inline-block}
.evidence-section{margin:24px 0;padding:20px;background:#111;border:1px solid #2a2a2a;border-radius:12px}
.evidence-stats{display:flex;gap:16px;margin:12px 0}
.ev-stat{text-align:center}
.ev-num{display:block;font-size:24px;font-weight:700;font-family:'DM Mono',monospace;color:#059669}
.ev-label{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1px}
.ev-item{padding:8px 12px;border-bottom:1px solid #1a1a1a;display:flex;gap:8px;align-items:center;font-size:13px}
.ev-item.verified{border-left:3px solid #059669}
.ev-item.unverified{border-left:3px solid #d97706}
.ev-item.conflicting{border-left:3px solid #dc2626}
.ev-id{font-family:'DM Mono',monospace;color:#94a3b8;font-size:0.8rem}
.ev-source{flex:1}
.ev-status{font-size:11px;font-weight:600}
"""

# ══════════════════════════════════════════════════════════════════════
#  NARAD 29: MINI APP SPA — API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
def api_dashboard():
    """Dashboard data: KPIs, alerts, dept cards, admin status."""
    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        r_today = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        r_week = _query("SELECT COUNT(*) as c FROM dialog_history WHERE created_at>=?", (week_ago,), fetch=True)
        r_cost_today = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        r_cost_month = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (month_ago,), fetch=True)
        r_reports_today = _query("SELECT COUNT(*) as c FROM miniapp_responses WHERE created_at>=?", (today,), fetch=True)

        tasks_today = r_today[0]["c"] if r_today else 0
        tasks_week = r_week[0]["c"] if r_week else 0
        cost_today = r_cost_today[0]["t"] if r_cost_today else 0
        cost_month = r_cost_month[0]["t"] if r_cost_month else 0
        reports_today = r_reports_today[0]["c"] if r_reports_today else 0

        # Average rating
        r_avg = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE created_at>=?", (week_ago,), fetch=True)
        avg_rating = r_avg[0]["a"] if r_avg else 0

        kpis = {
            "tasks": tasks_today, "tasks_week": tasks_week,
            "cost_today": round(cost_today, 2), "cost_month": round(cost_month, 2),
            "rating": round(avg_rating, 1), "reports": reports_today,
        }

        # Dept cards
        dept_cards = []
        for dept in [d for d in DEPT_NAMES if d != "admin"]:
            c = DEPT_COLORS.get(dept, DEPT_COLORS["admin"])
            r_d = _query("SELECT COUNT(*) as c FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
            r_m = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
            calls = r_d[0]["c"] if r_d else 0
            rating = r_m[0]["a"] if r_m else 0
            status = "active" if calls > 5 else "idle" if calls > 0 else "inactive"
            dept_cards.append({
                "slug": dept, "name": DEPT_NAMES.get(dept, dept),
                "color": c, "calls": calls, "rating": round(rating, 1),
                "status": status, "override": _cfg_cache["overrides"].get(dept) or None,
            })

        # Admin status
        kg_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph", fetch=True)
        kg_edges = _query("SELECT COUNT(*) as c FROM knowledge_edges", fetch=True)
        issues = _query("SELECT COUNT(*) as c FROM admin_findings WHERE status='open'", fetch=True)
        proposals = _query("SELECT COUNT(*) as c FROM admin_proposals WHERE status='pending'", fetch=True)

        admin_status = {
            "nodes": kg_nodes[0]["c"] if kg_nodes else 0,
            "edges": kg_edges[0]["c"] if kg_edges else 0,
            "issues": issues[0]["c"] if issues else 0,
            "proposals": proposals[0]["c"] if proposals else 0,
            "code_health": round(avg_rating, 1),
        }

        return jsonify({"status": "ok", "kpis": kpis, "depts": dept_cards, "admin": admin_status})
    except Exception as e:
        log.error(f"api_dashboard error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/dept/<slug>")
def api_dept(slug):
    """Department details: KPIs, recent tasks, skills, corrections, model config."""
    dept = slug.lower()
    if dept not in DEPT_NAMES:
        return jsonify({"status": "error", "message": "Unknown department"}), 404
    try:
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        r_tasks = _query("SELECT COUNT(*) as c FROM dialog_history WHERE dept=? AND created_at>=? AND role='user'", (dept, week_ago), fetch=True)
        r_rating = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        r_tokens = _query("SELECT COALESCE(SUM(input_tokens),0)+COALESCE(SUM(output_tokens),0) as t FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        r_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)

        kpis = {
            "tasks": r_tasks[0]["c"] if r_tasks else 0,
            "rating": round(r_rating[0]["a"], 1) if r_rating else 0,
            "tokens": r_tokens[0]["t"] if r_tokens else 0,
            "cost": round(r_cost[0]["t"], 2) if r_cost else 0,
        }

        # Recent tasks
        recent = _query("SELECT content, created_at FROM dialog_history WHERE dept=? AND role='user' ORDER BY id DESC LIMIT 5", (dept,), fetch=True)
        tasks = [{"text": r["content"][:100], "created": r["created_at"][:16]} for r in recent]

        # Corrections
        corrs = _query("SELECT original_query, correction, created_at FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 5", (dept,), fetch=True)
        corrections = [{"original": r["original_query"][:80], "corrected": r["correction"][:80], "created": r["created_at"][:10]} for r in corrs]

        # Skills
        skills_idx = CFG_DIR / f"../skills_index/{dept}.txt"
        skills = []
        if skills_idx.exists():
            skills = [s.strip() for s in skills_idx.read_text().strip().split("\n") if s.strip()][:15]

        # Model config
        model = _cfg_cache["overrides"].get(dept) or _cfg_cache["priority_model"] or "glm-4.6"
        provider = _cfg_cache["priority_provider"]

        return jsonify({
            "status": "ok", "slug": dept, "name": DEPT_NAMES[dept],
            "color": DEPT_COLORS.get(dept, {}),
            "kpis": kpis, "tasks": tasks, "corrections": corrections,
            "skills": skills, "model": model, "provider": provider,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/models")
def api_models():
    """Model statuses with usage stats."""
    try:
        now = datetime.utcnow()
        month_ago = (now - timedelta(days=30)).isoformat()
        models = []

        # Build model list from providers + overrides
        seen = set()
        model_info = {
            "zai": {"name": "GLM 4.6", "provider": "zai", "label": "Z.ai", "tier": "priority"},
            "deepseek": {"name": "DeepSeek Chat", "provider": "deepseek", "label": "DeepSeek", "tier": "cheap"},
            "groq": {"name": "Llama 3.3 70B", "provider": "groq", "label": "Groq", "tier": "free"},
            "grok": {"name": "Grok 3", "provider": "grok", "label": "xAI", "tier": "free_limit"},
            "anthropic": {"name": "Claude Sonnet 4", "provider": "anthropic", "label": "Anthropic", "tier": "paid"},
            "openai": {"name": "GPT-4o", "provider": "openai", "label": "OpenAI", "tier": "paid"},
            "apodex": {"name": "Apodex 1.0", "provider": "apodex", "label": "Apodex", "tier": "special"},
        }

        for prov_key, info in model_info.items():
            api_key = os.environ.get(PROVIDERS[prov_key]["env_key"])
            if prov_key in seen:
                continue
            seen.add(prov_key)

            r_calls = _query("SELECT COUNT(*) as c FROM token_usage WHERE provider=? AND created_at>=?", (prov_key, month_ago), fetch=True)
            r_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE provider=? AND created_at>=?", (prov_key, month_ago), fetch=True)
            calls = r_calls[0]["c"] if r_calls else 0
            cost = r_cost[0]["t"] if r_cost else 0

            # Check if it's the priority provider
            is_priority = prov_key == _cfg_cache["priority_provider"]

            status = "active" if api_key else "no_key"
            if prov_key == "grok":
                # Check if rate limited (mock: if calls > 500)
                status = "limited" if calls > 500 else status

            models.append({
                "key": prov_key, "name": info["name"], "label": info["label"],
                "tier": info["tier"], "status": status, "priority": is_priority,
                "calls": calls, "cost": round(cost, 2),
            })

        # Overrides per dept
        overrides = {d: v for d, v in _cfg_cache["overrides"].items() if v}

        # Today analytics
        today = now.isoformat()[:10]
        r_today = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        r_today_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        active_provs = _query("SELECT DISTINCT provider FROM token_usage WHERE created_at>=?", (today,), fetch=True)

        analytics = {
            "requests_today": r_today[0]["c"] if r_today else 0,
            "cost_today": round(r_today_cost[0]["t"], 2) if r_today_cost else 0,
            "active_providers": len(active_provs),
        }

        return jsonify({"status": "ok", "models": models, "overrides": overrides, "analytics": analytics})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/economics")
def api_economics():
    """Economics data: costs by dept, by model, by period."""
    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        # Period costs
        periods = {}
        for label, start in [("today", today), ("week", week_ago), ("month", month_ago)]:
            r = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (start,), fetch=True)
            periods[label] = round(r[0]["t"], 2) if r else 0

        # By dept (month)
        dept_costs = _query("SELECT dept, COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=? GROUP BY dept ORDER BY t DESC", (month_ago,), fetch=True)
        by_dept = [{"dept": r["dept"], "name": DEPT_NAMES.get(r["dept"], r["dept"]), "cost": round(r["t"], 2), "color": DEPT_COLORS.get(r["dept"], {}).get("accent", "#C9A84C")} for r in dept_costs]

        # By provider (month)
        prov_costs = _query("SELECT provider, COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=? GROUP BY provider ORDER BY t DESC", (month_ago,), fetch=True)
        by_provider = [{"provider": r["provider"], "cost": round(r["t"], 2)} for r in prov_costs]

        # Budget
        budget_rows = _query("SELECT value FROM system_settings WHERE key='daily_budget'", fetch=True)
        budget = budget_rows[0]["value"] if budget_rows else "10"

        return jsonify({"status": "ok", "periods": periods, "by_dept": by_dept, "by_provider": by_provider, "budget": budget})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/narads")
def api_narads():
    """List narads."""
    try:
        rows = _query("SELECT id, title, description, risk_level, status, created_at, approved_at FROM narads ORDER BY id DESC LIMIT 20", fetch=True)
        narads = []
        for r in rows:
            narads.append({
                "id": r["id"], "title": r["title"], "description": r["description"] or "",
                "risk": r["risk_level"], "status": r["status"],
                "created": r["created_at"][:16] if r["created_at"] else "",
                "approved": r["approved_at"][:16] if r["approved_at"] else "",
            })
        return jsonify({"status": "ok", "narads": narads})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/narads/<nid>/approve")
def api_narad_approve(nid):
    try:
        _query("UPDATE narads SET status='approved', approved_at=datetime('now') WHERE id=?", (nid,))
        _log_audit("narad_approve_miniapp", {"narad_id": nid})
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/narads/<nid>/reject")
def api_narad_reject(nid):
    try:
        _query("UPDATE narads SET status='rejected' WHERE id=?", (nid,))
        _log_audit("narad_reject_miniapp", {"narad_id": nid})
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/archive")
def api_archive():
    """Search archive. Accepts ?q= query param, optional ?dept= filter."""
    try:
        q = request.args.get("q", "")
        dept_filter = request.args.get("dept", "")
        if q:
            search_term = f"%{q}%"
            if dept_filter:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE (raw_text LIKE ? OR title LIKE ?) AND dept=? ORDER BY created_at DESC LIMIT 50",
                             (search_term, search_term, dept_filter), fetch=True)
            else:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE raw_text LIKE ? OR title LIKE ? ORDER BY created_at DESC LIMIT 50",
                             (search_term, search_term), fetch=True)
        else:
            if dept_filter:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE dept=? ORDER BY created_at DESC LIMIT 50", (dept_filter,), fetch=True)
            else:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses ORDER BY created_at DESC LIMIT 50", fetch=True)

        results = [{"id": r["id"], "dept": r["dept"], "title": r["title"], "created": r["created_at"][:16] if r["created_at"] else ""} for r in rows]
        return jsonify({"status": "ok", "results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/admin/status")
def api_admin_status():
    """Admin stats: graph, issues, proposals."""
    try:
        kg_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph", fetch=True)
        kg_edges = _query("SELECT COUNT(*) as c FROM knowledge_edges", fetch=True)
        issues = _query("SELECT id, severity, file_path, issue, status FROM admin_findings WHERE status='open' ORDER BY id DESC LIMIT 10", fetch=True)
        proposals = _query("SELECT id, content, status FROM admin_proposals WHERE status='pending' ORDER BY id DESC LIMIT 10", fetch=True)
        reports = _query("SELECT COUNT(*) as c FROM admin_reports", fetch=True)

        return jsonify({
            "status": "ok",
            "graph": {"nodes": kg_nodes[0]["c"] if kg_nodes else 0, "edges": kg_edges[0]["c"] if kg_edges else 0},
            "issues": [{"id": r["id"], "severity": r["severity"], "file": r["file_path"], "issue": r["issue"]} for r in issues],
            "proposals": [{"id": r["id"], "content": r["content"][:200], "status": r["status"]} for r in proposals],
            "reports_count": reports[0]["c"] if reports else 0,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  ADMIN UA — Understand Anything (6 sub-agents)
# ══════════════════════════════════════════════════════════════════════

SKIP_DIRS = {'data', '.git', 'node_modules', '__pycache__', 'отчёты', 'tool-results', 'scripts', 'upload'}
KNOWN_BUILTINS = ['send_message', 'query', 'db_execute', 'kv_set', 'kv_get',
    'http_post', 'http_get', 'read_file', 'write_file', 'call_llm',
    'json_get', 'parse_json', 'json_encode', 'respond', 'respond_html',
    'memorize', 'recall', 'whisper_transcribe', 'tts_send', 'git_push',
    'web_search', 'env', 'now', 'len', 'replace', 'split', 'AuditLog',
    'RecordUserMessage', 'RecordAssistantMessage', 'BuildContext',
    'SendTelegramReply', 'SendReport', 'DetectDepartment', 'CallLLMProxy',
    'InitDB', 'HandleAdmin', 'HandleYana', 'HandleOSP', 'HandleLZ',
    'list_dir', 'escape_json', 'to_string', 'to_float', 'to_int',
    'index_of', 'substring', 'trim', 'lower', 'upper', 'starts_with',
    'ends_with', 'contains', 'json_body', 'query_param', 'http_get']


@app.get("/admin-ua/scan")
def admin_ua_scan():
    """Scanner: inventory of all files in /office."""
    inventory = {'files': [], 'total_lines': 0, 'total_files': 0, 'by_type': {}, 'by_dir': {}}
    office_dir = Path('/office')

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            rel = str(fpath.relative_to(office_dir))
            try:
                lines = len(fpath.read_text(errors='ignore').splitlines())
            except Exception:
                lines = 0
            ext = fpath.suffix
            dir_name = rel.split('/')[0] if '/' in rel else 'root'
            inventory['files'].append({
                'path': rel, 'lines': lines, 'ext': ext, 'dir': dir_name,
                'size_kb': round(fpath.stat().st_size / 1024, 1),
            })
            inventory['total_lines'] += lines
            inventory['total_files'] += 1
            inventory['by_type'][ext] = inventory['by_type'].get(ext, 0) + 1
            inventory['by_dir'][dir_name] = inventory['by_dir'].get(dir_name, 0) + 1

    inventory['files'].sort(key=lambda x: x['lines'], reverse=True)
    summary = (f"SCAN COMPLETE\n  Files: {inventory['total_files']} | "
               f"Lines: {inventory['total_lines']:,} | "
               f"Dirs: {len(inventory['by_dir'])}\n")
    for ext, cnt in sorted(inventory['by_type'].items(), key=lambda x: -x[1]):
        summary += f"  {ext or '(none)'}: {cnt} files\n"
    if inventory['files']:
        summary += f"  Largest: {inventory['files'][0]['path']} ({inventory['files'][0]['lines']} lines)\n"
    return jsonify({'summary': summary, 'inventory': inventory})


@app.get("/admin-ua/analyze")
def admin_ua_analyze():
    """Analyzer: extract patterns, routes, imports, builtins from each file."""
    office_dir = Path('/office')
    analysis = []

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            ext = fpath.suffix
            if ext not in ('.mlog', '.py'):
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue

            fa = {'path': rel, 'patterns': [], 'routes': [], 'imports': [],
                  'builtins_used': [], 'tables': []}

            if ext == '.mlog':
                for m in re.finditer(r'pattern\s+(\w+)\(([^)]*)\)\s*->\s*(\w+)', content):
                    fa['patterns'].append({'name': m.group(1), 'args': m.group(2), 'returns': m.group(3)})
                for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                    fa['routes'].append({'path': m.group(1), 'method': m.group(2)})
                for m in re.finditer(r'import\s+([\w/]+)', content):
                    fa['imports'].append(m.group(1))
                for b in KNOWN_BUILTINS:
                    if b + '(' in content:
                        fa['builtins_used'].append(b)
                for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?(\w+)', content):
                    fa['tables'].append(m.group(1))

            elif ext == '.py':
                for m in re.finditer(r'def\s+(\w+)\(', content):
                    fa['patterns'].append({'name': m.group(1), 'args': '', 'returns': ''})
                for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                    fa['routes'].append({'path': m.group(1), 'method': 'GET/POST'})

            analysis.append(fa)

    total_patterns = sum(len(f['patterns']) for f in analysis)
    total_routes = sum(len(f['routes']) for f in analysis)
    total_imports = sum(len(f['imports']) for f in analysis)
    summary = (f"ANALYZE COMPLETE\n  Files: {len(analysis)} | "
               f"Patterns: {total_patterns} | Routes: {total_routes} | Imports: {total_imports}")

    return jsonify({'summary': summary, 'analysis': analysis})


def _ua_analyze_internal():
    """Internal analyzer — returns list of file analysis dicts (no Flask)."""
    office_dir = Path('/office')
    analysis = []

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            ext = fpath.suffix
            if ext not in ('.mlog', '.py'):
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue

            fa = {'path': rel, 'patterns': [], 'routes': [], 'imports': [],
                  'builtins_used': [], 'tables': []}

            if ext == '.mlog':
                for m in re.finditer(r'pattern\s+(\w+)\(([^)]*)\)\s*->\s*(\w+)', content):
                    fa['patterns'].append({'name': m.group(1), 'args': m.group(2), 'returns': m.group(3)})
                for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                    fa['routes'].append({'path': m.group(1), 'method': m.group(2)})
                for m in re.finditer(r'import\s+([\w/]+)', content):
                    fa['imports'].append(m.group(1))
                for b in KNOWN_BUILTINS:
                    if b + '(' in content:
                        fa['builtins_used'].append(b)
                for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?(\w+)', content):
                    fa['tables'].append(m.group(1))

            elif ext == '.py':
                for m in re.finditer(r'def\s+(\w+)\(', content):
                    fa['patterns'].append({'name': m.group(1), 'args': '', 'returns': ''})
                for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                    fa['routes'].append({'path': m.group(1), 'method': 'GET/POST'})

            analysis.append(fa)

    return analysis


def _ua_scan_internal():
    """Internal scanner — returns inventory dict (no Flask)."""
    inventory = {'files': [], 'total_lines': 0, 'total_files': 0, 'by_type': {}, 'by_dir': {}}
    office_dir = Path('/office')

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            rel = str(fpath.relative_to(office_dir))
            try:
                lines = len(fpath.read_text(errors='ignore').splitlines())
            except Exception:
                lines = 0
            ext = fpath.suffix
            dir_name = rel.split('/')[0] if '/' in rel else 'root'
            inventory['files'].append({
                'path': rel, 'lines': lines, 'ext': ext, 'dir': dir_name,
                'size_kb': round(fpath.stat().st_size / 1024, 1),
            })
            inventory['total_lines'] += lines
            inventory['total_files'] += 1
            inventory['by_type'][ext] = inventory['by_type'].get(ext, 0) + 1
            inventory['by_dir'][dir_name] = inventory['by_dir'].get(dir_name, 0) + 1

    inventory['files'].sort(key=lambda x: x['lines'], reverse=True)
    return inventory


def _ua_review_internal():
    """Internal reviewer — returns findings dict with health_score (no Flask)."""
    office_dir = Path('/office')
    findings = []
    all_mlog = {}
    all_patterns = {}
    called_patterns = set()
    imported_files = set()

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix != '.mlog':
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            all_mlog[rel] = content
            for m in re.finditer(r'pattern\s+(\w+)\(', content):
                all_patterns[m.group(1)] = rel
            for m in re.finditer(r'import\s+([\w/]+)', content):
                imported_files.add(m.group(1) + '.mlog')
            for pname in all_patterns:
                if pname + '(' in content:
                    called_patterns.add(pname)
            if rel.startswith('dept/') and 'AuditLog' not in content and rel not in ('dept/utils.mlog', 'dept/context.mlog'):
                findings.append({'severity': 'medium', 'category': 'ARCHITECTURE',
                                 'file': rel, 'issue': 'No AuditLog calls — actions not logged',
                                 'fix': 'Add AuditLog() after LLM calls'})

    for f in all_mlog:
        if f != 'app.mlog' and f not in imported_files and f not in ('file_cache.mlog', 'file_cache_skills.mlog'):
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': f, 'issue': f'File not imported — possible dead code',
                             'fix': 'Import in app.mlog or delete'})

    entry_points = {'InitDB', 'Main', 'mlogserver'}
    for pname, pfile in all_patterns.items():
        if pname not in called_patterns and pname not in entry_points:
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': pfile, 'issue': f'Pattern {pname}() defined but never called',
                             'fix': 'Call it or remove'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'route\s+"(/cron/[^"]+)"', content):
            route_block = content[m.end():m.end() + 500]
            if 'CRON_SECRET' not in route_block and 'secret' not in route_block.lower():
                findings.append({'severity': 'high', 'category': 'SECURITY',
                                 'file': f, 'issue': f'Route {m.group(1)} has no CRON_SECRET check',
                                 'fix': 'Add secret validation'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'contains\([^)]+\)\s*==\s*1\.0', content):
            findings.append({'severity': 'medium', 'category': 'BUGS',
                             'file': f, 'issue': 'contains() returns Bool, == 1.0 is type mismatch',
                             'fix': 'Use: if contains(...) then { }'})

    high = len([f for f in findings if f['severity'] == 'high'])
    medium = len([f for f in findings if f['severity'] == 'medium'])
    low = len([f for f in findings if f['severity'] == 'low'])
    score = max(1, round(10 - high * 2 - medium * 0.5 - low * 0.1, 1))

    return {'findings': findings, 'health_score': score}


@app.get("/admin-ua/graph")
def admin_ua_graph():
    """Grapher: build knowledge graph from analysis data, save to SQLite."""
    conn = sqlite3.connect(str(DB_FILE))
    c = conn.cursor()

    # Ensure tables exist (may be missing if DB predates this feature)
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge_graph
        (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT,
         file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge_edges
        (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT,
         edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')))""")

    # Clear old graph
    c.execute("DELETE FROM knowledge_graph")
    c.execute("DELETE FROM knowledge_edges")

    # Run analyzer internally (not via Flask)
    analysis = _ua_analyze_internal()

    nodes_saved = 0
    edges_saved = 0
    now_ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    for fa in analysis:
        rel = fa['path']
        # Node: file
        c.execute(
            "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
            ('file', rel, rel, f"{len(fa.get('patterns', []))} patterns, {len(fa.get('routes', []))} routes", now_ts))
        nodes_saved += 1

        # Nodes + edges: patterns
        for p in fa.get('patterns', []):
            pname = p.get('name', '')
            if not pname:
                continue
            c.execute(
                "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                ('pattern', pname, rel, f"args={p.get('args', '')} returns={p.get('returns', '')}", now_ts))
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, pname, 'defines', rel, now_ts))
            edges_saved += 1

        # Nodes + edges: routes
        for r in fa.get('routes', []):
            rname = r.get('path', '')
            if not rname:
                continue
            c.execute(
                "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                ('route', rname, rel, r.get('method', ''), now_ts))
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, rname, 'exposes', rel, now_ts))
            edges_saved += 1

        # Nodes + edges: tables
        for t in fa.get('tables', []):
            c.execute(
                "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                ('table', t, rel, 'CREATE TABLE', now_ts))
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, t, 'creates', rel, now_ts))
            edges_saved += 1

        # Edges: imports
        for imp in fa.get('imports', []):
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, imp + '.mlog', 'imports', rel, now_ts))
            edges_saved += 1

        # Edges: builtins used
        for b in fa.get('builtins_used', []):
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, b, 'calls_builtin', rel, now_ts))
            edges_saved += 1

    # Cross-file pattern calls: find which files call patterns from other files
    pattern_to_file = {}
    for fa in analysis:
        for p in fa.get('patterns', []):
            pname = p.get('name', '')
            if pname:
                pattern_to_file[pname] = fa['path']

    for fa in analysis:
        rel = fa['path']
        for pname in pattern_to_file:
            if pname == 'Main' or pname == 'InitDB' or pname == 'mlogserver':
                continue
            if pattern_to_file[pname] != rel:
                try:
                    fpath = (BASE_DIR / rel)
                    if fpath.exists():
                        content = fpath.read_text(errors='ignore')
                        if pname + '(' in content:
                            c.execute(
                                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                                (rel, pname, 'calls', rel, now_ts))
                            edges_saved += 1
                except Exception:
                    pass

    conn.commit()
    conn.close()

    summary = (f"GRAPH COMPLETE\n  Nodes: {nodes_saved} | Edges: {edges_saved}\n  "
               f"Files analyzed: {len(analysis)}")
    return jsonify({'summary': summary, 'nodes': nodes_saved, 'edges': edges_saved})


@app.get("/admin-ua/review")
def admin_ua_review():
    """Reviewer: orphans, bugs, security, architecture checks."""
    office_dir = Path('/office')
    findings = []

    all_mlog = {}
    all_patterns = {}
    called_patterns = set()
    imported_files = set()

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix != '.mlog':
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            all_mlog[rel] = content

            for m in re.finditer(r'pattern\s+(\w+)\(', content):
                all_patterns[m.group(1)] = rel

            for m in re.finditer(r'import\s+([\w/]+)', content):
                imported_files.add(m.group(1) + '.mlog')

            for pname in all_patterns:
                if pname + '(' in content:
                    called_patterns.add(pname)

            if rel.startswith('dept/') and 'AuditLog' not in content and rel not in ('dept/utils.mlog', 'dept/context.mlog'):
                findings.append({'severity': 'medium', 'category': 'ARCHITECTURE',
                                 'file': rel, 'issue': 'No AuditLog calls — actions not logged',
                                 'fix': 'Add AuditLog() after LLM calls'})

    for f in all_mlog:
        if f != 'app.mlog' and f not in imported_files and f not in ('file_cache.mlog', 'file_cache_skills.mlog'):
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': f, 'issue': f'File not imported — possible dead code',
                             'fix': 'Import in app.mlog or delete'})

    entry_points = {'InitDB', 'Main', 'mlogserver'}
    for pname, pfile in all_patterns.items():
        if pname not in called_patterns and pname not in entry_points:
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': pfile, 'issue': f'Pattern {pname}() defined but never called',
                             'fix': 'Call it or remove'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'route\s+"(/cron/[^"]+)"', content):
            route_block = content[m.end():m.end() + 500]
            if 'CRON_SECRET' not in route_block and 'secret' not in route_block.lower():
                findings.append({'severity': 'high', 'category': 'SECURITY',
                                 'file': f, 'issue': f'Route {m.group(1)} has no CRON_SECRET check',
                                 'fix': 'Add secret validation'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'contains\([^)]+\)\s*==\s*1\.0', content):
            findings.append({'severity': 'medium', 'category': 'BUGS',
                             'file': f, 'issue': 'contains() returns Bool, == 1.0 is type mismatch',
                             'fix': 'Use: if contains(...) then { }'})

    high = len([f for f in findings if f['severity'] == 'high'])
    medium = len([f for f in findings if f['severity'] == 'medium'])
    low = len([f for f in findings if f['severity'] == 'low'])
    score = max(1, round(10 - high * 2 - medium * 0.5 - low * 0.1, 1))
    summary = f"REVIEW COMPLETE\n  Findings: {len(findings)} (high={high}, medium={medium}, low={low})\n  Health: {score}/10"

    return jsonify({'summary': summary, 'findings': findings, 'health_score': score})


@app.get("/admin-ua/impact")
def admin_ua_impact():
    """Differ: impact analysis for a file."""
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({'error': 'Missing ?file= parameter', 'dependents': [], 'risk': 'unknown'})

    office_dir = Path('/office')
    dependents = []
    target_module = file_path.replace('.mlog', '').replace('/', '')

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix != '.mlog':
                continue
            rel = str(fpath.relative_to(office_dir))
            if rel == file_path:
                continue
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            if f'import {target_module}' in content or f'import dept/{target_module}' in content:
                dependents.append({'file': rel, 'relation': 'imports'})

    risk = 'low'
    if len(dependents) > 5 or file_path == 'app.mlog':
        risk = 'high'
    elif len(dependents) > 2:
        risk = 'medium'

    summary = f"Impact Analysis: {file_path}\n  Risk: {risk} | Dependents: {len(dependents)}\n"
    for d in dependents:
        summary += f"  {d['file']} ({d['relation']})\n"

    return jsonify({'summary': summary, 'file': file_path, 'dependents': dependents,
                    'risk': risk, 'dependent_count': len(dependents)})


@app.get("/admin-ua/docs")
def admin_ua_docs():
    """Documenter: auto-generate project structure and API reference."""
    office_dir = Path('/office')
    files_info = []
    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix not in ('.mlog', '.py', '.txt', '.html'):
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                lines = len(fpath.read_text(errors='ignore').splitlines())
            except Exception:
                lines = 0
            files_info.append({'path': rel, 'lines': lines})
    files_info.sort(key=lambda x: x['path'])

    structure = f"# Fosved Office v2 — Структура проекта\n\n**{len(files_info)} файлов**\n\n"
    for f in files_info:
        structure += f"- `{f['path']}` — {f['lines']} строк\n"

    api = "# API Reference\n\n"
    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix not in ('.mlog', '.py'):
                continue
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            rel = str(fpath.relative_to(office_dir))
            if fpath.suffix == '.mlog':
                for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                    api += f"### `{m.group(2).upper()} {m.group(1)}`\nFile: `{rel}`\n\n"
            elif fpath.suffix == '.py':
                for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                    api += f"### `{m.group(1)}`\nFile: `{rel}`\n\n"

    return jsonify({'structure': structure, 'api': api})


@app.post("/admin-ua/night-cycle")
def admin_ua_night_cycle():
    """
    Full UA night cycle: Scanner → Analyzer → Grapher → Reviewer → Differ → Documenter.
    Saves results to admin_night_reports, updates knowledge graph.
    Called from /cron/night or /admin analyze.
    """
    try:
        log.info("UA Night Cycle: Phase 1/6 — Scanner")
        inventory = _ua_scan_internal()

        log.info("UA Night Cycle: Phase 2/6 — Analyzer")
        analysis = _ua_analyze_internal()

        log.info("UA Night Cycle: Phase 3/6 — Grapher")
        # Build graph in SQLite
        conn = sqlite3.connect(str(DB_FILE))
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge_graph
            (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT,
             file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')))""")
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge_edges
            (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT,
             edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')))""")
        c.execute("DELETE FROM knowledge_graph")
        c.execute("DELETE FROM knowledge_edges")

        nodes_saved = 0
        edges_saved = 0
        now_ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        for fa in analysis:
            rel = fa['path']
            c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?,?,?,?,?)",
                      ('file', rel, rel, f"{len(fa.get('patterns', []))}p {len(fa.get('routes', []))}r", now_ts))
            nodes_saved += 1
            for p in fa.get('patterns', []):
                pname = p.get('name', '')
                if not pname: continue
                c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?,?,?,?,?)",
                          ('pattern', pname, rel, '', now_ts))
                nodes_saved += 1
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, pname, 'defines', rel, now_ts))
                edges_saved += 1
            for r in fa.get('routes', []):
                rname = r.get('path', '')
                if not rname: continue
                c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?,?,?,?,?)",
                          ('route', rname, rel, r.get('method', ''), now_ts))
                nodes_saved += 1
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, rname, 'exposes', rel, now_ts))
                edges_saved += 1
            for imp in fa.get('imports', []):
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, imp + '.mlog', 'imports', rel, now_ts))
                edges_saved += 1

        # Cross-file pattern calls
        pattern_to_file = {}
        for fa in analysis:
            for p in fa.get('patterns', []):
                if p.get('name'): pattern_to_file[p['name']] = fa['path']
        for fa in analysis:
            rel = fa['path']
            for pname, pfile in pattern_to_file.items():
                if pname in ('Main', 'InitDB', 'mlogserver'): continue
                if pfile != rel:
                    try:
                        content = (Path('/office') / rel).read_text(errors='ignore')
                        if pname + '(' in content:
                            c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                                      (rel, pname, 'calls', rel, now_ts))
                            edges_saved += 1
                    except Exception:
                        pass

        conn.commit()
        conn.close()

        log.info("UA Night Cycle: Phase 4/6 — Reviewer")
        review = _ua_review_internal()
        findings = review['findings']
        health = review['health_score']

        log.info("UA Night Cycle: Phase 5/6 — Differ (skip — needs file param)")
        # Differ is on-demand via /admin impact <file>

        log.info("UA Night Cycle: Phase 6/6 — Documenter")
        structure_lines = []
        api_lines = []
        for fa in sorted(analysis, key=lambda x: x['path']):
            structure_lines.append(f"- `{fa['path']}` — {len(fa.get('patterns', []))} patterns")
            for r in fa.get('routes', []):
                api_lines.append(f"{r.get('method', '?')} {r['path']} ({fa['path']})")

        # Save night report to DB
        import json as _json
        _query("INSERT INTO admin_night_reports (scan_data, review_data, health_score, findings_count, created_at) VALUES (?,?,?,?,?)",
               (_json.dumps({'total_files': inventory['total_files'], 'total_lines': inventory['total_lines']}),
                _json.dumps(findings[:50]),
                health, len(findings), datetime.utcnow().isoformat()))

        # Save findings to admin_findings table
        for f in findings:
            _query("INSERT INTO admin_findings (severity, category, file, issue, fix, status) VALUES (?,?,?,?,?,?)",
                   (f['severity'], f['category'], f.get('file', ''), f['issue'], f.get('fix', ''), 'open'))

        # Close open findings that are resolved
        _query("UPDATE admin_findings SET status='closed' WHERE status='open' AND created_at < datetime('now', '-7 days')")

        summary = (f"UA NIGHT CYCLE COMPLETE\n"
                   f"  Files: {inventory['total_files']} ({inventory['total_lines']:,} lines)\n"
                   f"  Patterns: {sum(len(f['patterns']) for f in analysis)}\n"
                   f"  Routes: {sum(len(f['routes']) for f in analysis)}\n"
                   f"  Graph: {nodes_saved} nodes, {edges_saved} edges\n"
                   f"  Findings: {len(findings)} (h={len([f for f in findings if f['severity']=='high'])} "
                   f"m={len([f for f in findings if f['severity']=='medium'])} "
                   f"l={len([f for f in findings if f['severity']=='low'])})\n"
                   f"  Health: {health}/10")

        _log_audit("ua_night_cycle", {"files": inventory['total_files'], "nodes": nodes_saved,
                                       "edges": edges_saved, "findings": len(findings), "health": health})

        return jsonify({'status': 'ok', 'summary': summary, 'health_score': health,
                        'findings_count': len(findings)})

    except Exception as e:
        log.error(f"ua_night_cycle error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.get("/admin-ua/tour")
def admin_ua_tour():
    """Tour: guided architecture tour using all 6 sub-agents."""
    # Use internal functions, not Flask self-calls
    scan_data = _ua_scan_internal()
    review_data = _ua_review_internal()
    g_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph", fetch=True)
    g_edges = _query("SELECT COUNT(*) as c FROM knowledge_edges", fetch=True)
    kg_nodes = g_nodes[0]['c'] if g_nodes else 0
    kg_edges = g_edges[0]['c'] if g_edges else 0

    tour = f"Guided Tour по Fosved Office v2\n\n"
    tour += f"Офис: {scan_data['total_files']} файлов ({scan_data['total_lines']:,} строк)\n"
    tour += f"Knowledge graph: {kg_nodes} nodes, {kg_edges} edges\n\n"

    top_files = sorted(scan_data['files'], key=lambda x: x['lines'], reverse=True)[:5]
    tour += "Ключевые файлы:\n"
    for f in top_files:
        tour += f"  {f['path']} — {f['lines']} строк ({f['size_kb']} KB)\n"

    # Top dirs
    by_dir = scan_data.get('by_dir', {})
    tour += f"\nСтруктура: {len(by_dir)} директорий\n"
    for d, cnt in sorted(by_dir.items(), key=lambda x: -x[1])[:6]:
        tour += f"  {d}/ — {cnt} файлов\n"

    health = review_data.get('health_score', '?')
    findings = review_data.get('findings', [])
    tour += f"\nCode health: {health}/10\n"

    high_f = [f for f in findings if f['severity'] == 'high'][:3]
    med_f = [f for f in findings if f['severity'] == 'medium'][:3]
    if high_f:
        tour += f"\nHIGH severity ({len(high_f)}):\n"
        for f in high_f:
            tour += f"  [{f['category']}] {f['file']}: {f['issue']}\n"
    if med_f:
        tour += f"\nMEDIUM ({len(med_f)}):\n"
        for f in med_f:
            tour += f"  [{f['category']}] {f['file']}: {f['issue']}\n"

    return jsonify({'tour': tour})


# ══════════════════════════════════════════════════════════════════════
#  MINI APP SPA — STATIC FILE SERVING
# ══════════════════════════════════════════════════════════════════════

MINIAPP_DIR = BASE_DIR / "miniapp"

@app.get("/miniapp")
@require_telegram
def miniapp_redirect():
    """Redirect /miniapp to /miniapp-spa."""
    from flask import redirect
    return redirect("/miniapp-spa", code=301)

@app.get("/miniapp-spa")
@app.get("/miniapp-spa/")
@require_telegram
def miniapp_spa_index():
    """Serve the Mini App SPA index page with API_SECRET injected."""
    index_path = MINIAPP_DIR / "index.html"
    if not index_path.exists():
        return "<h1>Mini App not found</h1>", 404
    html = index_path.read_text(encoding="utf-8")
    html = html.replace('{{API_SECRET}}', API_SECRET)
    return Response(html, mimetype="text/html")

@app.get("/miniapp-spa/<path:filepath>")
def miniapp_spa_static(filepath):
    """Serve static assets for the Mini App SPA.

    No initData check here: browsers do not send custom headers when loading
    <link> and <script> resources, so requiring it would break every screen.
    These files contain no user data — the pages that do remain protected.
    """
    file_path = (MINIAPP_DIR / filepath).resolve()
    if not str(file_path).startswith(str(MINIAPP_DIR.resolve())):
        return "<h1>Not found</h1>", 404
    if not file_path.exists() or not file_path.is_file():
        return "<h1>Not found</h1>", 404
    ext = file_path.suffix
    mimes = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
             ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json"}
    return Response(file_path.read_bytes(), mimetype=mimes.get(ext, "application/octet-stream"))

# ══════════════════════════════════════════════════════════════════════
#  LZ DAILY REPORT — GitHub scan + LLM analysis + Admin delivery
# ══════════════════════════════════════════════════════════════════════

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN_METALOGOS", "")
GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    GITHUB_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# Queries for GitHub scanning — tuned to Fosved's tech stack
# Dates are dynamic: search repos updated/created in last 14 days
def _build_github_queries():
    """Build GitHub search queries for Fosved's tech stack."""
    return [
        "LLM agent framework language:python stars:>10",
        "telegram bot AI assistant python stars:>5",
        "Rust DSL parser interpreter stars:>5",
        "multi-agent LLM office automation stars:>3",
        "RAG retrieval augmented python stars:>10",
        "mcp model context protocol tool stars:>5",
        "mem0 mem0ai agent memory stars:>5",
        "Flask LLM proxy failover stars:>3",
    ]

# Repos to watch for new releases
GITHUB_WATCH_RELEASES = [
    "moorcheh-ai/memanto",
    "langchain-ai/langchain",
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
]


def _github_search(query, sort="updated", per_page=5):
    """Search GitHub repos, return list of dicts. Works without token (public API)."""
    try:
        params = {"q": query, "sort": sort, "order": "desc", "per_page": per_page}
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN and not GITHUB_TOKEN.startswith("["):
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        resp = http_requests.get(
            "https://api.github.com/search/repositories",
            headers=headers, params=params, timeout=15
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            return [{
                "name": r["full_name"],
                "desc": (r.get("description") or "")[:120],
                "stars": r.get("stargazers_count", 0),
                "lang": r.get("language", ""),
                "updated": r.get("updated_at", "")[:10],
                "url": r.get("html_url", ""),
                "created": r.get("created_at", "")[:10],
            } for r in items]
        elif resp.status_code == 403:
            log.warning(f"GitHub API rate limited: {query[:50]}")
            return []
        else:
            log.warning(f"GitHub search {resp.status_code}: {query[:50]}")
            return []
    except Exception as e:
        log.error(f"GitHub search error: {e}")
        return []


def _github_releases(repo_full_name):
    """Get latest 3 releases for a repo. Works without token."""
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN and not GITHUB_TOKEN.startswith("["):
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        resp = http_requests.get(
            f"https://api.github.com/repos/{repo_full_name}/releases?per_page=3",
            headers=headers, timeout=10
        )
        if resp.status_code == 200:
            return [{
                "repo": repo_full_name,
                "tag": r.get("tag_name", ""),
                "name": r.get("name", ""),
                "body": (r.get("body") or "")[:200],
                "date": r.get("published_at", "")[:10],
                "url": r.get("html_url", ""),
            } for r in resp.json() if not r.get("draft", False)]
        return []
    except Exception as e:
        log.error(f"GitHub releases error for {repo_full_name}: {e}")
        return []


@app.post("/scheduler/lz-daily")
def scheduler_lz_daily():
    """
    LZ Daily Report: scan GitHub → LLM analysis → save to memory → return report.
    Called by /cron/lz-daily or manually.
    """
    d = request.get_json(force=True) or {}
    owner_id = d.get("owner_id", os.environ.get("OWNER_TELEGRAM_ID", ""))
    dry_run = d.get("dry_run", False)

    try:
        # ── Phase 1: GitHub Scan (direct API) ─────────────────
        log.info("LZ Daily: starting GitHub scan")
        all_repos = []
        seen = set()
        for q in _build_github_queries():
            repos = _github_search(q, per_page=3)
            time.sleep(1)
            for r in repos:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    all_repos.append(r)

        # Check watched repos for new releases
        all_releases = []
        seen_release_keys = set()  # dedup by (repo, tag) across runs
        for repo in GITHUB_WATCH_RELEASES:
            releases = _github_releases(repo)
            time.sleep(1)
            for r in releases:
                rkey = f"{r['repo']}@{r['tag']}"
                if rkey not in seen_release_keys:
                    seen_release_keys.add(rkey)
                    all_releases.append(r)

        github_ok = bool(all_repos or all_releases)
        if not github_ok:
            log.warning("LZ Daily: GitHub API returned 0 results, will use LLM fallback")

        # Also check lz_monitors table for custom topics
        monitor_topics = []
        try:
            monitors = _query("SELECT query FROM lz_monitors WHERE frequency = 'daily'", fetch=True)
            monitor_topics = [m["query"] for m in monitors] if monitors else []
        except Exception:
            pass  # Table may not exist yet (created by mlog InitDB)

        scan_summary = {
            "repos_found": len(all_repos),
            "releases_found": len(all_releases),
            "monitors_active": len(monitor_topics),
            "github_api_ok": github_ok,
        }

        # ── Phase 2: LLM Analysis ─────────────────────────────
        lz_prompt = get_dept_prompt("lz")

        if github_ok:
            # Direct API worked — analyze the data we collected
            repos_text = ""
            for i, r in enumerate(all_repos[:15], 1):
                repos_text += f"{i}. {r['name']} ({r['stars']}★, {r['lang']}) — {r['desc']}\n   {r['url']}\n"
            releases_text = ""
            for r in all_releases:
                releases_text += f"- {r['repo']} {r['tag']}: {r['name']} ({r['date']})\n  {r['body']}\n  {r['url']}\n"
            monitors_text = ""
            if monitor_topics:
                monitors_text = "Custom monitors: " + ", ".join(monitor_topics)

            analysis_messages = [
                {"role": "system", "content": lz_prompt + "\n\n"
                 "Ты — Лаборатория Загадок Фосвед Офиса. Задача: проанализировать ежедневный скан GitHub.\n\n"
                 "ТВОЯ КЛЮЧЕВАЯ РОЛЬ: отобрать НОВИНКИ, которые Админ должен изучить для применения в офисе.\n\n"
                 "Структура отчёта:\n"
                 "1. 🔥 TOP-3 находки (с disrupting potential 1-10) — что полезно для Фосвед Офиса\n"
                 "2. 📦 Новые релизы — что обновилось в ключевых проектах\n"
                 "3. 💡 Рекомендации — что Админу стоит изучить и почему\n"
                 "4. 📊 Статистика скана\n\n"
                 "Фильтруй: только релевантное для AI-офиса, multi-agent систем, Telegram ботов, DSL, memory systems.\n"
                 "Язык: русский."},
                {"role": "user", "content": f"Данные скана за {datetime.utcnow().isoformat()[:10]}:\n\n"
                 f"=== НОВЫЕ РЕПОЗИТОРИИ ({len(all_repos)} найдено) ===\n"
                 f"{repos_text}\n\n"
                 f"=== НОВЫЕ РЕЛИЗЫ ({len(all_releases)}) ===\n"
                 f"{releases_text}\n\n"
                 f"{monitors_text}"}
            ]
        else:
            # GitHub API failed — LLM researches directly
            log.info("LZ Daily: using LLM fallback for GitHub research")
            analysis_messages = [
                {"role": "system", "content": lz_prompt + "\n\n"
                 "Ты — Лаборатория Загадок Фосвед Офиса. GitHub API недоступен, поэтому ты проводишь "
                 "исследование САМОСТОЯТЕЛЬНО, используя свои знания.\n\n"
                 "ТВОЯ КЛЮЧЕВАЯ РОЛЬ: найти НОВИНКИ за последнюю неделю, которые Админ должен изучить.\n\n"
                 "Ищи в областях:\n"
                 "- LLM agent frameworks (Python): новые фреймворки, мажорные обновления\n"
                 "- Telegram bot AI assistants\n"
                 "- Multi-agent systems, MCP protocol\n"
                 "- RAG, memory systems (mem0 и аналоги)\n"
                 "- Rust DSL / интерпретаторы\n\n"
                 "Структура отчёта:\n"
                 "1. 🔥 TOP-3 находки (с disrupting potential 1-10)\n"
                 "2. 📦 Ключевые обновления проектов\n"
                 "3. 💡 Рекомендации Админу\n\n"
                 "Если не знаешь конкретных новостей за последнюю неделю — так и скажи.\n"
                 "Язык: русский."},
                {"role": "user", "content": f"Сделай ежедневный обзор новинок на GitHub за последнюю неделю.\n"
                 f"Дата: {datetime.utcnow().isoformat()[:10]}\n"
                 f"Фокус: AI agents, LLM, Telegram bots, memory systems, MCP, RAG.\n\n"
                 f"Для каждого проекта укажи: название, URL, что нового, почему релевантно Фосвед Офису."}
            ]

        result = call_llm("lz", analysis_messages)
        analysis = result.get("reply", "Analysis failed.")

        # ── Phase 3: Save to DB + Memory (with cross-run dedup) ───────────
        if not dry_run:
            # LZ Dedup: save releases & repos to lz_telegram_posts with update_id
            # update_id format: "gh:{repo}:{tag}" for releases, "gh:repo:{name}" for repos
            # UNIQUE constraint on update_id prevents duplicate entries across scans
            for r in all_releases:
                try:
                    _query(
                        "INSERT OR IGNORE INTO lz_telegram_posts (update_id, channel_id, channel_name, text, date) VALUES (?, ?, ?, ?, ?)",
                        (f"gh:{r.get('repo','')}:{r.get('tag','')}", r.get('repo',''), r.get('repo',''), r.get('body','')[:500], r.get('date',''))
                    )
                except Exception:
                    pass  # update_id column may not exist yet (pre-ALTER TABLE state)
            for r in all_repos:
                try:
                    _query(
                        "INSERT OR IGNORE INTO lz_telegram_posts (update_id, channel_id, channel_name, text, date) VALUES (?, ?, ?, ?, datetime('now'))",
                        (f"gh:repo:{r.get('name','')}", "github", r.get('lang',''), r.get('desc','')[:300])
                    )
                except Exception:
                    pass

            today_key = f"lz_daily:{datetime.utcnow().isoformat()[:10]}"
            # Check if we already stored today's scan summary
            existing = memory.recall(today_key, source="lz_daily", limit=1)
            if not existing:
                memory.remember(
                    f"LZ Daily {datetime.utcnow().isoformat()[:10]}: {len(all_repos)} repos, {len(all_releases)} releases scanned",
                    "observation", 0.7, "lz_daily"
                )
            # Save top findings as individual memories (dedup by content prefix)
            for line in analysis.split("\n"):
                line = line.strip()
                if line.startswith(("1.", "2.", "3.")) and len(line) > 20:
                    mem_key = f"lz_find:{line[:60]}"
                    if not memory.recall(mem_key, source="lz_daily", limit=1):
                        memory.remember(
                            f"LZ находка: {line[:200]}",
                            "observation", 0.8, "lz_daily"
                        )

        # ── Phase 4: Build Report ─────────────────────────────
        report = f"🔍 LZ DAILY REPORT — {datetime.utcnow().isoformat()[:10]}\n"
        report += f"{'=' * 40}\n\n"
        report += analysis
        report += f"\n\n{'─' * 40}\n"
        report += f"Скан: {len(all_repos)} repos, {len(all_releases)} releases, {len(monitor_topics)} monitors\n"
        report += f"Provider: {result.get('provider', '?')} | Tokens: {result.get('tokens_in', 0)}+{result.get('tokens_out', 0)}"

        # ── Phase 5: Send to Owner (Admin) ────────────────────
        msg_id = None
        if owner_id and not dry_run:
            if len(report) > 1500:
                msg_id = _tg_send_report_with_button(owner_id, report)
            else:
                msg_id = _tg_send_message(owner_id, report)

        _log_audit("lz_daily_report", {
            "repos": len(all_repos), "releases": len(all_releases),
            "monitors": len(monitor_topics), "provider": result.get("provider"),
            "msg_id": msg_id, "dry_run": dry_run
        })

        return jsonify({
            "status": "ok",
            "report": report,
            "scan": scan_summary,
            "msg_id": msg_id,
            "sent_to": owner_id if not dry_run else None,
        })

    except Exception as e:
        log.error(f"lz_daily_report error: {e}")
        _log_audit("lz_daily_report_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/scheduler/admin-daily")
def scheduler_admin_daily():
    """
    Admin Daily Report: comprehensive report combining:
    - Night cycle results (from kv)
    - Memory maintenance summary
    - LZ daily findings
    - System health
    Sent to owner.
    """
    d = request.get_json(force=True) or {}
    owner_id = d.get("owner_id", os.environ.get("OWNER_TELEGRAM_ID", ""))

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        parts = []

        # 1. Night cycle summary (if available)
        night_summary = ""  # Would need to read from mlog kv — call mlog internal
        parts.append(f"📅 АДМИН ДAILY REPORT — {today}")
        parts.append("=" * 40)

        # 2. Memory stats
        mem_stats = memory.stats()
        parts.append(f"\n🧠 ПАМЯТЬ: {mem_stats['total_active']} активных записей")
        for t, info in sorted(mem_stats['by_type'].items(), key=lambda x: -x[1]['count'])[:5]:
            parts.append(f"  {t}: {info['count']} (avg conf {info['avg_confidence']})")

        # 3. Memory conflicts
        conflicts = memory.detect_conflicts()
        if conflicts:
            parts.append(f"\n⚠️ КОНФЛИКТЫ: {len(conflicts)}")
            for c in conflicts[:3]:
                parts.append(f"  [{c['type']}] {c['memory_a']['content'][:50]} vs {c['memory_b']['content'][:50]}")

        # 4. Memory maintenance
        maint = memory.nightly_maintenance()
        parts.append(f"\n🔧 MEMORY MAINTENANCE:\n{maint}")

        # 5. LZ daily findings
        lz_findings = memory.recall("LZ Daily", type_filter="observation", limit=3)
        if lz_findings:
            parts.append(f"\n🔍 LZ ПОСЛЕДНИЕ НАХОДКИ:")
            for f in lz_findings:
                ts = time.strftime('%m-%d', time.localtime(f['created_at']))
                parts.append(f"  [{ts}] {f['content'][:100]}")

        # 6. System metrics
        yesterday = (now - timedelta(days=1)).isoformat()[:10] + "T00:00:00"
        metrics = _collect_metrics_for_period(yesterday, today + "T00:00:00")
        parts.append(f"\n📊 МЕТРИКИ (вчера):")
        tasks_total = sum(metrics.get("tasks", {}).values())
        reports_total = sum(metrics.get("reports", {}).values())
        parts.append(f"  Tasks: {tasks_total} | Reports: {reports_total}")

        # 7. Open issues from night cycle
        f_cnt, p_cnt = 0, 0
        try:
            findings = _query(
                "SELECT COUNT(*) as cnt FROM admin_findings WHERE status = 'open'", fetch=True
            )
            proposals = _query(
                "SELECT COUNT(*) as cnt FROM admin_proposals WHERE status = 'pending'", fetch=True
            )
            if findings and proposals:
                f_cnt = findings[0].get("cnt", 0) if isinstance(findings[0], dict) else 0
                p_cnt = proposals[0].get("cnt", 0) if isinstance(proposals[0], dict) else 0
        except Exception:
            pass  # Tables may not exist yet (created by mlog InitDB)
        if f_cnt or p_cnt:
            parts.append(f"\n📋 АДМИН: {f_cnt} open issues, {p_cnt} pending proposals")

        report = "\n".join(parts)

        # Send to owner
        if len(report) > 2000:
            msg_id = _tg_send_report_with_button(owner_id, report)
        else:
            msg_id = _tg_send_message(owner_id, report)

        _log_audit("admin_daily_report", {"owner_id": owner_id, "msg_id": msg_id, "chars": len(report)})

        return jsonify({"status": "ok", "report": report, "msg_id": msg_id})

    except Exception as e:
        log.error(f"admin_daily_report error: {e}")
        _log_audit("admin_daily_report_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  FOSVED MEMORY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.route('/memory/recall', methods=['POST'])
def memory_recall_endpoint():
    """Recall memories by query."""
    data = request.get_json(force=True) or {}
    query = data.get('query', '')
    mem_type = data.get('type')
    limit = data.get('limit', 10)
    if not query:
        return jsonify({'error': 'query required'}), 400
    results = memory.recall(query, type_filter=mem_type, limit=limit)
    return jsonify({'results': results, 'count': len(results)})


@app.route('/memory/remember', methods=['POST'])
def memory_remember_endpoint():
    """Save a new memory."""
    data = request.get_json(force=True) or {}
    if 'content' not in data:
        return jsonify({'error': 'content required'}), 400
    mem_id = memory.remember(
        content=data['content'],
        mem_type=data.get('type', 'fact'),
        confidence=float(data.get('confidence', 0.8)),
        source=data.get('source', 'manual')
    )
    return jsonify({'id': mem_id, 'status': 'remembered'})


@app.route('/memory/stats', methods=['GET'])
def memory_stats_endpoint():
    """Memory statistics."""
    return jsonify(memory.stats())


@app.route('/memory/answer', methods=['POST'])
def memory_answer_endpoint():
    """RAG answer based on memory."""
    data = request.get_json(force=True) or {}
    answer_text = memory.answer(data.get('question', ''))
    return jsonify({'answer': answer_text})


@app.route('/memory/maintenance', methods=['POST'])
def memory_maintenance_endpoint():
    """Run nightly maintenance."""
    result = memory.nightly_maintenance()
    return jsonify({'result': result})


@app.route('/memory/conflicts', methods=['GET'])
def memory_conflicts_endpoint():
    """Detect memory conflicts."""
    conflicts = memory.detect_conflicts()
    return jsonify({'conflicts': conflicts, 'count': len(conflicts)})


@app.route('/yana/auto-memorize', methods=['POST'])
def yana_auto_memorize():
    """Extract key facts from Yana exchange and store to FosvedMemory.
    Uses cheap model (groq) for extraction. Fire and forget."""
    d = request.get_json(force=True) or {}
    query = d.get('query', '')
    reply = d.get('reply', '')
    chat_id = d.get('chat_id', '')
    if len(query) < 10 or len(reply) < 20:
        return jsonify({'status': 'skipped', 'reason': 'too short'})
    try:
        prompt = [
            {"role": "system", "content": "Extract 1-3 key facts worth remembering long-term from this conversation. "
                "Only facts about the OWNER: name, location, preferences, decisions, obligations, relationships, projects, health. "
                "Ignore: greetings, meta-comments, questions about system nature. "
                "Output ONLY a JSON array of objects with keys: content (string), type (fact|preference|commitment|decision|context), confidence (0.5-1.0). "
                "When a fact is a commitment or reminder with a date/time, include a \"date\" key with the date in YYYY-MM-DD HH:MM format (or YYYY-MM-DD if no time). If the date is relative (tomorrow, next week), calculate the actual date based on today being 2026-07-06. If nothing worth remembering, output: []"},
            {"role": "user", "content": f"User: {query[:500]}\nYana: {reply[:500]}"}
        ]
        result = _call_single_provider("groq", "llama-3.3-70b-versatile", prompt, dept="yana", max_tokens=300, is_internal=True)
        if result and result.get('reply'):
            import json as _json
            text = result['reply'].strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            facts = _json.loads(text)
            saved = 0
            for f in facts[:3]:
                if isinstance(f, dict) and f.get('content'):
                    memory.remember(
                        content=f['content'][:500],
                        mem_type=f.get('type', 'fact'),
                        confidence=float(f.get('confidence', 0.8)),
                        source='yana_auto'
                    )
                    saved += 1
            log.info(f"Yana auto-memorize: extracted {saved} facts from chat {chat_id}")

            # Also check for dated reminders — store in yana_events for scheduler
            for f in facts[:3]:
                if isinstance(f, dict) and f.get('type') == 'commitment' and f.get('date'):
                    _query("INSERT OR IGNORE INTO yana_events (event_text, event_date, event_type) VALUES (?, ?, 'reminder')",
                           (f['content'][:300], f['date'][:20]))
                    log.info(f"Yana reminder stored: {f['content'][:60]} at {f.get('date', '?')}")

            return jsonify({'status': 'ok', 'saved': saved})
    except Exception as e:
        log.warning(f"Yana auto-memorize failed: {e}")
    return jsonify({'status': 'error'})


# ══════════════════════════════════════════════════════════════════════
#  REMINDER CHECK — send due reminders to owner
# ══════════════════════════════════════════════════════════════════════

@app.post("/scheduler/reminder-check")
def scheduler_reminder_check():
    """Check yana_events for due reminders and send them to owner."""
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        return jsonify({"status": "error", "message": "OWNER_TELEGRAM_ID not set"}), 400

    try:
        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        # Find events due now (event_date <= now) that haven't been reminded yet
        rows = _query("SELECT id, event_text, event_date FROM yana_events "
                       "WHERE event_date <= ? AND reminded_at IS NULL "
                       "ORDER BY event_date ASC LIMIT 5",
                       (now_iso,))

        sent = 0
        for r in rows:
            event_text = r["event_text"]
            event_date = r["event_date"]
            event_id = r["id"]

            msg = f"Напоминание: {event_text}\n({event_date})"
            _send_telegram_message(owner_id, msg)

            # Mark as reminded
            _query("UPDATE yana_events SET reminded_at = datetime('now') WHERE id = ?", (event_id,))
            sent += 1
            log.info(f"Reminder sent: [{event_date}] {event_text[:60]}")

        # Clean up old reminded events (older than 7 days)
        _query("DELETE FROM yana_events WHERE reminded_at IS NOT NULL AND reminded_at < datetime('now', '-7 days')")

        return jsonify({"status": "ok", "sent": sent, "checked": len(rows)})
    except Exception as e:
        log.error(f"reminder_check error: {e}")
        _log_audit("scheduler_reminder_check_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  IMAGE GENERATION ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.route('/generate-image', methods=['POST'])
def generate_image_endpoint():
    """Generate an image via z-ai API and send it to Telegram chat.
    Request body: {prompt, size?, chat_id, caption?}
    Returns: {status, path?, error?}"""
    d = request.get_json(force=True) or {}
    prompt = d.get('prompt', '').strip()
    chat_id = str(d.get('chat_id', ''))
    size = d.get('size', '1024x1024')
    caption = d.get('caption', '')
    if not prompt:
        return jsonify({'status': 'error', 'error': 'prompt is required'}), 400
    if not chat_id:
        return jsonify({'status': 'error', 'error': 'chat_id is required'}), 400
    # Send upload_photo action so user sees progress
    _tg_send_chat_action(chat_id, 'upload_photo')
    fpath, err = _generate_image(prompt, size)
    if err:
        _tg_send_message(chat_id, f"Не удалось сгенерировать изображение: {err}")
        return jsonify({'status': 'error', 'error': err}), 500
    # Send to Telegram
    msg_id = _tg_send_photo(chat_id, fpath, caption or None)
    _log_audit('image_generated', {'prompt': prompt[:100], 'size': size, 'path': fpath, 'chat_id': chat_id, 'tg_msg_id': msg_id}, dept='design')
    return jsonify({'status': 'ok', 'path': fpath, 'tg_msg_id': msg_id})


# ══════════════════════════════════════════════════════════════════════
#  OSINT ENDPOINT — Aliens Eye 840+ platforms
# ══════════════════════════════════════════════════════════════════════

@app.route('/lz/osint', methods=['POST'])
def lz_osint():
    """OSINT scan via Aliens Eye. Owner-only, rate-limited."""
    import time as _time
    d = request.get_json(force=True) or {}
    username = d.get('username', '').strip()
    level = d.get('level', 'basic')
    tor = d.get('tor', False)
    sites = d.get('sites', None)
    chat_id = str(d.get('chat_id', ''))
    caller_id = str(d.get('caller_id', ''))

    if not username:
        return jsonify({'error': 'Username required'}), 400

    # Owner-only check
    owner_id = os.environ.get('OWNER_TELEGRAM_ID', '')
    if owner_id and caller_id and caller_id != owner_id:
        _log_audit('lz_osint_denied', {'caller_id': caller_id, 'username': username}, 'lz')
        return jsonify({'error': 'OSINT доступен только владельцу'}), 403

    # Rate limit
    now = _time.time()
    last = _osint_last_time.get(chat_id, 0)
    if now - last < OSINT_RATE_LIMIT:
        wait = int(OSINT_RATE_LIMIT - (now - last))
        return jsonify({'error': f'Rate limit: подождите {wait} сек между сканами'}), 429
    _osint_last_time[chat_id] = now

    # Typing indicator
    try:
        _tg_send_message(chat_id, f"🔍 Сканирую {username} по 840+ платформам... (30-120 сек)")
    except Exception:
        pass

    # Scan
    result = scan_osint(username, level=level, tor=tor, sites=sites)

    if 'error' in result:
        _log_audit('lz_osint_error', {'username': username, 'error': result['error']}, 'lz')
        return jsonify({'response': f"Ошибка OSINT: {result['error']}\n\n{OSINT_DISCLAIMER}", 'osint_data': result, 'dept': 'lz'}), 500

    # LLM analysis
    lz_profile = CONDENSED_PROMPTS.get('lz', '')
    analysis_prompt = f"""{lz_profile}

Проанализируй результаты OSINT-сканирования username "{username}":

Найдено: {result['found']} платформ
Под вопросом: {result['maybe']} платформ
Просканировано: {result['total_scanned']} платформ
Время: {result['scan_time']}

Платформы где найден:
{json.dumps(result['platforms'], indent=2, ensure_ascii=False)}

Под вопросом:
{json.dumps(result['uncertain'], indent=2, ensure_ascii=False)}

Анализируй:
1. Цифровой профиль — кто этот человек судя по платформам?
2. Категоризация активности (tech/social/professional/media)
3. Аномалии — отсутствие на ожидаемых платформах
4. Противоречия между профилями
5. Уровень цифровой гигиены (много следов = низкая, мало = высокая)
6. [ФАКТ] для подтверждённых находок, [ИНТЕРПРЕТАЦИЯ] для выводов

{OSINT_DISCLAIMER}"""

    llm_result = _call_llm_with_failover(analysis_prompt, 'lz')
    analysis = llm_result.get('reply', 'Ошибка LLM-анализа') if isinstance(llm_result, dict) else str(llm_result)

    # Token tracking
    t_in = llm_result.get('tokens_in', 0) if isinstance(llm_result, dict) else 0
    t_out = llm_result.get('tokens_out', 0) if isinstance(llm_result, dict) else 0
    prov = llm_result.get('provider', '?') if isinstance(llm_result, dict) else '?'
    now_iso = datetime.utcnow().isoformat()
    _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
           (prov, 'osint-analysis', t_in, t_out, 0, 'lz', now_iso))

    _log_audit('lz_osint', {
        'username': username, 'found': result['found'], 'maybe': result['maybe'],
        'total': result['total_scanned'], 'scan_time': result['scan_time']
    }, 'lz')

    return jsonify({
        'response': analysis,
        'osint_data': result,
        'dept': 'lz',
        'disclaimer': OSINT_DISCLAIMER
    })

# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

# ──────────────────────────── PYTHON TELEGRAM WEBHOOK ────────────────────────────
# Bypasses mlog binary entirely — full control over FORMAT_INSTRUCTION, voice, Mini App

OWNER_ID = os.environ.get("OWNER_TELEGRAM_ID", "")
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("RENDER_URL", "https://fosved-office-v2.onrender.com"))
_voice_enabled = False
_tts_voice = "ru-RU-SvetlanaNeural"

@app.post("/webhook/telegram")
def telegram_webhook():
    # Verify Telegram webhook secret
    if not _verify_webhook_secret():
        log.warning("Webhook secret verification failed")
        return "forbidden", 403

    global _voice_enabled, _tts_voice
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message", {})
    if not msg:
        return "ok", 200
    
    chat_id = str(msg.get("chat", {}).get("id", ""))
    user_id = str(msg.get("from", {}).get("id", ""))
    user_name = msg.get("from", {}).get("first_name", "")
    text = msg.get("text", "").strip()
    voice = msg.get("voice")
    
    # Owner check
    if OWNER_ID and user_id != OWNER_ID:
        return "ok", 200
    
    # Voice → STT
    if voice and not text:
        file_id = voice.get("file_id", "")
        if file_id:
            try:
                stt_resp = http_requests.post(f"http://127.0.0.1:4000/stt",
                    json={"file_id": file_id, "chat_id": chat_id}, timeout=60)
                stt_data = stt_resp.json()
                text = stt_data.get("text", "")
                if text:
                    _tg_send_message(chat_id, f"🎤 Распознано: {text}")
            except Exception as e:
                log.error(f"STT failed: {e}")
                _tg_send_message(chat_id, "Ошибка распознавания голоса")
                return "ok", 200
    
    if not text:
        return "ok", 200
    
    log.info(f"[WEBHOOK] from={user_name} text={text[:80]}")
    
    # ── Simple commands ──
    if text.lower() in ("/start", "/help"):
        _tg_send_message(chat_id, "Fosved Office v2\n\nОтделы: /yana /osp /lz /expert /marketing /finance /legal /dev /design /qa /visual /engineering /forge /admin\n\nУтилиты: /brief /digest /audit /learning /review /cost /good /fix\nГолос: /voice on|off|male|female\nОценка: /rate <1-10>\nМодель: /model auto|cheap|best|fusion\n\nПросто напиши сообщение — маршрутизация автоматическая.")
        return "ok", 200
    
    if text.lower() == "/status":
        _tg_send_message(chat_id, f"Fosved Office v2 — online\nVoice: {'on' if _voice_enabled else 'off'}\nWebhook: Python (direct)")
        return "ok", 200
    
    if text.lower().startswith("/voice"):
        parts = text.split()
        if len(parts) > 1:
            cmd = parts[1].lower()
            if cmd == "on": _voice_enabled = True; _tg_send_message(chat_id, "Голос включён 🎙")
            elif cmd == "off": _voice_enabled = False; _tg_send_message(chat_id, "Голос выключен")
            elif cmd == "male": _tts_voice = "ru-RU-SvetlanaNeural"; _tg_send_message(chat_id, "Голос: мужской")
            elif cmd == "female": _tts_voice = "ru-RU-SvetlanaNeural"; _tg_send_message(chat_id, "Голос: женский")
        else:
            _tg_send_message(chat_id, f"Voice: {'on' if _voice_enabled else 'off'}\n/voice on|off|male|female")
        return "ok", 200
    
    if text.lower().startswith("/rate "):
        try:
            score = int(text.split()[1])
            _query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES ('yana','owner_feedback',?,?,?)",
                   (str(score), 'manual', datetime.utcnow().isoformat()))
            _tg_send_message(chat_id, f"Оценка записана: {score}/10")
        except: _tg_send_message(chat_id, "Формат: /rate <1-10>")
        return "ok", 200

    # ── Manual trigger commands (MEGA-3) ──
    if text.lower() == "/brief":
        action_stop = _send_chat_action_loop(chat_id, "typing", interval=5)
        try:
            r = http_requests.post("http://127.0.0.1:4000/ask",
                json={"dept": "yana", "messages": [
                    {"role": "system", "content": get_dept_prompt("yana")},
                    {"role": "user", "content": "Сделай утренний brief: что произошло за ночь, что на сегодня запланировано, что критично."}
                ]}, timeout=120)
            action_stop.set()
            reply = r.json().get("reply", "Не удалось получить brief")
            _tg_send_message(chat_id, reply)
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /brief: {e}")
        return "ok", 200

    if text.lower() == "/digest":
        action_stop = _send_chat_action_loop(chat_id, "typing", interval=5)
        try:
            r = http_requests.post("http://127.0.0.1:4000/ask",
                json={"dept": "yana", "messages": [
                    {"role": "system", "content": get_dept_prompt("yana")},
                    {"role": "user", "content": "Сделай вечерний свод: что сделано за день, что перенесено, на чём акцент завтра."}
                ]}, timeout=120)
            action_stop.set()
            reply = r.json().get("reply", "Не удалось получить digest")
            _tg_send_message(chat_id, reply)
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /digest: {e}")
        return "ok", 200

    if text.lower() == "/audit":
        try:
            rows = _query("SELECT dept, COUNT(*) as c FROM dialog_history WHERE created_at >= datetime('now', '-7 days') AND role='user' GROUP BY dept ORDER BY c DESC", fetch=True)
            dept_activity = "\n".join([f"  {r['dept']}: {r['c']} запросов" for r in rows]) if rows else "Нет данных"
            costs = _query("SELECT dept, SUM(cost_usd) as total FROM token_usage WHERE created_at >= datetime('now', '-7 days') GROUP BY dept ORDER BY total DESC", fetch=True)
            cost_lines = "\n".join([f"  {r['dept']}: ${float(r['total'] or 0):.4f}" for r in costs]) if costs else "Нет данных"
            _tg_send_message(chat_id, f"📋 Аудит за 7 дней\n\nАктивность по отделам:\n{dept_activity}\n\nРасходы по отделам:\n{cost_lines}")
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /audit: {e}")
        return "ok", 200

    if text.lower() == "/learning":
        try:
            corrections = _query("SELECT COUNT(*) as c FROM adapt_corrections WHERE created_at >= datetime('now', '-7 days')", fetch=True)
            positives = _query("SELECT COUNT(*) as c FROM adapt_corrections WHERE created_at >= datetime('now', '-7 days') AND corr_type='positive'", fetch=True)
            errors = _query("SELECT COUNT(*) as c FROM error_patterns WHERE created_at >= datetime('now', '-7 days')", fetch=True)
            c_count = corrections[0]['c'] if corrections else 0
            p_count = positives[0]['c'] if positives else 0
            e_count = errors[0]['c'] if errors else 0
            _tg_send_message(chat_id, f"📊 Обучение за 7 дней\n\nКорректировок: {c_count}\nПозитивных примеров: {p_count}\nОшибок зафиксировано: {e_count}")
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /learning: {e}")
        return "ok", 200

    if text.lower() == "/review":
        try:
            now = datetime.utcnow()
            week_ago = (now - timedelta(days=7)).isoformat()
            tasks = _query("SELECT COUNT(*) as c FROM dialog_history WHERE created_at >= ? AND role='user'", (week_ago,), fetch=True)
            metrics = _query("SELECT metric_name, metric_value, created_at FROM dept_metrics WHERE created_at >= ? ORDER BY created_at DESC LIMIT 10", (week_ago,), fetch=True)
            msg = f"📊 Обзор за 7 дней\n\nВсего запросов: {tasks[0]['c'] if tasks else 0}\n\nПоследние метрики:\n"
            for m in (metrics or []):
                msg += f"  [{m['dept'] or '?'}] {m['metric_name']}: {m['metric_value']}\n"
            _tg_send_message(chat_id, msg)
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /review: {e}")
        return "ok", 200

    if text.lower() == "/good":
        try:
            rows = _query("SELECT dept, content FROM dialog_history WHERE chat_id=? AND role='assistant' ORDER BY id DESC LIMIT 1", (chat_id,), fetch=True)
            u_rows = _query("SELECT content FROM dialog_history WHERE chat_id=? AND role='user' ORDER BY id DESC LIMIT 1", (chat_id,), fetch=True)
            if rows and u_rows:
                _query("INSERT INTO adapt_corrections (dept, original_query, correction, created_at, corr_type) VALUES (?,?,?,?,?)",
                       (rows[0]['dept'], u_rows[0]['content'][:500], rows[0]['content'][:2000], datetime.utcnow().isoformat(), "positive"))
                _tg_send_message(chat_id, "✅ Последний ответ отмечен как хороший пример.")
            else:
                _tg_send_message(chat_id, "Нет предыдущего ответа для оценки.")
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /good: {e}")
        return "ok", 200

    if text.lower() == "/cost":
        try:
            rows = _query("SELECT provider, model, SUM(cost_usd) as total, SUM(input_tokens + output_tokens) as tokens FROM token_usage WHERE created_at >= datetime('now', '-7 days') GROUP BY provider, model ORDER BY total DESC", fetch=True)
            msg = "💰 Расходы за 7 дней\n\n"
            total_cost = 0
            for r in (rows or []):
                cost = float(r['total'] or 0)
                total_cost += cost
                msg += f"  {r['provider']}/{r['model']}: ${cost:.4f} ({r['tokens']} tokens)\n"
            msg += f"\nИтого: ${total_cost:.4f}"
            _tg_send_message(chat_id, msg)
        except Exception as e:
            _tg_send_message(chat_id, f"Ошибка /cost: {e}")
        return "ok", 200

    # ── Department detection ──
    dept = detect_dept(text)
    
    # Extract query (remove command prefix)
    query = text
    for prefix in [f"/{dept}", "/analyze", "/scan", "/deep", "/forge", "/calc", "/simulate",
                   "/quickanalyze", "/wargame", "/market-research", "/segment", "/competitors", "/campaign"]:
        if text.lower().startswith(prefix):
            query = text[len(prefix):].strip() or text
            break
    
    log.info(f"[WEBHOOK] dept={dept} query={query[:80]}")
    
    # ── Build prompt ──
    system_prompt = get_dept_prompt(dept)
    # Inject current time for ALL departments (was yana-only — root cause of OSP date bug)
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Minsk")
        now_local = datetime.now(tz)
        months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня",
                      "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        weekdays_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        human_time = f"Сейчас: {now_local.day} {months_ru[now_local.month-1]} {now_local.year}, {weekdays_ru[now_local.weekday()]}, {now_local.strftime('%H:%M')} (Europe/Minsk, UTC+3)"
        system_prompt += f"\n\n=== Current Time & Date ===\n{human_time}"
        if dept == "osp":
            system_prompt += f"\n\nКРИТИЧНО: используй ТОЛЬКО дату выше как текущую. Дату в шапке отчёта («Дата препарирования», «Сейчас», ID) копируй ПОСИМВОЛЬНО из значения выше. Игнорируй любые другие даты, включая упомянутые в архиве/памяти/примерах."
    except Exception:
        pass
    
    # Record user message
    _query("INSERT INTO dialog_history (chat_id,role,dept,content,created_at) VALUES (?,?,?,?,?)",
           (chat_id, "user", dept, text[:2000], datetime.utcnow().isoformat()))

    # ── Typing indicator while LLM processes ──
    action_stop = _send_chat_action_loop(chat_id, "typing", interval=5)

    # ── Call LLM ──
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]
    
    log.info(f"[WEBHOOK] LLM call dept={dept} sys_len={len(system_prompt)} has_format={'ФОРМАТ ОТВЕТА' in system_prompt}")
    
    result = call_llm(dept, messages)
    action_stop.set()  # stop typing indicator
    reply = result.get("reply", "Ошибка: пустой ответ")
    provider = result.get("provider", "?")
    
    log.info(f"[WEBHOOK] reply_len={len(reply)} provider={provider}")
    
    # Record assistant message
    _query("INSERT INTO dialog_history (chat_id,role,dept,content,created_at) VALUES (?,?,?,?,?)",
           (chat_id, "assistant", dept, reply[:2000], datetime.utcnow().isoformat()))
    
    # ── Send response ──
    if dept in ("yana", "admin"):
        # Formatted text with MarkdownV2 (bold, italic, underline via __text__)
        _tg_send_formatted(chat_id, reply, dept=dept)
    elif len(reply) > 800:
        # Mini App report for long responses
        doc_id = f"doc-{int(datetime.utcnow().timestamp())}"
        try:
            css = (BASE_DIR / "report_css.txt").read_text() if (BASE_DIR / "report_css.txt").exists() else ""
            c = DEPT_COLORS.get(dept, DEPT_COLORS["admin"])
            name = DEPT_NAMES.get(dept, dept)
            
            # Format badges in reply
            body_html = reply.replace("\n", "<br>")
            body_html = body_html.replace("[ФАКТ]", '<span class="badge badge-fact">✓</span>')
            body_html = body_html.replace("[ИНТЕРПРЕТАЦИЯ]", '<span class="badge badge-interp">◈</span>')
            body_html = body_html.replace("[СПЕКУЛЯЦИЯ]", '<span class="badge badge-spec">⚡</span>')
            body_html = body_html.replace("[FACT]", '<span class="badge badge-fact">✓</span>')
            body_html = body_html.replace("[INTERPRETATION]", '<span class="badge badge-interp">◈</span>')
            body_html = body_html.replace("[SPECULATION]", '<span class="badge badge-spec">⚡</span>')
            
            html = f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>{css}</style></head><body>
<div class="report-container">
<div class="report-header" style="background:linear-gradient(135deg,{c['start']},{c['end']})">
<h1>{name}</h1><div class="subtitle">{query[:100]}</div></div>
<div class="report-meta"><span>ID: {doc_id}</span><span>{datetime.utcnow().strftime('%Y-%m-%d %H:%M')}</span></div>
<div class="report-body">{body_html}</div>
{_build_action_bar(dept, doc_id)}
</div></body></html>'''
            
            _query("INSERT INTO miniapp_responses (id,dept,title,query,raw_text,html,confidence,created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (doc_id, dept, query[:200], query[:200], reply, html, "2.0", datetime.utcnow().isoformat()))
            
            miniapp_url = f"{RENDER_URL}/miniapp/{doc_id}"
            short = reply[:200] + "..."
            
            # Send with Mini App button
            payload = {
                "chat_id": chat_id,
                "text": short,
                "reply_markup": {"inline_keyboard": [[{
                    "text": f"📂 Открыть отчёт: {name}",
                    "web_app": {"url": miniapp_url}
                }]]}
            }
            http_requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                             json=payload, timeout=30)
        except Exception as e:
            log.error(f"Mini App report failed: {e}")
            _tg_send_message(chat_id, reply)
    else:
        # Short response — plain text
        _tg_send_message(chat_id, reply)
    
    # ── Voice response (TTS) — clean text for natural speech ──
    if _voice_enabled and len(reply) > 5:
        tts_text = _clean_text_for_tts(reply)
        if dept not in ("yana", "admin") and len(tts_text) > 1000:
            tts_text = tts_text[:500] + ". Продолжение в текстовом отчёте."
        if len(tts_text) < 5:
            tts_text = reply  # fallback to raw if cleaning was too aggressive
        try:
            voice = "ru-RU-DmitryNeural" if dept == "admin" else _tts_voice
            http_requests.post("http://127.0.0.1:4000/tts",
                json={"text": tts_text, "voice": voice, "chat_id": chat_id}, timeout=60)
        except Exception as e:
            log.error(f"TTS failed: {e}")
    
    return "ok", 200



# ── Cron endpoint ──
@app.route("/cron/collect-news", methods=["GET"])
def cron_collect_news():
    secret = request.args.get("secret", "")
    if secret != os.environ.get("CRON_SECRET", ""):
        return "Forbidden", 403
    rss_count = collect_rss()
    gdelt_count = collect_gdelt_themes()
    _log_audit("news_collection", {"rss": rss_count, "gdelt": gdelt_count}, "collector")
    return jsonify({"rss": rss_count, "gdelt": gdelt_count, "total": rss_count + gdelt_count})


# ── Fresh news for mlog BuildContext ──
@app.route("/news/fresh", methods=["POST"])
def news_fresh():
    d = request.get_json(force=True)
    query = d.get("query", "")
    dept = d.get("dept", "")
    limit = int(d.get("limit", 5))
    news = get_fresh_news(query, dept=dept, limit=limit)
    return jsonify({"news": news})


# ── /lz news endpoint ──
@app.route("/lz/news", methods=["POST"])
def lz_news():
    d = request.get_json(force=True)
    query = d.get("query", "")
    category = d.get("category", None)
    limit = int(d.get("limit", 15))
    if query:
        news = get_fresh_news(query, dept="lz", limit=limit)
    elif category:
        rows = _query("""SELECT source, title, summary, url, published FROM news_cache
                         WHERE category = ? ORDER BY published DESC LIMIT ?""", (category, limit), fetch=True)
        news = "\n".join(f"[{r[0]}] {r[1]}\n  {r[2] or ''}" for r in rows) if rows else "Нет событий"
    else:
        rows = _query("""SELECT source, title, summary, url, published FROM news_cache
                         ORDER BY published DESC LIMIT ?""", (limit,), fetch=True)
        news = "\n".join(f"[{r[0]}] {r[1]}\n  {r[2] or ''}" for r in rows) if rows else "Нет событий"

    lz_prompt = get_dept_prompt("lz")
    analysis_prompt = lz_prompt + "\n\nПроанализируй свежие события. Выдели тренды, аномалии, сигналы. Маркируй [ФАКТ], [ИНТЕРПРЕТАЦИЯ], [СПЕКУЛЯЦИЯ].\n\n" + news
    try:
        result = call_llm("lz", [{"role": "user", "content": analysis_prompt}])
        analysis = result.get("reply", "Ошибка анализа")
    except Exception as e:
        analysis = f"Ошибка: {e}"
    return jsonify({"response": analysis, "news_count": news.count("\n")})


# ── News stats ──
@app.route("/news/stats", methods=["GET"])
@require_telegram
def news_stats():
    total = _query("SELECT COUNT(*) FROM news_cache", fetch=True)[0][0]
    last_24h = _query("SELECT COUNT(*) FROM news_cache WHERE collected > datetime('now', '-24 hours')", fetch=True)[0][0]
    by_source = _query("SELECT source, COUNT(*) as c FROM news_cache GROUP BY source ORDER BY c DESC LIMIT 10", fetch=True)
    by_category = _query("SELECT category, COUNT(*) as c FROM news_cache GROUP BY category ORDER BY c DESC", fetch=True)
    return jsonify({"total": total, "last_24h": last_24h,
                    "by_source": {r[0]: r[1] for r in by_source},
                    "by_category": {r[0]: r[1] for r in by_category}})


# ══════════════════════════════════════════════════════════════════════
#  NEWS MONITORING: RSS + GDELT + Telegram channels
# ══════════════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "ria": {"url": "https://ria.ru/export/rss2/archive/index.xml", "category": "news_ru", "language": "ru", "name": "РИА Новости"},
    "tass": {"url": "https://tass.ru/rss/v2.xml", "category": "news_ru", "language": "ru", "name": "ТАСС"},
    "rbk": {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "category": "news_ru", "language": "ru", "name": "РБК"},
    "interfax": {"url": "https://www.interfax.ru/rss.asp", "category": "news_ru", "language": "ru", "name": "Интерфакс"},
    "kommersant": {"url": "https://www.kommersant.ru/RSS/news.xml", "category": "news_ru", "language": "ru", "name": "Коммерсантъ"},
    "reuters": {"url": "https://feeds.reuters.com/reuters/topNews", "category": "news_en", "language": "en", "name": "Reuters"},
    "bbc": {"url": "http://feeds.bbci.co.uk/news/world/rss.xml", "category": "news_en", "language": "en", "name": "BBC World"},
    "techcrunch": {"url": "https://techcrunch.com/feed/", "category": "tech", "language": "en", "name": "TechCrunch"},
    "theverge": {"url": "https://www.theverge.com/rss/index.xml", "category": "tech", "language": "en", "name": "The Verge"},
    "hackernews": {"url": "https://hnrss.org/frontpage", "category": "tech", "language": "en", "name": "Hacker News"},
    "arxiv_ai": {"url": "https://rss.arxiv.org/rss/cs.AI", "category": "science", "language": "en", "name": "arXiv AI"},
    "arxiv_cl": {"url": "https://rss.arxiv.org/rss/cs.CL", "category": "science", "language": "en", "name": "arXiv NLP"},
    "investing_ru": {"url": "https://ru.investing.com/rss/news.rss", "category": "finance", "language": "ru", "name": "Investing.com RU"},
    "foreignaffairs": {"url": "https://www.foreignaffairs.com/rss.xml", "category": "geopolitics", "language": "en", "name": "Foreign Affairs"},
}

GDELT_BASE = "https://api.gdeltproject.org/api/v2"

DEPT_QUERIES = {
    "osp": "geopolitics OR sanctions OR regulation OR war OR election",
    "lz": "artificial intelligence OR quantum computing OR disruption OR breakthrough",
    "finance": "economy OR inflation OR GDP OR stock market OR cryptocurrency",
    "legal": "legislation OR court OR GDPR OR compliance OR lawsuit",
    "marketing": "consumer trends OR advertising OR social media OR brand",
    "engineering": "infrastructure OR energy OR construction OR nuclear OR solar",
}

DEPT_CATEGORIES = {
    "osp": ("news_ru", "geopolitics", "news_en"),
    "lz": ("tech", "science"),
    "finance": ("finance",),
    "legal": ("geopolitics", "news_ru"),
    "marketing": ("tech", "news_en"),
}


def collect_rss():
    """Collect from all RSS feeds. Dedup by hash(title+url). TTL 7 days."""
    import feedparser as _fp
    collected, errors = 0, 0
    for feed_id, fc in RSS_FEEDS.items():
        try:
            feed = _fp.parse(fc["url"])
            for entry in feed.entries[:20]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", ""))).strip()
                url = entry.get("link", "").strip()
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if not title:
                    continue
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                content_hash = hashlib.md5((title + url).encode()).hexdigest()
                pub_date = None
                if published:
                    try:
                        pub_date = datetime(*published[:6]).isoformat()
                    except Exception:
                        pass
                try:
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (fc["name"], title, summary, url, fc["category"], fc["language"], pub_date, content_hash))
                    collected += 1
                except Exception:
                    pass
        except Exception as e:
            errors += 1
            _log_audit("rss_error", {"feed": feed_id, "error": str(e)[:100]}, "collector")
    _query("DELETE FROM news_cache WHERE collected < datetime('now', '-7 days')")
    _log_audit("rss_collected", {"collected": collected, "errors": errors}, "collector")
    return collected


def collect_gdelt(query=None, language="russian", max_items=25):
    """GDELT DOC API — free, no key."""
    params = {
        "query": query or "Russia OR technology OR AI",
        "mode": "artlist",
        "maxrecords": str(max_items),
        "format": "json",
        "sort": "DateDesc",
        "sourcelang": language,
    }
    try:
        resp = http_requests.get(f"{GDELT_BASE}/doc/doc", params=params, timeout=15)
        if resp.status_code != 200:
            return 0
        data = resp.json()
        articles = data.get("articles", [])
        collected = 0
        for a in articles:
            title = a.get("title", "").strip()
            url = a.get("url", "").strip()
            source = a.get("domain", a.get("sourcecountry", "GDELT"))
            seendate = a.get("seendate", "")
            tone = a.get("tone", 0)
            if not title:
                continue
            content_hash = hashlib.md5((title + url).encode()).hexdigest()
            cat = "geopolitics"
            tl = title.lower()
            if any(w in tl for w in ["technology", "ai", "artificial", "технолог", "искусствен"]):
                cat = "tech"
            elif any(w in tl for w in ["economy", "экономик", "market", "рынок", "billion", "млрд"]):
                cat = "finance"
            elif any(w in tl for w in ["science", "наук", "research", "исследован"]):
                cat = "science"
            try:
                _query("""INSERT OR IGNORE INTO news_cache
                    (source,title,summary,url,category,language,published,relevance_score,hash)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (f"GDELT/{source}", title, f"Tone: {float(tone):.1f}", url, cat,
                     language[:2], seendate, abs(float(tone)), content_hash))
                collected += 1
            except Exception:
                pass
        _log_audit("gdelt_collected", {"collected": collected}, "collector")
        return collected
    except Exception as e:
        _log_audit("gdelt_error", {"error": str(e)[:200]}, "collector")
        return 0


def collect_gdelt_themes():
    total = 0
    for dept, query in DEPT_QUERIES.items():
        total += collect_gdelt(query=query, language="russian", max_items=10)
        total += collect_gdelt(query=query, language="english", max_items=10)
    return total


def _extract_keywords(text):
    stop = {"и", "в", "на", "с", "по", "для", "от", "что", "как", "не", "это", "the", "a", "an", "in", "on", "for", "of", "and", "to", "is", "it"}
    words = re.findall(r"[а-яёa-z]{3,}", text.lower())
    return [w for w in words if w not in stop][:10]


def get_fresh_news(query, dept=None, limit=5, max_chars=1500):
    """Get recent news relevant to query. Used by BuildContext in mlog."""
    keywords = _extract_keywords(query)
    conditions, params = [], []
    for kw in keywords[:5]:
        conditions.append("(title LIKE ? OR summary LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    where = " OR ".join(conditions) if conditions else "1=1"

    cats = DEPT_CATEGORIES.get(dept, ("news_ru", "tech", "geopolitics"))
    cat_filter = " OR ".join(["category = ?" for _ in cats])
    params.extend(cats)

    sql = f"""SELECT source, title, summary, url, published, relevance_score
             FROM news_cache WHERE ({where}) AND ({cat_filter})
             AND collected > datetime('now', '-48 hours')
             ORDER BY published DESC LIMIT ?"""
    params.append(limit)
    rows = _query(sql, params, fetch=True)

    if not rows:
        sql2 = f"""SELECT source, title, summary, url, published, relevance_score
                  FROM news_cache WHERE ({cat_filter})
                  AND collected > datetime('now', '-24 hours')
                  ORDER BY published DESC LIMIT ?"""
        rows = _query(sql2, list(cats) + [limit], fetch=True)

    if not rows:
        return ""

    news_text = "=== СВЕЖИЕ СОБЫТИЯ (последние 48ч) ===\n\n"
    current_len = 0
    for r in rows:
        entry = f"[{r[0]}] {r[1]}\n"
        if r[2] and r[2] != r[1]:
            entry += f"  {r[2][:150]}\n"
        if r[4]:
            entry += f"  Дата: {r[4]}\n"
        entry += "\n"
        if current_len + len(entry) > max_chars:
            break
        news_text += entry
        current_len += len(entry)

    news_text += "=== КОНЕЦ СОБЫТИЙ ===\n"
    return news_text


def get_night_news_digest():
    """Top-5 events over last 12 hours for morning brief."""
    rows = _query("""SELECT source, title, category FROM news_cache
                     WHERE collected > datetime('now', '-12 hours')
                     ORDER BY relevance_score DESC, published DESC LIMIT 5""", fetch=True)
    if not rows:
        return ""
    emoji = {"tech": "🔬", "finance": "💰", "geopolitics": "🌍", "science": "🧪", "news_ru": "📌", "news_en": "📌"}
    digest = "\n📰 Топ события за ночь:\n"
    for r in rows:
        digest += f"  {emoji.get(r[2], '📄')} [{r[0]}] {r[1][:80]}\n"
    return digest


# ══════════════════════════════════════════════════════════════════════
#  WATCH SWEEP — daily sweep of WatchlistItem table
#  Checks all active items, updates lastCheckAt/nextCheckAt, detects deltas
#  Called by Render cron at 06:00 UTC = 09:00 MSK
# ══════════════════════════════════════════════════════════════════════

@app.post("/scheduler/watch-sweep")
def scheduler_watch_sweep():
    """Sweep all active WatchlistItems, check for deltas, update timestamps.
    For each item:
      1. Query news/LLM for recent changes on the topic
      2. Compare with lastDelta — if new information, increment deltaCount
      3. Update lastCheckAt, compute nextCheckAt from frequency
      4. If delta detected, send brief notification to owner
    """
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        return jsonify({"status": "error", "message": "OWNER_TELEGRAM_ID not set"}), 400

    try:
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Get all active watchlist items
        items = _query("""
            SELECT w.id, w.analysis_id, w.topic, w.frequency, w.last_delta, w.delta_count,
                   a.topic AS analysis_topic
            FROM watchlist_item w
            LEFT JOIN analysis a ON a.id = w.analysis_id
            WHERE w.active = 1
            ORDER BY w.next_check_at ASC
        """, fetch=True)

        if not items:
            return jsonify({"status": "ok", "swept": 0, "message": "no active watchlist items"})

        swept = 0
        deltas = 0
        notifications = []

        for item in items:
            wid, analysis_id, topic, frequency, last_delta, delta_count, analysis_topic = item

            # Query LLM for recent developments on this topic
            sweep_prompt = f"""Ты мониторинг-аналитик ОСП. Проверь тему на предмет новых событий за последние 24 часа.

Тема: {topic}
Контекст анализа: {analysis_topic or 'N/A'}
Предыдущий дельта: {last_delta or 'нет'}

Если есть новые существенные изменения (не шум, не повтор), опиши кратко (1-2 предложения).
Если изменений нет — ответь ровно одним словом: NO_DELTA"""

            llm_result = _call_llm_with_failover(sweep_prompt, 'osp')
            reply = llm_result.get('reply', '') if isinstance(llm_result, dict) else str(llm_result)
            new_delta = None if 'NO_DELTA' in reply.upper()[:50] else reply.strip()

            # Compute nextCheckAt based on frequency
            freq_days = {'DAILY': 1, 'WEEKLY': 7, 'BIWEEKLY': 14}.get(frequency, 1)
            next_check = (datetime.utcnow() + timedelta(days=freq_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

            if new_delta:
                # Delta detected
                new_count = (delta_count or 0) + 1
                _query("UPDATE watchlist_item SET last_check_at=?, next_check_at=?, last_delta=?, delta_count=? WHERE id=?",
                       (now_iso, next_check, new_delta[:500], new_count, wid))
                deltas += 1
                notifications.append(f"▸ {topic}: {new_delta[:150]}")
            else:
                # No delta — just update timestamps
                _query("UPDATE watchlist_item SET last_check_at=?, next_check_at=? WHERE id=?",
                       (now_iso, next_check, wid))

            swept += 1

        # Send consolidated notification if any deltas found
        if notifications:
            msg = "🔍 Watch Sweep — обнаружены дельты:\n\n" + "\n".join(notifications[:10])
            if len(notifications) > 10:
                msg += f"\n\n...и ещё {len(notifications) - 10}"
            _send_telegram_message(owner_id, msg)

        _log_audit('watch_sweep', {'swept': swept, 'deltas': deltas}, 'osp')
        log.info(f"Watch sweep: {swept} items, {deltas} deltas")
        return jsonify({"status": "ok", "swept": swept, "deltas": deltas})

    except Exception as e:
        log.error(f"watch_sweep error: {e}")
        _log_audit("watch_sweep_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  INDICATOR PRE-REMINDERS — 7-day pre-verification reminders
#  Finds indicators with verifyDate within N days, sends reminder to owner
#  Called by Render cron at 03:00 UTC = 06:00 MSK (before morning brief)
# ══════════════════════════════════════════════════════════════════════

@app.post("/scheduler/indicator-pre-reminders")
def scheduler_indicator_pre_reminders():
    """Find indicators with verifyDate within `days_ahead` days.
    Send a consolidated pre-reminder to owner with:
      - Indicator description + verifyDate
      - How many days until verification
      - What the indicator confirms
    Marks pre_verify_reminder_sent = 1 so we don't re-notify.
    """
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        return jsonify({"status": "error", "message": "OWNER_TELEGRAM_ID not set"}), 400

    d = request.get_json(force=True, silent=True) or {}
    days_ahead = int(d.get("days_ahead", 7))

    try:
        cutoff = (datetime.utcnow() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT23:59:59Z")
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Find unverified indicators with verifyDate within N days that haven't been pre-reminded
        indicators = _query("""
            SELECT i.id, i.description, i.verify_date, i.is_binary, i.confirms_what,
                   i.pre_verify_reminder_sent, a.topic AS analysis_topic
            FROM indicator i
            LEFT JOIN analysis a ON a.id = i.analysis_id
            WHERE i.verified_at IS NULL
              AND i.verify_date <= ?
              AND i.verify_date >= ?
              AND i.pre_verify_reminder_sent = 0
            ORDER BY i.verify_date ASC
        """, (cutoff, now_iso), fetch=True)

        if not indicators:
            return jsonify({"status": "ok", "reminders": 0, "message": f"no indicators due within {days_ahead}d"})

        # Build reminder message
        lines = []
        for ind in indicators:
            iid, desc, vdate, is_binary, confirms, pre_sent, analysis_topic = ind
            # Compute days until verification
            try:
                verify_dt = datetime.strptime(vdate[:10], "%Y-%m-%d")
                days_left = (verify_dt - datetime.utcnow()).days
                days_str = f"{days_left}д" if days_left > 0 else "СЕГОДНЯ" if days_left == 0 else "ПРОСРОЧЕН"
            except Exception:
                days_str = "?"

            line = f"▸ {desc[:100]}\n  Верификация: {vdate[:10]} ({days_str})\n  Подтверждает: {confirms[:80]}"
            if analysis_topic:
                line += f"\n  Анализ: {analysis_topic[:60]}"
            lines.append(line)

            # Mark as pre-reminded
            _query("UPDATE indicator SET pre_verify_reminder_sent = 1 WHERE id = ?", (iid,))

        # Send consolidated message
        msg = f"⏰ I&W Пред-напоминания ({days_ahead}д до верификации):\n\n"
        msg += "\n\n".join(lines[:8])
        if len(lines) > 8:
            msg += f"\n\n...и ещё {len(lines) - 8} индикаторов"

        msg += "\n\n/osp verify <id> — верифицировать индикатор"

        _send_telegram_message(owner_id, msg)

        _log_audit('indicator_pre_reminders', {'count': len(indicators), 'days_ahead': days_ahead}, 'osp')
        log.info(f"Indicator pre-reminders: {len(indicators)} indicators within {days_ahead}d")
        return jsonify({"status": "ok", "reminders": len(indicators), "days_ahead": days_ahead})

    except Exception as e:
        log.error(f"indicator_pre_reminders error: {e}")
        _log_audit("indicator_pre_reminders_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  EXPERT CHART ENDPOINT
#  Called by mlog via http_post to generate PNG charts (residual value,
#  operation cost, TCO comparison) using scripts/expert_charts.py
# ══════════════════════════════════════════════════════════════════════

@app.post("/expert/chart")
def expert_chart():
    """Generate PNG chart for Expert automotive analysis.
    Expects JSON: {chart_type: "residual_value"|"operation_cost"|"comparison", data: {...}}
    Calls scripts/expert_charts.py to render the chart.
    """
    import subprocess
    d = request.get_json(force=True)
    chart_type = d.get("chart_type", "residual_value")
    chart_data = d.get("data", {})

    if not chart_data:
        return jsonify({"error": "data required"}), 400

    script_path = os.path.join(os.path.dirname(__file__), "scripts", "expert_charts.py")
    if not os.path.exists(script_path):
        # Fallback: try /home/z/my-project/scripts/expert_charts.py
        script_path = "/home/z/my-project/scripts/expert_charts.py"

    try:
        # Write data to temp file (avoid shell escaping issues with JSON)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
            json.dump(chart_data, tf, ensure_ascii=False)
            tmp_path = tf.name

        result = subprocess.run(
            [sys.executable, script_path, chart_type, tmp_path],
            capture_output=True, text=True, timeout=30
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            app.logger.error(f"Expert chart error: {result.stderr}")
            return jsonify({"error": "chart generation failed", "detail": result.stderr[:500]}), 500

        chart_result = json.loads(result.stdout)
        return jsonify(chart_result)

    except subprocess.TimeoutExpired:
        return jsonify({"error": "chart generation timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    log.info(f"Starting LLM Proxy on port {PORT}, DB={DB_FILE}")
    log.info(f"Endpoints: health, detect-dept, ask, rate_cmd, context_cmd, voice-set, "
             f"archive/digest, archive/publish, archive/daily-digest, miniapp, enrich, tg-send, dept-dashboard, office-dashboard, "
             f"expert/chart, tts, stt, scheduler/*, learning/*, audit/recent, search, generate-image, lz/deep-research, lz/osint, memory/*, "
             f"scheduler/watch-sweep, scheduler/indicator-pre-reminders")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


