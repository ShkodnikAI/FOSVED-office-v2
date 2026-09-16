#!/usr/bin/env python3
"""SHOP-3 tests (диспатч #172): сборщики площадок + хранилище + склейка.

Снапшоты — по ЖИВЫМ ответам, снятым из песочницы 2026-09-16 (см. докстринг
proxy/shop_collectors.py): WB v4 (sizes[].price в копейках, feedbacks,
supplier*) и Kufar search-api v2 (price_byn, paid_services.halva,
account_parameters). Onliner — форма по памяти (оборонительный парсер +
kind:"api_form_mismatch"). 21vek — честный каркас not_implemented_live.

Хранилище: DDL извлекается прямо из app.mlog (гвард SHOP-1) и исполняется
в тестовой БД DATABASE_PATH — upsert/история проверяются на живой схеме.
Транспорт подменяется через sc.FETCH_JSON_FN (никакой сети в тестах).
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop3-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy import shop_collectors as sc  # noqa: E402
from proxy.core import _query  # noqa: E402

# ── живые снапшоты (укороченные до существенных полей) ──────────────────
WB_SNAPSHOT = {
    "metadata": {"name": "кофемолка", "rs": 100},
    "total": 56109,
    "products": [
        {
            "id": 414389121, "name": "Кофемолка электрическая SM",
            "brand": "SM", "rating": 5, "reviewRating": 4.8,
            "feedbacks": 18790, "totalQuantity": 53,
            "supplier": "ТотСамыйМагазин", "supplierId": 572164,
            "supplierRating": 4.9,
            "sizes": [{"name": "один размер",
                       "price": {"basic": 385000, "product": 70400,
                                 "logistics": 0, "return": 0, "cashback": 0}}],
        },
        {
            "id": 999000111, "name": "Кофемолка ручная",
            "brand": "Manual", "rating": 4, "reviewRating": 4.2,
            "feedbacks": 12, "totalQuantity": 0,
            "supplier": "Мастерская", "supplierId": 42,
            "supplierRating": 4.5,
            "sizes": [{"price": {"basic": 90000, "product": 90000}}],
        },
    ],
}

KUFAR_SNAPSHOT = {
    "ads": [
        {"ad_id": 1085316386,
         "ad_link": "https://www.kufar.by/item/1085316386?utm_source=test",
         "subject": "Кофемолка Bosch", "price_byn": 300, "price_usd": 99,
         "currency": "BYR", "company_ad": False,
         "account_parameters": [{"p": "name", "v": "Юрий"}],
         "paid_services": {"halva": True}},
        {"ad_id": 1085316387,
         "ad_link": "https://www.kufar.by/item/1085316387",
         "subject": "Кофемолка новая", "price_byn": 210,
         "currency": "BYR", "company_ad": True,
         "account_parameters": [{"p": "name", "v": "ТехноМагазин"}],
         "paid_services": {"halva": False}},
    ]
}

ONLINER_SNAPSHOT = {
    "products": [
        {"key": "kofemolka-bosch-tsm6", "name": "Кофемолка Bosch TSM6",
         "full_name": "Кофемолка Bosch TSM6A013",
         "prices": {"price": {"amount": "129.00", "currency": "BYN"},
                    "offers_count": 4}},
        {"key": "kofemolka-x", "name": "Кофемолка X",
         "prices": {"price": {"amount": "89.50", "currency": "BYN"},
                    "offers_count": 0}},
    ]
}


# ── тестовая БД: DDL прямо из app.mlog ──────────────────────────────────
def _shop_ddl():
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    return [s for s in
            __import__("re").findall(
                r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
            if "shop_" in s]


@pytest.fixture(autouse=True)
def shop_db():
    # DB-файл офиса = DATABASE_PATH/fosved.db (proxy/core.py: DB_FILE)
    db_file = os.path.join(os.environ["DATABASE_PATH"], "fosved.db")
    conn = sqlite3.connect(db_file)
    for stmt in _shop_ddl():
        conn.execute(stmt)
    conn.commit()
    conn.close()
    _query("DELETE FROM shop_price_history")
    _query("DELETE FROM shop_offers")
    _query("DELETE FROM shop_sellers")
    _query("DELETE FROM shop_products")
    yield
    _query("DELETE FROM shop_price_history")
    _query("DELETE FROM shop_offers")
    _query("DELETE FROM shop_sellers")
    _query("DELETE FROM shop_products")


@pytest.fixture(autouse=True)
def stub_transport(monkeypatch):
    """Транспорт подменён: URL → снапшот. Никакой сети."""
    def fake_fetch(tool, args):
        url = args.get("url", "")
        if "search.wb.ru" in url:
            return {"ok": True, "url": url, "status": 200, "data": WB_SNAPSHOT}
        if "kufar" in url:
            return {"ok": True, "url": url, "status": 200, "data": KUFAR_SNAPSHOT}
        if "onliner" in url:
            return {"ok": True, "url": url, "status": 200, "data": ONLINER_SNAPSHOT}
        return {"ok": False, "error": "неожиданный URL", "kind": "test"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake_fetch)


# ── canonical_url ───────────────────────────────────────────────────────
def test_canonical_url_strips_tracking():
    u = sc.canonical_url("https://www.kufar.by/item/1?utm_source=t&gclid=x&id=2")
    assert u == "https://www.kufar.by/item/1?id=2"
    assert sc.canonical_url(
        "https://www.wildberries.ru/catalog/1/detail.aspx") == \
        "https://www.wildberries.ru/catalog/1/detail.aspx"
    assert sc.canonical_url("мусор") == "мусор"


# ── WB (живая форма) ────────────────────────────────────────────────────
def test_wb_collector_parses_live_form():
    res = sc.collect_wb("кофемолка", rates={"RUB": 0.034})
    assert res["ok"] is True and len(res["offers"]) == 2
    o = res["offers"][0]
    assert o["platform_code"] == "414389121"
    assert o["url"] == "https://www.wildberries.ru/catalog/414389121/detail.aspx"
    # копейки → валюта → BYN: 704.00 RUB × 0.034 = 23.94
    assert o["price_byn"] == pytest.approx(704.0 * 0.034, abs=0.01)
    # basic 3850.00 RUB — старая цена
    assert o["old_price_byn"] == pytest.approx(3850.0 * 0.034, abs=0.01)
    assert o["in_stock"] == 1
    assert o["reviews_count"] == 18790
    assert o["rating"] == 4.8
    assert o["seller_name"] == "ТотСамыйМагазин"
    assert o["seller_rating"] == 4.9
    o2 = res["offers"][1]
    assert o2["in_stock"] == 0  # totalQuantity 0
    assert o2["price_byn"] == pytest.approx(900.0 * 0.034, abs=0.01)
    assert o2["old_price_byn"] == pytest.approx(900.0 * 0.034, abs=0.01)  # basic == product


def test_wb_without_rates_is_honest():
    res = sc.collect_wb("кофемолка", rates=None)
    assert res["ok"] is True
    assert res["offers"][0]["price_byn"] is None  # RUB без курса → не выдумываем
    assert res["offers"][0]["currency_note"] == "RUB"


def test_wb_form_mismatch_is_loud(monkeypatch):
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "data": {"unexpected": 1}})
    res = sc.collect_wb("x")
    assert res["ok"] is False and res["kind"] == "api_form_mismatch"


# ── Kufar (живая форма) ─────────────────────────────────────────────────
def test_kufar_collector_parses_live_form():
    res = sc.collect_kufar("кофемолка")
    assert res["ok"] is True and len(res["offers"]) == 2
    o = res["offers"][0]
    assert o["platform_code"] == "1085316386"
    assert o["url"] == "https://www.kufar.by/item/1085316386"  # utm снят
    assert o["price_byn"] == 300.0
    assert o["installment_ok"] == 1  # halva=True
    assert o["seller_name"] == "Юрий"
    assert o["seller_official"] == 0  # частник
    o2 = res["offers"][1]
    assert o2["installment_ok"] == 0 and o2["seller_official"] == 1  # компания


# ── Onliner / 21vek (честные ограничения) ───────────────────────────────
def test_onliner_defensive_parse(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "coffeegrinder")
    res = sc.collect_onliner("кофемолка")
    assert res["ok"] is True and len(res["offers"]) == 2
    o = res["offers"][0]
    assert o["price_byn"] == 129.0  # BYN напрямую
    assert o["url"].startswith("https://catalog.onliner.by/")
    assert res["offers"][1]["in_stock"] == 0


def test_onliner_without_category_is_config_missing(monkeypatch):
    monkeypatch.delenv("SHOP_ONLINER_CATEGORY", raising=False)
    res = sc.collect_onliner("x")
    assert res["ok"] is False and res["kind"] == "config_missing"


def test_21vek_is_honest_carrier():
    res = sc.collect_21vek("x")
    assert res["ok"] is False and res["kind"] == "not_implemented_live"


def test_unknown_platform():
    res = sc.collect("amazon", "x")
    assert res["ok"] is False and res["kind"] == "no_collector"


# ── Хранилище: upsert + история + склейка с движком ─────────────────────
def _make_product(title="Кофемолка Bosch TSM6"):
    _query("INSERT INTO shop_products (title) VALUES (?)", (title,))
    # каждое _query — новое соединение: lastrowid берём обратным SELECT
    return _query("SELECT id FROM shop_products WHERE title=? ORDER BY id DESC LIMIT 1",
                  (title,), fetch=True)[0]["id"]


def test_refresh_upserts_offers_and_history():
    pid = _make_product()
    r1 = sc.refresh_product(pid, "wb", "кофемолка", rates={"RUB": 0.034})
    assert r1["ok"] is True and r1["offers"] == 2 and r1["history_rows"] == 2
    offers = _query("SELECT * FROM shop_offers WHERE product_id=?", (pid,), fetch=True)
    assert len(offers) == 2
    row = [o for o in offers if o["platform_code"] == "414389121"][0]
    assert row["price_byn"] == pytest.approx(704.0 * 0.034, abs=0.01)
    assert row["seller_id"] is not None
    hist = _query("SELECT price_byn FROM shop_price_history WHERE offer_id=?",
                  (row["id"],), fetch=True)
    assert len(hist) == 1
    # повторный сбор с НОВОЙ ценой: UPDATE оффера + вторая строка истории
    WB_SNAPSHOT["products"][0]["sizes"][0]["price"]["product"] = 60000
    try:
        r2 = sc.refresh_product(pid, "wb", "кофемолка", rates={"RUB": 0.034})
        assert r2["offers"] == 2
        row2 = [o for o in _query("SELECT * FROM shop_offers WHERE product_id=?", (pid,),
                                  fetch=True) if o["platform_code"] == "414389121"][0]
        assert row2["id"] == row["id"]  # тот же оффер, обновлён
        assert row2["price_byn"] == pytest.approx(600.0 * 0.034, abs=0.01)
        hist2 = _query("SELECT price_byn FROM shop_price_history WHERE offer_id=? ORDER BY id",
                       (row["id"],), fetch=True)
        assert len(hist2) == 2  # история растёт — фейк-детект будет с данными
    finally:
        WB_SNAPSHOT["products"][0]["sizes"][0]["price"]["product"] = 70400


def test_kufar_offer_without_price_skips_history_row():
    pid = _make_product()
    KUFAR_SNAPSHOT["ads"][0]["price_byn"] = None
    try:
        r = sc.refresh_product(pid, "kufar", "кофемолка")
        assert r["ok"] is True and r["history_rows"] == 1  # только у второго
    finally:
        KUFAR_SNAPSHOT["ads"][0]["price_byn"] = 300


def test_score_product_end_to_end():
    """SHOP-1 + SHOP-3: сбор → БД → вердикт движка."""
    pid = _make_product()
    sc.refresh_product(pid, "wb", "кофемолка", rates={"RUB": 0.034})
    sc.refresh_product(pid, "kufar", "кофемолка")
    res = sc.score_product(pid)
    assert res["ok"] is True
    scored = res["scored"]
    assert len(scored["offers"]) == 4  # 2 WB + 2 Kufar, все с ценой
    assert scored["verdict"] is not None and scored["verdict"]["text"]
    # бейдж «дешевле всех» указывает на реальный оффер из БД
    ids = {o["id"] for o in scored["offers"]}
    assert scored["badges"]["cheapest"] in ids
