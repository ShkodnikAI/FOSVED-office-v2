#!/usr/bin/env python3
"""proxy/redact.py — deep-редакция env-секретов из payload перед наружу.

Дисциплина free-router redact.mjs: значения полей с именами
*_API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL
(значение ≥8 симв.) вырезаются на ЛЮБОЙ глубине структуры. Используется
Memory-MCP-сервером (FO-021) на каждом ответе наружу; общий модуль для FO-022.
"""
import re

SECRET_KEY_RE = re.compile(
    r"(?i)(?:^|[_-])(api[_-]?key|secret|token|password|passwd|private[_-]?key|"
    r"access[_-]?key|credential)s?([_-]|$)"
)
MIN_SECRET_LEN = 8
REDACTED = "[REDACTED]"


def _is_secret_key(key):
    return bool(key) and bool(SECRET_KEY_RE.search(str(key)))


def redact_text(text):
    """JSON-текст → JSON-текст без секретов. Не-JSON возвращается как есть."""
    import json
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    return json.dumps(redact_obj(data), ensure_ascii=False)


def redact_obj(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(k) and isinstance(v, str) and len(v) >= MIN_SECRET_LEN:
                out[k] = REDACTED
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    return obj
