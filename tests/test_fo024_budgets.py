#!/usr/bin/env python3
"""FO-024 tests: enforcement бюджетов llm_proxy (soft/hard/stop per dept/day).

Наряд #111. Критерии «сделано, когда»:
- расход 80% → soft-алерт (ровно один раз), 100% → эконом-модель, 120% →
  стоп; admin и аварийные команды живы всегда;
- ролловер дня снимает стопы (расход «вчера» не считается);
- per-dept оверрайд перекрывает глобальный daily_budget;
- счётчик честен на пустом дне и после инвалидации по записи token_usage;
- shadow-метка (FO-025) не считается в бюджет;
- audit-след полный: budget_soft / budget_hard / budget_stop.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['TELEGRAM_BOT_TOKEN'] = 'test-bot-token'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo24-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy import budget as bud  # noqa: E402
from proxy.core import _query  # noqa: E402


@pytest.fixture(autouse=True)
def clean_budget():
    _query("DELETE FROM token_usage")
    _query("DELETE FROM audit_log WHERE action LIKE 'budget_%'")
    _query("DELETE FROM system_settings WHERE key LIKE 'daily_budget%' OR key LIKE 'budget_soft_alert%'")
    bud.invalidate()
    yield
    bud.invalidate()


def _usage(dept, cost, when=None, request_type=None):
    ts = when or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at,request_type) "
           "VALUES ('mock','mock','10','10',?,?,?,?)",
           (str(cost), dept, ts, request_type))
    bud.invalidate()


def _set_limit(dept, value):
    key = "daily_budget" if dept is None else f"daily_budget_{dept}"
    _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))


# ── Счётчик ──────────────────────────────────────────────────────────────
def test_empty_day_spends_zero():
    assert bud.spent_today() == 0.0
    assert bud.spent_today("legal") == 0.0
    assert bud.probe("legal")["state"] == "unlimited"


def test_counter_reflects_usage_after_invalidation():
    _usage("legal", 0.3)
    assert bud.spent_today("legal") == pytest.approx(0.3)
    _usage("legal", 0.2)
    assert bud.spent_today("legal") == pytest.approx(0.5)
    assert bud.spent_today("finance") == 0.0  # per-dept изоляция счётчика


def test_shadow_rows_not_counted():
    _usage("legal", 0.5, request_type="shadow_canary")
    assert bud.spent_today("legal") == 0.0
    _usage("legal", 0.5, request_type="normal")
    assert bud.spent_today("legal") == pytest.approx(0.5)


# ── Оверрайды и лимиты ───────────────────────────────────────────────────
def test_dept_override_beats_global():
    _set_limit(None, 10.0)          # глобальный
    _set_limit("legal", 1.0)        # оверрайд департамента
    assert bud.limit_for("legal") == 1.0
    assert bud.limit_for("finance") == 10.0
    assert bud.limit_for("admin") == 10.0


def test_no_limit_means_unlimited():
    assert bud.limit_for("legal") == 0.0
    assert bud.probe("legal")["state"] == "unlimited"


# ── Пороги: soft / hard / stop ───────────────────────────────────────────
def test_soft_alert_exactly_once(monkeypatch):
    _set_limit("legal", 1.0)
    sent = []
    monkeypatch.setattr("proxy.telegram._tg_send_message", lambda cid, text: sent.append(text))

    _usage("legal", 0.5)
    st = bud.enforce("legal")
    assert st["state"] == "ok"

    _usage("legal", 0.31)  # 0.81 → soft
    st = bud.enforce("legal")
    assert st["state"] == "soft"
    assert st["alerted"] is True
    assert len(sent) == 1

    # повторный вызов в тот же день — алерт не дублируется, но state остаётся
    st = bud.enforce("legal")
    assert st["state"] == "soft"
    assert st["alerted"] is False
    assert len(sent) == 1

    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE action='budget_soft' AND dept='legal'", fetch=True)
    assert rows[0]["c"] == 2  # audit пишется на каждый enforce (след полный)


def test_hard_returns_econom_model():
    _set_limit("legal", 1.0)
    _usage("legal", 1.01)  # >100%
    st = bud.enforce("legal")
    assert st["state"] == "hard"
    assert st["econom_model"]
    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE action='budget_hard' AND dept='legal'", fetch=True)
    assert rows[0]["c"] == 1


def test_call_llm_hard_slices_heavy_model(monkeypatch):
    """hard (100%..120%) → модель департамента срезана до эконом (последний элемент цепи)."""
    _set_limit("dev", 1.0)
    _usage("dev", 1.1)

    captured = {}

    def fake_single(provider, model, messages, dept="yana", max_tokens=4096, is_internal=False):
        captured["model"] = model
        return {"reply": "ok", "provider": provider, "model": model,
                "tokens_in": 1, "tokens_out": 1}

    monkeypatch.setattr("proxy.providers._call_single_provider", fake_single)
    from proxy.providers import call_llm
    res = call_llm("dev", [{"role": "user", "content": "hi"}],
                   model_override="glm-4.6", command="")
    assert res.get("budget_state") != "stop"
    assert captured["model"] == bud.econom_model_for("dev")


def test_stop_blocks_dept_but_not_admin_or_emergency():
    _set_limit("legal", 1.0)
    _usage("legal", 1.25)  # ≥120%
    st = bud.enforce("legal")
    assert st["state"] == "stop"
    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE action='budget_stop' AND dept='legal'", fetch=True)
    assert rows[0]["c"] == 1

    # admin не стопится никогда
    st_admin = bud.enforce("admin", command="")
    assert st_admin["state"] == "ok" and st_admin.get("exempt") is True
    # аварийные команды не стопятся
    st_emerg = bud.enforce("legal", command="/budget")
    assert st_emerg["state"] == "ok" and st_emerg.get("exempt") is True


def test_call_llm_stop_returns_honest_refusal(monkeypatch):
    _set_limit("dev", 1.0)
    _usage("dev", 1.3)
    called = {"n": 0}

    def fake_single(*a, **kw):
        called["n"] += 1
        return {"reply": "x", "provider": "p", "model": "m", "tokens_in": 1, "tokens_out": 1}

    monkeypatch.setattr("proxy.providers._call_single_provider", fake_single)
    from proxy.providers import call_llm
    res = call_llm("dev", [{"role": "user", "content": "hi"}], command="")
    assert res["budget_state"] == "stop"
    assert "Budget" in res["reply"]
    assert called["n"] == 0  # до провайдера дело не дошло


def test_rollover_clears_stop():
    """Расход «вчера» не считается: ролловер дня снимает стоп."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    _set_limit("legal", 1.0)
    _usage("legal", 5.0, when=yesterday)
    st = bud.enforce("legal")
    assert st["state"] in ("unlimited", "ok") or st["state"] != "stop"
    assert st["spent"] == pytest.approx(0.0)


# ── /api/budget/status ───────────────────────────────────────────────────
def test_status_snapshot_shape():
    _set_limit("legal", 2.0)
    _usage("legal", 1.6)  # 80% → soft
    snap = bud.status_snapshot()
    assert snap["date_utc"]
    assert "spent" in snap["global"] and "limit" in snap["global"]
    legal = next(d for d in snap["depts"] if d["dept"] == "legal")
    assert legal["spent"] == pytest.approx(1.6)
    assert legal["limit"] == 2.0
    assert legal["state"] == "soft"
    assert isinstance(snap["econom"], list)


def test_status_endpoint_no_side_effects(client=None):
    """HTTP-эндпоинт отвечает ok и не пишет audit (читающий)."""
    _set_limit("legal", 2.0)
    _usage("legal", 1.6)
    from proxy.core import app as flask_app
    with flask_app.test_client() as c:
        resp = c.get("/api/budget/status",
                     headers={"Authorization": "Bearer test-secret-123"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        legal = next(d for d in data["depts"] if d["dept"] == "legal")
        assert legal["state"] == "soft"
    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE action LIKE 'budget_%'", fetch=True)
    assert rows[0]["c"] == 0  # чтение не создаёт enforcement-события
