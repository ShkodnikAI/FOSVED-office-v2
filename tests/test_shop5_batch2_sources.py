#!/usr/bin/env python3
"""SHOP-3 батч-2 (наряды #335/#337/#338/#339/#340): 4 честных каркаса +
Яндекс.Маркет — официальная реализация Content API с честным гейтом.

Разведка 2026-09-24 (докстринг shop_collectors — источник правды):
  - 7745/shopby — recon_unreachable (GeoIP-блок 403 датацентровых IP,
    у 7745 robots/sitemap живы — статика отдаётся, динамика нет);
  - tomas/unishop — robots_disallow_surface (поисковая поверхность
    закрыта для честных клиентов; у unishop дополнительно reagate-капча);
  - ym — полная реализация: config_missing без ключа → дневной счётчик
    100/сутки (авто-сброс 00:00 UTC) → кэш повторов 5 мин (повтор тот же
    запрос лимит НЕ жжёт) → оборонительный парсер нескольких известных
    форм (расхождение → api_form_mismatch) → транспорт-ошибки (401/403)
    пробрасываются с человечьей нотой, счётчик НЕ бьётся (запрос до API
    не дошёл).

Транспорт подменяется через sc.FETCH_JSON_FN — никакой сети в тестах.
FX зажат через SHOP_FX_RATES_JSON (первый приоритет fx_rates).
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop5-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query  # noqa: E402
from proxy import shop_collectors as sc  # noqa: E402
from proxy import shop_watch as sw  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_kv():
    _query("CREATE TABLE IF NOT EXISTS system_settings "
           "(key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_ym%'")
    yield
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_ym%'")


# ── 1. Честные каркасы: kind/платформа/текст ────────────────────────────
@pytest.mark.parametrize("platform,kind", [
    ("7745", "recon_unreachable"),
    ("shopby", "recon_unreachable"),
    ("unishop", "antibot_blocked"),
])
def test_batch2_refusals_are_honest(platform, kind):
    r = sc.collect(platform, "смартфон")
    assert r["ok"] is False
    assert r["kind"] == kind
    assert r["platform"] == platform
    assert r["error"], "отказ обязан быть с текстом, не молчанкой"


# ── #406: tomas — живая попытка (стаб транспорта, без сети) ────────────
def test_tomas_live_attempt_captcha_is_honest(monkeypatch):
    """Антибот-стена «Проверка безопасности» → antibot_blocked с диагнозом."""
    def fake(tool, args):
        assert tool == "fetch_page" and "tomas.by/search/" in args["url"]
        return {"ok": True, "content": "<title>Проверка безопасности</title> recaptcha"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    r = sc.collect_tomas("смартфон")
    assert r["ok"] is False and r["kind"] == "antibot_blocked"
    assert "антибот" in r["error"]


def test_tomas_parses_jsonld_products(monkeypatch):
    """Если egress не встречает антибот — витрина берётся из JSON-LD."""
    ld = ('<script type="application/ld+json">'
          '{"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",'
          '"name":"Смартфон X","sku":"X100","offers":{"price":899.0,'
          '"priceCurrency":"BYN","url":"https://tomas.by/item/x100",'
          '"seller":{"name":"Магазин Плюс"}}}}]}</script>')
    def fake(tool, args):
        return {"ok": True, "content": ld}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    r = sc.collect_tomas("смартфон")
    assert r["ok"] is True and r["offers"]
    o = r["offers"][0]
    assert o["seller_name"] == "Магазин Плюс"  # продавец-участник, не «Tomas.by»
    assert o["price_byn"] == 899.0


def test_batch2_registered_in_collectors_and_mvp():
    for p in ("7745", "shopby", "tomas", "unishop", "ym"):
        assert p in sc.COLLECTORS, p
        assert p in sw.PLATFORMS_MVP, p


def test_status_map_covers_batch2():
    from proxy import routes_admin as ra
    for p in ("7745", "shopby", "tomas", "unishop", "ym"):
        status = ra._SHOP_SOURCE_STATUS.get(p)
        assert status and status[0] and status[1] == "warn", p


# ── 2. Яндекс.Маркет: гейт на ключ ──────────────────────────────────────
def test_ym_config_missing_without_key(monkeypatch):
    monkeypatch.delenv("YANDEX_MARKET_API_KEY", raising=False)
    r = sc.collect_yandexmarket("смартфон")
    assert r["ok"] is False
    assert r["kind"] == "config_missing"
    assert "владельц" in r["error"]  # шаг A.1 — за владельцем, не молчанка


# ── 3. Яндекс.Маркет: полный поток с подменой транспорта ────────────────
YM_SNAPSHOT = {
    "result": {"offers": [
        {"id": 111, "name": "Смартфон Пример X",
         "price": {"value": 1000.0, "currency": "RUB"},
         "url": "https://market.yandex.ru/product--x?yclid=abc",
         "rating": 4.5, "reviewsCount": 12,
         "seller": {"id": 7, "name": "Магазин Плюс"},
         "stockState": {"inStock": 5}},
        {"id": 222, "fullName": "Ноутбук Пример Pro",
         "price": {"value": 2000, "currency": "BYN"},
         "link": "https://market.yandex.ru/product--p",
         "rating": 47, "feedbacksCount": 3,
         "shopInfo": {"name": "ТД Три"}},
    ]},
}


@pytest.fixture()
def ym_env(monkeypatch):
    monkeypatch.setenv("YANDEX_MARKET_API_KEY", "test-ym-key-123456")
    monkeypatch.setenv("SHOP_FX_RATES_JSON", json.dumps({"RUB": 0.0345}))
    return monkeypatch


def test_ym_full_flow_counter_and_cache(ym_env, monkeypatch):
    calls = []

    def fake_fetch(tool, args):
        calls.append((tool, dict(args)))
        return {"ok": True, "status": 200, "data": json.loads(json.dumps(YM_SNAPSHOT))}

    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake_fetch)
    r = sc.collect_yandexmarket("смартфон")
    assert r["ok"] is True and len(r["offers"]) == 2
    o1, o2 = r["offers"]
    assert o1["platform"] == "ym" and o1["platform_code"] == "111"
    assert abs(o1["price_byn"] - 34.5) < 0.01      # 1000 RUB × 0.0345
    assert o1["url"] == "https://market.yandex.ru/product--x"  # yclid вычищен
    assert o1["in_stock"] == 1 and o1["rating"] == 4.5
    assert o1["seller_name"] == "Магазин Плюс"
    assert o2["price_byn"] == 2000                 # BYN проходит как есть
    assert o2["rating"] == 4.7                     # 0..50 → /10
    assert o2["seller_name"] == "ТД Три"
    assert o2["reviews_count"] == 3
    # транспорт: fetch_api_json с Bearer-токеном
    assert calls[0][0] == "fetch_api_json"
    assert calls[0][1]["token"] == "test-ym-key-123456"
    # счётчик: ровно 1 запрос лимита
    assert sc._ym_counter_read()["count"] == 1
    # повтор того же запроса — кэш, лимит НЕ жжётся
    r2 = sc.collect_yandexmarket("смартфон")
    assert r2.get("cached") is True and r2["ok"] is True
    assert len(calls) == 1
    assert sc._ym_counter_read()["count"] == 1
    # другой запрос — новый транспорт-вызов, счётчик 2
    r3 = sc.collect_yandexmarket("ноутбук")
    assert r3["ok"] is True and len(calls) == 2
    assert sc._ym_counter_read()["count"] == 2


def test_ym_daily_limit_stops_before_transport(ym_env, monkeypatch):
    def boom(tool, args):  # транспорт не должен дёргаться
        raise AssertionError("транспорт вызван при исчерпанном лимите")

    monkeypatch.setattr(sc, "FETCH_JSON_FN", boom)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    sc._setting_set(sc.YM_COUNTER_KEY,
                    json.dumps({"date": today, "count": sc.YM_DAILY_LIMIT}))
    r = sc.collect_yandexmarket("смартфон")
    assert r["ok"] is False and r["kind"] == "daily_limit"


def test_ym_counter_resets_next_utc_day():
    sc._setting_set(sc.YM_COUNTER_KEY,
                    json.dumps({"date": "2026-09-20", "count": 99}))
    assert sc._ym_counter_read()["count"] == 0  # старая дата → сброс


def test_ym_api_form_mismatch(ym_env, monkeypatch):
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "status": 200,
                                      "data": {"unexpected": "shape"}})
    r = sc.collect_yandexmarket("смартфон")
    assert r["ok"] is False and r["kind"] == "api_form_mismatch"
    # 200-ответ — лимит израсходован, даже если форма не разобралась
    assert sc._ym_counter_read()["count"] == 1


def test_ym_transport_401_no_counter_bump(ym_env, monkeypatch):
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": False, "kind": "http_401",
                                      "error": "HTTP 401: Unauthorized"})
    r = sc.collect_yandexmarket("смартфон")
    assert r["ok"] is False and r["kind"] == "http_401"
    assert "ключ невалиден" in r["error"]
    assert sc._ym_counter_read()["count"] == 0     # до API не дошло — не бьём


# ── 4. Совместимость оффера со скорингом (score_offers) ─────────────────
def test_ym_offer_shape_scoreable():
    from proxy.shop_engine import score_offers
    offers = sc._ym_offers_from(json.loads(json.dumps(YM_SNAPSHOT)), {"RUB": 0.0345})
    assert offers and all(o["price_byn"] is not None for o in offers)
    for i, o in enumerate(offers):
        o["id"] = i + 1
    scored = score_offers(offers, {1: [34.5], 2: [2000.0]}, profile="default")
    assert scored.get("offers"), "офферы ym должны проходить движок без ошибки"
