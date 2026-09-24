#!/usr/bin/env python3
"""FO-053 (#325) tests: /metrics/activity — фид owner_activity.

Покрытие:
1. Auth: ACTIVITY_FEED_TOKEN (НЕ CRON_SECRET), decoded-OR-raw по паттерну
   cron_secret_ok() (урок №425); ОТЛИЧИЕ, громко: оба пустых = ОТКАЗ
   (fail-closed) — счётчики приватности не отдаются незаданным токеном.
2. Счётчики: dialog_message (user/assistant), audit_log (dept_query,
   cron_*) — почасовые бакеты, только числа.
3. Форма ответа: allowlist-схема, целые счётчики, окно hours с зажимом.
4. Privacy-гвард (мутационный ≥2/2): добавление контент-поля / chat_id /
   нечислового счётчика в ряд → гвард ловит, ответ не уходит.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-activity-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query, app  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app
from proxy.routes_tail import assert_activity_payload_clean  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS dialog_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    dept TEXT DEFAULT '',
    data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT);
"""


@pytest.fixture()
def feed_db(monkeypatch):
    db_file = os.path.join(os.environ["DATABASE_PATH"], "fosved.db")
    conn = sqlite3.connect(db_file)
    conn.executescript(DDL)
    conn.commit()
    conn.close()
    _query("DELETE FROM dialog_message")
    _query("DELETE FROM audit_log")
    monkeypatch.delenv("ACTIVITY_FEED_TOKEN", raising=False)
    yield
    _query("DELETE FROM dialog_message")
    _query("DELETE FROM audit_log")


@pytest.fixture()
def client():
    with app.test_client() as c:
        yield c


def _seed_activity():
    """Час A: 2 входящих, 1 исходящий, 1 dept_query, 2 cron; час B: 1 входящий."""
    _query("INSERT INTO dialog_message (session_id, role, created_at) VALUES "
           "('555', 'user', '2026-09-24 10:05:00'), "
           "('555', 'user', '2026-09-24 10:20:00'), "
           "('555', 'assistant', '2026-09-24 10:21:00'), "
           "('555', 'user', '2026-09-24 11:00:00')")
    _query("INSERT INTO audit_log (action, actor, timestamp) VALUES "
           "('dept_query', 'yana', '2026-09-24 10:07:00'), "
           "('cron_admin_reply', 'scheduler', '2026-09-24 10:25:00'), "
           "('cron_shop_tick', 'scheduler', '2026-09-24 10:40:00')")


def test_auth_fail_closed_without_token(feed_db, client, monkeypatch):
    monkeypatch.delenv("ACTIVITY_FEED_TOKEN", raising=False)
    r = client.get("/metrics/activity")
    assert r.status_code == 403  # оба пустых = ОТКАЗ (отличие от cron-паттерна)


def test_auth_wrong_token_403(feed_db, client, monkeypatch):
    monkeypatch.setenv("ACTIVITY_FEED_TOKEN", "правильный-токен")
    assert client.get("/metrics/activity").status_code == 403
    assert client.get("/metrics/activity?token=нет").status_code == 403


def test_auth_token_simple_ok(feed_db, client, monkeypatch):
    monkeypatch.setenv("ACTIVITY_FEED_TOKEN", "tkn-abc")
    r = client.get("/metrics/activity?token=tkn-abc")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_auth_token_raw_plus_matches_decoded(feed_db, client, monkeypatch):
    """Урок №425: секрет с '+' — декодированное ('+'→пробел) ИЛИ сырое
    значение в query; оба варианта авторизованы."""
    monkeypatch.setenv("ACTIVITY_FEED_TOKEN", "Shkodnik+probe-325")
    r_raw = client.get("/metrics/activity?token=Shkodnik%2Bprobe-325")
    # Flask декодирует %2B в '+' — совпадение с ожидаемым напрямую
    assert r_raw.status_code == 200
    # сырая форма: '+' как есть в query — raw-ветка cron_secret_ok-паттерна
    r_sp = client.get("/metrics/activity?token=Shkodnik+probe-325")
    assert r_sp.status_code == 200


def test_feed_counters_hourly_buckets(feed_db, client, monkeypatch):
    monkeypatch.setenv("ACTIVITY_FEED_TOKEN", "tkn")
    _seed_activity()
    r = client.get("/metrics/activity?token=tkn&hours=48")
    data = r.get_json()
    assert r.status_code == 200
    assert set(data.keys()) == {"ok", "window_hours", "generated_at", "hours"}
    by_hour = {row["hour"]: row for row in data["hours"]}
    a = by_hour["2026-09-24T10:00:00"]
    assert a["incoming_owner"] == 2 and a["outgoing_office"] == 1
    assert a["dept_llm_calls"] == 1 and a["cron_slots"] == 2
    b = by_hour["2026-09-24T11:00:00"]
    assert b["incoming_owner"] == 1 and b["outgoing_office"] == 0
    # только числа: все счётчики — int (privacy by design, проверка формы)
    for row in data["hours"]:
        for k, v in row.items():
            if k != "hour":
                assert isinstance(v, int), (k, v)


def test_feed_window_clamped_and_validated(feed_db, client, monkeypatch):
    monkeypatch.setenv("ACTIVITY_FEED_TOKEN", "tkn")
    assert client.get("/metrics/activity?token=tkn&hours=мусор").status_code == 400
    r = client.get("/metrics/activity?token=tkn&hours=999999")
    assert r.status_code == 200 and r.get_json()["window_hours"] <= 24 * 90


# ── privacy-гвард: мутационный ≥2/2 ─────────────────────────────────────
def _clean_payload():
    return {"ok": True, "window_hours": 168, "generated_at": "2026-09-24T00:00:00Z",
            "hours": [{"hour": "2026-09-24T10:00:00", "incoming_owner": 2,
                       "outgoing_office": 1, "dept_llm_calls": 1, "cron_slots": 2}]}


def test_guard_catches_content_field_mutation():
    """Мутация 1/2: текстовое поле контента в ряду → гвард ловит."""
    payload = _clean_payload()
    payload["hours"][0]["content"] = "фрагмент сообщения владельца"
    with pytest.raises(ValueError):
        assert_activity_payload_clean(payload)


def test_guard_catches_chat_id_and_non_int_mutations():
    """Мутация 2/2: chat_id в ряду → гвард ловит; нечисловой счётчик тоже."""
    payload = _clean_payload()
    payload["hours"][0]["chat_id"] = "555000"
    with pytest.raises(ValueError):
        assert_activity_payload_clean(payload)
    payload2 = _clean_payload()
    payload2["hours"][0]["incoming_owner"] = "два сообщения"
    with pytest.raises(ValueError):
        assert_activity_payload_clean(payload2)
    # лишнее поле в шапке — тоже отказ
    payload3 = _clean_payload()
    payload3["leak"] = "x"
    with pytest.raises(ValueError):
        assert_activity_payload_clean(payload3)
    # чистый payload гвард пропускает
    assert_activity_payload_clean(_clean_payload())


def test_auth_uses_separate_token_not_cron_secret():
    """Anti-copy-drift: фид — отдельный ACTIVITY_FEED_TOKEN, не CRON_SECRET."""
    src = open(os.path.join(REPO_ROOT, "proxy", "routes_tail.py"), encoding="utf-8").read()
    assert 'os.environ.get("ACTIVITY_FEED_TOKEN", "")' in src
    assert "if not expected:\n        return False" in src  # fail-closed ветка
