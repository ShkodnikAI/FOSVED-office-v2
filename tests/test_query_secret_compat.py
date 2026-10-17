#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""№425: совместимость CRON_SECRET с URL-декодированием query.

Корень: 0.21 percent-декодирует значения query (server.rs
url_decode_fallback: '+' -> ' ', %XX -> байты), Flask request.args
декодирует так же, а клиенты (entrypoint curl, mlog http_*, cron-job.org)
вставляли секрет в URL RAW — литеральный '+' приходил как пробел и честно
не совпадал: 403 на /cron/morning (cron-job.org) и «no answer» на
/schedules/bootstrap (entrypoint). Проба на реальном бинаре —
scripts/probe021qp.sh: raw=403, --data-urlencode=200 KEEP×7.

Часть 1 — entrypoint.sh: секрет/токен в query только через -G
--data-urlencode (анти-copy-drift по тексту entrypoint).
Часть 2 — proxy/routes_tail.cron_secret_ok(): декодированное ИЛИ сырое
значение query; оба пустых = pass-through (пежний контракт).
"""
import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINT = os.path.join(REPO_ROOT, "entrypoint.sh")

# ── Часть 1: entrypoint ───────────────────────────────────────────────────


def _ep() -> str:
    return open(ENTRYPOINT, encoding="utf-8").read()


def test_entrypoint_has_no_raw_secret_in_query():
    src = _ep()
    assert "?secret=${CRON_SECRET}" not in src, (
        "сырая вставка CRON_SECRET в query — 0.21 декодирует '+'/%XX, "
        "auth честно даёт 403 (находка №425)"
    )


def test_entrypoint_has_no_raw_token_in_query():
    src = _ep()
    assert "?token=${INTERNAL_API_TOKEN" not in src


def test_entrypoint_encodes_secret_and_header_token():
    src = _ep()
    # бутстрап (три попытки) и фоновый прогрев — через -G --data-urlencode;
    # #429 A.3 добавил второй --data-urlencode "secret=..." — прогрев
    # /cron/onliner-warm при старте (секрет в query внутреннего запроса,
    # в лог не печатается)
    assert src.count('--data-urlencode "secret=${CRON_SECRET}"') == 2
    # #536 A.2/A.3: INTERNAL_API_TOKEN больше не ходит в URL (утечка через
    # текст исключений requests) — только заголовок X-Internal-Token:
    # A.3-вердикт + version-чек (:-вариант) и department-validation (без :-)
    assert src.count('--data-urlencode "token=${INTERNAL_API_TOKEN:-}"') == 0
    assert src.count('--data-urlencode "token=${INTERNAL_API_TOKEN}"') == 0
    assert 'data-urlencode "token=' not in src, "токен в query запрещён (#536)"
    assert src.count('-H "X-Internal-Token: ${INTERNAL_API_TOKEN:-}"') == 2
    assert src.count('-H "X-Internal-Token: ${INTERNAL_API_TOKEN}"') == 1
    # -G остаётся у двух secret-вызовов (bootstrap + прогрев)
    assert src.count("-G ") >= 2


def test_entrypoint_bootstrap_url_has_no_query():
    src = _ep()
    assert '-G "http://127.0.0.1:10001/schedules/bootstrap"' in src
    # в URL бутстрапа не осталось query-хвоста
    assert re.search(r'-G "http://127\.0\.0\.1:10001/schedules/bootstrap\?', src) is None


# ── Часть 2: proxy/routes_tail.cron_secret_ok ─────────────────────────────


def _ctx(query_string: str):
    from proxy.core import app
    return app.test_request_context(f"/cron/backup{query_string}")


def test_raw_plus_secret_matches(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.setenv("CRON_SECRET", "Shkodnik+vto")
    # сырая вставка: werkzeug декодирует '+' -> ' ', совпасть должно сырое значение
    with _ctx("?secret=Shkodnik+vto"):
        assert cron_secret_ok() is True


def test_percent_encoded_secret_matches(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.setenv("CRON_SECRET", "Shkodnik+vto")
    # корректно закодированный клиент: decoded args == env
    with _ctx("?secret=Shkodnik%2Bvto"):
        assert cron_secret_ok() is True


def test_percent_in_secret_raw_match(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.setenv("CRON_SECRET", "pct%20tok")
    # decoded = "pct tok" != env; сырая выжимка "pct%20tok" == env
    with _ctx("?secret=pct%20tok"):
        assert cron_secret_ok() is True


def test_wrong_secret_rejected(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.setenv("CRON_SECRET", "Shkodnik+vto")
    with _ctx("?secret=WRONG"):
        assert cron_secret_ok() is False


def test_no_secret_rejected_when_env_set(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.setenv("CRON_SECRET", "Shkodnik+vto")
    with _ctx(""):
        assert cron_secret_ok() is False


def test_both_empty_pass_through(monkeypatch):
    # прежний контракт: env не задан и секрет не передан = авторизовано
    # (паритет с mlog RequireInternalAuth: expected == "" -> ok)
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.delenv("CRON_SECRET", raising=False)
    with _ctx(""):
        assert cron_secret_ok() is True


def test_secret_with_env_unset_rejected(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.delenv("CRON_SECRET", raising=False)
    with _ctx("?secret=anything"):
        assert cron_secret_ok() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── #443: hash-form (mlog redact hash_only) принимается cron_secret_ok ──────
# mlog-слоты шлют секрет по сети ТОЛЬКО hash-form (private-egress гвард
# №391/№312). Формат верифицирован эмпирической пробой bin/mlog (0.27.1 при
# внедрении; пере-пробован /repos-гвардом на 0.28.0 — ADR-0015)
# (scripts/…hashprobe): [HASH:<sha256(secret)[:16]>] hex.

def test_mlog_hash_form_matches(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    secret = "test-secret-for-probe-12345"
    monkeypatch.setenv("CRON_SECRET", secret)
    import hashlib
    hash_form = f"[HASH:{hashlib.sha256(secret.encode()).hexdigest()[:16]}] hex"
    with _ctx("?secret=" + hash_form.replace(" ", "%20")):
        assert cron_secret_ok() is True


def test_mlog_hash_form_raw_query_string(monkeypatch):
    """Плюс проба через raw query_string (без percent-кодирования пробела)."""
    from proxy.routes_tail import cron_secret_ok
    secret = "another-secret"
    monkeypatch.setenv("CRON_SECRET", secret)
    import hashlib
    hash_form = f"[HASH:{hashlib.sha256(secret.encode()).hexdigest()[:16]}] hex"
    # werkzeug декодирует query: пробел в "hex" придёт из '%20' или '+' —
    # для сырой выжимки проверяем и вариант без пробела в query_string
    with _ctx("?secret=%5BHASH%3A" + hashlib.sha256(secret.encode()).hexdigest()[:16] + "%5D%20hex"):
        assert cron_secret_ok() is True


def test_wrong_hash_form_rejected(monkeypatch):
    from proxy.routes_tail import cron_secret_ok
    monkeypatch.setenv("CRON_SECRET", "Shkodnik+vto")
    with _ctx("?secret=%5BHASH%3Adeadbeefdeadbeef%5D%20hex"):
        assert cron_secret_ok() is False
