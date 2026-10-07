"""Наряд #486: ночная проверка ключей и провайдеров (key_health).

Манифест — INTEGRATIONS_REGISTRY + перепись census (метаданные из fdf7ae1);
валидация дешёвыми вызовами (таймаут ≤10 c, без платных токенов); НИ ОДНОГО
значения ключа в выводах; фаза ночного цикла (A.3), утренний раздел (A.4),
команда /admin keys и статус в Mini App (A.5).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-keyhealth-test-db')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
ROUTES_ADMIN = (REPO_ROOT / "proxy" / "routes_admin.py").read_text(encoding="utf-8")
ROUTES_SCHED = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")

from proxy import key_health  # noqa: E402
from proxy.core import INTEGRATIONS_REGISTRY, _query, init_db  # noqa: E402


def test_manifest_covers_registry_and_naryad():
    """A.1: манифест — один источник (реестр + перепись), метаданные на месте."""
    manifest_keys = [e["env_key"] for e in key_health.KEY_MANIFEST]
    assert len(manifest_keys) == len(set(manifest_keys)), "дубли в манифесте"
    reg_keys = {i["env_key"] for i in INTEGRATIONS_REGISTRY}
    assert reg_keys <= set(manifest_keys), f"в манифесте нет: {reg_keys - set(manifest_keys)}"
    for extra in ("TELEGRAM_BOT_TOKEN", "FRED_API_KEY", "ALPHAVANTAGE_API_KEY"):
        assert extra in manifest_keys, f"нет {extra} (наряд A.2/перепись env)"
    for e in key_health.KEY_MANIFEST:
        for field in ("label", "kind", "required", "sanctions_ok", "why", "how_link"):
            assert field in e, f"{e['env_key']}: нет поля {field}"


def test_sanctions_map_from_fdf7ae1():
    """Санкционная карта: ANTHROPIC/OpenAI — False, Telegram/DeepSeek — True (fdf7ae1)."""
    sanctions = {e["env_key"]: e["sanctions_ok"] for e in key_health.KEY_MANIFEST}
    assert sanctions["ANTHROPIC_API_KEY"] is False
    assert sanctions["OPENAI_API_KEY"] is False
    assert sanctions["TELEGRAM_BOT_TOKEN"] is True
    assert sanctions["DEEPSEEK_API_KEY"] is True


def test_no_key_values_in_output(monkeypatch):
    """Ни одного значения ключа в выводе check_all (гвард утечки)."""
    secret = "SECRETVALUE999-never-leak"
    monkeypatch.setattr(key_health, "_key_value", lambda env_key: secret)

    class FakeResp:
        status_code = 200
        def json(self):
            return {"data": [{"id": "x"}], "ok": True}

    monkeypatch.setattr(key_health.http_requests, "get", lambda *a, **k: FakeResp())
    summary = key_health.check_all()
    blob = json.dumps(summary, ensure_ascii=False)
    assert secret not in blob, "значение ключа утекло в итог проверки"
    assert "Bearer" not in blob, "заголовок авторизации не должен попадать в вывод"
    # и в тексте отчёта тоже
    text = key_health.format_report(summary)
    assert secret not in text


def test_status_mapping_by_http_code(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)

        class R:
            status_code = fake_get.code
            def json(self):
                return {"data": []}

        return R()

    monkeypatch.setattr(key_health.http_requests, "get", fake_get)
    for code, expected in ((200, "ok"), (401, "invalid"), (403, "invalid"),
                           (429, "quota"), (404, "unverified"), (503, "unreachable")):
        fake_get.code = code
        status, http_code, _ = key_health._run_check(
            "X", {"type": "openai_models", "url": "https://x/v1/models"}, "value")
        assert status == expected, f"HTTP {code}: got {status}, want {expected}"


def test_network_error_is_unreachable(monkeypatch):
    def boom(url, **kwargs):
        raise key_health.http_requests.ConnectionError("boom")

    monkeypatch.setattr(key_health.http_requests, "get", boom)
    status, http_code, detail = key_health._run_check(
        "X", {"type": "openai_models", "url": "https://x/v1/models"}, "value")
    assert status == "unreachable"
    # текст исключения requests может содержать URL — в деталях только класс
    assert "boom" not in detail and "https" not in detail


def test_deepseek_balance_quota(monkeypatch):
    ds = next(e for e in key_health.KEY_MANIFEST if e["env_key"] == "DEEPSEEK_API_KEY")

    class Resp:
        def __init__(self, body):
            self.status_code = 200
            self._b = body
        def json(self):
            return self._b

    def fake_get(url, **kwargs):
        if "balance" in url:
            return Resp({"is_available": False, "balance": "0.00"})
        return Resp({"data": [{"id": "deepseek-chat"}]})

    monkeypatch.setattr(key_health.http_requests, "get", fake_get)
    status, _, detail = key_health._run_check("DEEPSEEK_API_KEY", ds["check"], "value")
    assert status == "quota" and "is_available=false" in detail


def test_alphavantage_body_semantics(monkeypatch):
    av = next(e for e in key_health.KEY_MANIFEST if e["env_key"] == "ALPHAVANTAGE_API_KEY")
    cases = [
        ({"Global Quote": {"01. symbol": "SPY"}}, "ok"),
        ({"Information": "rate limit"}, "quota"),
        ({"Error Message": "invalid api key"}, "invalid"),
    ]
    for body, expected in cases:
        class R:
            status_code = 200
            def json(self):
                return body
        monkeypatch.setattr(key_health.http_requests, "get", lambda *a, **k: R())
        status, _, _ = key_health._run_check("ALPHAVANTAGE_API_KEY", av["check"], "value")
        assert status == expected, f"{list(body)}: {status} != {expected}"


def test_missing_key_and_unverified(monkeypatch):
    # пустой ключ -> missing (без сетевого вызова)
    monkeypatch.setattr(key_health, "_key_value", lambda env_key: "")
    r = key_health.check_entry(key_health.KEY_MANIFEST[0])
    assert r["status"] == "missing"
    # провайдер без дешёвой проверки -> unverified, не ok
    ym = next(e for e in key_health.KEY_MANIFEST if e["env_key"] == "YANDEX_MARKET_API_KEY")
    monkeypatch.setattr(key_health, "_key_value", lambda env_key: "value")
    r2 = key_health.check_entry(ym)
    assert r2["status"] == "unverified"


def test_night_phase_and_admin_command_guards():
    """A.3/A.5 (mlog-сторона): фаза ночи, команда /admin keys, help."""
    assert "admin/keys/night-check" in APP, "NightSlot не вызывает фазу «Ключи»"
    assert "Phase 5: Ключи и провайдеры" in APP
    assert 'query == "keys"' in APP, "команды /admin keys нет в диспетчере"
    help_line = [l for l in APP.splitlines() if "Admin commands" in l][0]
    assert "/keys" in help_line, "/keys нет в справке /admin"
    # python-сторона: эндпоинты и утренняя строка
    assert "key_health_status" in ROUTES_ADMIN, "нет чтения статусов для Mini App"
    assert "/admin/keys/run" in ROUTES_ADMIN and "/admin/keys/night-check" in ROUTES_ADMIN
    assert "build_morning_line" in ROUTES_SCHED, "утренний отчёт не читает проверку ключей"


def test_endpoints_live_with_mock(monkeypatch):
    """Живой прогон эндпоинтов через Flask test_client (проверка замокана)."""
    import proxy.routes_admin as ra

    fixed = {
        "checked_at": "2026-10-06 02:00:00",
        "results": [
            {"env_key": "ZAI_API_KEY", "label": "Z.ai (GLM)", "kind": "model",
             "required": False, "sanctions_ok": True, "status": "ok", "http_code": 200, "detail": ""},
            {"env_key": "FRED_API_KEY", "label": "FRED (макроданные)", "kind": "service",
             "required": False, "sanctions_ok": True, "status": "invalid", "http_code": 400,
             "detail": "FRED error в ответе"},
        ],
        "problems": [],
        "ok_count": 1,
        "total": 2,
    }
    fixed["problems"] = [fixed["results"][1]]
    monkeypatch.setattr(key_health, "check_all", lambda timeout=key_health.TIMEOUT_S: fixed)
    monkeypatch.setattr(key_health, "save_results", lambda summary: None)

    client = ra.app.test_client()
    r1 = client.get("/admin/keys/run")
    assert r1.status_code == 200
    text = r1.get_data(as_text=True)
    assert "Z.ai (GLM)" in text and "invalid (HTTP 400" in text and "проблем 1" in text

    r2 = client.post("/admin/keys/night-check")
    assert r2.status_code == 200
    body = r2.get_json()
    assert body["status"] == "problems"
    assert body["ok_count"] == 1 and body["total"] == 2
    assert "FRED" in body["problems_line"]


def test_save_results_upsert():
    """Сохранение результата: upsert по env_key, без дублей."""
    init_db()
    summary = {
        "checked_at": "2026-10-06 02:00:00",
        "results": [
            {"env_key": "__test_key__", "label": "t", "kind": "model", "required": False,
             "sanctions_ok": True, "status": "ok", "http_code": 200, "detail": ""},
        ],
    }
    key_health.save_results(summary)
    key_health.save_results({**summary, "results": [
        {**summary["results"][0], "status": "invalid", "http_code": 401}]})
    rows = _query("SELECT status, http_code FROM key_health_status WHERE env_key='__test_key__'", fetch=True)
    assert len(rows) == 1, "апсерт задублировал строку"
    assert rows[0]["status"] == "invalid" and rows[0]["http_code"] == 401
    _query("DELETE FROM key_health_status WHERE env_key='__test_key__'")


def test_morning_line_formats(monkeypatch):
    """A.4: детерминированные форматы строки «Ключи».

    Фикс мины замедленного действия (2026-10-07): дата была захардкожена
    ("2026-10-06 02:00:00") и через >26 ч после мержа стала «протухшей» —
    build_morning_line честно уходил в stale-ветку, тест падал в CI на main
    (6811903, до перехода 0.29.0). Свежесть теперь динамическая.
    """
    import proxy.core as core

    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        {"env_key": "ZAI_API_KEY", "status": "ok", "http_code": 200, "checked_at": fresh},
        {"env_key": "FRED_API_KEY", "status": "invalid", "http_code": 400, "checked_at": fresh},
        {"env_key": "TAVILY_API_KEY", "status": "unverified", "http_code": None, "checked_at": fresh},
    ]
    monkeypatch.setattr(core, "_query", lambda sql, params=(), fetch=False: rows)
    line = key_health.build_morning_line()
    assert line.startswith("🔑 Ключи: ⚠️")
    assert "FRED (макроданные) invalid (400)" in line
    assert "остальные 2 — ok" in line, "unverified считается «остальным», не проблемой"

    monkeypatch.setattr(core, "_query", lambda *a, **k: [
        {"env_key": "ZAI_API_KEY", "status": "ok", "http_code": 200, "checked_at": fresh}])
    assert "все 1 — ok" in key_health.build_morning_line()

    monkeypatch.setattr(core, "_query", lambda *a, **k: [])
    assert "ещё не проверялись" in key_health.build_morning_line()

    monkeypatch.setattr(core, "_query", lambda *a, **k: [
        {"env_key": "ZAI_API_KEY", "status": "ok", "http_code": 200, "checked_at": "2026-09-01 02:00:00"}])
    assert "НЕ выполнялась с" in key_health.build_morning_line()
