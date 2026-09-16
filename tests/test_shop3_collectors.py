#!/usr/bin/env python3
"""SHOP-3 tests (диспатч #172): сборщики площадок + хранилище + склейка.

Снапшоты — по ЖИВЫМ ответам, снятым из песочницы 2026-09-16 (см. докстринг
proxy/shop_collectors.py): WB v4 (sizes[].price в копейках, feedbacks,
supplier*) и Onliner catalog (цены BYN строкой; форма по памяти —
оборонительный парсер + kind:"api_form_mismatch").
Kufar ВЫВЕДЕН из реестра по решению владельца 2026-09-16 — его парсер
и снапшоты удалены; регресс «collect('kufar') → no_collector» остался.
Ozon — каркас за антиботом (TLS-фингерпринт + JS-челлендж, живые пробы
2026-09-16): транспортный отказ честно пробрасывается, форма не снята
→ kind:"api_form_unknown". 21vek — честный каркас not_implemented_live.
FX: env SHOP_FX_RATES_JSON → кэш system_settings → egress НБРБ/er-api →
устаревший кэш → аварийные константы (fx_rates()).

Хранилище: DDL извлекается прямо из app.mlog (гвард SHOP-1) и исполняется
в тестовой БД DATABASE_PATH — upsert/история проверяются на живой схеме.
Транспорт подменяется через sc.FETCH_JSON_FN (никакой сети в тестах).
"""
import json
import os
import sqlite3
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
        if "ozon.by" in url:
            # живое поведение 2026-09-16: антибот → честный отказ транспорта
            return {"ok": False, "url": url, "error": "антибот (тест): 307-петля",
                    "kind": "transport"}
        if "onliner" in url:
            return {"ok": True, "url": url, "status": 200, "data": ONLINER_SNAPSHOT}
        return {"ok": False, "error": "неожиданный URL", "kind": "test"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake_fetch)


@pytest.fixture(autouse=True)
def fx_env(monkeypatch):
    """Фиксированный курс для модуля: сбор детерминирован, FX-egress
    из тестов не дёргается (в FX-тестах переопределяется)."""
    monkeypatch.setenv("SHOP_FX_RATES_JSON", '{"RUB": 0.034}')


@pytest.fixture()
def fx_clean():
    """Чистый kv system_settings для FX-тестов (таблица — общая с mlog)."""
    _query("CREATE TABLE IF NOT EXISTS system_settings "
           "(key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM system_settings WHERE key='shop_fx_rates'")
    yield
    _query("DELETE FROM system_settings WHERE key='shop_fx_rates'")


def _no_net(tool, args):
    raise AssertionError("сеть не должна зваться")


# ── canonical_url ───────────────────────────────────────────────────────
def test_canonical_url_strips_tracking():
    u = sc.canonical_url("https://www.ozon.by/product/1?utm_source=t&gclid=x&id=2")
    assert u == "https://www.ozon.by/product/1?id=2"
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
    # пустой rates = конвертации нет (валюта вне курса) → честный None;
    # неявный rates=None теперь тянет fx_rates() (env/кэш/egress/константы)
    res = sc.collect_wb("кофемолка", rates={})
    assert res["ok"] is True
    assert res["offers"][0]["price_byn"] is None  # RUB без курса → не выдумываем
    assert res["offers"][0]["currency_note"] == "RUB"


def test_wb_form_mismatch_is_loud(monkeypatch):
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "data": {"unexpected": 1}})
    res = sc.collect_wb("x")
    assert res["ok"] is False and res["kind"] == "api_form_mismatch"


# ── Ozon: каркас за антиботом (живые пробы 2026-09-16, см. модуль) ──────
def test_ozon_transport_refusal_propagates_with_antibot_note(monkeypatch):
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": False, "error": "fetch: 307 loop",
                                      "kind": "transport"})
    res = sc.collect_ozon("боксеры")
    assert res["ok"] is False and res["kind"] == "transport"
    assert "антибот Ozon" in res["error"] and "ozon.by" in res["url"]


def test_ozon_silent_refusal_defaults_to_antibot_blocked(monkeypatch):
    monkeypatch.setattr(sc, "FETCH_JSON_FN", lambda t, a: {"ok": False, "error": ""})
    res = sc.collect_ozon("боксеры")
    assert res["ok"] is False and res["kind"] == "antibot_blocked"
    assert res["error"].startswith("антибот Ozon")  # без слипшегося разделителя


def test_ozon_transport_ok_but_form_unknown(monkeypatch):
    """Если egress однажды пройдёт, но форма не снята — честный отказ,
    парсер вслепую не пишем (дисциплина form-истины SHOP-3)."""
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "data": {"widgetStates": {}}})
    res = sc.collect_ozon("боксеры")
    assert res["ok"] is False and res["kind"] == "api_form_unknown"


def test_kufar_removed_ozon_registered():
    """Решение владельца 2026-09-16: Kufar выведен, Ozon в реестре."""
    assert "ozon" in sc.COLLECTORS
    res = sc.collect("kufar", "x")
    assert res["ok"] is False and res["kind"] == "no_collector"


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


def test_onliner_offer_without_price_skips_history_row(monkeypatch):
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "coffeegrinder")
    pid = _make_product()
    ONLINER_SNAPSHOT["products"][0]["prices"]["price"]["amount"] = None
    try:
        r = sc.refresh_product(pid, "onliner", "кофемолка")
        assert r["ok"] is True and r["history_rows"] == 1  # только у второго
    finally:
        ONLINER_SNAPSHOT["products"][0]["prices"]["price"]["amount"] = "129.00"


def test_score_product_end_to_end(monkeypatch):
    """SHOP-1 + SHOP-3: сбор → БД → вердикт движка."""
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "coffeegrinder")
    pid = _make_product()
    sc.refresh_product(pid, "wb", "кофемолка", rates={"RUB": 0.034})
    sc.refresh_product(pid, "onliner", "кофемолка")
    res = sc.score_product(pid)
    assert res["ok"] is True
    scored = res["scored"]
    assert len(scored["offers"]) == 4  # 2 WB + 2 Onliner, все с ценой
    assert scored["verdict"] is not None and scored["verdict"]["text"]
    # бейдж «дешевле всех» указывает на реальный оффер из БД
    ids = {o["id"] for o in scored["offers"]}
    assert scored["badges"]["cheapest"] in ids


# ── FX: env → кэш → НБРБ → er-api → устаревший кэш → константы ──────────
NBRB_SNAPSHOT = [
    {"Cur_Abbreviation": "RUB", "Cur_Scale": 100, "Cur_OfficialRate": 3.45},
    {"Cur_Abbreviation": "USD", "Cur_Scale": 1, "Cur_OfficialRate": 3.05},
]


def test_fx_env_override_wins(monkeypatch, fx_clean):
    monkeypatch.setenv("SHOP_FX_RATES_JSON", '{"RUB": 0.05}')
    monkeypatch.setattr(sc, "FETCH_JSON_FN", _no_net)
    assert sc.fx_rates() == {"RUB": 0.05}


def test_fx_nbrb_fetched_and_cached(monkeypatch, fx_clean):
    monkeypatch.delenv("SHOP_FX_RATES_JSON", raising=False)
    calls = []

    def fake(tool, args):
        calls.append(args.get("url", ""))
        return {"ok": True, "data": NBRB_SNAPSHOT}

    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    rates = sc.fx_rates()
    assert rates["RUB"] == pytest.approx(0.0345, abs=1e-6)
    assert rates["USD"] == pytest.approx(3.05, abs=1e-6)
    assert any("nbrb.by" in u for u in calls)
    row = _query("SELECT value FROM system_settings WHERE key='shop_fx_rates'",
                 fetch=True)
    assert row and json.loads(row[0]["value"])["source"] == "nbrb"


def test_fx_fresh_cache_skips_network(monkeypatch, fx_clean):
    monkeypatch.delenv("SHOP_FX_RATES_JSON", raising=False)
    sc._fx_cache_write({"RUB": 0.034}, "test")
    monkeypatch.setattr(sc, "FETCH_JSON_FN", _no_net)
    assert sc.fx_rates() == {"RUB": 0.034}


def test_fx_stale_cache_on_egress_failure(monkeypatch, fx_clean):
    monkeypatch.delenv("SHOP_FX_RATES_JSON", raising=False)
    sc._setting_set(sc.FX_CACHE_KEY, json.dumps(
        {"rates": {"RUB": 0.034}, "source": "test",
         "fetched_at": time.time() - 7 * 3600}))
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": False, "kind": "network"})
    assert sc.fx_rates() == {"RUB": 0.034}


def test_fx_builtin_constants_last_resort(monkeypatch, fx_clean):
    monkeypatch.delenv("SHOP_FX_RATES_JSON", raising=False)
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": False, "kind": "network"})
    assert sc.fx_rates() == sc.FX_FALLBACK
