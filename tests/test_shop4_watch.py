#!/usr/bin/env python3
"""SHOP-4 tests (диспатч #172): вотчлист + алерты (на моках).

Покрытие:
- ensure_product: товар + первичный сбор двух площадок;
- add_watch: один активный watch на продукт (старый уходит в paused);
- target-цель: алерт при rank_price <= цели; повтор с той же ценой —
  НЕ дублируется; снижение цены — новый алерт (дельта);
- настоящая скидка ≥ порога — алерт; фейковая — молчание;
- in-stock переход out → in — алерт, повтор — молчание;
- kill-switch SHOP_ENABLED=0 — такт полностью молчит;
- площадки недоступны (transport ok:false) — такт живёт, алерт по БД.
Транспорт и отправка TG подменены (никакой сети и Telegram).
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
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop4-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy import shop_collectors as sc  # noqa: E402
from proxy import shop_watch as sw  # noqa: E402
from proxy.core import _query  # noqa: E402

WB_SNAP = {
    "products": [{
        "id": 414389121, "name": "Кофемолка SM", "rating": 5, "reviewRating": 4.8,
        "feedbacks": 100, "totalQuantity": 5, "supplier": "Маг", "supplierId": 1,
        "supplierRating": 4.9,
        "sizes": [{"price": {"basic": 100000, "product": 70000}}],
    }]
}

PLATFORMS_REAL = tuple(sw.PLATFORMS_MVP)  # до фикстурных подмен (регресс внизу)

ONLINER_SNAP = {
    "products": [{
        "key": "kofemolka-sm-200", "name": "Кофемолка SM-200",
        "full_name": "Кофемолка SM-200",
        "prices": {"price": {"amount": "220.00", "currency": "BYN"},
                   "offers_count": 3},
    }]
}


def _shop_ddl():
    """CREATE + идемпотентные ALTER shop_* — ровно как исполняет офис."""
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    import re
    creates = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    alters = re.findall(r'try db_execute\("(ALTER TABLE shop_[^"]+)"\)', ddl)
    return [s for s in creates if "shop_" in s] + alters


@pytest.fixture(autouse=True)
def shop_db(monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    # по умолчанию FX выключен явно ({} = пустой dict-выключатель);
    # тесты, которым нужен курс, ставят свой SHOP_FX_RATES_JSON
    monkeypatch.setenv("SHOP_FX_RATES_JSON", "{}")
    db_file = os.path.join(os.environ["DATABASE_PATH"], "fosved.db")
    conn = sqlite3.connect(db_file)
    for stmt in _shop_ddl():
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            # ALTER не идемпотентен между тестами одной сессии:
            # дубликат колонки = таблица уже достроена, это ок
            if "duplicate column name" not in str(e):
                raise
    conn.commit()
    conn.close()
    for t in ("shop_price_history", "shop_offers", "shop_sellers",
              "shop_products", "shop_watches"):
        _query(f"DELETE FROM {t}")
    # транспорт: WB 700.00 RUB → без курса price_byn=None; Onliner 220 BYN.
    # КУФАР ВЫВЕДЕН (решение владельца 2026-09-16): такт ходит по
    # PLATFORMS_MVP=("wb","ozon"), ozon — каркас за антиботом (отказ).
    # Для конвейерных тестов второй РАБОЧЕЙ площадкой подставляем onliner
    # (реальный парсер) через подмену PLATFORMS_MVP.
    monkeypatch.setenv("SHOP_ONLINER_CATEGORY", "coffeegrinder")
    monkeypatch.setattr(sw, "PLATFORMS_MVP", ("wb", "onliner"))

    def fake_fetch(tool, args):
        url = args.get("url", "")
        if "search.wb.ru" in url:
            return {"ok": True, "data": WB_SNAP}
        if "ozon.by" in url:
            return {"ok": False, "error": "антибот (тест): 307-петля",
                    "kind": "transport"}
        if "onliner" in url:
            return {"ok": True, "data": ONLINER_SNAP}
        return {"ok": False, "error": "неожиданный URL", "kind": "test"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake_fetch)
    yield
    for t in ("shop_price_history", "shop_offers", "shop_sellers",
              "shop_products", "shop_watches"):
        _query(f"DELETE FROM {t}")


@pytest.fixture()
def sent():
    return []


@pytest.fixture(autouse=True)
def capture_send(monkeypatch, sent):
    monkeypatch.setattr(sw, "_send_alert", lambda text: sent.append(text) or True)
    return sent


# WB без курса → price None; чтобы rank_price считался, Onliner-цена работает.
# Для target-теста нужен оффер с ценой: даём курс через env-снимок.

def _add_product_with_wb_rate(monkeypatch, rate=None):
    if rate:
        monkeypatch.setenv("SHOP_FX_RATES_JSON", json.dumps({"RUB": rate}))
    else:
        # {} — явный выключатель конвертации (без egress и кэша)
        monkeypatch.setenv("SHOP_FX_RATES_JSON", "{}")
    pid, details = sw.ensure_product("кофемолка")
    return pid


def test_ensure_product_creates_and_collects(monkeypatch):
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    row = _query("SELECT * FROM shop_products WHERE id=?", (pid,), fetch=True)
    assert row[0]["query_text"] == "кофемолка"
    offers = _query("SELECT * FROM shop_offers WHERE product_id=?", (pid,), fetch=True)
    assert len(offers) == 2  # WB + Onliner
    prices = sorted(o["price_byn"] for o in offers)
    assert prices == pytest.approx([700.0 * 0.034, 220.0], abs=0.01)


def test_add_watch_single_active_per_product():
    pid, _ = sw.ensure_product("кофемолка")
    w1 = sw.add_watch(pid, target_price_byn=200)
    w2 = sw.add_watch(pid, target_price_byn=150)
    assert w1 != w2
    active = _query("SELECT id FROM shop_watches WHERE status='active'", fetch=True)
    assert len(active) == 1 and active[0]["id"] == w2
    paused = _query("SELECT id FROM shop_watches WHERE status='paused'", fetch=True)
    assert len(paused) == 1 and paused[0]["id"] == w1


def test_target_alert_no_dup_and_delta(monkeypatch, sent):
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    sw.add_watch(pid, target_price_byn=30)
    r1 = sw.tick_shop_watches()
    assert r1["ok"] is True and r1["alerts"] == 1, r1
    assert len(sent) == 1 and "цель" in sent[0]
    # повторный такт, цена не изменилась → дубликата нет
    r2 = sw.tick_shop_watches()
    assert r2["alerts"] == 0 and len(sent) == 1
    # цена снизилась (630 RUB × 0.034 = 21.42) → дельта-алерт
    WB_SNAP["products"][0]["sizes"][0]["price"]["product"] = 63000
    try:
        r3 = sw.tick_shop_watches()
        assert r3["alerts"] == 1 and len(sent) == 2
        assert "21.42" in sent[1]
    finally:
        WB_SNAP["products"][0]["sizes"][0]["price"]["product"] = 70000


def test_target_not_reached_no_alert(monkeypatch, sent):
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    sw.add_watch(pid, target_price_byn=10)  # цель слишком низкая
    r = sw.tick_shop_watches()
    assert r["alerts"] == 0 and sent == []


def test_discount_alert_real_not_fake(monkeypatch, sent):
    # лучший оффер — WB (23.8 BYN при курсе 0.034); историю строим ЕМУ:
    # медиана 34 BYN, текущая 23.8 → честные −30%
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    best = _query("SELECT id FROM shop_offers WHERE platform='wb' ORDER BY id LIMIT 1",
                  fetch=True)[0]["id"]
    for p in (35.0, 34.0, 33.0):
        _query("INSERT INTO shop_price_history (offer_id, price_byn) VALUES (?, ?)",
               (best, p))
    sw.add_watch(pid, discount_pct=10)
    r = sw.tick_shop_watches()
    assert r["alerts"] == 1, (r, sent)
    assert "скидка" in sent[0]
    # фейковая не алертится: старая цена завышена, честной скидки нет
    sent.clear()
    _query("UPDATE shop_watches SET last_alert_json=NULL")
    _query("DELETE FROM shop_price_history WHERE offer_id=?", (best,))
    for p in (23.9, 23.85, 23.82):
        _query("INSERT INTO shop_price_history (offer_id, price_byn) VALUES (?, ?)",
               (best, p))
    r2 = sw.tick_shop_watches()
    assert r2["alerts"] == 0 and sent == []


def test_in_stock_transition_alert(monkeypatch, sent):
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    sw.add_watch(pid, alert_in_stock=True)
    # такт 1: всё в наличии → состояние True зафиксировано, алерта нет
    r1 = sw.tick_shop_watches()
    assert r1["alerts"] == 0
    # такт 2: WB распродан, Onliner снял с показа; оффер Onliner в БД тоже
    # помечаем out (пустая выдача не удаляет офферы — обновления нет)
    WB_SNAP["products"][0]["totalQuantity"] = 0
    saved_products = ONLINER_SNAP["products"]
    ONLINER_SNAP["products"] = []
    _query("UPDATE shop_offers SET in_stock=0 WHERE platform='onliner'")
    try:
        r2 = sw.tick_shop_watches()
        assert r2["alerts"] == 0
        # такт 3: товар вернулся → переход in → алерт
        WB_SNAP["products"][0]["totalQuantity"] = 5
        ONLINER_SNAP["products"] = saved_products
        r3 = sw.tick_shop_watches()
        assert r3["alerts"] == 1 and "в наличии" in sent[-1]
        # такт 4: всё ещё в наличии → молчание
        r4 = sw.tick_shop_watches()
        assert r4["alerts"] == 0
    finally:
        WB_SNAP["products"][0]["totalQuantity"] = 5
        ONLINER_SNAP["products"] = saved_products


def test_kill_switch_silences_everything(monkeypatch, sent):
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    sw.add_watch(pid, target_price_byn=999)
    monkeypatch.setenv("SHOP_ENABLED", "0")
    r = sw.tick_shop_watches()
    assert r["ok"] is False and r["kind"] == "disabled"
    assert sent == []
    assert sw.enabled() is False


def test_transport_down_tick_survives(monkeypatch, sent):
    pid = _add_product_with_wb_rate(monkeypatch, 0.034)
    sw.add_watch(pid, target_price_byn=220)

    def dead_fetch(tool, args):
        return {"ok": False, "error": "сеть недоступна", "kind": "network"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", dead_fetch)
    r = sw.tick_shop_watches()
    # сбор упал, но скоринг по сохранённым в БД офферам жив → алерт по цели
    assert r["ok"] is True and r["alerts"] == 1
    assert "цель" in sent[0]


def test_platforms_mvp_kufar_out_ozon_in():
    """Решение владельца 2026-09-16: Kufar выведен из такта, Ozon в такте
    (каркас за антиботом — отказ честный, такт живёт)."""
    assert PLATFORMS_REAL == ("wb", "ozon")


def test_dashboard_doc_has_shop_cron_and_switch():
    # render.yaml с 2026-09-20 управляет только стейджингом (#182, #276);
    # кроны настроены в дашборде — канонический инвентарь: docs/render-dashboard.md
    txt = (REPO_ROOT / "docs" / "render-dashboard.md").read_text(encoding="utf-8")
    assert "shop-tick" in txt and "/cron/shop-tick?secret=" in txt
    assert "0 */6 * * *" in txt  # 4 раза/сутки
    assert "SHOP_ENABLED" in txt
