#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #588: ночь и утро — OOM-гигиена, дубли, пустые части, бриф, алерт QA, имя ЛЗ.

Гварды:
- mlog-сценарий test_n588_night.mlog (A.3 resume-гварды, B.1 резка/пустые части) — ALL PASS;
- B.2: утренний бриф пишется в dialog_history → ответ Админа 07:25 его находит;
- B.3: _is_night_msk (22:00–06:59 MSK); алерт «ниже порога» ≠ «Регрессия»;
  ночью — в owner_outbox (тишина #550), днём — сразу в Telegram;
- B.1: lz-daily deliver="none" не доставляет отчёт (ни outbox, ни Telegram),
  в ответе — счётчики скана для ночной одной строки;
- B.4: «Лаборатория Загадок» в коде не встречается.
"""
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n588-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')
os.environ.setdefault('CRON_SECRET', 'test-cron-secret')

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import routes_sched, routes_tail, lz_github  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
API_AUTH = {'Authorization': 'Bearer test-secret-123'}
BINARY = REPO_ROOT / "bin" / "mlog"
SCENARIO = REPO_ROOT / "test_n588_night.mlog"


def _client():
    return flask_app.test_client()


# ──────────────────────────── mlog-сценарий (A.3/B.1) ────────────────────────────

def _run_scenario():
    try:
        BINARY.chmod(0o755)
    except OSError:
        pass
    # сценарий держит db в /tmp/n588-test (заголовок test_n588_night.mlog:
    # «Запуск: rm -rf /tmp/n588-test && mkdir -p /tmp/n588-test») — на чистом
    # раннере CI каталога нет, connect падает («unable to open database file»,
    # прогон 39674738541). Готовим каталог честно и идемпотентно.
    import shutil
    shutil.rmtree("/tmp/n588-test", ignore_errors=True)
    os.makedirs("/tmp/n588-test", exist_ok=True)
    return subprocess.run(
        [str(BINARY), "run", str(SCENARIO)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
        env={**os.environ, "OWNER_TELEGRAM_ID": "1", "CRON_SECRET": "x"},
    )


def test_scenario_all_marks_pass():
    proc = _run_scenario()
    assert proc.returncode == 0, f"бинарь упал: rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    out = proc.stdout
    assert "ALL PASS" in out, f"нет ALL PASS:\n{out[-2000:]}"
    assert "=false" not in out, f"есть провалы:\n{out[-2000:]}"
    # ключевые метки наряда
    for mark in ("c1_three_chunks", "c2_no_loss_9000", "c3_two_chunks", "c4_empty",
                 "d1_begin_acquired_then_done", "d2_new_then_done",
                 "f1_no_empty_parts", "f2_dup_guard"):
        assert f"{mark}=true" in out, f"нет метки {mark}\n{out[-2000:]}"


# ──────────────────────────── B.2: бриф виден Админу ────────────────────────────

@pytest.fixture()
def clean_dialog(monkeypatch):
    _query("DELETE FROM dialog_history WHERE dept='yana' AND role='assistant' AND content LIKE '%ТЕСТ-БРИФ%'")
    _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")
    # №596 A.3: обход «BRIEF-1 доп.» удалён из брифа — scheduler_lz_daily_core
    # больше не импортируется в routes_sched, реальный lz-скан из брифа
    # больше не достижим (гвард — tests/test_n596_timeouts_lz_once.py)
    yield
    _query("DELETE FROM dialog_history WHERE dept='yana' AND role='assistant' AND content LIKE '%ТЕСТ-БРИФ%'")
    _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")


def test_b2_brief_written_to_dialog_history(monkeypatch, clean_dialog):
    brief = "ТЕСТ-БРИФ Яны: сводка на утро."
    monkeypatch.setattr(routes_sched, "call_llm", lambda dept, messages: {"reply": brief, "provider": "mock", "tokens_in": 0, "tokens_out": 0})
    sent = {}
    monkeypatch.setattr(routes_sched, "_tg_send_formatted", lambda chat_id, text, dept=None: sent.setdefault("text", text) or 42)
    r = _client().post("/scheduler/morning-brief", headers=API_AUTH, json={"owner_id": "12345"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"
    rows = _query("SELECT content, dept, role, chat_id FROM dialog_history WHERE dept='yana' AND role='assistant' AND content LIKE '%ТЕСТ-БРИФ%'", fetch=True)
    assert rows, "бриф не записан в dialog_history"
    # к брифу добавляются дословные строки (ключи/FORGE) — проверяем начало
    assert rows[0]["content"].startswith(brief)
    assert rows[0]["role"] == "assistant"
    assert rows[0]["chat_id"] == "12345"


def test_b2_admin_reply_finds_brief(monkeypatch, clean_dialog):
    brief = "ТЕСТ-БРИФ Яны: сводка на утро для Админа."
    _query("INSERT INTO dialog_history (dept, chat_id, role, content) VALUES ('yana', '12345', 'assistant', ?)", (brief,))
    monkeypatch.setattr(routes_sched, "call_llm", lambda dept, messages: {"reply": "Комментарий Админа к брифу.", "provider": "mock", "tokens_in": 0, "tokens_out": 0})
    tg = {"calls": 0}
    monkeypatch.setattr(routes_sched, "_tg_send_message", lambda chat_id, text: tg.__setitem__("calls", tg["calls"] + 1) or 1)
    monkeypatch.setattr(routes_sched, "_tg_send_formatted", lambda chat_id, text, dept=None: tg.__setitem__("calls", tg["calls"] + 1) or 1)
    r = _client().post("/scheduler/admin-morning-reply", headers=API_AUTH, json={"owner_id": "12345"})
    d = r.get_json()
    assert d.get("status") == "ok"
    # бриф найден: фолбэк-ветка «не найден свежий отчёт Яны» НЕ сработала
    assert d.get("note") != "no_yana_brief"
    assert tg["calls"] >= 1


# ──────────────────────────── B.3: алерт качества ────────────────────────────

def test_is_night_msk_units():
    utc = timezone.utc
    assert routes_tail._is_night_msk(datetime(2026, 10, 21, 20, 0, tzinfo=utc)) is True   # 23:00 MSK
    assert routes_tail._is_night_msk(datetime(2026, 10, 21, 19, 0, tzinfo=utc)) is True   # 22:00 MSK
    assert routes_tail._is_night_msk(datetime(2026, 10, 21, 18, 59, tzinfo=utc)) is False  # 21:59 MSK
    assert routes_tail._is_night_msk(datetime(2026, 10, 21, 10, 0, tzinfo=utc)) is False  # 13:00 MSK
    assert routes_tail._is_night_msk(datetime(2026, 10, 21, 3, 59, tzinfo=utc)) is True   # 06:59 MSK
    assert routes_tail._is_night_msk(datetime(2026, 10, 21, 4, 0, tzinfo=utc)) is False   # 07:00 MSK


def _golden_summary(avg, prev, failed=0):
    return {"dept": "qa", "avg_score": avg, "previous_avg": prev, "failed": failed,
            "results": [{"task": "worst-task", "score": avg - 0.1}]}


@pytest.fixture()
def clean_outbox():
    _query("DELETE FROM owner_outbox WHERE source='golden-evals'")
    yield
    _query("DELETE FROM owner_outbox WHERE source='golden-evals'")


def _patch_golden(monkeypatch, avg, prev, night):
    monkeypatch.setattr(routes_tail, "_golden_load", lambda dept: [{"task": "t", "prompt": "p"}])
    monkeypatch.setattr(routes_tail, "_golden_run_dept", lambda dept, tasks: _golden_summary(avg, prev))
    monkeypatch.setattr(routes_tail, "_golden_previous_avg", lambda dept: prev)
    monkeypatch.setattr(routes_tail, "_is_night_msk", lambda: night)
    tg = {"calls": 0, "text": ""}
    monkeypatch.setattr(routes_tail, "_tg_send_message", lambda chat_id, text: tg.__setitem__("calls", tg["calls"] + 1) or tg.__setitem__("text", text))
    return tg


def test_b3_below_threshold_night_goes_to_outbox(monkeypatch, clean_outbox):
    """Прод-кейс 21.10: yana 0.54 (было 0.54) — «ниже порога», НЕ «Регрессия»; ночью — в outbox."""
    tg = _patch_golden(monkeypatch, avg=0.54, prev=0.54, night=True)
    r = _client().post(f"/scheduler/golden-evals?secret={os.environ['CRON_SECRET']}", headers=API_AUTH, json={"depts": ["qa"]})
    assert r.status_code == 200
    rows = _query("SELECT text FROM owner_outbox WHERE source='golden-evals'", fetch=True)
    assert rows, "ночной алерт не попал в outbox"
    text = rows[0]["text"]
    assert "ниже порога" in text and "0.54" in text
    assert "Регрессия" not in text
    assert tg["calls"] == 0, "ночью Telegram-отправка запрещена (#550)"


def test_b3_regression_day_sends_immediately(monkeypatch, clean_outbox):
    tg = _patch_golden(monkeypatch, avg=0.39, prev=0.54, night=False)
    r = _client().post(f"/scheduler/golden-evals?secret={os.environ['CRON_SECRET']}", headers=API_AUTH, json={"depts": ["qa"]})
    assert r.status_code == 200
    assert tg["calls"] == 1 and "Регрессия" in tg["text"] and "было 0.54" in tg["text"]
    rows = _query("SELECT COUNT(*) AS c FROM owner_outbox WHERE source='golden-evals'", fetch=True)
    assert rows[0]["c"] == 0, "днём алерт не должен попадать в outbox"


def test_b3_healthy_dept_no_alert(monkeypatch, clean_outbox):
    tg = _patch_golden(monkeypatch, avg=0.85, prev=0.84, night=False)
    r = _client().post(f"/scheduler/golden-evals?secret={os.environ['CRON_SECRET']}", headers=API_AUTH, json={"depts": ["qa"]})
    assert r.status_code == 200
    assert tg["calls"] == 0
    assert r.get_json()["totals"]["regressions"] == 0


# ──────────────────────────── B.1: lz-daily deliver="none" ────────────────────────────

def test_b1_lz_daily_deliver_none(monkeypatch):
    monkeypatch.setattr(lz_github, "_build_github_queries", lambda: ["q"])
    monkeypatch.setattr(lz_github, "_github_search", lambda q, per_page=3: [])
    monkeypatch.setattr(lz_github, "_github_releases", lambda repo: [])
    monkeypatch.setattr(lz_github.time, "sleep", lambda s: None)
    monkeypatch.setattr(lz_github, "call_llm", lambda *a, **kw: {"reply": "анализ-стаб", "provider": "mock", "tokens_in": 0, "tokens_out": 0})
    tg = {"calls": 0}
    monkeypatch.setattr(lz_github, "_tg_send_message", lambda *a, **kw: tg.__setitem__("calls", tg["calls"] + 1))
    monkeypatch.setattr(lz_github, "_tg_send_report_with_button", lambda *a, **kw: tg.__setitem__("calls", tg["calls"] + 1))
    before = _query("SELECT COUNT(*) AS c FROM owner_outbox WHERE source='lz-daily'", fetch=True)[0]["c"]
    r = _client().post("/scheduler/lz-daily", headers=API_AUTH, json={"owner_id": "12345", "deliver": "none"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok"
    # счётчики скана в ответе — источник одной строки в ночном блоке
    assert "repos_found" in d["scan"] and "releases_found" in d["scan"]
    # НИ одной доставки: ни outbox, ни Telegram
    after = _query("SELECT COUNT(*) AS c FROM owner_outbox WHERE source='lz-daily'", fetch=True)[0]["c"]
    assert after == before, "deliver=none не должен писать в outbox"
    assert tg["calls"] == 0, "deliver=none не должен отправлять в Telegram"


# ──────────────────────────── B.4: имя ЛЗ ────────────────────────────

def test_b4_no_lz_old_name():
    for rel in ("proxy/lz_github.py", "dept/lz.mlog"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "Загадок" not in src, f"старое имя ЛЗ в {rel}"
        assert "Лаборатория знаний" in src or "Лаборатории знаний" in src, f"нет нового имени в {rel}"
