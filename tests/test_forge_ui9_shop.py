#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-9 tests (#202): настройки Закупок.

Гварды:
- источники: новая таблица shop_sources (source_id/enabled/custom/url),
  флаг реально фильтрует опрос (ensure_product и tick_shop_watches не ходят
  на выключенный источник); Ozon — жёлтый статус «заблокирован антиботом»,
  отличный от выключенного вручную; «свой магазин» регистрируется честно;
- профили: 2 новых весовых (cheap: price=1.0; availability: access=0.7) +
  «Топ-3 по диапазонам» — ОТДЕЛЬНАЯ функция top3_by_price_bands (3 терции
  по цене, топ-3 в каждой), не модификация score_offers; профили дают
  видимо разный результат на одном запросе;
- слежение: дефолты (порог скидки, уведомлять о наличии) подхватываются
  add_watch, когда параметры не заданы явно;
- превью: POST /api/shop/preview c профилем; архив закупок — решение
  «вынесено в под-наряд» зафиксировано.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui9-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import shop_watch as sw  # noqa: E402
from proxy.shop_engine import (  # noqa: E402
    WEIGHTS_CHEAP, WEIGHTS_AVAILABILITY, top3_by_price_bands, score_offers,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def shop_db():
    _query("CREATE TABLE IF NOT EXISTS shop_sources (source_id TEXT PRIMARY KEY, "
           "enabled INTEGER DEFAULT 1, custom INTEGER DEFAULT 0, url TEXT)")
    _query("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
    _query("CREATE TABLE IF NOT EXISTS shop_products (id INTEGER PRIMARY KEY AUTOINCREMENT, "
           "title TEXT, query_text TEXT)")
    _query("CREATE TABLE IF NOT EXISTS shop_offers (id INTEGER PRIMARY KEY AUTOINCREMENT, "
           "product_id INTEGER, platform TEXT, title TEXT, url TEXT, price_byn REAL)")
    _query("CREATE TABLE IF NOT EXISTS shop_watches (id INTEGER PRIMARY KEY AUTOINCREMENT, "
           "product_id TEXT, target_price_byn REAL, discount_pct REAL, alert_in_stock INTEGER DEFAULT 0, "
           "status TEXT DEFAULT 'active')")
    _query("DELETE FROM shop_sources")
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_watch_%'")
    _query("DELETE FROM shop_products")
    _query("DELETE FROM shop_offers")
    _query("DELETE FROM shop_watches")
    yield
    _query("DELETE FROM shop_sources")
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_watch_%'")
    _query("DELETE FROM shop_products")
    _query("DELETE FROM shop_offers")
    _query("DELETE FROM shop_watches")


# ── Блок A. Источники ────────────────────────────────────────────────────

def test_sources_table_and_toggle_endpoint():
    _query("INSERT INTO shop_sources (source_id, enabled) VALUES ('21vek', 0)")
    with _client() as c:
        r = c.post("/api/shop/sources/21vek/toggle", headers=API_AUTH, json={"enabled": True})
    assert r.status_code == 200 and r.get_json()["enabled"] is True
    row = _query("SELECT enabled FROM shop_sources WHERE source_id='21vek'", fetch=True)
    assert row[0]["enabled"] == 1


def test_disabled_source_not_polled(monkeypatch):
    """Smoke-1: выключенный источник реально не опрашивается."""
    calls = []
    monkeypatch.setattr("proxy.shop_collectors.refresh_product",
                        lambda pid, platform, query: calls.append(platform) or {"ok": True})
    monkeypatch.setattr(sw, "PLATFORMS_MVP", ("wb", "ozon"))
    _query("INSERT INTO shop_sources (source_id, enabled) VALUES ('ozon', 0)")
    pid, details = sw.ensure_product("тестовый запрос")
    assert calls == ["wb"] or "ozon" not in calls
    assert details["ozon"]["kind"] == "source_disabled"


def test_ozon_status_antibot_not_off():
    # жёлтый статус «заблокирован антиботом» — состояние, отличное от «выключено»
    assert 'ozon": ("заблокирован антиботом", "warn")' in \
        open(os.path.join(REPO_ROOT, "proxy", "routes_admin.py"), encoding="utf-8").read()
    assert 'SHOP_SOURCE_STATUS[x.id]' in INDEX  # фронт рисует честный статус из карты


def test_custom_source_registered_honestly():
    with _client() as c:
        r = c.post("/api/shop/sources/custom", headers=API_AUTH,
                   json={"name": "Мой Магазин", "url": "https://shop.example"})
    assert r.status_code == 200
    sid = r.get_json()["id"]
    assert sid.startswith("custom-")
    row = _query("SELECT custom, url FROM shop_sources WHERE source_id=?", (sid,), fetch=True)
    assert row[0]["custom"] == 1 and "shop.example" in row[0]["url"]
    # честное предупреждение в интерфейсе
    assert 'понадобится отдельная настройка сборщика' in INDEX


# ── Блок B. Профили оценки ───────────────────────────────────────────────

def test_new_weight_profiles_exact_values():
    assert WEIGHTS_CHEAP == {"price": 1.0, "quality": 0.0, "access": 0.0, "seller": 0.0}
    assert WEIGHTS_AVAILABILITY == {"price": 0.1, "quality": 0.1, "access": 0.7, "seller": 0.1}


def _offers():
    # o0 — самый дешёвый, но продавец плохой (нерейтинговый, неофициальный);
    # o3 — средняя цена с идеальным продавцом. cheap и best разойдутся.
    base = {"in_stock": 1, "platform": "wb", "title": "т"}
    out = []
    for i in range(6):
        good = i == 3
        out.append(dict(base, id=f"o{i}", price_byn=100.0 + i * 50,
                        seller_rating=5.0 if good else 2.0,
                        seller_official=1 if good else 0,
                        seller_years=5 if good else 1, seller_deals=900 if good else 3))
    return out


def test_profiles_give_visible_difference():
    offers = _offers()
    # у o0 лучшая цена, но продавец слабее — cheap и best меняют порядок
    cheap = score_offers(offers, profile="cheap")
    best = score_offers(offers, profile="best")
    cheap_ids = [o["id"] for o in sorted(cheap["offers"], key=lambda x: x["total"], reverse=True)]
    best_ids = [o["id"] for o in sorted(best["offers"], key=lambda x: x["total"], reverse=True)]
    assert cheap_ids != best_ids


def test_top3_is_separate_structure():
    offers = _offers()
    r = top3_by_price_bands(offers)
    assert "bands" in r and len(r["bands"]) == 3
    assert [b["band"] for b in r["bands"]] == ["low", "mid", "high"]
    for b in r["bands"]:
        assert len(b["offers"]) <= 3 and b["count"] == 2
    # цены диапазонов упорядочены
    assert r["bands"][0]["price_to"] <= r["bands"][1]["price_from"]


def test_api_preview_profiles(monkeypatch):
    monkeypatch.setattr("proxy.shop_collectors.refresh_product",
                        lambda pid, platform, query: {"ok": True})
    monkeypatch.setattr(sw, "PLATFORMS_MVP", ("wb",))
    _seed_offers_for_preview(monkeypatch)
    with _client() as c:
        r_flat = c.post("/api/shop/preview", headers=API_AUTH,
                        json={"query": "кофемолка", "profile": "cheap"})
        r_top3 = c.post("/api/shop/preview", headers=API_AUTH,
                        json={"query": "кофемолка", "profile": "top3"})
    assert "offers" in r_flat.get_json()
    assert "bands" in r_top3.get_json()  # структурно другой вывод


def _seed_offers_for_preview(monkeypatch):
    # ensure_product создаёт продукт; офферы кладём напрямую
    from proxy.core import _query as q
    q("INSERT INTO shop_products (title, query_text) VALUES ('кофемолка','кофемолка')")
    row = q("SELECT id FROM shop_products WHERE query_text='кофемолка' ORDER BY id DESC LIMIT 1", fetch=True)
    pid = row[0]["id"]
    for i in range(6):
        q("INSERT INTO shop_offers (product_id, platform, title, url, price_byn) "
          "VALUES (?, 'wb', 'кофемолка '||?, 'u'||?, ?)", (pid, i, i, 100.0 + i * 50))


# ── Блок C. Слежение ─────────────────────────────────────────────────────

def test_watch_defaults_picked_up_by_add_watch():
    _query("INSERT INTO system_settings (key, value) VALUES "
           "('shop_watch_default_discount', '15'), ('shop_watch_default_in_stock', '1')")
    w = sw.add_watch("P-UI9", target_price_byn=100)
    row = _query("SELECT discount_pct, alert_in_stock FROM shop_watches WHERE id=?", (w,), fetch=True)
    assert row[0]["discount_pct"] == 15.0
    assert row[0]["alert_in_stock"] == 1
    # явные параметры приоритетнее дефолтов
    w2 = sw.add_watch("P-UI9b", target_price_byn=100, discount_pct=5, alert_in_stock=False)
    row2 = _query("SELECT discount_pct, alert_in_stock FROM shop_watches WHERE id=?", (w2,), fetch=True)
    assert row2[0]["discount_pct"] == 5 and row2[0]["alert_in_stock"] == 0


def test_settings_endpoints_roundtrip():
    with _client() as c:
        r = c.post("/api/shop/settings", headers=API_AUTH,
                   json={"default_discount_pct": 20, "default_in_stock": True})
        assert r.status_code == 200
        g = c.get("/api/shop/settings", headers=API_AUTH)
    body = g.get_json()
    assert body["default_discount_pct"] == 20.0 and body["default_in_stock"] is True


# ── Блок D. Архив — решение зафиксировано ────────────────────────────────

def test_archive_deferred_honestly():
    # FORGE-UI-13 (#216): обещанный под-наряд реализован — строка ведёт на
    # реальный экран архива закупок, заглушка-тост удалена.
    assert 'id="shopArchiveRow"' in INDEX
    assert 'openShopArchive' in INDEX
    assert 'id="shopArchWrap"' in INDEX


def test_ui9_frontend_statics():
    assert 'SHOP_SOURCE_STATUS[x.id]' in INDEX  # честные статусы площадок
    assert '["best","Лучшее соотношение"' in INDEX and '["top3","Топ-3 по ценовым диапазонам"' in INDEX
    assert 'data-go="shopset"' in INDEX  # экран доступен из «Ещё»
