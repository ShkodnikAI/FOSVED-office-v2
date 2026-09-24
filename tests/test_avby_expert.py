#!/usr/bin/env python3
"""av.by → Эксперт (наряд #336): мост, честная деградация, гейт темы.

Разведка 2026-09-24: cars.av.by закрыт WAF SafeLine (HTTP 468) с
датацентровых IP. Проверяется:
  - питон-сторона: WAF-вердикт честно кэшируется на 1 ч (повторный вызов
    НЕ бьётся в площадку), транспорт-отказы → recon_unreachable с
    человекочитаемым разделом «честно пуст»;
  - транспорт прошёл, форма не знакома → api_form_mismatch (парсер
    вслепую не пишется);
  - известная форма JSON → реальный список объявлений (ok:True);
  - мост зарегистрирован в CALL_PYTHON_ALLOWED (call_python-контракт);
  - mlog-паттерн ExpertAvByListings существует и вызывается ТОЛЬКО из
    автомобильной ветки BuildExpertContext (гейт ExpertIsAutomotiveTopic).
Транспорт подменяется — никакой сети в тестах.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-avby-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query  # noqa: E402
from proxy import avby_collector as av  # noqa: E402

EXPERT_MLOG = (REPO_ROOT / "dept" / "expert.mlog").read_text(encoding="utf-8")
TAIL_ROUTES = (REPO_ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean_kv():
    _query("CREATE TABLE IF NOT EXISTS system_settings "
           "(key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_avby%'")
    yield
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_avby%'")


def test_waf_refusal_is_honest_and_cached(monkeypatch):
    calls = []

    def fake_fetch(tool, args):
        calls.append(args)
        return {"ok": False, "kind": "http_468", "error": "HTTP 468: Forbidden"}

    monkeypatch.setattr(av, "FETCH_JSON_FN", fake_fetch, raising=False)
    r1 = av.search_avby("Toyota Camry до 30000 BYN")
    assert r1["ok"] is False and r1["kind"] == "recon_unreachable"
    assert "WAF" in r1["error"] and "честно пуст" in r1["result"]["text"]
    assert r1["result"]["text"].startswith("реальные объявления av.by")
    # вердикт закэширован: второй вызов в площадку НЕ бьётся
    r2 = av.search_avby("BMW X5")
    assert len(calls) == 1
    assert r2["kind"] == "recon_unreachable"
    # кэш истёк → снова живая проба
    _query("UPDATE system_settings SET value=? WHERE key=?",
           (json.dumps({"ts": 0, "blocked": True}), av.WAF_VERDICT_KEY))
    r3 = av.search_avby("Audi A4")
    assert len(calls) == 2


def test_transport_ok_but_unknown_form(monkeypatch):
    monkeypatch.setattr(av, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "status": 200,
                                      "data": {"unexpected": "html-ish"}})
    r = av.search_avby("Toyota Camry")
    assert r["ok"] is False and r["kind"] == "api_form_mismatch"
    assert "вслепую" in r["result"]["text"]


def test_known_form_returns_real_listings(monkeypatch):
    snapshot = {"result": {"items": [
        {"title": "Toyota Camry 2016", "year": 2016, "price": "18 500 BYN",
         "city": "Минск", "url": "https://cars.av.by/Toyota%20Camry/123"},
        {"title": "Toyota Camry 2019", "year": 2019, "price": "27 900 BYN",
         "city": "Брест", "url": "https://cars.av.by/Toyota%20Camry/456"},
    ]}}
    monkeypatch.setattr(av, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "status": 200, "data": snapshot})
    r = av.search_avby("Toyota Camry")
    assert r["ok"] is True
    text = r["result"]["text"]
    assert "Toyota Camry 2016" in text and "18 500 BYN" in text
    assert "Минск" in text and "https://cars.av.by/Toyota%20Camry/123" in text
    assert len(text.splitlines()) == 2


def test_bridge_registered_in_call_python_whitelist():
    from proxy.routes_tail import CALL_PYTHON_ALLOWED
    assert "avby_collector" in CALL_PYTHON_ALLOWED
    assert "search_avby" in CALL_PYTHON_ALLOWED["avby_collector"]


def test_mlog_pattern_exists_and_is_gated_by_automotive_topic():
    assert "pattern ExpertAvByListings(query: String)" in EXPERT_MLOG
    # мост по контракту lz_sources: call_python + redact недоверенных данных
    assert 'call_python("avby_collector", "search_avby", json_encode([query]))' in EXPERT_MLOG
    # вызов живёт ТОЛЬКО внутри автомобильной ветки BuildExpertContext
    ctx = EXPERT_MLOG[EXPERT_MLOG.index("pattern BuildExpertContext"):]
    assert "ExpertAvByListings(query)" in ctx
    avby_call_pos = ctx.index("ExpertAvByListings(query)")
    automotive_gate_pos = ctx.index("if ExpertIsAutomotiveTopic(query) == true")
    assert automotive_gate_pos < avby_call_pos
    # не попал в закупочный контур (#336: НЕ shop_engine)
    assert "avby" not in (REPO_ROOT / "proxy" / "shop_watch.py").read_text(encoding="utf-8")
    assert "avby" not in TAIL_ROUTES.split("CALL_PYTHON_ALLOWED")[0]


def test_empty_query_is_honest():
    r = av.search_avby("")
    assert r["ok"] is False and r["kind"] == "bad_request"
    assert r["result"]["text"] == ""
