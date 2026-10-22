#!/usr/bin/env python3
"""SHOP-SUPPLY-1 (наряд #421): очередь заданий снабженцу + /supply/next, /supply/result.

Приёмка по чек-листу наряда (раздел «Сделано когда»):
- /supply/next без заголовка/с неверным токеном → 401; fail-closed без
  SUPPLY_AGENT_TOKEN в окружении (урок #325);
- /supply/next с верным токеном и пустой очередью → 200 {"task": null} (п.9);
- /shop/product с площадкой снабженца → collect.<platform>.kind ==
  "supply_pending", в shop_supply_queue строка status=pending;
- задание выдаётся ОДИН раз (pending → dispatched), повторный вызов не
  отдаёт то же задание;
- /supply/result ok:true + офферы → офферы в shop_offers (product_id +
  platform) тем же путём, что у wb (_persist_offers: upsert по
  platform_code + история цен + _upsert_seller);
- /supply/result ok:false kind=antibot_blocked → failed с переданным
  kind/error (диагноз показывает именно его, не supply_pending);
- задание без результата дольше timeout_s → failed kind=task_timeout,
  очередь не блокируется вечно;
- регрессия: wb/onliner/ym не проходят через SUPPLY_AGENT_PLATFORMS —
  collect() вызывается как раньше.

Транспорт и Telegram не используются: collect() подменяется, chat_id
пустой (досье не шлётся), сеть не трогается.
"""
import json
import os
import re
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
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop7-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy import shop_collectors as sc  # noqa: E402
from proxy import shop_supply as sup  # noqa: E402
from proxy import shop_watch as sw  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app
from proxy.core import _query, app  # noqa: E402

TOKEN = "supply-test-token-abc123"
HDR = {"Authorization": f"Bearer {TOKEN}"}


def _shop_ddl():
    """CREATE + идемпотентные ALTER shop_* — ровно как исполняет офис."""
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    creates = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    alters = re.findall(r'try db_execute\("(ALTER TABLE shop_[^"]+)"\)', ddl)
    return [s for s in creates if "shop_" in s] + alters


@pytest.fixture(autouse=True)
def shop_db(monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_FX_RATES_JSON", "{}")
    monkeypatch.setenv("SUPPLY_AGENT_TOKEN", TOKEN)
    monkeypatch.delenv("SUPPLY_TASK_TIMEOUT_S", raising=False)
    db_file = os.path.join(os.environ["DATABASE_PATH"], "fosved.db")
    conn = sqlite3.connect(db_file)
    for stmt in _shop_ddl():
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    conn.commit()
    conn.close()
    sup.ensure_schema()
    for t in ("shop_price_history", "shop_offers", "shop_sellers",
              "shop_products", "shop_watches", "shop_supply_queue",
              "shop_supply_waves"):
        _query(f"DELETE FROM {t}")
    # №598 A.1: supply-ключи (возможности/связь) — в БД, чистим, чтобы
    # тесты файла шли в дефолтном фолбэке 7745 без утечки между тестами
    _query("DELETE FROM system_settings WHERE key IN "
           "('supply_platforms', 'supply_last_seen')")
    # сбор по неснабженческим площадкам подменён честной заглушкой-отказом:
    # сеть не трогается; площадки снабженца до collect() не доходят
    def fake_collect(platform, query, **kw):
        return {"ok": False, "platform": platform,
                "error": "тестовая заглушка", "kind": "test_stub"}
    monkeypatch.setattr(sc, "collect", fake_collect)
    yield
    for t in ("shop_price_history", "shop_offers", "shop_sellers",
              "shop_products", "shop_watches", "shop_supply_queue",
              "shop_supply_waves"):
        _query(f"DELETE FROM {t}")
    _query("DELETE FROM system_settings WHERE key IN "
           "('supply_platforms', 'supply_last_seen')")


@pytest.fixture()
def client():
    return app.test_client()


OFFER = {
    "platform": "ozon", "platform_code": "oz-100500",
    "url": "https://ozon.by/product/oz-100500",
    "title": "Чайник Xiaomi", "price_byn": 149.9, "old_price_byn": 189.0,
    "in_stock": 1, "installment_ok": 0, "rating": 4.8, "reviews_count": 213,
    "seller_name": "Классный продавец", "seller_rating": 4.9,
    "seller_official": 1, "image_url": None,
}


def test_platforms_set_exact():
    """Ровно 7 площадок снабженца; wb/onliner/ym в списке НЕТ (наряд #421)."""
    assert sup.SUPPLY_AGENT_PLATFORMS == {
        "ozon", "21vek", "tmby", "7745", "shopby", "tomas", "unishop"}
    assert not ({"wb", "onliner", "ym"} & sup.SUPPLY_AGENT_PLATFORMS)


def test_next_401_without_or_wrong_token(client, monkeypatch):
    """Без заголовка / с неверным токеном → 401 (чек-лист наряда)."""
    assert client.get("/supply/next").status_code == 401
    r = client.get("/supply/next", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    # fail-closed: SUPPLY_AGENT_TOKEN не задан → 401 даже «с чем-то»
    monkeypatch.delenv("SUPPLY_AGENT_TOKEN", raising=False)
    assert client.get("/supply/next", headers=HDR).status_code == 401


def test_next_empty_queue_task_null(client):
    """Пустая очередь → 200 {"task": null} (п.9 контракта: JSON, не 204)."""
    r = client.get("/supply/next", headers=HDR)
    assert r.status_code == 200
    assert r.get_json() == {"task": None}


def test_shop_product_returns_supply_pending(client, monkeypatch):
    """/shop/product с ozon → collect.ozon.kind == "supply_pending" +
    строка в очереди status=pending (чек-лист наряда).

    Наряд #598 A.1: очередь — только интерсекция
    SUPPLY_AGENT_PLATFORMS ∩ supply_platforms; ozon подводится через
    supply_platforms в БД (как если бы снабженец прислал заголовок)."""
    _query("INSERT OR REPLACE INTO system_settings (key, value) "
           "VALUES ('supply_platforms', 'ozon')")
    monkeypatch.setattr(sw, "PLATFORMS_MVP", ("wb", "ozon", "onliner"))
    r = client.post("/shop/product", json={"query": "чайник xiaomi"})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["ok"] is True
    oz = body["collect"]["ozon"]
    assert oz["kind"] == "supply_pending", oz
    assert oz["ok"] is False
    # task_id в HTTP-ответ не входит (чек-лист требует kind + строку в БД;
    # _collect_summary не трогаем — граница «существующие /shop/*»)
    row = _query("SELECT * FROM shop_supply_queue WHERE product_id=? AND "
                 "platform='ozon' ORDER BY rowid DESC LIMIT 1",
                 (body["product_id"],), fetch=True)
    assert row and row[0]["status"] == "pending"
    assert row[0]["type"] == "search" and row[0]["query"] == "чайник xiaomi"
    assert row[0]["task_id"]
    # регрессия внутри того же ответа: неснабженческие площадки — старый путь
    assert body["collect"]["wb"]["kind"] == "test_stub"
    assert body["collect"]["onliner"]["kind"] == "test_stub"


def test_shop_product_not_ready_platform_skips_queue(client, monkeypatch):
    """Наряд #598 A.1: снабженческая площадка ВНЕ supply_platforms →
    collector_not_ready, задания в очереди НЕТ (честная метка вместо
    «ждёт выполнения» и отказов снабженца collector_not_implemented)."""
    monkeypatch.setattr(sw, "PLATFORMS_MVP", ("wb", "ozon", "onliner"))
    r = client.post("/shop/product", json={"query": "чайник xiaomi"})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    oz = body["collect"]["ozon"]
    assert oz["kind"] == "collector_not_ready", oz
    assert oz["ok"] is False
    row = _query("SELECT COUNT(*) c FROM shop_supply_queue WHERE product_id=? "
                 "AND platform='ozon'", (body["product_id"],), fetch=True)
    assert row[0]["c"] == 0


def test_dequeue_dispatch_once(client):
    """Задание выдаётся один раз: pending → dispatched; повторный вызов
    без нового POST /supply/result — другое задание или {"task": null}."""
    t1 = sup.enqueue_supply_task(1, "ozon", "чайник")
    t2 = sup.enqueue_supply_task(2, "21vek", "утюг")
    r1 = client.get("/supply/next", headers=HDR).get_json()["task"]
    assert r1["task_id"] == t1 and r1["platform"] == "ozon" \
        and r1["type"] == "search" and r1["product_id"] == 1
    assert _query("SELECT status FROM shop_supply_queue WHERE task_id=?",
                  (t1,), fetch=True)[0]["status"] == "dispatched"
    # второе задание — уже ДРУГОЕ (t2), то же самое t1 не отдаётся
    r2 = client.get("/supply/next", headers=HDR).get_json()["task"]
    assert r2["task_id"] == t2
    # очередь пуста — task null, а не повтор
    r3 = client.get("/supply/next", headers=HDR)
    assert r3.get_json() == {"task": None}
    # прямой dequeue после ручного dispatched тоже не отдаёт задание повторно
    _query("UPDATE shop_supply_queue SET status='pending' WHERE task_id=?",
           (t2,))
    got = sup.dequeue_next_task()
    assert got["task_id"] == t2
    assert sup.dequeue_next_task() is None


def test_dequeue_fifo_order():
    """FIFO по created_at: старое задание уходит первым."""
    a = sup.enqueue_supply_task(1, "ozon", "первый")
    b = sup.enqueue_supply_task(2, "shopby", "второй")
    c = sup.enqueue_supply_task(3, "tmby", "третий")
    got = [sup.dequeue_next_task()["task_id"] for _ in range(3)]
    assert got == [a, b, c]


def test_result_ok_true_saves_offers_like_wb(client):
    """ok:true + офферы → shop_offers тем же путём, что wb
    (upsert по (platform, platform_code), история цен, продавец)."""
    t = sup.enqueue_supply_task(77, "ozon", "чайник xiaomi")
    payload = {"task_id": t, "ok": True, "offers": [dict(OFFER)]}
    r = client.post("/supply/result", json=payload, headers=HDR)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["ok"] is True and r.get_json()["offers_saved"] == 1
    row = _query("SELECT * FROM shop_supply_queue WHERE task_id=?",
                 (t,), fetch=True)
    assert row[0]["status"] == "done"
    assert json.loads(row[0]["result_json"])["ok"] is True
    off = _query("SELECT * FROM shop_offers WHERE product_id=77 AND "
                 "platform='ozon'", fetch=True)
    assert len(off) == 1 and off[0]["platform_code"] == "oz-100500"
    assert off[0]["price_byn"] == pytest.approx(149.9)
    assert off[0]["url"] == OFFER["url"]
    hist = _query("SELECT * FROM shop_price_history WHERE offer_id=?",
                  (off[0]["id"],), fetch=True)
    assert len(hist) == 1 and hist[0]["price_byn"] == pytest.approx(149.9)
    seller = _query("SELECT id FROM shop_sellers WHERE platform='ozon'",
                    fetch=True)
    assert seller, "продавец сохранён _upsert_seller (тот же путь, что wb)"
    assert off[0]["seller_id"] == seller[0]["id"]
    # повторный срез тем же оффером — UPSERT, дубля нет, история +1
    r2 = sup.enqueue_supply_task(77, "ozon", "чайник xiaomi")
    client.post("/supply/result", json={"task_id": r2, "ok": True,
                                        "offers": [dict(OFFER)]}, headers=HDR)
    off2 = _query("SELECT * FROM shop_offers WHERE product_id=77 AND "
                  "platform='ozon'", fetch=True)
    assert len(off2) == 1, "тот же platform_code — апдейт, не дубль"
    hist2 = _query("SELECT * FROM shop_price_history WHERE offer_id=?",
                   (off2[0]["id"],), fetch=True)
    assert len(hist2) == 2


def test_result_ok_false_stores_kind_error(client):
    """ok:false kind=antibot_blocked → failed, переданный kind/error в БД —
    диагноз видит именно их, не зависший supply_pending."""
    t = sup.enqueue_supply_task(5, "unishop", "дрель")
    r = client.post("/supply/result", json={
        "task_id": t, "ok": False, "kind": "antibot_blocked",
        "error": "reagate на весь сайт"}, headers=HDR)
    assert r.status_code == 200 and r.get_json()["ok"] is True, \
        "отказ снабженца ПРИНЯТ (это разные ok)"
    row = _query("SELECT * FROM shop_supply_queue WHERE task_id=?",
                 (t,), fetch=True)[0]
    assert row["status"] == "failed"
    assert row["kind"] == "antibot_blocked"
    assert row["error"] == "reagate на весь сайт"
    assert row["result_json"] and "antibot_blocked" in row["result_json"]


def test_result_rejects_bad_shapes(client):
    """Кривые результаты не роняют 500 и не отмечаются успехом."""
    t = sup.enqueue_supply_task(6, "ozon", "чайник")
    # ok:true без offers[] → задание failed kind=result_format
    r = client.post("/supply/result", json={"task_id": t, "ok": True},
                    headers=HDR)
    assert r.status_code == 200 and r.get_json()["ok"] is True
    row = _query("SELECT kind, status FROM shop_supply_queue WHERE task_id=?",
                 (t,), fetch=True)[0]
    assert row["status"] == "failed" and row["kind"] == "result_format"
    # оффер без platform_code/url → failed result_format, батч не писался
    t2 = sup.enqueue_supply_task(6, "ozon", "чайник")
    client.post("/supply/result", json={
        "task_id": t2, "ok": True,
        "offers": [{"platform_code": "", "url": "https://x"}]}, headers=HDR)
    row2 = _query("SELECT kind, status FROM shop_supply_queue WHERE task_id=?",
                  (t2,), fetch=True)[0]
    assert row2["status"] == "failed" and row2["kind"] == "result_format"
    assert not _query("SELECT id FROM shop_offers WHERE product_id=6",
                      fetch=True)


def test_result_unknown_or_closed_task_404(client):
    """Неизвестный task_id и повтор по закрытому заданию → 404
    (дубль POST не перезаписывает честный исход)."""
    r = client.post("/supply/result", json={"task_id": "нет-такого",
                                            "ok": True, "offers": []},
                    headers=HDR)
    assert r.status_code == 404
    t = sup.enqueue_supply_task(8, "ozon", "чайник")
    client.post("/supply/result", json={"task_id": t, "ok": False,
                                        "kind": "antibot_blocked"},
                headers=HDR)
    r2 = client.post("/supply/result", json={"task_id": t, "ok": True,
                                             "offers": [dict(OFFER)]},
                     headers=HDR)
    assert r2.status_code == 404
    row = _query("SELECT status FROM shop_supply_queue WHERE task_id=?",
                 (t,), fetch=True)[0]
    assert row["status"] == "failed", "повтор не перезаписал failed → done"
    # без токена /supply/result тоже 401
    assert client.post("/supply/result", json={"task_id": t}).status_code == 401


def test_result_requires_token(client):
    assert client.post("/supply/result", json={"task_id": "x",
                                               "ok": True}).status_code == 401


def test_expire_stale_pending_and_dispatched():
    """Задание без результата дольше timeout_s → failed kind=task_timeout;
    очередь не блокируется вечно (чек-лист: тест с timeout_s=1 и паузой;
    пауза заменена сдвигом часов очереди на прошлое — детерминизм)."""
    t1 = sup.enqueue_supply_task(11, "ozon", "медленное задание")
    # пауза не нужна: сдвигаем часы очереди на прошлое (эквивалент timeout_s=1 + sleep)
    _query("UPDATE shop_supply_queue SET created_at="
           "datetime('now','-2 seconds'), timeout_s=1 WHERE task_id=?", (t1,))
    got = sup.dequeue_next_task()
    assert got is None, "протухшее pending не выдаётся"
    row = _query("SELECT status, kind FROM shop_supply_queue WHERE task_id=?",
                 (t1,), fetch=True)[0]
    assert row["status"] == "failed" and row["kind"] == "task_timeout"
    # dispatched без результата — тот же исход, от точки выдачи
    t2 = sup.enqueue_supply_task(12, "shopby", "взяли и забыли")
    got2 = sup.dequeue_next_task()
    assert got2["task_id"] == t2
    _query("UPDATE shop_supply_queue SET dispatched_at="
           "datetime('now','-2 seconds'), timeout_s=1 WHERE task_id=?", (t2,))
    assert sup.dequeue_next_task() is None
    row2 = _query("SELECT status, kind FROM shop_supply_queue WHERE task_id=?",
                  (t2,), fetch=True)[0]
    assert row2["status"] == "failed" and row2["kind"] == "task_timeout"
    # свежее задание после двух протухших — выдаётся, очередь жива
    t3 = sup.enqueue_supply_task(13, "tomas", "очередь не блокируется")
    assert sup.dequeue_next_task()["task_id"] == t3


def test_expire_runs_on_enqueue_and_dequeue():
    """expire_stale_tasks вызывается и из enqueue (наряд: dequeue + /shop/
    diagnose — diagnose попадает сюда через ensure_product → enqueue)."""
    t = sup.enqueue_supply_task(14, "ozon", "протухнет до enqueue")
    _query("UPDATE shop_supply_queue SET created_at="
           "datetime('now','-999 seconds'), timeout_s=1 WHERE task_id=?", (t,))
    sup.enqueue_supply_task(15, "ozon", "новое задание")
    row = _query("SELECT status, kind FROM shop_supply_queue WHERE task_id=?",
                 (t,), fetch=True)[0]
    assert row["status"] == "failed" and row["kind"] == "task_timeout"


def test_regression_wb_onliner_ym_not_routed_to_queue(monkeypatch):
    """wb/onliner/ym — collect() вызывается как раньше, очередь не растёт."""
    calls = []

    def spy_collect(platform, query, **kw):
        calls.append(platform)
        if platform == "wb":
            return {"ok": True, "platform": "wb", "url": "x",
                    "offers": [dict(OFFER, platform="wb",
                                    platform_code="wb-1",
                                    url="https://www.wildberries.ru/catalog/1/detail.aspx")]}
        return {"ok": False, "platform": platform,
                "error": "тестовая заглушка", "kind": "test_stub"}
    monkeypatch.setattr(sc, "collect", spy_collect)
    for p in ("wb", "onliner", "ym"):
        r = sc.refresh_product(21, p, "чайник")
        if p == "wb":
            assert r["ok"] is True and r["offers"] == 1
        else:
            assert r["ok"] is False and "task_id" not in r
    assert calls == ["wb", "onliner", "ym"]
    assert not _query("SELECT task_id FROM shop_supply_queue", fetch=True), \
        "неснабженческие площадки не ставят заданий"
    off = _query("SELECT * FROM shop_offers WHERE platform='wb'", fetch=True)
    assert len(off) == 1 and off[0]["product_id"] == 21


def test_supply_route_registered_and_public_routable():
    """Маршруты зарегистрированы; префикс /supply/ в LLM_ROUTES_PREFIXES
    reverse_proxy (иначе фронт-дверь молча отдаёт mlog-404 — класс FO-042)."""
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/supply/next" in rules and "/supply/result" in rules
    src = (REPO_ROOT / "reverse_proxy.py").read_text(encoding="utf-8")
    assert '"/supply/"' in src
