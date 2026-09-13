#!/usr/bin/env python3
"""proxy/shadow.py — FO-025: shadow-оценка моделей (канареечный роутинг).

Промышленный паттерн безопасного rollout (Portkey shadow-gateway, canary):
кандидата зеркалят на X% живого трафика, ответ кандидата НЕ уходит
пользователю; сравнение — на живых данных, метрика — verifier-попарное
сравнение (Chatbot Arena-семантика: слепое попарное сравнение).

Настройка (admin-плоскость, без правки кода):
  system_settings shadow_<dept> = {"model": "<alias>", "rate": 0.1}
  (mlog: kv_set("shadow_finance", "{\\"model\\":\\"glm-4.6\\",\\"rate\\":0.1}")
   или HTTP-роут /shadow в app.mlog; /shadow off <dept> — выключить)

Гард-рейлы (наряд):
  - shadow-вызов полностью в try/except: падение кандидата не влияет на
    основной ответ (прозрачно);
  - таймаут кандидата меньше основного (SHADOW_TIMEOUT_SECS, 25 c);
  - shadow НЕ учитывается в бюджете дважды: token_usage-строка кандидата
    помечена request_type='shadow' (FO-024 исключает 'shadow%' из счётчика);
  - shadow-ошибки помечены pair_id + kind='shadow_error' — failure-buckets
    FO-022 смогут фильтровать их без дезинформации.

Метрики: парные записи в trace_log (FO-004, event='shadow', одинаковый
pair_id) + строка cost кандидата отдельной строкой. Недельный отчёт —
/routes_tail /api/shadow/report (win-rate, дельта-качество, дельта-цена,
рекомендация Go/No-Go владельцу).
"""
import json
import os
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from proxy.core import (
    _get_setting, _log_audit, _log_error, _query, _write_llm_trace, log,
)

# Таймаут кандидата меньше основного (гард-рейл наряда)
SHADOW_TIMEOUT_SECS = float(os.environ.get("SHADOW_TIMEOUT_SECS", "25"))

_shadow_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shadow")


def get_config(dept):
    """shadow_<dept> из system_settings → {"model","rate"} | None. Не бросает."""
    raw = _get_setting(f"shadow_{dept}", "")
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
        model = str(cfg.get("model", "")).strip()
        rate = float(cfg.get("rate", 0))
        if not model or rate <= 0:
            return None
        return {"model": model, "rate": min(rate, 1.0)}
    except (ValueError, TypeError):
        return None


def _trace_pair(pair_id, dept, side, model, ok, latency_ms=0, t_in=0, t_out=0,
                cost=0.0, score=None, error=None):
    """Одна из двух парных trace-записей (event='shadow')."""
    _write_llm_trace({
        "event": "shadow",
        "pair_id": pair_id,
        "side": side,  # main | shadow
        "ts": datetime.now(timezone.utc).isoformat(),
        "dept": dept,
        "gen_ai.request.model": model,
        "ok": ok,
        "latency_ms": round(latency_ms),
        "gen_ai.usage.input_tokens": t_in,
        "gen_ai.usage.output_tokens": t_out,
        "cost_usd": round(cost, 6),
        "verifier_score": score,
        "error": error,
    })


def _score_safe(problem, candidate):
    """Verifier не должен ломать shadow-контур."""
    try:
        import llm_verifier
        return round(float(llm_verifier.score(problem, candidate)), 4)
    except Exception as e:
        _log_error(f"shadow verifier failed: {e}", source="shadow", dept="",
                   kind="shadow_error")
        return None


def _run_candidate(model, messages, dept, pair_id):
    """Вызов кандидату в отдельном потоке с укороченным таймаутом."""
    from proxy.providers import _call_single_provider, _provider_for_model, TOKEN_COSTS
    provider = _provider_for_model(model)
    started = time.monotonic()
    future = _shadow_pool.submit(_call_single_provider, provider, model,
                                 messages, dept, 4096, True)
    try:
        result = future.result(timeout=SHADOW_TIMEOUT_SECS)
    except Exception as e:
        latency = time.monotonic() - started
        _log_error(f"shadow candidate failed pair={pair_id} model={model}: {e}",
                   source="shadow", dept=dept, kind="shadow_error")
        _trace_pair(pair_id, dept, "shadow", model, ok=False, latency_ms=latency * 1000,
                    error=str(e)[:300])
        return None
    latency = time.monotonic() - started
    if not (isinstance(result, dict) and result.get("reply")):
        _log_error(f"shadow candidate empty reply pair={pair_id} model={model}",
                   source="shadow", dept=dept, kind="shadow_error")
        _trace_pair(pair_id, dept, "shadow", model, ok=False,
                    latency_ms=latency * 1000, error="empty reply")
        return None

    t_in = int(result.get("tokens_in", 0) or 0)
    t_out = int(result.get("tokens_out", 0) or 0)
    costs = TOKEN_COSTS.get(provider, {"input": 1, "output": 1})
    cost = t_in * costs["input"] / 1_000_000 + t_out * costs["output"] / 1_000_000
    # FO-024-соседство: кандидат — ОТДЕЛЬНАЯ строка с меткой shadow,
    # в бюджет департамента не попадает (budget исключает 'shadow%')
    _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at,request_type) "
           "VALUES (?,?,?,?,?,?,?,?)",
           (provider, model, t_in, t_out, round(cost, 6), dept,
            datetime.now(timezone.utc).isoformat(), "shadow"))
    return {"result": result, "latency_ms": latency * 1000, "cost": cost,
            "t_in": t_in, "t_out": t_out}


def maybe_shadow(dept, messages, main_result, main_latency_ms=None):
    """Точка зеркала: вызвать ПОСЛЕ успешного основного вызова.
    Никогда не бросает и не меняет main_result."""
    try:
        cfg = get_config(dept)
        if cfg is None or not isinstance(main_result, dict):
            return
        if not main_result.get("reply"):
            return
        if random.random() >= cfg["rate"]:
            return

        pair_id = uuid.uuid4().hex[:12]
        problem = next((m.get("content", "") for m in reversed(messages)
                        if m.get("role") == "user"), "")
        started = time.monotonic()

        cand = _run_candidate(cfg["model"], messages, dept, pair_id)

        # trace пары: основная сторона — до таймаута/падения кандидата
        main_latency = main_latency_ms if main_latency_ms is not None \
            else (time.monotonic() - started) * 1000
        main_score = _score_safe(problem, main_result["reply"]) \
            if cand is not None else None

        if cand is None:
            _trace_pair(pair_id, dept, "main", main_result.get("model", "?"),
                        ok=True, latency_ms=main_latency)
            return

        shadow_score = _score_safe(problem, cand["result"]["reply"])
        _trace_pair(pair_id, dept, "main", main_result.get("model", "?"), ok=True,
                    latency_ms=main_latency, score=main_score)
        _trace_pair(pair_id, dept, "shadow", cfg["model"], ok=True,
                    latency_ms=cand["latency_ms"], t_in=cand["t_in"],
                    t_out=cand["t_out"], cost=cand["cost"], score=shadow_score)

        _log_audit("shadow_eval", {"pair_id": pair_id, "dept": dept,
                                   "candidate": cfg["model"],
                                   "main_score": main_score,
                                   "shadow_score": shadow_score}, dept=dept)
    except Exception as e:
        # гард-рейл: shadow не может уронить основной вызов никогда
        _log_error(f"shadow pipeline failed: {e}", source="shadow", dept=dept,
                   kind="shadow_error")
