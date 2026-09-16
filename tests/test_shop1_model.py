#!/usr/bin/env python3
"""SHOP-1 tests (диспатч #172): весовой движок + модель данных.

Покрытие:
- parse_price: розничные форматы РБ («1 299,90 р.», «1,299.90», «1.299»);
- to_byn: нормализация валют, честная деградация без курса;
- median / honest_discount: фейк-скидка (завышенная зачёркнутая,
  косметическая), настоящая скидка, cold start (<3 точек);
- score_offers: группы, веса default/expensive, бейджи, стоп-флаги,
  вердикт («брать сейчас» / «осторожно» / «ждать»);
- app.mlog: shop-DDL присутствует и ИСПОЛНЯЕТСЯ в in-memory SQLite
  (строки вытаскиваются прямо из app.mlog — защита от SQL-опечаток,
  которые mlog check не видит внутри строк db_execute).
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop1-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.shop_engine import (  # noqa: E402
    honest_discount,
    median,
    parse_price,
    rank_price,
    score_offers,
    stop_flags,
    to_byn,
)


# ── parse_price ──────────────────────────────────────────────────────

def test_parse_price_belarusian_retail_formats():
    assert parse_price("1 299,90 р.") == 1299.90
    assert parse_price("1\u00a0299,90 р.") == 1299.90  # неразрывный пробел
    assert parse_price("1299,90") == 1299.90
    assert parse_price("89.99") == 89.99
    assert parse_price("BYN 89.99") == 89.99


def test_parse_price_thousands_and_us_style():
    assert parse_price("1,299.90") == 1299.90
    assert parse_price("1 299 900") == 1299900.0
    assert parse_price("1.299.900") == 1299900.0
    assert parse_price("1.299") == 1299.0  # розничный приоритет: тысячи


def test_parse_price_garbage_returns_none():
    assert parse_price(None) is None
    assert parse_price("") is None
    assert parse_price("цена по запросу") is None
    assert parse_price("—") is None
    assert parse_price(",,,") is None


# ── to_byn / median ──────────────────────────────────────────────────

def test_to_byn_converts_and_degrades_honestly():
    assert to_byn(100, "USD", {"USD": 3.27}) == 327.0
    assert to_byn(100, "BYN", {}) == 100.0
    assert to_byn(100, None, {}) == 100.0
    assert to_byn(10, "GBP", {}) is None      # нет курса — не выдумываем
    assert to_byn(None, "USD", {"USD": 3.27}) is None


def test_median_odd_even_empty():
    assert median([3, 1, 2]) == 2.0
    assert median([1, 2, 3, 4]) == 2.5
    assert median([]) is None
    assert median([None, 5]) == 5.0


# ── honest_discount (фейк-детект v1) ─────────────────────────────────

def test_honest_discount_inflated_old_price_is_fake():
    r = honest_discount(100.0, 150.0, [95.0, 100.0, 105.0])  # медиана 100
    assert r["claimed_pct"] == 33.3
    assert r["honest_pct"] == 0.0
    assert r["is_fake"] is True
    assert "фейковая" in r["note"]


def test_honest_discount_cosmetic_fake():
    # заявлено -10%, по факту против медианы всего -1.5%; зачёркнутая 110
    # НЕ выше типичной (медиана 100.5 × 1.10 = 110.55) — чистая косметика
    r = honest_discount(99.0, 110.0, [100.0, 100.5, 101.0])
    assert r["claimed_pct"] == 10.0
    assert r["is_fake"] is True
    assert "заявлено" in r["note"]


def test_honest_discount_real_deal():
    r = honest_discount(100.0, 150.0, [140.0, 150.0, 160.0])  # медиана 150
    assert r["honest_pct"] == 33.3
    assert r["is_fake"] is False


def test_honest_discount_cold_start_is_honest():
    r = honest_discount(100.0, 150.0, [100.0])
    assert r["honest_pct"] is None
    assert r["is_fake"] is False
    assert "история копится" in r["note"]


# ── rank_price / stop_flags ──────────────────────────────────────────

def test_rank_price_uses_card_price_and_delivery():
    o = {"price_byn": 100.0, "card_price_byn": 90.0, "delivery_cost_byn": 5.0}
    assert rank_price(o) == 95.0
    assert rank_price({"price_byn": 100.0}) == 100.0
    assert rank_price({}) is None


def test_stop_flags_anomaly_seller_returns_specs():
    o = {"price_byn": 40.0, "seller_deals": None, "return_ok": 0,
         "specs": {"color": "red"}}
    flags = stop_flags(o, [100.0, 110.0, 120.0], product_specs={"material": "cotton"})
    codes = {f["code"] for f in flags}
    assert {"anomaly_price", "seller_no_history", "no_returns", "spec_mismatch"} == codes


def test_stop_flags_quiet_when_data_is_clean():
    o = {"price_byn": 105.0, "seller_deals": 500, "return_ok": 1,
         "specs": {"material": "cotton", "color": "red"}}
    assert stop_flags(o, [100.0, 110.0, 120.0], {"material": "cotton"}) == []


# ── score_offers ─────────────────────────────────────────────────────

OFFERS = [
    {
        "id": 1, "platform": "wb", "price_byn": 89.99, "old_price_byn": 129.99,
        "rating": 4.8, "reviews_count": 512, "in_stock": 1, "delivery_days": 3,
        "installment_ok": 0, "seller_rating": 4.9, "seller_deals": 5000,
        "seller_years": 4, "return_ok": 1,
    },
    {
        "id": 2, "platform": "site", "price_byn": 95.0, "rating": 4.5,
        "reviews_count": 12, "in_stock": 1, "delivery_days": 1,
        "installment_ok": 1, "seller_deals": None, "return_ok": 0,
    },
]

HISTORY = {1: [100.0, 110.0, 120.0], 2: [94.0, 95.0, 96.0]}


def test_score_offers_groups_badges_verdict():
    res = score_offers(OFFERS, HISTORY)
    by_id = {o["id"]: o for o in res["offers"]}
    # дешёвый с настоящей скидкой: rank 89.99 < 95 → максимум цены
    assert res["badges"]["cheapest"] == 1
    # вердикт: у offer 1 честная скидка (медиана 110 → 18.2%) ≥10%
    assert res["verdict"]["best_offer_id"] == 1
    assert "брать сейчас" in res["verdict"]["text"]
    assert "18.2%" in res["verdict"]["text"]
    # стоп-флаги оффера 2: продавец без истории + возврат невозможен
    codes2 = {f["code"] for f in by_id[2]["stop_flags"]}
    assert {"seller_no_history", "no_returns"} <= codes2
    # у оффера 1 флагов нет
    assert by_id[1]["stop_flags"] == []
    # группы в диапазоне и total = весовая сумма
    for o in res["offers"]:
        gs = o["group_scores"]
        assert all(0.0 <= v <= 100.0 for v in gs.values())
        assert abs(o["total"] - (0.35 * gs["price"] + 0.30 * gs["quality"]
                                 + 0.20 * gs["access"] + 0.15 * gs["seller"])) < 0.35
    assert res["unscored"] == []


def test_score_offers_fastest_and_installment_badges():
    res = score_offers(OFFERS, HISTORY)
    assert res["badges"]["fastest"] == 2       # доставка 1 день
    assert res["badges"]["best_installment"] == 2  # рассрочка только у 2


def test_score_offers_expensive_profile_shifts_weight():
    cheap_bad = {
        "id": 10, "platform": "wb", "price_byn": 50.0, "in_stock": 1,
        "rating": 3.0, "reviews_count": 3, "seller_deals": 2,
    }
    pricey_good = {
        "id": 11, "platform": "site", "price_byn": 100.0, "in_stock": 1,
        "rating": 5.0, "reviews_count": 200, "seller_deals": 5000,
        "seller_years": 5, "seller_official": 1,
    }
    d = score_offers([cheap_bad, pricey_good], profile="default")
    e = score_offers([cheap_bad, pricey_good], profile="expensive")
    assert d["verdict"]["best_offer_id"] == 10  # дешёвый берёт при дефолте
    assert e["verdict"]["best_offer_id"] == 11  # качество/продавец решают
    assert abs(d["offers"][0]["group_scores"]["price"]
               - e["offers"][0]["group_scores"]["price"]) < 0.01  # сами группы не меняются


def test_score_offers_wait_verdict_and_unscored():
    offers = [
        {"id": 3, "platform": "wb", "price_byn": 130.0, "in_stock": 1,
         "rating": 4.0, "reviews_count": 100, "seller_deals": 900},
    ]
    res = score_offers(offers, {3: [100.0, 105.0, 110.0]})  # медиана 105, цена выше на 24%
    assert "ждать" in res["verdict"]["text"]
    assert "медиана 105.0" in res["verdict"]["text"]
    res2 = score_offers([{"id": 4, "platform": "wb", "price_byn": None}, offers[0]])
    assert res2["unscored"] == [4]
    res3 = score_offers([])
    assert res3["verdict"] is None and res3["offers"] == []


def test_score_offers_target_price_beats_wait():
    offers = [{"id": 5, "platform": "wb", "price_byn": 95.0, "in_stock": 1,
               "rating": 4.0, "reviews_count": 100, "seller_deals": 900}]
    res = score_offers(offers, {5: [100.0, 105.0, 110.0]}, target_price_byn=95.0)
    assert "цель достигнута" in res["verdict"]["text"]


# ── app.mlog: модель данных присутствует и исполняется ──────────────

def test_app_mlog_has_shop_ddl_and_it_executes():
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    for table in ("shop_products", "shop_sellers", "shop_offers",
                  "shop_price_history", "shop_watches", "shop_dossiers"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl, table
    stmts = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    shop_stmts = [s for s in stmts if "shop_" in s]
    assert len(shop_stmts) == 7, f"ожидалось 6 таблиц + 1 индекс, найдено {len(shop_stmts)}"
    conn = sqlite3.connect(":memory:")
    for stmt in shop_stmts:
        conn.execute(stmt)  # SQL-опечатка внутри строки app.mlog здесь упадёт
    # UNIQUE(platform, platform_code) работает
    conn.execute(
        "INSERT INTO shop_offers (product_id, platform, platform_code, url) VALUES (1, 'wb', '111', 'u')")
    try:
        conn.execute(
            "INSERT INTO shop_offers (product_id, platform, platform_code, url) VALUES (2, 'wb', '111', 'u2')")
        raise AssertionError("ожидали UNIQUE-нарушение")
    except sqlite3.IntegrityError:
        pass
