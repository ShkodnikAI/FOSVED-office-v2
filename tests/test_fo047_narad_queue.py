#!/usr/bin/env python3
"""FO-047 tests: диспетчер нарядной очереди (диспатч #161).

Критерии «сделано, когда»:
- наряд проходит полный цикл approved → in_work → testing без ручного SQL;
- выбор следующего: приоритет high → normal → low, внутри — старые вперёд;
- наряд без исполнителя очередь не берёт;
- durable: провал степы фиксируется (failed), следующий тик возобновляет;
- крах между persist и результатом возобновляем (степа pending остаётся);
- attempts >= NARAD_MAX_ATTEMPTS → наряд блокируется с причиной в result;
- /cron/narad-tick защищён CRON_SECRET.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo47-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['CRON_SECRET'] = 'cron-test-secret'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
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
def schema(monkeypatch):
    nq.ensure_schema()
    _query(NARADS_SQL)
    _query("DELETE FROM narads")
    _query("DELETE FROM narad_steps")
    monkeypatch.setattr(nq, "_notify_owner", lambda text, markup=None: None)
    yield
    _query("DELETE FROM narads")
    _query("DELETE FROM narad_steps")


def _ins(nid, title="наряд", status="approved", dept="dev", priority="normal", days_ago=0):
    _query("INSERT INTO narads (id, title, description, requested_by, risk_level, status, dept, priority, created_at) "
           "VALUES (?, ?, 'описание', '12345', 'low', ?, ?, ?, datetime('now', ?))",
           (nid, title, status, dept, priority, f'-{days_ago} days'))


def _narad_status(nid):
    return _query("SELECT status FROM narads WHERE id=?", (nid,), fetch=True)[0]["status"]


def test_full_cycle_approved_to_testing():
    _ins("N1", "починить крон")
    out = nq.execute_next(invoke_fn=lambda dept, q, chat: "ОТЧЁТ: сделано, проверено")
    assert out["action"] == "executed", out
    assert _narad_status("N1") == "testing"
    row = _query("SELECT result FROM narads WHERE id=?", ("N1",), fetch=True)[0]
    assert "сделано" in row["result"]
    step = _query("SELECT status, reply FROM narad_steps WHERE narad_id=?", ("N1",), fetch=True)[0]
    assert step["status"] == "ok"
    assert "ОТЧЁТ" in step["reply"]


def test_priority_then_age_ordering():
    _ins("N-LOW-NEW", priority="low", days_ago=0)
    _ins("N-NORM-OLD", priority="normal", days_ago=5)
    _ins("N-HIGH-MID", priority="high", days_ago=2)
    assert nq.execute_next(invoke_fn=lambda d, q, c: "ok")["narad_id"] == "N-HIGH-MID"
    assert nq.execute_next(invoke_fn=lambda d, q, c: "ok")["narad_id"] == "N-NORM-OLD"
    assert nq.execute_next(invoke_fn=lambda d, q, c: "ok")["narad_id"] == "N-LOW-NEW"


def test_same_priority_oldest_first():
    _ins("N-A", days_ago=3)
    _ins("N-B", days_ago=1)
    assert nq.execute_next(invoke_fn=lambda d, q, c: "ok")["narad_id"] == "N-A"


def test_no_dept_skipped():
    _ins("N-NODEPT", dept="")
    _ins("N-DEPT", dept="qa")
    out = nq.execute_next(invoke_fn=lambda d, q, c: "ok")
    assert out["narad_id"] == "N-DEPT"


def test_failure_then_resume():
    _ins("N1")

    def flaky(dept, q, chat):
        raise RuntimeError("mlogserve down")

    out = nq.execute_next(invoke_fn=flaky)
    assert out["action"] == "failed"
    assert _narad_status("N1") == "in_work"
    step = _query("SELECT status FROM narad_steps WHERE narad_id=?", ("N1",), fetch=True)[0]
    assert step["status"] == "failed"

    out = nq.tick(invoke_fn=lambda d, q, c: "восстановлено")
    assert out["action"] == "resumed"
    assert _narad_status("N1") == "testing"


def test_crash_between_persist_and_invoke_resumes():
    _ins("N1")
    # симуляция краха процесса: наряд in_work, степа осталась pending
    _query("UPDATE narads SET status='in_work', in_work_at=datetime('now') WHERE id=?", ("N1",))
    _query("INSERT INTO narad_steps (narad_id, dept, input_hash, status) VALUES ('N1', 'dev', 'h', 'pending')")
    out = nq.tick(invoke_fn=lambda d, q, c: "дожили")
    assert out["action"] == "resumed"
    assert _narad_status("N1") == "testing"


def test_blocked_after_max_attempts(monkeypatch):
    monkeypatch.setattr(nq, "NARAD_MAX_ATTEMPTS", 2)
    _ins("N1")

    def flaky(dept, q, chat):
        raise RuntimeError("падаю")

    assert nq.execute_next(invoke_fn=flaky)["action"] == "failed"
    out = nq.tick(invoke_fn=flaky)
    assert out["action"] == "blocked", out
    row = _query("SELECT status, result FROM narads WHERE id=?", ("N1",), fetch=True)[0]
    assert row["status"] == "blocked"
    assert "2 раз" in row["result"]


def test_tick_idle_on_empty_queue():
    assert nq.tick(invoke_fn=lambda d, q, c: "ok")["action"] == "idle"


def test_queue_counts():
    _ins("N1", status="pending")
    _ins("N2", status="queued")
    _ins("N3", status="in_work")
    _ins("N4", status="testing")
    counts = nq.queue_counts()
    assert counts["pending"] == 1
    assert counts["queued"] == 1
    assert counts["in_work"] == 1
    assert counts["testing"] == 1


def test_build_query_carries_plan_and_acceptance():
    _ins("N1")
    _query("UPDATE narads SET plan='шаг один', acceptance='тесты зелёные' WHERE id=?", ("N1",))
    row = nq.next_narad()[0]
    q = nq.build_query(row)
    assert "НАРЯД N1" in q
    assert "шаг один" in q
    assert "тесты зелёные" in q


def test_tick_endpoint_auth_and_wiring():
    with flask_app.test_client() as c:
        assert c.get("/cron/narad-tick").status_code == 403
        resp = c.get("/cron/narad-tick?secret=cron-test-secret")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
