#!/usr/bin/env python3
"""FO-026 tests: fan-out + debate для /chain — параллельные департаменты и судья.

Наряд #113. Критерии «сделано, когда»:
- гард-рейлы enforced: cap 3 департамента parallel (4-й — громкий отказ),
  debate ровно 2; раунды ≤ 2;
- parallel быстрее wall-clock последовательного на той же паре;
- упавший департамент не валит группу — судья работает на оставшихся
  с громкой пометкой «ответов N/M»;
- оба вклада цитируются судьёй (промпт судьи содержит вклады + group_id);
- sequential-путь не изменился (1-в-1: диспетчеризация вынесена в
  ChainDispatchDept, поведение ExecuteChain прежнее — golden CI остаётся).
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo26-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
import proxy.chain_parallel as cp  # noqa: E402
from proxy.core import app as flask_app, _query  # noqa: E402


@pytest.fixture(autouse=True)
def clean_chain():
    _query("DELETE FROM audit_log WHERE action LIKE 'chain_%'")
    yield


@pytest.fixture()
def client():
    with flask_app.test_client() as c:
        yield c


AUTH = {"Authorization": "Bearer test-secret-123"}


def _fanout(client, mode, depts, query="оценка сделки"):
    return client.post("/chain/fanout", headers=AUTH,
                       json={"mode": mode, "depts": depts, "query": query,
                             "chat_id": "0"})


def _mock_steps(monkeypatch, lat=0.05, fail_depts=(), capture=None, fail_round2_depts=()):
    """Мок шага департамента: задержка + опциональные падения (по депту или во 2-м раунде)."""
    def fake_invoke(dept, query, chat_id, group_id, round_no=1, peer_context=None):
        time.sleep(lat)
        if dept in fail_depts or (round_no == 2 and dept in fail_round2_depts):
            raise RuntimeError(f"dept {dept} down")
        if capture is not None:
            capture.append({"dept": dept, "round": round_no, "peer": peer_context,
                            "group_id": group_id})
        return f"ОТВЕТ-{dept}-R{round_no}"

    monkeypatch.setattr(cp, "_invoke_step", fake_invoke)


def _mock_judge(monkeypatch, prompts=None):
    """Мок LLM судьи: захватывает ПОЛНЫЙ промпт (вклады + пометка деградации).
    Реальный _judge выполняется — audit chain_judge с group_id пишется."""
    def fake_call_llm(dept, messages, **kw):
        assert dept == "admin"
        if prompts is not None:
            prompts.append(messages[0]["content"])
        return {"reply": "ВЕРДИКТ: синтез вкладов (тест)", "provider": "mock",
                "model": "mock", "tokens_in": 1, "tokens_out": 1}

    monkeypatch.setattr("proxy.providers.call_llm", fake_call_llm)


# ── Гард-рейлы: caps enforced ────────────────────────────────────────────
def test_fourth_department_is_loud_rejection(client):
    resp = _fanout(client, "parallel", ["qa", "legal", "finance", "dev"])
    assert resp.status_code == 400
    assert "3" in resp.get_json()["message"]


def test_debate_third_department_is_loud_rejection(client):
    resp = _fanout(client, "debate", ["qa", "legal", "finance"])
    assert resp.status_code == 400
    assert "2" in resp.get_json()["message"]


def test_unknown_mode_rejected(client):
    resp = _fanout(client, "mob", ["qa", "legal"])
    assert resp.status_code == 400


def test_single_department_rejected(client):
    resp = _fanout(client, "parallel", ["qa"])
    assert resp.status_code == 400


# ── Parallel: wall-clock + цитирование + group_id ────────────────────────
def test_parallel_faster_than_sequential_wallclock(client, monkeypatch):
    """2 департамента по 0.4 с: параллельно ≈ 0.4 с, последовательно было бы 0.8 с."""
    _mock_steps(monkeypatch, lat=0.4)
    _mock_judge(monkeypatch)
    started = time.monotonic()
    resp = _fanout(client, "parallel", ["qa", "legal"])
    wall = time.monotonic() - started
    assert resp.status_code == 200
    assert wall < 0.75, f"wall-clock {wall:.2f}s — фанаут не параллелен"


def test_parallel_judge_sees_both_contributions(client, monkeypatch):
    prompts = []
    _mock_steps(monkeypatch, lat=0.01)
    _mock_judge(monkeypatch, prompts=prompts)
    resp = _fanout(client, "parallel", ["qa", "legal"])
    assert resp.status_code == 200
    assert len(prompts) == 1
    # оба вклада цитируются судьёй (в промпте с именами департаментов)
    assert "=== Вклад qa ===" in prompts[0]
    assert "ОТВЕТ-qa-R1" in prompts[0]
    assert "=== Вклад legal ===" in prompts[0]
    assert "ОТВЕТ-legal-R1" in prompts[0]


def test_parallel_degradation_one_dept_down(client, monkeypatch):
    """Упавший департамент не валит группу: судья на оставшемся + пометка."""
    prompts = []
    _mock_steps(monkeypatch, lat=0.01, fail_depts=("legal",))
    _mock_judge(monkeypatch, prompts=prompts)
    resp = _fanout(client, "parallel", ["qa", "legal"])
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["failed"] == ["legal"]
    assert [a["dept"] for a in data["answers"]] == ["qa"]
    # громкая пометка деградации: и в промпте судьи, и в финале
    assert "ответов 1/2" in prompts[0]
    assert "не ответили" in data["judge"]


def test_all_depts_down_is_loud_error(client, monkeypatch):
    _mock_steps(monkeypatch, fail_depts=("qa", "legal"))
    resp = _fanout(client, "parallel", ["qa", "legal"])
    assert resp.status_code == 502


def test_group_id_in_audit_trail(client, monkeypatch):
    _mock_steps(monkeypatch, lat=0.01)
    _mock_judge(monkeypatch)
    resp = _fanout(client, "parallel", ["qa", "legal"])
    gid = resp.get_json()["group_id"]
    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE details LIKE ?",
                  (f"%{gid}%",), fetch=True)
    assert rows[0]["c"] >= 2  # fanout_start + judge — одна сессия в трейсах


# ── Debate: раунды и peer-контекст ──────────────────────────────────────
def test_debate_two_rounds_with_peer_context(client, monkeypatch):
    steps = []
    _mock_steps(monkeypatch, lat=0.01, capture=steps)
    _mock_judge(monkeypatch)
    resp = _fanout(client, "debate", ["qa", "legal"])
    assert resp.status_code == 200
    # раунд 1: 2 шага без peer; раунд 2: 2 шага с peer-контекстом
    r1 = [s for s in steps if s["round"] == 1]
    r2 = [s for s in steps if s["round"] == 2]
    assert len(r1) == 2 and len(r2) == 2  # ≤ 2 раундов enforced
    assert all(s["peer"] is None for s in r1)
    qa_r2 = next(s for s in r2 if s["dept"] == "qa")
    assert "ОТВЕТ-legal-R1" in qa_r2["peer"]  # видит ответ коллеги
    # единый group_id на всю группу
    assert len({s["group_id"] for s in steps}) == 1


def test_debate_fallback_to_round1_answer(client, monkeypatch):
    steps = []
    prompts = []
    # legal отвечает в раунде 1, но падает во 2-м
    _mock_steps(monkeypatch, lat=0.01, fail_round2_depts=("legal",), capture=steps)
    _mock_judge(monkeypatch, prompts=prompts)
    resp = _fanout(client, "debate", ["qa", "legal"])
    assert resp.status_code == 200
    data = resp.get_json()
    answers = {a["dept"]: a["answer"] for a in data["answers"]}
    # legal упал во 2-м раунде, но ответ 1-го раунда попал к судье с пометкой
    assert "ОТВЕТ-legal-R1" in answers["legal"]
    assert "не дал" in answers["legal"]
    assert "ОТВЕТ-legal-R1" in prompts[0]  # судья видит его вклад


# ── Sequential не изменился (1-в-1) ─────────────────────────────────────
def test_sequential_path_untouched():
    """Структура sequential-пути сохранена: ExecuteChain и старый парсинг
    /chain без mode остались в app.mlog/dept/chain.mlog (golden-регрессия
    прогоняется CI-джобой FO-005)."""
    import re
    app_src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app.mlog"), encoding="utf-8").read()
    # mode-префикс обрабатывается ДО sequential-ветки
    assert 'if starts_with(trimmed_rest, "parallel ")' in app_src
    assert 'ExecuteChain(dept_chain, query, chat_id)' in app_src
    # диспетчеризация единая
    chain_src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "dept", "chain.mlog"), encoding="utf-8").read()
    assert "pattern ChainDispatchDept" in chain_src
    assert "let step_result = ChainDispatchDept(dept, query, chat_id)" in chain_src
    # старое поведение — обработчики вызываются 1-в-1
    for h in ("HandleYana", "HandleLegal", "HandleDev"):
        assert f"{h}(query, chat_id)" in chain_src
