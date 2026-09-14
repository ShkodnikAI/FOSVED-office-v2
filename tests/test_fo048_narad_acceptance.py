#!/usr/bin/env python3
"""FO-048 tests: приёмка-gate (диспатч #161).

Критерии «сделано, когда»:
- python-сторона петли доработки: build_query несёт замечания приёмки
  (test_log) при повторном исполнении после fail;
- кнопки приёмки формируются с callback na_ok_/na_fail_;
- уведомление о результате несёт разметку кнопок;
- mlog-логика гейта (NaradAccept/NaradDone, rework-счётчик) покрыта
  test_narad2v3.mlog (локальный прогон).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo48-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import _query  # noqa: E402
from proxy import narad_queue as nq  # noqa: E402

NARADS_SQL = (
    "CREATE TABLE IF NOT EXISTS narads (id TEXT PRIMARY KEY, title TEXT, description TEXT, "
    "requested_by TEXT, changed_files TEXT, risk_level TEXT, status TEXT, "
    "created_at TEXT DEFAULT (datetime('now')), approved_at TEXT, executed_at TEXT, result TEXT, "
    "dept TEXT, priority TEXT DEFAULT 'normal', plan TEXT, acceptance TEXT, "
    "test_status TEXT DEFAULT 'none', test_log TEXT, report TEXT, dispatch_id TEXT, "
    "rework_count INTEGER DEFAULT 0, in_work_at TEXT, testing_at TEXT)"
)


@pytest.fixture(autouse=True)
def schema():
    nq.ensure_schema()
    _query(NARADS_SQL)
    _query("DELETE FROM narads")
    _query("DELETE FROM narad_steps")
    yield
    _query("DELETE FROM narads")
    _query("DELETE FROM narad_steps")


def test_build_query_carries_rework_remarks():
    _query("INSERT INTO narads (id, title, status, dept, test_status, test_log, rework_count) "
           "VALUES ('N1', 'доработка', 'queued', 'dev', 'failed', 'не закрыт критерий 2', 1)")
    row = nq.next_narad()[0]
    q = nq.build_query(row)
    assert "ОТКЛОНЕНА НА ПРИЁМКЕ" in q
    assert "не закрыт критерий 2" in q
    assert "rework 1" in q


def test_build_query_clean_on_first_run():
    _query("INSERT INTO narads (id, title, status, dept) VALUES ('N2', 'первый прогон', 'approved', 'qa')")
    row = nq.next_narad()[0]
    q = nq.build_query(row)
    assert "ОТКЛОНЕНА" not in q


def test_accept_markup_buttons():
    m = nq._accept_markup("N12")
    btns = m["inline_keyboard"][0]
    assert btns[0]["callback_data"] == "na_ok_N12"
    assert btns[1]["callback_data"] == "na_fail_N12"


def test_notify_owner_carries_markup(monkeypatch):
    captured = {}

    def fake_send(chat_id, text, parse_mode=None, reply_markup=None):
        captured["markup"] = reply_markup
        return "ok"

    import proxy.telegram as tg
    monkeypatch.setattr(tg, "_tg_send_message", fake_send)
    nq._notify_owner("тестовое уведомление", nq._accept_markup("N1"))
    assert captured["markup"] is not None
    assert "na_ok_N1" in captured["markup"]["inline_keyboard"][0][0]["callback_data"]
