#!/usr/bin/env python3
"""FO-025 tests: shadow-оценка моделей — канареечный роутинг с verifier-сравнением.

Наряд #112. Критерии «сделано, когда»:
- rate=0 → ноль shadow-вызовов; rate=1 → вызов есть, у пользователя ровно
  один ответ (основной результат идентичен);
- падение кандидата прозрачно для основного ответа;
- в trace_log парные записи (event='shadow', одинаковый pair_id);
- cost-строки раздельны (token_usage request_type='shadow' — вне бюджета FO-024);
- недельный отчёт собирается из trace_log (win-rate/дельты/рекомендация).
"""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo25-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy import shadow as sh  # noqa: E402
from proxy.core import _query, _TRACE_DIR  # noqa: E402
from proxy.providers import call_llm, _call_llm_impl  # noqa: E402


@pytest.fixture(autouse=True)
def clean_shadow():
    _query("DELETE FROM token_usage")
    _query("DELETE FROM audit_log WHERE action LIKE 'shadow%'")
    _query("DELETE FROM system_settings WHERE key LIKE 'shadow_%'")
    yield


def _set_shadow(dept, model, rate):
    cfg = json.dumps({"model": model, "rate": rate})
    _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
           (f"shadow_{dept}", cfg))


def _impl_ok(monkeypatch, reply="MAIN-REPLY", model="glm-4.6"):
    """Мокаем ТЕЛО call_llm (impl), зеркало должно остаться снаружи."""
    calls = {"n": 0}

    def fake_impl(dept, messages, model_override=None, combo=None, command='', depth=2, chat_id=None):
        calls["n"] += 1
        return {"reply": reply, "provider": "zai", "model": model,
                "tokens_in": 100, "tokens_out": 50}

    monkeypatch.setattr("proxy.providers._call_llm_impl", fake_impl)
    return calls


def _candidate_ok(monkeypatch, reply="CAND-REPLY"):
    calls = {"n": 0}

    def fake_single(provider, model, messages, dept="yana", max_tokens=4096, is_internal=False):
        calls["n"] += 1
        return {"reply": reply, "provider": provider, "model": model,
                "tokens_in": 80, "tokens_out": 40}

    monkeypatch.setattr("proxy.providers._call_single_provider", fake_single)
    return calls


def _candidate_boom(monkeypatch):
    def fake_single(provider, model, messages, dept="yana", max_tokens=4096, is_internal=False):
        raise RuntimeError("candidate provider down")
    monkeypatch.setattr("proxy.providers._call_single_provider", fake_single)


def _read_traces():
    recs = []
    d = Path(_TRACE_DIR)
    if not d.exists():
        return recs
    for tf in sorted(d.glob("llm_*.jsonl")):
        for line in tf.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return [r for r in recs if r.get("event") == "shadow"]


# ── Конфиг ───────────────────────────────────────────────────────────────
def test_config_missing_or_bad_means_off():
    assert sh.get_config("finance") is None
    _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('shadow_finance', 'not-json')")
    assert sh.get_config("finance") is None
    _set_shadow("finance", "glm-4.6", 0.0)  # rate 0 = выключено
    assert sh.get_config("finance") is None


# ── Гард-рейлы и поток ───────────────────────────────────────────────────
def test_rate_zero_means_no_shadow(monkeypatch):
    _set_shadow("finance", "glm-4.6", 0.0)
    calls = _impl_ok(monkeypatch)
    cand = _candidate_ok(monkeypatch)
    res = call_llm("finance", [{"role": "user", "content": "q"}])
    assert res["reply"] == "MAIN-REPLY"
    assert cand["n"] == 0  # rate=0 → ноль shadow-вызовов
    assert calls["n"] == 1


def test_rate_one_shadows_and_user_gets_one_answer(monkeypatch):
    _set_shadow("finance", "glm-4.6", 1.0)
    _impl_ok(monkeypatch)
    cand = _candidate_ok(monkeypatch)
    monkeypatch.setattr("proxy.shadow._score_safe", lambda p, c: 0.7)
    res = call_llm("finance", [{"role": "user", "content": "q"}])
    # ровно один ответ пользователю — основной, кандидат НЕ уходит наружу
    assert res["reply"] == "MAIN-REPLY"
    assert res["model"] == "glm-4.6"
    assert cand["n"] == 1  # дублированный вызов кандидату состоялся


def test_candidate_failure_transparent_for_main(monkeypatch):
    """Падение кандидата: основной ответ идентичен, диагностика — в след."""
    _set_shadow("finance", "glm-4.6", 1.0)
    _impl_ok(monkeypatch)
    _candidate_boom(monkeypatch)
    res = call_llm("finance", [{"role": "user", "content": "q"}])
    assert res["reply"] == "MAIN-REPLY"  # прозрачность
    assert res.get("budget_state") is None
    # shadow-ошибка помечена kind='shadow_error' (не дезинформирует FO-022)
    rows = _query("SELECT COUNT(*) AS c FROM error_log WHERE kind='shadow_error'", fetch=True)
    assert rows[0]["c"] >= 1


def test_paired_trace_records(monkeypatch):
    _set_shadow("finance", "glm-4.6", 1.0)
    _impl_ok(monkeypatch)
    _candidate_ok(monkeypatch)
    scores = {"n": 0}

    def fake_score(problem, candidate):
        scores["n"] += 1
        return 0.5 + 0.1 * scores["n"]

    monkeypatch.setattr(sh, "_score_safe", fake_score)
    call_llm("finance", [{"role": "user", "content": "q"}])
    recs = _read_traces()
    mains = [r for r in recs if r.get("side") == "main"]
    shadows = [r for r in recs if r.get("side") == "shadow"]
    assert mains and shadows, "парные записи должны быть"
    main_rec, shadow_rec = mains[-1], shadows[-1]
    assert main_rec["pair_id"] == shadow_rec["pair_id"]  # парность
    assert shadow_rec["gen_ai.request.model"] == "glm-4.6"
    assert shadow_rec["verifier_score"] is not None
    assert main_rec["verifier_score"] is not None


def test_candidate_cost_row_is_shadow_labeled(monkeypatch):
    """Кандидат — отдельная cost-строка request_type='shadow' (вне бюджета)."""
    _set_shadow("finance", "glm-4.6", 1.0)
    _impl_ok(monkeypatch)
    _candidate_ok(monkeypatch)
    monkeypatch.setattr(sh, "_score_safe", lambda p, c: 0.5)
    call_llm("finance", [{"role": "user", "content": "q"}])
    rows = _query("SELECT request_type, dept FROM token_usage WHERE model='glm-4.6'", fetch=True)
    shadow_rows = [r for r in rows if (r["request_type"] or "").startswith("shadow")]
    assert len(shadow_rows) == 1  # ровно одна строка кандидата, помеченная
    assert shadow_rows[0]["dept"] == "finance"


def test_no_config_no_shadow_no_calls(monkeypatch):
    calls = _impl_ok(monkeypatch)
    cand = _candidate_ok(monkeypatch)
    res = call_llm("finance", [{"role": "user", "content": "q"}])
    assert res["reply"] == "MAIN-REPLY"
    assert cand["n"] == 0


# ── Недельный отчёт ──────────────────────────────────────────────────────
def test_weekly_report_from_traces(monkeypatch):
    from proxy.core import app as flask_app
    _set_shadow("legal", "glm-4.6", 1.0)
    _impl_ok(monkeypatch)
    _candidate_ok(monkeypatch)

    def fake_score(problem, candidate):
        # кандидат чуть лучше основной модели на этом контуре
        return 0.9 if candidate == "CAND-REPLY" else 0.5

    monkeypatch.setattr(sh, "_score_safe", fake_score)
    call_llm("legal", [{"role": "user", "content": "q"}])

    with flask_app.test_client() as c:
        resp = c.get("/api/shadow/report",
                     headers={"Authorization": "Bearer test-secret-123"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["total_pairs"] >= 1
        legal = next(d for d in data["depts"] if d["dept"] == "legal")
        assert legal["pairs"] >= 1
        assert legal["candidate_model"] == "glm-4.6"
        assert legal["win_rate"] == 1.0  # кандидат выиграл все пары
        assert legal["recommendation"] in ("GO", "KEEP-TESTING", "NO-GO")
