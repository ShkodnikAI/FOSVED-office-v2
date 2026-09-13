#!/usr/bin/env python3
"""FO-027 tests: durable-степы цепочек — чекпоинты и resume ExecuteChain.

Наряд #114. Критерии «сделано, когда»:
- «kill на шаге 4/5 → resume → шаги 1–3 из кэша, шаг 4 исполняется» —
  симуляция краха: ok-степы в chain_steps, счётчик LLM-вызовов = 0 по ним;
- идемпотентность доказана счётчиком invoke-вызовов (double-run = ровно один);
- input_hash-инвалидация при изменении query;
- TTL-очистка (>14 дней) и expired (>24 ч без прогресса);
- регрессия FO-026 чистая (fan-out прогоняется через тот же durable-слой).
"""
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo27-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy import chain_durable as cd  # noqa: E402
import proxy.chain_parallel as cp  # noqa: E402
from proxy.core import app as flask_app, _query  # noqa: E402


@pytest.fixture(autouse=True)
def clean_steps():
    cd.ensure_schema()
    _query("DELETE FROM chain_steps")
    _query("DELETE FROM audit_log WHERE action LIKE 'chain_%'")
    yield


def _calls_counter(monkeypatch, replies=None, fail_depts=()):
    """Счётчик 'LLM-вызовов' (invoke_fn). Каждому депту — свой ответ."""
    state = {"n": 0}

    def invoke(dept, query, chat_id, chain_id, step_num, peer_context=None):
        state["n"] += 1
        if dept in fail_depts:
            raise RuntimeError(f"{dept} down")
        return (replies or {}).get(dept, f"REPLY-{dept}-{step_num}")

    return state, invoke


def _rows():
    return _query("SELECT chain_id, step_num, dept, status, reply, input_hash FROM chain_steps", fetch=True)


# ── Базовая семантика durable-степы ─────────────────────────────────────
def test_first_run_persists_pending_then_ok(monkeypatch):
    state, invoke = _calls_counter(monkeypatch)
    out = cd.run_durable_step("qa", "q1", "0", "c1", 1.0, "fanout", invoke)
    assert out["reused"] is False and out["reply"] == "REPLY-qa-1.0"
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["status"] == "ok" and rows[0]["reply"] == "REPLY-qa-1.0"
    assert rows[0]["input_hash"] == cd.step_hash("c1", 1.0, "qa", "q1")


def test_double_run_is_exactly_one_llm_call(monkeypatch):
    """Идемпотентность: double-run одной степы = ровно один LLM-вызов."""
    state, invoke = _calls_counter(monkeypatch)
    out1 = cd.run_durable_step("qa", "q1", "0", "c1", 1.0, "fanout", invoke)
    out2 = cd.run_durable_step("qa", "q1", "0", "c1", 1.0, "fanout", invoke)
    assert state["n"] == 1           # ровно один вызов
    assert out1["reused"] is False
    assert out2["reused"] is True    # второй — из кэша
    assert out1["reply"] == out2["reply"]


def test_input_hash_invalidation_on_query_change(monkeypatch):
    """query изменился → hash разошёлся → степа исполняется заново."""
    state, invoke = _calls_counter(monkeypatch)
    cd.run_durable_step("qa", "q1", "0", "c1", 1.0, "fanout", invoke)
    out = cd.run_durable_step("qa", "q2-новый", "0", "c1", 1.0, "fanout", invoke)
    assert state["n"] == 2           # переисполнение
    assert out["reused"] is False
    rows = _query("SELECT input_hash FROM chain_steps WHERE chain_id='c1'", fetch=True)
    assert all(r["input_hash"] == cd.step_hash("c1", 1.0, "qa", "q2-новый") for r in rows)


def test_failed_step_is_resumable(monkeypatch):
    """failed-степа → следующий вызов исполняет заново (крах возобновляем)."""
    state, invoke = _calls_counter(monkeypatch, fail_depts=("qa",))
    with pytest.raises(RuntimeError):
        cd.run_durable_step("qa", "q1", "0", "c1", 1.0, "fanout", invoke)
    rows = _rows()
    assert rows[0]["status"] == "failed"
    # «починили» провайдера — resume исполняет степу
    state2, invoke2 = _calls_counter(monkeypatch)
    out = cd.run_durable_step("qa", "q1", "0", "c1", 1.0, "fanout", invoke2)
    assert out["reused"] is False and state2["n"] == 1
    assert _rows()[0]["status"] == "ok"


# ── Kill в середине → resume без повторных вызовов ──────────────────────
def test_kill_midway_resume_reuses_ok_steps(monkeypatch):
    """«kill на шаге 4/5 → resume»: шаги 1–3 из кэша (0 вызовов), 4–5 исполняются."""
    state, invoke = _calls_counter(monkeypatch)
    depts = ["a", "b", "c", "d", "e"]
    chain_id = "seq_killtest"
    # Шаги 1–3 успели выполниться до «краха»
    for i, d in enumerate(depts[:3], start=1):
        cd.run_durable_step(d, "Q", "0", chain_id, float(i), "sequential", invoke)
    assert state["n"] == 3

    # КРАХ ПРОЦЕССА: новый «процесс» resumed-прогон всех 5 шагов
    state2, invoke2 = _calls_counter(monkeypatch)  # счётчик нового процесса = 0
    results = {}
    for i, d in enumerate(depts, start=1):
        out = cd.run_durable_step(d, "Q", "0", chain_id, float(i),
                                  "sequential", invoke2)
        results[d] = out
    # ok-степы 1–3: из кэша, ноль LLM-вызовов
    assert all(results[d]["reused"] for d in depts[:3])
    assert results[depts[0]]["reply"] == f"REPLY-{depts[0]}-1.0"  # тот же ответ
    # 4–5 исполнились впервые
    assert not results[depts[3]]["reused"] and not results[depts[4]]["reused"]
    assert state2["n"] == 2  # только два новых вызова на 5 степов


def test_fanout_runs_through_durable_layer(monkeypatch):
    """FO-026 fan-out персистится через тот же слой: шаги оседают в chain_steps."""
    from proxy.core import app as flask_app
    def fake_invoke_step(dept, query, chat_id, group_id, round_no=1, peer_context=None):
        return f"FAN-{dept}-R{round_no}"
    monkeypatch.setattr(cp, "_invoke_step", fake_invoke_step)
    monkeypatch.setattr("proxy.providers.call_llm",
                        lambda dept, messages, **kw:
                        {"reply": "judge", "provider": "m", "model": "m",
                         "tokens_in": 1, "tokens_out": 1})
    with flask_app.test_client() as c:
        resp = c.post("/chain/fanout", headers={"Authorization": "Bearer test-secret-123"},
                      json={"mode": "parallel", "depts": ["qa", "legal"],
                            "query": "fanq", "chat_id": "0"})
        assert resp.status_code == 200
        gid = resp.get_json()["group_id"]
    rows = _query("SELECT dept, status, mode FROM chain_steps WHERE chain_id=?",
                  (gid,), fetch=True)
    assert {r["dept"] for r in rows} == {"qa", "legal"}
    assert all(r["status"] == "ok" and r["mode"] == "fanout" for r in rows)


# ── TTL и expired ────────────────────────────────────────────────────────
def test_ttl_cleanup_and_expired():
    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    # свежая ok-степа — не трогается
    cd.run_durable_step("qa", "q", "0", "fresh", 1.0, "fanout",
                        lambda *a, **k: "r")
    # старая ok-степа (>14 дней) — удалится
    _query("""INSERT INTO chain_steps (chain_id, step_num, dept, mode, input_hash, status, created_at, updated_at)
              VALUES ('old', 1, 'qa', 'fanout', 'h', 'ok', ?, ?)""", (old, old))
    # pending без прогресса >24 ч (но в пределах TTL) — станет expired
    _query("""INSERT INTO chain_steps (chain_id, step_num, dept, mode, input_hash, status, created_at, updated_at)
              VALUES ('stuck', 2, 'legal', 'fanout', 'h', 'pending', ?, ?)""", (two_days_ago, two_days_ago))
    result = cd.cleanup()
    remaining = {r["chain_id"] for r in _rows()}
    assert "old" not in remaining        # TTL-очистка
    assert "fresh" in remaining
    stuck = [r for r in _rows() if r["chain_id"] == "stuck"]
    assert all(r["status"] == "expired" for r in stuck)  # expired-алерт данные
    assert result["expired_chains"] and result["expired_chains"][0]["chain_id"] == "stuck"


# ── Структура mlog-стороны ───────────────────────────────────────────────
def test_mlog_side_hooks_present():
    """Sequential персистится теми же chain_steps; /chain continue и
    авто-resume на месте (mlog-сторона, dept/chain.mlog + app.mlog)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chain_src = open(os.path.join(base, "dept", "chain.mlog"), encoding="utf-8").read()
    assert "pattern ResumeChainSteps" in chain_src
    assert 'INSERT INTO chain_steps' in chain_src          # persist before run
    assert "UPDATE chain_steps SET status='ok'" in chain_src   # persist after
    app_src = open(os.path.join(base, "app.mlog"), encoding="utf-8").read()
    assert "chain_auto_resume" in chain_src                 # авто-resume <1 ч (в chain.mlog)
    assert "CREATE TABLE IF NOT EXISTS chain_steps" in app_src
    assert "chain_expired" in app_src                       # ночная TTL-фаза
