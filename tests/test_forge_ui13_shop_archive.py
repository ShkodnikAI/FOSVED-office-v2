#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-13 tests (#216): экран Архив закупок.

Гварды:
- backend GET /api/shop/dossiers: реальные записи shop_dossiers (схема не
  меняется), только format='snapshot'; фильтры year/month/day по created_at
  реально сужают список; q ищет по названию товара (shop_products.title) и
  содержимому snapshot_json; карточки: id, короткое название, дата,
  on_watch по активному shop_watches, url — кликабельная ссылка на
  существующий рендер /shop/dossier/<id>?t=HMAC;
- вход: строка «Архив запросов закупок» из Настроек → Закупки (UI-9) больше
  не тост-заглушка, а openShopArchive(); back — возвращает к закупкам;
- фронт: тот же UI-паттерн, что Архив отчётов — три daterow (год/месяц/день),
  карточки с названием и датой; клик открывает url полного досье.
"""
import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui13-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture()
def shop_schema():
    tables = ["shop_dossiers", "shop_products", "shop_watches"]
    for t in tables:
        _query(f"DROP TABLE IF EXISTS {t}")
    _query("""CREATE TABLE shop_dossiers (id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL, format TEXT NOT NULL, payload TEXT,
        snapshot_json TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))""")
    _query("""CREATE TABLE shop_products (id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL, query_text TEXT)""")
    _query("""CREATE TABLE shop_watches (id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER, status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now')))""")
    yield
    for t in tables:
        _query(f"DROP TABLE IF EXISTS {t}")


def _seed(product_id, title, query, snap_text, created=None, fmt="snapshot"):
    _query("INSERT INTO shop_products (id, title, query_text) VALUES (?, ?, ?)",
           (product_id, title, query))
    if created:
        _query("INSERT INTO shop_dossiers (product_id, format, snapshot_json, created_at) VALUES (?, ?, ?, ?)",
               (product_id, fmt, json.dumps({"product": {"title": title}, "verdict": None, "x": snap_text}, ensure_ascii=False), created))
    else:
        _query("INSERT INTO shop_dossiers (product_id, format, snapshot_json) VALUES (?, ?, ?)",
               (product_id, fmt, json.dumps({"product": {"title": title}, "verdict": None, "x": snap_text}, ensure_ascii=False)))


def test_list_real_records_with_title_and_url(shop_schema):
    _seed(1, "Трусы боксеры", "трусы боксеры мужские", "OFFER-CONTENT-XYZ")
    r = _client().get("/api/shop/dossiers", headers=API_AUTH)
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Трусы боксеры"
    assert it["product_id"] == 1
    assert it["created"] and len(it["created"]) >= 10
    assert "/shop/dossier/" in it["url"] and "?t=" in it["url"]


def test_date_filters_narrow_list(shop_schema):
    _seed(1, "Январский товар", "q1", "s1", created="2026-01-15 10:00:00")
    _seed(2, "Майский товар", "q2", "s2", created="2026-05-15 10:00:00")
    c = _client()
    assert len(c.get("/api/shop/dossiers", headers=API_AUTH).get_json()["items"]) == 2
    y = c.get("/api/shop/dossiers?year=2026", headers=API_AUTH).get_json()["items"]
    assert len(y) == 2
    y = c.get("/api/shop/dossiers?year=2025", headers=API_AUTH).get_json()["items"]
    assert len(y) == 0
    m = c.get("/api/shop/dossiers?month=5", headers=API_AUTH).get_json()["items"]
    assert [i["title"] for i in m] == ["Майский товар"]
    d = c.get("/api/shop/dossiers?day=15", headers=API_AUTH).get_json()["items"]
    assert len(d) == 2
    d = c.get("/api/shop/dossiers?day=1", headers=API_AUTH).get_json()["items"]
    assert len(d) == 0


def test_q_search_over_title_and_snapshot(shop_schema):
    _seed(1, "Трусы боксеры", "трусы мужские", "уникальный-артикул-777")
    _seed(2, "Яхта", "яхта алюминий", "другой снапшот")
    c = _client()
    # по названию товара
    r1 = c.get("/api/shop/dossiers?q=боксеры", headers=API_AUTH).get_json()["items"]
    assert [i["id"] for i in r1] == [1]
    # по содержимому snapshot_json
    r2 = c.get("/api/shop/dossiers?q=артикул-777", headers=API_AUTH).get_json()["items"]
    assert [i["id"] for i in r2] == [1]
    # по product_id как тексту
    r3 = c.get("/api/shop/dossiers?q=2", headers=API_AUTH).get_json()["items"]
    assert [i["id"] for i in r3] == [2]


def test_on_watch_flag_and_non_snapshot_excluded(shop_schema):
    _seed(1, "Товар на контроле", "q", "s")
    _seed(2, "Товар без вотча", "q", "s")
    _query("INSERT INTO shop_dossiers (product_id, format, snapshot_json) VALUES (2, 'txt', '{}')")
    _query("INSERT INTO shop_watches (product_id, status) VALUES (1, 'active')")
    _query("INSERT INTO shop_watches (product_id, status) VALUES (2, 'paused')")
    items = {i["id"]: i for i in _client().get("/api/shop/dossiers", headers=API_AUTH).get_json()["items"]}
    assert items[1]["on_watch"] is True
    assert items[2]["on_watch"] is False
    # format='txt' в список не попадает (только snapshot)
    assert len(items) == 2


def test_ui_entry_row_opens_screen_and_back():
    # вход из Настроек → Закупки → Архив запросов (больше не заглушка-тост)
    assert "if(t.id===\"shopArchiveRow\"){openShopArchive();return}" in INDEX
    assert "Вынесено в отдельный под-наряд" not in INDEX
    # экран + back
    assert 'id="shopArchWrap"' in INDEX and "id=\"shopArchBack\"" in INDEX
    assert "function openShopArchive()" in INDEX and "function shopArchBack()" in INDEX


def test_ui_pattern_matches_reports_archive():
    # тот же UI-паттерн, что Архив отчётов: три строки даты + поиск + карточки
    for el in ("syearRow", "smonthRow", "sdayRow", "shopArchList", "shopArchSearch"):
        assert f'id="{el}"' in INDEX
    # клик карточки — открытие полного досье по url (data-sdossier → window.open)
    assert "data-sdossier" in INDEX and 'window.open(su,"_blank")' in INDEX
    # признак «на контроле» в карточке
    assert "на контроле" in INDEX
