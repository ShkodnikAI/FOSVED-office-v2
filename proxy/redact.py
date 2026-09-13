#!/usr/bin/env python3
"""proxy/redact.py — deep-редакция env-секретов из payload перед наружу.

Дисциплина free-router redact.mjs: значения полей с именами
*_API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL
(значение ≥8 симв.) вырезаются на ЛЮБОЙ глубине структуры. Используется
Memory-MCP-сервером (FO-021) на каждом ответе наружу; общий модуль для FO-022.

FO-022 (наряд #88): второй контур — литеральные ЗНАЧЕНИЯ известных секретов
(env + secrets_store) вырезаются из любой строки payload: даже если секрет
просочился в контекст департамента, наружу (LLM-провайдеру / MCP-клиенту) он
не уходит. Множество значений собирается заново на каждом использовании
(TTL 5 c + invalidate) — redactor «перестраивается при смене ключа».

Контракт redact-семантики: docs/redact-contract.md (общий с Metalogos №274).
"""
import os
import re
import threading
import time

SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|[_-])(api[_-]?key|secret|token|password|passwd|private[_-]?key|"
    r"access[_-]?key|credential)s?([_-]|$)"
)
MIN_SECRET_LEN = 8
REDACTED = "[REDACTED]"

_VALUES_TTL = 5.0
_values_cache = {"values": frozenset(), "ts": 0.0}
_values_lock = threading.Lock()


def _is_secret_key(key):
    return bool(key) and bool(SECRET_KEY_RE.search(str(key)))


def _collect_secret_values():
    """Литеральные значения известных секретов: env-переменные + secrets_store.
    Сбор дешёвый и без side effects; БД-хвост необязателен (тесты без БД)."""
    vals = set()
    for k, v in os.environ.items():
        if _is_secret_key(k) and isinstance(v, str) and len(v) >= MIN_SECRET_LEN:
            vals.add(v)
    try:
        from proxy.core import _query, get_secret  # лениво: без БД → просто пусто
        rows = _query("SELECT name FROM secrets_store", fetch=True) or []
        for r in rows:
            name = r["name"] if isinstance(r, dict) else r[0]
            if not _is_secret_key(name):
                continue
            v = get_secret(name)
            if v and len(v) >= MIN_SECRET_LEN:
                vals.add(v)
    except Exception:  # noqa: BLE001 — БД может отсутствовать (тесты/ранний старт)
        pass
    return frozenset(vals)


def known_secret_values(force=False):
    """Множество секретных значений; перестраивается при смене ключа
    (TTL + invalidate_values_cache после ротации)."""
    with _values_lock:
        now = time.time()
        if force or not _values_cache["values"] or (now - _values_cache["ts"]) > _VALUES_TTL:
            _values_cache["values"] = _collect_secret_values()
            _values_cache["ts"] = now
        return _values_cache["values"]


def invalidate_values_cache():
    """Сброс кэша значений (вызывать после смены ключа в secrets_store/env)."""
    with _values_lock:
        _values_cache["values"] = frozenset()
        _values_cache["ts"] = 0.0


def redact_values_in_text(text, values=None):
    """Замена литеральных секретных значений внутри произвольной строки."""
    if not isinstance(text, str) or not text:
        return text
    if values is None:
        values = known_secret_values()
    for v in values:
        if v and v in text:
            text = text.replace(v, REDACTED)
    return text


def redact_text(text):
    """JSON-текст → JSON-текст без секретов. Не-JSON возвращается как есть."""
    import json
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    return json.dumps(redact_obj(data), ensure_ascii=False)


def redact_obj(obj, values=None):
    """Deep-редакция: секретные ПОЛЯ по имени + литеральные ЗНАЧЕНИЯ секретов
    внутри любых строк (FO-022, второй контур taint-инварианта)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(k) and isinstance(v, str) and len(v) >= MIN_SECRET_LEN:
                out[k] = REDACTED
            else:
                out[k] = redact_obj(v, values)
        return out
    if isinstance(obj, list):
        return [redact_obj(x, values) for x in obj]
    if isinstance(obj, str):
        return redact_values_in_text(obj, values)
    return obj
