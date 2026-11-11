#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #706 QA-1 (P2): evals=FAIL в night-tick — причины неотличимы.

Прод-факт 11.11: night-tick принёс «evals=FAIL» без причины; прод 22.10 —
«evals=FAIL при живом прогоне» (таймаут поллинга). В dept/scheduler.mlog
evals_state = "FAIL" по умолчанию, ok — только при state=done: старт без
job_id, задание failed (с готовым error!), таймаут поллинга 25 мин — всё
молча даёт «evals=FAIL»; job_id нигде не логируется. В Python
(_golden_evals_impl) исключение одного департамента роняло весь фоновый
job → state=failed → ночь видела только «evals=FAIL».

Здесь:
- A.3 (unit): битый golden-JSON одного департамента / исключение прогона —
  оба департамента в results, impl не падает, алерт — «Прогон упал: …»;
- A.1/A.2 (структурные, идиома test_n485): evals-сегмент NightTickSlot
  различает failed/timeout/старт; причина — в строке отчёта
  «evals=FAIL(<причина>)»; AuditLog с job_id/state/причиной — в обеих
  ветках, под TryVal; сравнения недоверенных строк — redact-fingerprint;
- живой прогон (харнесс #687): мок статуса golden-задания →
  {"status":"failed","error":"boom n706"} → в owner_outbox строка
  night-tick содержит «evals=FAIL(…boom n706…)», фаза не роняет тик.

Мутационный самотест: возврат безликого «evals=FAIL», потеря ветки
failed/timeout, аудит только в ok-ветке — каждый краснеет.
"""
import os
import re
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')
os.environ.setdefault('CRON_SECRET', 'cron-test-secret')

SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")


def _code_lines(seg: str) -> list:
    """Некомментарные строки (упоминания в комментариях не считаются)."""
    return [l for l in seg.splitlines() if not l.strip().startswith("//")]


def _night_tick_seg(src: str) -> str:
    """Тело NightTickSlot: от объявления до следующего 'pattern '."""
    decl = "pattern NightTickSlot()"
    start = src.index(decl)
    rest = src[start + len(decl):]
    nxt = rest.find("\npattern ")
    return rest[:nxt] if nxt != -1 else rest


# ── A.3 (unit): устойчивость _golden_evals_impl по департаментам ──

class TestGoldenImplResilience:
    def _ok_summary(self, dept, avg=0.9):
        return {"dept": dept, "avg_score": avg, "failed": 0,
                "tasks_total": 1, "results": [{"task": "t1", "score": avg}]}

    def test_broken_golden_json_one_dept(self, monkeypatch):
        """Битый JSON одного департамента + валидный другой: оба в results,
        impl не падает, алерт — «Прогон упал» (не «качество ниже порога»)."""
        import llm_proxy  # noqa: F401 — инициализация env раньше routes_tail
        import proxy.routes_tail as _rt
        import llm_verifier

        sent = []
        monkeypatch.setattr(_rt, "_tg_send_message", lambda cid, text, **kw: sent.append(text) or "ok")
        monkeypatch.setattr(_rt, "_golden_load",
                            lambda dept: (_ for _ in ()).throw(ValueError("Expecting value: broken json"))
                            if dept == "osp" else [{"id": "y1", "input": "q", "expect": {}}])
        monkeypatch.setattr(_rt, "_golden_run_dept",
                            lambda dept, tasks: self._ok_summary(dept))
        monkeypatch.setattr(_rt, "_golden_previous_avg", lambda dept: 0.9)
        monkeypatch.setattr(_rt, "_is_night_msk", lambda: False)
        monkeypatch.setattr(llm_verifier, "score", lambda p, c, criteria="": 0.9)

        out = _rt._golden_evals_impl(["osp", "yana"])
        by_dept = {r["dept"]: r for r in out["results"]}
        assert "osp" in by_dept and "yana" in by_dept, "оба департамента должны быть в results"
        assert "error" in by_dept["osp"], "упавший департамент — с 'error'"
        assert "golden load failed" in by_dept["osp"]["error"]
        assert "avg_score" in by_dept["yana"], "живой департамент — с avg_score"
        assert out["status"] == "ok", "impl не упал целиком"
        assert sent and "Прогон упал: osp" in sent[0], sent
        assert "Качество ниже порога" not in sent[0], "упавший — не «качество ниже порога»"

    def test_run_crash_one_dept(self, monkeypatch):
        """Исключение прогона одного департамента: оба в results, алерт
        «Прогон упал», живой департамент выполняется."""
        import llm_proxy  # noqa: F401
        import proxy.routes_tail as _rt

        sent = []
        monkeypatch.setattr(_rt, "_tg_send_message", lambda cid, text, **kw: sent.append(text) or "ok")

        def fake_load(dept):
            return [{"id": "t1", "input": "q", "expect": {}}]

        def fake_run(dept, tasks):
            if dept == "osp":
                raise RuntimeError("call_llm down")
            return self._ok_summary(dept)

        monkeypatch.setattr(_rt, "_golden_load", fake_load)
        monkeypatch.setattr(_rt, "_golden_run_dept", fake_run)
        monkeypatch.setattr(_rt, "_golden_previous_avg", lambda dept: None)
        monkeypatch.setattr(_rt, "_is_night_msk", lambda: False)

        out = _rt._golden_evals_impl(["osp", "yana"])
        by_dept = {r["dept"]: r for r in out["results"]}
        assert "osp" in by_dept and "yana" in by_dept
        assert "run failed: call_llm down" in by_dept["osp"]["error"]
        assert "avg_score" in by_dept["yana"]
        assert out["status"] == "ok"
        assert sent and "Прогон упал: osp — run failed: call_llm down" in sent[0], sent


# ── A.1/A.2 (структурные гварды evals-сегмента NightTickSlot) ──

def _violations(src: str) -> list:
    v = []
    seg = "\n".join(_code_lines(_night_tick_seg(src)))
    # A.1: исходы различимы — ветки failed/timeout, причина в строке отчёта
    if '== redact("failed", "hash_only")' not in seg:
        v.append("A.1: нет ветки state=failed (задание упало — причина теряется)")
    if '== redact("timeout", "hash_only")' not in seg:
        v.append("A.1: нет ветки state=timeout (таймаут поллинга неотличим)")
    if '" evals=FAIL(" + evals_reason' not in seg:
        v.append("A.1: причина отсутствует в строке отчёта (безликое «evals=FAIL»)")
    if 'старт не удался' not in seg:
        v.append("A.1: нет причины для старта без job_id")
    # A.2: телеметрия в аудит в обеих ветках, с job/state
    n_audit = seg.count('AuditLog("cron_golden_evals"')
    if n_audit < 2:
        v.append(f"A.2: AuditLog cron_golden_evals встречается {n_audit} раз (< 2: обе ветки)")
    if 'TryVal(try AuditLog("cron_golden_evals"' not in seg:
        v.append("A.2: аудит cron_golden_evals не под TryVal (#569 A.4)")
    if '" state=FAIL reason=" +' not in seg:
        v.append("A.2: FAIL-ветка аудита без state/reason")
    if '" state=ok"' not in seg:
        v.append("A.2: ok-ветка аудита без state")
    if "job=\" + evals_job" not in seg:
        v.append("A.2: job_id не попадает в телеметрию аудита")
    return v


def test_n706_evals_segment_guards_green():
    """Все структурные гварды #706 зелёные на текущем dept/scheduler.mlog."""
    v = _violations(SCHED)
    assert not v, "нарушения гвардов #706:\n" + "\n".join(v)


# ── мутационный самотест: каждая мутация обязана краснеть ──

def test_mutation_faceless_fail():
    m = SCHED.replace('report = report + " evals=FAIL(" + evals_reason + ")"',
                      'report = report + " evals=FAIL"', 1)
    assert m != SCHED, "мутация не применилась"
    assert any("A.1" in x for x in _violations(m)), "безликий «evals=FAIL» не пойман"


def test_mutation_failed_branch_lost():
    m = SCHED.replace('if redact(ge_state, "hash_only") == redact("failed", "hash_only") then {',
                      'if redact(ge_state, "hash_only") == redact("never", "hash_only") then {', 1)
    assert m != SCHED, "мутация не применилась"
    assert any("failed" in x for x in _violations(m)), "потеря ветки failed не поймана"


def test_mutation_timeout_branch_lost():
    m = SCHED.replace('if redact(ge_state, "hash_only") == redact("timeout", "hash_only") then {',
                      'if redact(ge_state, "hash_only") == redact("never", "hash_only") then {', 1)
    assert m != SCHED, "мутация не применилась"
    assert any("timeout" in x for x in _violations(m)), "потеря ветки timeout не поймана"


def test_mutation_fail_audit_lost():
    m = SCHED.replace(
        'let _ = TryVal(try AuditLog("cron_golden_evals", "qa", "job=" + evals_job + " state=FAIL reason=" + evals_reason))\n'
        '      report = report + " evals=FAIL(" + evals_reason + ")"',
        'report = report + " evals=FAIL(" + evals_reason + ")"', 1)
    assert m != SCHED, "мутация не применилась"
    v = _violations(m)
    assert any("A.2" in x for x in v), "потеря аудита FAIL-ветки не поймана"


# ── живой прогон (харнесс #687): упавший golden-задание ──

@pytest.fixture(scope="module")
def upstream():
    """Мок фаз на 127.0.0.1:4000 — тот же сервер/порт, что у #687;
    в одной pytest-сессии модули идут последовательно, порт свободен
    (после teardown модуля #687) — поднимаем свою копию."""
    from tests.test_n687_night_slot import UpstreamHandler, UPSTREAM_PORT
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", UPSTREAM_PORT)) == 0:
            pytest.skip(f"порт {UPSTREAM_PORT} занят — в этом окружении мок не поднять")
    server = ThreadingHTTPServer(("127.0.0.1", UPSTREAM_PORT), UpstreamHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    yield UpstreamHandler.upstream
    server.shutdown()


def test_night_tick_evals_fail_with_reason(tmp_path, upstream):
    """Мок статуса golden-задания → {"status":"failed","error":"boom n706"}:
    night-tick содержит «evals=FAIL(…boom n706…)», тик не падает (night=ok
    в строке тика, безликого «evals=FAIL» нет)."""
    from tests.test_n687_night_slot import _run_night_scenario, _outbox_texts

    extra = {"GET /scheduler/golden-evals/status":
             (200, {"status": "failed", "error": "boom n706", "result": None})}
    for db_path, _proc in _run_night_scenario(tmp_path, upstream, extra_config=extra):
        tick = "\n".join(_outbox_texts(db_path, "night-tick"))
        assert "evals=FAIL(" in tick, "нет «evals=FAIL(<причина>)»:\n" + tick[-1500:]
        assert "boom n706" in tick, "причина из статуса задания не дошла:\n" + tick[-1500:]
        assert "задание failed" in tick, tick[-1500:]
        assert re.search(r"evals=FAIL(?!\()", tick) is None, "безликий «evals=FAIL» вернулся:\n" + tick[-1500:]
        assert "night=FAIL" not in tick, "фаза evals уронила весь тик:\n" + tick[-1500:]
