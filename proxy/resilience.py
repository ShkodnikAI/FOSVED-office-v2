#!/usr/bin/env python3
"""proxy/resilience.py — FO-022 (наряд #88): free-tier intelligence llm_proxy.

Дисциплина www222fff/free-router (HOW_IT_WORKS.md, quota.mjs, redact.mjs):

1. Failure buckets — каждый upstream-отказ категорируется:
   rateLimit | timeout | serverError | empty | notFound | forbidden | aborted | other.
   Категория пишется в трейсы FO-004 (failure_bucket) и агрегируется в /health.
2. Разбор 429 (quota.mjs): limit:0 = модель не offered → кэш «нет free-tier»
   (долгий cooldown); limit>0 = cooldown до ролловера квотного дня в таймзоне
   провайдера (конфиг quota_tz.json, дефолт UTC); retryDelay из Retry-After /
   RetryInfo перекрывает догадки.
3. Фолбэк учитывает категорию: notFound/forbidden → провайдер вычеркивается
   надолго (long-cooldown 6 ч); rateLimit → cooldown квоты; остальное —
   обычный circuit breaker (providers.py).

Модуль не знает о Flask и не импортирует providers (разрыв цикла): провайдеры
спрашивают skip-статус через provider_skipped().
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # noqa: BLE001 — zoneinfo есть в py3.9+; без него — UTC
    ZoneInfo = None

from proxy.core import CFG_DIR, _write_llm_trace, log

# ─────────────────────────── FAILURE BUCKETS ───────────────────────────
BUCKETS = ("rateLimit", "timeout", "serverError", "empty",
           "notFound", "forbidden", "aborted", "other")

_RATE_LIMIT_RE = re.compile(
    r"rate[ _-]?limit|too many requests|resource[_ ]exhausted|quota|429", re.I)
_NOT_FOUND_RE = re.compile(
    r"not[ _-]?found|does not exist|no such model|model[_ ]not[_ ]found|"
    r"unknown model|404", re.I)
_FORBIDDEN_RE = re.compile(
    r"unauthorized|invalid[ _-]?(api[ _-]?key|token)|invalid[_ ]api[_ ]key|"
    r"forbidden|authentication|permission denied|api key not valid|401|403", re.I)
_TIMEOUT_RE = re.compile(r"timed?[ _-]?out|timeout", re.I)
_ABORTED_RE = re.compile(
    r"connection aborted|reset by peer|remote end closed|broken pipe|"
    r"connection refused|max retries exceeded", re.I)
_SERVER_ERR_RE = re.compile(
    r"internal server error|bad gateway|service unavailable|overloaded|"
    r"server error|502|503|504", re.I)


def classify_failure(status_code=None, error_text="", kind=None):
    """Категория upstream-отказа. kind ∈ {'http','timeout','conn','empty',None}."""
    text = f"{error_text or ''}"
    if kind == "empty":
        return "empty"
    if kind == "timeout":
        return "timeout"
    if kind == "conn":
        if _RATE_LIMIT_RE.search(text):
            return "rateLimit"
        if _ABORTED_RE.search(text):
            return "aborted"
        return "aborted"
    if status_code is not None:
        if status_code == 429:
            return "rateLimit"
        if status_code in (401, 403):
            return "forbidden"
        if status_code == 404:
            return "notFound"
        if status_code >= 500:
            return "serverError"
    if _RATE_LIMIT_RE.search(text):
        return "rateLimit"
    if _NOT_FOUND_RE.search(text):
        return "notFound"
    if _FORBIDDEN_RE.search(text):
        return "forbidden"
    if _TIMEOUT_RE.search(text):
        return "timeout"
    if _ABORTED_RE.search(text):
        return "aborted"
    if _SERVER_ERR_RE.search(text):
        return "serverError"
    return "other"


# ─────────────────────────── QUOTA (429) TRACKER ───────────────────────────
# Ттаймзона ролловера квотного дня — в конфиге: CFG_DIR/quota_tz.json
# {"groq": "America/Chicago", ...}; дефолт UTC.
_NO_TIER_COOLDOWN_S = 24 * 3600      # limit:0 → «нет free-tier» на сутки
_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', re.I)
_LIMIT0_RE = re.compile(r"\blimit\s*[:=]?\s*0\b", re.I)


def _load_provider_tz():
    cfg = {}
    try:
        p = os.path.join(str(CFG_DIR), "quota_tz.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                cfg = {str(k): str(v) for k, v in raw.items()}
    except Exception as e:  # noqa: BLE001 — конфиг не должен ронять прокси
        log.warning(f"[resilience] quota_tz.json load failed: {e}")
    return cfg


_PROVIDER_TZ = _load_provider_tz()


def _provider_tz_name(provider):
    return _PROVIDER_TZ.get(provider, "UTC")


def _tz(tzname):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tzname)
        except Exception as e:  # noqa: BLE001 — кривое имя в конфиге
            log.warning(f"[resilience] bad timezone {tzname!r}: {e}, fallback UTC")
    return timezone.utc


def next_rollover(provider, now_ts=None):
    """Эпоха ролловера квотного дня: следующая полночь в таймзоне провайдера."""
    tz = _tz(_provider_tz_name(provider))
    now = datetime.now(tz) if now_ts is None else datetime.fromtimestamp(now_ts, tz)
    rollover = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return rollover.timestamp()


def _parse_retry_after(headers):
    """Retry-After: секунды или HTTP-дата. Возвращает секунды или None."""
    if not headers:
        return None
    try:
        raw = None
        if hasattr(headers, "get"):
            raw = headers.get("Retry-After") or headers.get("retry-after")
        if not raw:
            return None
        raw = str(raw).strip()
        if raw.isdigit():
            return float(raw)
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            return max((dt - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except Exception as e:  # noqa: BLE001 — кривой заголовок не фатален
        log.debug(f"[resilience] Retry-After parse failed: {e}")
    return None


def _extract_error_message(body_text):
    """error.message из типовых форм 429-ответов (openai/groq/google)."""
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return body_text[:300] if body_text else ""
    msg = ""
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        msg = str(err.get("message", ""))
        if not msg:
            details = err.get("details")
            if isinstance(details, list) and details:
                msg = json.dumps(details[0], ensure_ascii=False)[:300]
    if not msg and isinstance(data, dict):
        msg = str(data.get("message", ""))
    return msg or json.dumps(data, ensure_ascii=False)[:300]


def _extract_retry_delay_s(body_text):
    """Google RetryInfo: "retryDelay": "26s" → 26.0."""
    m = _RETRY_DELAY_RE.search(body_text or "")
    return float(m.group(1)) if m else None


class QuotaTracker:
    """Кулдауны (provider, model) после 429 — семантика quota.mjs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cooldown = {}  # (provider, model) -> dict(until, reason, kind)

    def note_rate_limited(self, provider, model, body_text="", headers=None,
                          now=None):
        """429 → кулдаун: Retry-After / RetryInfo > limit:0 «нет free-tier» >
        ролловер квотного дня в таймзоне провайдера."""
        now = time.time() if now is None else now
        retry_after = _parse_retry_after(headers)
        if retry_after is None:
            retry_after = _extract_retry_delay_s(body_text)
        msg = _extract_error_message(body_text)
        limit0 = bool(_LIMIT0_RE.search(msg)) or bool(_LIMIT0_RE.search(body_text or ""))
        if limit0:
            until = now + _NO_TIER_COOLDOWN_S
            kind, reason = "no_tier", "limit:0 — модель не offered (кэш «никогда»)"
        elif retry_after is not None and retry_after > 0:
            until = now + float(retry_after)
            kind, reason = "retry_after", f"Retry-After {retry_after}s"
        else:
            until = next_rollover(provider, now)
            kind = "rollover"
            tzname = _provider_tz_name(provider)
            reason = f"cooldown до ролловера квотного дня ({tzname})"
        with self._lock:
            self._cooldown[(provider, model)] = {
                "until": until, "reason": reason, "kind": kind, "since": now,
            }
        log.info(f"[resilience] quota 429: {provider}/{model} kind={kind} "
                 f"until={datetime.fromtimestamp(until, timezone.utc).isoformat()}")
        return until

    def is_limited(self, provider, model, now=None):
        """Строка-причина, если пара в кулдауне; None — можно звать."""
        now = time.time() if now is None else now
        with self._lock:
            rec = self._cooldown.get((provider, model))
            if not rec:
                return None
            if now >= rec["until"]:
                del self._cooldown[(provider, model)]
                return None
            return f"{rec['kind']}: {rec['reason']}"

    def status(self, now=None):
        """Снимок активных кулдаунов для /health."""
        now = time.time() if now is None else now
        out = {}
        with self._lock:
            for (prov, model), rec in list(self._cooldown.items()):
                if now >= rec["until"]:
                    del self._cooldown[(prov, model)]
                    continue
                out[f"{prov}/{model}"] = {
                    "kind": rec["kind"], "reason": rec["reason"],
                    "until": datetime.fromtimestamp(rec["until"], timezone.utc).isoformat(),
                    "remaining_s": round(rec["until"] - now),
                }
        return out


_quota = QuotaTracker()


# ─────────────────────────── LONG COOLDOWN (notFound/forbidden) ───────────────────────────
_LONG_COOLDOWN_S = 6 * 3600  # «вычеркивается надолго»
_long_lock = threading.Lock()
_long_cooldown = {}  # provider -> {"until": ts, "reason": str}


def note_long_cooldown(provider, reason, now=None):
    """notFound/forbidden → провайдер вычеркивается надолго."""
    now = time.time() if now is None else now
    with _long_lock:
        _long_cooldown[provider] = {"until": now + _LONG_COOLDOWN_S, "reason": reason[:200]}
    log.warning(f"[resilience] long-cooldown {provider} ({_LONG_COOLDOWN_S//3600}h): {reason[:120]}")


def provider_long_cooldown(provider, now=None):
    now = time.time() if now is None else now
    with _long_lock:
        rec = _long_cooldown.get(provider)
        if not rec:
            return None
        if now >= rec["until"]:
            del _long_cooldown[provider]
            return None
        return rec["reason"]


def provider_skipped(provider, model, now=None):
    """Центральный skip-предикат для обходов цепей: квота 429 + long-cooldown.
    Возвращает строку-причину или None."""
    reason = _quota.is_limited(provider, model, now=now)
    if reason:
        return reason
    return provider_long_cooldown(provider, now=now)


# ─────────────────────────── BUCKETS AGGREGATION (/health) ───────────────────────────
def buckets_last_24h():
    """Агрегат failure buckets за 24 ч из JSONL-трейсов FO-004 (переживает рестарт)."""
    from collections import Counter
    import glob
    counts = Counter()
    cutoff = time.time() - 24 * 3600
    trace_dir = os.path.join(os.environ.get("DATABASE_PATH", "./data"), "traces")
    try:
        files = sorted(glob.glob(os.path.join(trace_dir, "llm_*.jsonl")))[-3:]
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if rec.get("ok") is not False:
                            continue
                        ts = rec.get("ts", "")
                        try:
                            t = datetime.fromisoformat(ts).timestamp()
                        except (ValueError, TypeError):
                            continue
                        if t < cutoff:
                            continue
                        counts[rec.get("failure_bucket", "other")] += 1
            except OSError as e:
                log.debug(f"[resilience] trace file read failed {fp}: {e}")
    except OSError as e:
        log.debug(f"[resilience] trace dir read failed: {e}")
    return {b: counts.get(b, 0) for b in BUCKETS if counts.get(b, 0)}


def trace_fallback_event(from_provider, from_model, bucket, combo=None, dept=None):
    """Событие фолбэка в трейсы FO-004: причина фолбэка читается за 10 секунд."""
    try:
        _write_llm_trace({
            "event": "fallback",
            "ts": datetime.now(timezone.utc).isoformat(),
            "from_provider": from_provider,
            "from_model": from_model,
            "failure_bucket": bucket,
            "combo": combo,
            "dept": dept,
            "ok": False,
        })
    except Exception as e:  # noqa: BLE001 — трейс не должен ронять фолбэк
        log.debug(f"[resilience] fallback trace write failed: {e}")


def quota_status(now=None):
    """Снимок активных квотных кулдаунов для /health."""
    return _quota.status(now=now)


def note_rate_limited(provider, model, body_text="", headers=None, now=None):
    """Модульный враппер QuotaTracker.note_rate_limited (для providers.py)."""
    return _quota.note_rate_limited(provider, model, body_text=body_text,
                                    headers=headers, now=now)
