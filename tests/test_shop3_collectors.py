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
         "prices": {"price_min": {"amount": "129.00", "currency": "BYN"},
                    "price_max": {"amount": "140.00", "currency": "BYN"},
                    "offers": {"count": 4}},
         "reviews": {"rating": 48, "count": 12}},
        {"key": "kofemolka-x", "name": "Кофемолка X",
         "prices": {"price_min": {"amount": "89.50", "currency": "BYN"},
                    "offers": {"count": 0}}},
    ]
}

# Живой словарь схем Onliner (наряд #327): подмножество реального словаря
# /schemas 2026-09-24 (полный снапшот 886 схем — в отчёте наряда)
SCHEMAS_PAGE1 = {"schemas": [
    {"key": "mobile", "name": "Мобильные телефоны"},
    {"key": "phoneaccum", "name": "Аккумуляторы для телефонов"},
    {"key": "featurephone", "name": "Кнопочные телефоны"},
    {"key": "lawn", "name": "Семена трав, газон"},
]}
SCHEMAS_PAGE2 = {"schemas": [
    {"key": "notebook", "name": "Ноутбуки"},
    {"key": "notebatteries", "name": "Аккумуляторы для ноутбуков"},
    {"key": "coffee", "name": "Кофеварки и кофемашины"},
    {"key": "headphones", "name": "Наушники и гарнитуры"},
    {"key": "mowers", "name": "Газонокосилки"},
    {"key": "washingmachine", "name": "Стиральные машины"},
    {"key": "vacuumcleaner", "name": "Пылесосы"},
    {"key": "microvawe", "name": "Микроволновые печи"},
]}


# ── тестовая БД: DDL прямо из app.mlog ──────────────────────────────────
def _shop_ddl():
    """CREATE + идемпотентные ALTER shop_* (db_execute И
    db_execute_with_grant — паттерн #329), как исполняет офис."""
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    import re
    stmts = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    stmts += re.findall(r'try db_execute\("(ALTER TABLE shop_[^"]+)"\)', ddl)
    stmts += re.findall(r'try db_execute_with_grant\(grant_issue\([^)]*\), '
                        r'"(ALTER TABLE shop_[^"]+)"\)', ddl)
    return [s for s in stmts if "shop_" in s]


@pytest.fixture(autouse=True)
def shop_db():
    # DB-файл офиса = DATABASE_PATH/fosved.db (proxy/core.py: DB_FILE).
    # Пересоздаём shop_* с ПОЛНОЙ живой схемой: другие тест-модули (UI9)
    # в том же процессе создают урезанные версии этих таблиц — DROP+CREATE
    # гарантирует честную схему независимо от порядка импортов.
    db_file = os.path.join(os.environ["DATABASE_PATH"], "fosved.db")
    conn = sqlite3.connect(db_file)
    for t in ("shop_products", "shop_sellers", "shop_offers",
              "shop_price_history", "shop_watches", "shop_dossiers"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    for stmt in _shop_ddl():
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise  # CREATE уже несёт колонку — ALTER-дубль легален
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
    """Транспорт подменён: URL → снапшот. Никакой сети.
    probe_url (#329) по умолчанию — честная 404-проба (как живой инструмент).
    """
    def fake_fetch(tool, args):
        url = args.get("url", "")
        if tool == "probe_url":
            return {"ok": True, "url": url, "status": 404, "method": "HEAD"}
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
def basket_kv():
    """kv для карты basket-шардов (#329) и словаря Onliner (#327):
    таблица общая с mlog, кэш чистый."""
    _query("CREATE TABLE IF NOT EXISTS system_settings "
           "(key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM system_settings WHERE key IN "
           "('shop_wb_basket_map', 'shop_onliner_schemas')")
    yield
    _query("DELETE FROM system_settings WHERE key IN "
           "('shop_wb_basket_map', 'shop_onliner_schemas')")


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
def _stub_with_schemas(monkeypatch, search_snapshot=None, fail_pages_from=None):
    """Транспорт: /schemas — страницы словаря; search — снапшот.
    fail_pages_from=N — страница N отказывает ОДИН раз (деградация
    сети на первый вызов; следующий вызов продолжает)."""
    pages = [SCHEMAS_PAGE1, SCHEMAS_PAGE2, {"schemas": []}]
    calls = {"schemas": 0}

    def fake(tool, args):
        url = args.get("url", "")
        if "/schemas?page=" in url:
            calls["schemas"] += 1
            n = int(url.rsplit("=", 1)[1])
            if fail_pages_from and n >= fail_pages_from \
                    and calls["schemas"] <= fail_pages_from:
                return {"ok": False, "error": "тест-отказ", "kind": "network"}
            return {"ok": True, "url": url, "status": 200, "data": pages[n - 1]}
        if "search.wb.ru" in url:
            return {"ok": True, "url": url, "status": 200, "data": WB_SNAPSHOT}
        if "catalog.api.onliner.by/search" in url and search_snapshot is not None:
            return {"ok": True, "url": url, "status": 200, "data": search_snapshot}
        if "ozon.by" in url:
            return {"ok": False, "error": "антибот (тест): 307-петля", "kind": "transport"}
        if "onliner" in url:
            return {"ok": True, "url": url, "status": 200, "data": ONLINER_SNAPSHOT}
        return {"ok": False, "error": "неожиданный URL", "kind": "test"}

    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    return calls


# ── Onliner (#327): живая форма + динамическая категория ────────────
def test_onliner_real_form_prices_and_reviews(monkeypatch):
    """Живая форма 2026-09-24: prices.price_min (не prices.price!),
    offers.count, reviews.rating 0..50."""
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "coffeegrinder")
    res = sc.collect_onliner("кофемолка")
    assert res["ok"] is True and len(res["offers"]) == 2
    o = res["offers"][0]
    assert o["price_byn"] == 129.0  # BYN напрямую
    assert o["in_stock"] == 1      # offers.count=4
    assert o["rating"] == 4.8      # 48/10
    assert o["reviews_count"] == 12
    assert o["url"].startswith("https://catalog.onliner.by/")
    assert res["offers"][1]["in_stock"] == 0


def test_onliner_category_from_keyword_map(monkeypatch):
    """Карта синонимов по живому словарю: «телефон» → mobile,
    «газонокосилка» → mowers — значения проверены по словарю."""
    _stub_with_schemas(monkeypatch, search_snapshot=ONLINER_SNAPSHOT)
    res = sc.collect_onliner("телефон")
    assert res["ok"] is True and res["category"] == "mobile"
    res2 = sc.collect_onliner("газонокосилка")
    assert res2["ok"] is True and res2["category"] == "mowers"


def test_onliner_category_fuzzy_match_from_dictionary(monkeypatch):
    """Запрос вне карты — нечёткое совпадение по именам живого словаря;
    аксессуары «…для X» не выигрывают у основной категории."""
    _stub_with_schemas(monkeypatch, search_snapshot=ONLINER_SNAPSHOT)
    assert sc.onliner_resolve_category("микроволновка") == "microvawe"
    assert sc.onliner_resolve_category("стиральная машина") == "washingmachine"
    assert sc.onliner_resolve_category("аккумулятор") != "mobile"


def test_onliner_no_category_is_honest(monkeypatch):
    """Запрос без категории в словаре — честный no_category,
    слаг наугад не подставляем (граница наряда #327)."""
    _stub_with_schemas(monkeypatch)
    res = sc.collect_onliner("трусы")
    assert res["ok"] is False and res["kind"] == "no_category"


def test_onliner_env_category_still_wins(monkeypatch):
    """Legacy env SHOP_ONLINER_CATEGORY приоритетен (обратная совместимость)."""
    _stub_with_schemas(monkeypatch)
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "coffeegrinder")
    calls = 0
    res = sc.collect_onliner("телефон")
    assert res["ok"] is True and res["category"] == "coffeegrinder"


def test_onliner_schema_dict_persists_cursor(monkeypatch):
    """Дозагрузка словаря по курсору: отказ на стр.2 не теряет стр.1,
    следующий вызов продолжает со стр.2 (бюджет таймаутов).
    «газонокосилка»→mowers живёт на стр.2 — на первой её нет."""
    calls = _stub_with_schemas(monkeypatch, fail_pages_from=2)
    assert sc.onliner_resolve_category("газонокосилка") is None  # стр.2 не загружена
    assert calls["schemas"] == 2  # стр.1 получена, стр.2 отказала
    raw = json.loads(_query("SELECT value FROM system_settings WHERE "
                            "key='shop_onliner_schemas'", fetch=True)[0]["value"])
    assert raw["next_page"] == 2 and raw["complete"] is False
    # второй вызов: продолжение — стр.2, стр.3 (пустая) → complete
    assert sc.onliner_resolve_category("газонокосилка") == "mowers"
    raw2 = json.loads(_query("SELECT value FROM system_settings WHERE "
                             "key='shop_onliner_schemas'", fetch=True)[0]["value"])
    assert raw2["complete"] is True


def test_onliner_form_mismatch_is_loud(monkeypatch):
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "mobile")
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: {"ok": True, "data": {"unexpected": 1}})
    res = sc.collect_onliner("x")
    assert res["ok"] is False and res["kind"] == "api_form_mismatch"


# ── 21vek (#328/#406): живой сборщик — SSR-разбор или честный диагноз ──
def test_21vek_live_attempt_honest_refusal(monkeypatch):
    """SPA: страница отдаётся, товары не серверены → recon_unreachable."""
    def fake(tool, args):
        assert tool == "fetch_page" and "21vek.by/search/" in args["url"]
        return {"ok": True, "content": "<html><body>no products here</body></html>"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    res = sc.collect_21vek("чайник")
    assert res["ok"] is False and res["kind"] == "recon_unreachable"
    assert "не серверены" in res["error"]


def test_21vek_parses_jsonld_products(monkeypatch):
    """Если платформа серверит товары (JSON-LD) — сборщик их берёт."""
    ld = ('<script type="application/ld+json">'
          '{"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",'
          '"name":"Чайник Bosch","sku":"TWK7604","offers":{"price":249.9,'
          '"priceCurrency":"BYN","url":"https://www.21vek.by/items/twk7604"}}}]}'
          '</script>')
    def fake(tool, args):
        return {"ok": True, "content": ld}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    res = sc.collect_21vek("чайник")
    assert res["ok"] is True and res["offers"]
    o = res["offers"][0]
    assert o["platform_code"] == "TWK7604" and o["price_byn"] == 249.9
    assert o["seller_name"] == "21vek.by"


def test_tmby_is_honest_unreachable_carrier():
    res = sc.collect("tmby", "x")
    assert res["ok"] is False and res["kind"] == "recon_unreachable"
    assert "tmby" in sc.COLLECTORS


# ── WB basket-шарды и image_url (#329) ──────────────────────────────────
@pytest.fixture(autouse=True)
def no_real_wb_probe(monkeypatch):
    """#408: транспорт проб — прямой HEAD (_wb_direct_probe); в тестах он
    по умолчанию заглушен честным «нет ответа», чтобы ни один тест,
    не занимающийся фото-WB, не ходил в сеть."""
    monkeypatch.setattr(sc, "_wb_direct_probe", lambda url: False)


def _probe_stub(monkeypatch, hit_basket=None):
    """Транспорт-стаб: probe_url даёт 200 только на hit_basket (счётчик
    проб возвращается), fetch_json — живой WB-снапшот."""
    calls = {"n": 0}

    def fake_direct(url):
        """#408: проба — прямой HEAD; 200 только на hit_basket."""
        calls["n"] += 1
        m = __import__("re").search(r"basket-(\d+)\.wbbasket", url)
        return hit_basket is not None and m and int(m.group(1)) == hit_basket

    def fake(tool, args):
        url = args.get("url", "")
        if "search.wb.ru" in url:
            return {"ok": True, "url": url, "status": 200, "data": WB_SNAPSHOT}
        return {"ok": False, "error": "неожиданный URL", "kind": "test"}

    monkeypatch.setattr(sc, "_wb_direct_probe", fake_direct)
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    return calls


def test_wb_basket_for_vol_probes_and_caches(monkeypatch):
    calls = _probe_stub(monkeypatch, hit_basket=28)
    assert sc.wb_basket_for_vol(5460, pid=546061442) == 28
    assert calls["n"] == 28  # перебор 01..28, первый 200 — стоп
    # второй вызов — из кэша, сеть не бьётся
    assert sc.wb_basket_for_vol(5460, pid=546061442) == 28
    assert calls["n"] == 28
    raw = _query("SELECT value FROM system_settings WHERE key='shop_wb_basket_map'",
                 fetch=True)[0]["value"]
    assert "vol:5460" in raw and json.loads(raw)["vol:5460"]["basket"] == 28


def test_wb_basket_for_vol_miss_is_honest_and_cached(monkeypatch):
    calls = _probe_stub(monkeypatch, hit_basket=None)  # все 404
    assert sc.wb_basket_for_vol(12745, pid=1274546138) is None
    assert calls["n"] == 40  # честный перебор всего диапазона 01..40
    assert sc.wb_basket_for_vol(12745, pid=1274546138) is None
    assert calls["n"] == 40  # miss тоже кэшируется — шторма проб нет


def test_wb_image_url_formula(monkeypatch):
    _probe_stub(monkeypatch, hit_basket=28)
    u = sc.wb_image_url(546061442)
    assert u == ("https://basket-28.wbbasket.ru/vol5460/part546061/"
                 "546061442/images/big/1.webp")
    assert sc.wb_image_url(None) is None and sc.wb_image_url("мусор") is None


def test_wb_image_url_without_basket_is_none(monkeypatch):
    _probe_stub(monkeypatch, hit_basket=None)
    assert sc.wb_image_url(1274546138) is None


def test_collect_wb_offers_do_not_block_on_photos(monkeypatch):
    """#408 A.1: сбор НЕ подбирает фото в цикле по товарам (было: до ~4000
    HEAD-проб ДО возврата офферов) — image_url в офферах None, фото
    добираются после сохранения (см. test_refresh_product_persists_image_url)."""
    _probe_stub(monkeypatch, hit_basket=28)
    res = sc.collect_wb("кофемолка", rates={"RUB": 0.034})
    assert res["ok"] is True
    assert res["offers"], "ожидались офферы из WB-снапшота"
    assert all(o["image_url"] is None for o in res["offers"]), (
        "collect_wb больше не подбирает фото в критическом пути")


def test_refresh_product_persists_image_url(monkeypatch):
    _probe_stub(monkeypatch, hit_basket=28)
    _query("INSERT INTO shop_products (title, query_text) VALUES ('т', 'кф')")
    pid = _query("SELECT id FROM shop_products ORDER BY id DESC LIMIT 1",
                 fetch=True)[0]["id"]
    res = sc.refresh_product(pid, "wb", "кофемолка")
    assert res["ok"] is True and res["offers"] == 2
    row = _query("SELECT image_url FROM shop_offers WHERE product_id=? "
                 "ORDER BY id LIMIT 1", (pid,), fetch=True)
    assert row[0]["image_url"] and "basket-28" in row[0]["image_url"]
    # повторный refresh (existing-ветка UPDATE) не теряет image_url
    res2 = sc.refresh_product(pid, "wb", "кофемолка")
    assert res2["ok"] is True
    row2 = _query("SELECT image_url FROM shop_offers WHERE product_id=? "
                  "ORDER BY id LIMIT 1", (pid,), fetch=True)
    assert row2[0]["image_url"] == row[0]["image_url"]


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
    ONLINER_SNAPSHOT["products"][0]["prices"]["price_min"]["amount"] = None
    try:
        r = sc.refresh_product(pid, "onliner", "кофемолка")
        assert r["ok"] is True and r["history_rows"] == 1  # только у второго
    finally:
        ONLINER_SNAPSHOT["products"][0]["prices"]["price_min"]["amount"] = "129.00"


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
