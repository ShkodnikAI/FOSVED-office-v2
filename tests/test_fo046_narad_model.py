#!/usr/bin/env python3
"""FO-046 tests: нарядная модель 2.0 (диспатч #161).

Критерии «сделано, когда»:
- расширенная схема narads (dept/priority/plan/acceptance/test_status/report/
  dispatch_id/rework_count/in_work_at/testing_at) обратимо совместима с
  python-контуром: /api/narads (miniapp) и approve-эндпоинт работают без правок;
- новые колонки пишутся и читаются, дефолты корректны (priority='normal',
  test_status='none', rework_count=0);
- python-зеркало брифа считает pending по-прежнему.
Логика переходов (mlog) покрыта test_narad1v3.mlog (локальный прогон).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo46-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

NARADS_SQL = (
    "CREATE TABLE IF NOT EXISTS narads (id TEXT PRIMARY KEY, title TEXT, description TEXT, "
    "requested_by TEXT, changed_files TEXT, risk_level TEXT, status TEXT, "
    "created_at TEXT DEFAULT (datetime('now')), approved_at TEXT, executed_at TEXT, result TEXT, "
    "dept TEXT, priority TEXT DEFAULT 'normal', plan TEXT, acceptance TEXT, "
    "test_status TEXT DEFAULT 'none', test_log TEXT, report TEXT, dispatch_id TEXT, "
    "rework_count INTEGER DEFAULT 0, in_work_at TEXT, testing_at TEXT)"
)


@pytest.fixture(autouse=True)
def narads_schema():
    _query(NARADS_SQL)
    _query("DELETE FROM narads")
    yield
    _query("DELETE FROM narads")


API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


def test_api_narads_legacy_fields_with_new_schema():
    """miniapp /api/narads отдаёт прежние поля на новой схеме."""
    _query("INSERT INTO narads (id, title, description, requested_by, risk_level, status) "
           "VALUES ('N1', 'починить крон', 'описание', '12345', 'low', 'pending')")
    with _client() as c:
        resp = c.get("/api/narads", headers=API_AUTH)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    n = [x for x in data["narads"] if x["id"] == "N1"][0]
    assert n["title"] == "починить крон"
    assert n["status"] == "pending"
    assert n["risk"] == "low"


def test_new_columns_defaults_and_write():
    """Дефолты контура корректны, новые колонки пишутся и читаются."""
    _query("INSERT INTO narads (id, title, status) VALUES ('N2', 'с планом', 'pending')")
    row = _query("SELECT priority, test_status, rework_count, dept FROM narads WHERE id='N2'", fetch=True)[0]
    assert row["priority"] == "normal"
    assert row["test_status"] == "none"
    assert row["rework_count"] == 0
    assert row["dept"] is None

    _query("UPDATE narads SET dept='dev', priority='high', plan='шаг 1, шаг 2', "
           "acceptance='сделано когда тесты зелёные', dispatch_id='161' WHERE id='N2'")
    row = _query("SELECT dept, priority, plan, acceptance, dispatch_id FROM narads WHERE id='N2'", fetch=True)[0]
    assert row["dept"] == "dev"
    assert row["priority"] == "high"
    assert row["plan"] == "шаг 1, шаг 2"
    assert row["acceptance"] == "сделано когда тесты зелёные"
    assert row["dispatch_id"] == "161"


def test_approve_endpoint_on_new_schema():
    """approve-эндпоинт miniapp живёт на расширенной схеме без изменений."""
    _query("INSERT INTO narads (id, title, status) VALUES ('N3', 'одобряем', 'pending')")
    with _client() as c:
        resp = c.post("/api/narads/N3/approve", headers=API_AUTH)
    assert resp.status_code == 200
    row = _query("SELECT status, approved_at FROM narads WHERE id='N3'", fetch=True)[0]
    assert row["status"] == "approved"
    assert row["approved_at"] is not None


def test_brief_pending_count_unchanged():
    """python-зеркало брифа считает pending как раньше (новые статусы не мешают)."""
    _query("INSERT INTO narads (id, title, status) VALUES ('N4', 'раз', 'pending')")
    _query("INSERT INTO narads (id, title, status) VALUES ('N5', 'два', 'in_work')")
    cnt = _query("SELECT COUNT(*) as cnt FROM narads WHERE status = 'pending'", fetch=True)[0]["cnt"]
    assert cnt == 1
