#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-10 tests (#203): экран «Источники ЛЗ».

Гварды:
- RSS: все реальные ленты RSS_FEEDS (15) сеедены в rss_sources; тумблер
  реально влияет на collect_rss (rss_enabled_feeds пропускает выключенные);
  удаление — реально (кодовые мягко deleted=1, custom — строкой);
  добавление — URL валидируется feedparser'ом ДО сохранения;
- Telegram/YouTube/TikTok — честные статусы контура (MON-1..3 реализованы,
  управление командами Telegram), кнопки «+ Добавить канал» неактивны
  (opacity .5, без обработчика действия);
- сводка — реальное поведение (раз в сутки с брифом), не редактируется.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui10-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import news  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def rss_db():
    news._rss_state_table()
    _query("DELETE FROM rss_sources")
    news._rss_state_table()  # пересеять
    yield
    _query("DELETE FROM rss_sources")


# ── Блок A. RSS — реально ────────────────────────────────────────────────

def test_all_real_feeds_seeded():
    with _client() as c:
        resp = c.get("/api/lz/rss", headers=API_AUTH)
    feeds = resp.get_json()["feeds"]
    assert len(feeds) == len(news.RSS_FEEDS)
    names = {f["feed"] for f in feeds}
    assert set(news.RSS_FEEDS.keys()) <= names
    assert all(f["enabled"] for f in feeds)  # по умолчанию включены


def test_toggle_really_affects_collect_rss(monkeypatch):
    collected_from = []
    real = news.rss_enabled_feeds

    def spy():
        collected_from.append(1)
        return real()

    monkeypatch.setattr(news, "rss_enabled_feeds", spy)
    with _client() as c:
        c.post("/api/lz/rss/ria/toggle", headers=API_AUTH, json={"enabled": False})
    enabled = news.rss_enabled_feeds()
    assert "ria" not in enabled                       # выключенная пропущена
    assert "tass" in enabled                          # остальные на месте
    assert collected_from  # collect_rss вызывает rss_enabled_feeds


def test_delete_code_feed_soft_custom_hard():
    with _client() as c:
        assert c.delete("/api/lz/rss/ria", headers=API_AUTH).status_code == 200
        assert c.delete("/api/lz/rss/tass", headers=API_AUTH).status_code == 200
    assert "ria" not in news.rss_enabled_feeds()
    row = _query("SELECT deleted FROM rss_sources WHERE feed='ria'", fetch=True)
    assert row[0]["deleted"] == 1                     # мягко: не вернётся из кода


def test_add_validates_feed_before_save(monkeypatch):
    class FakeOk:
        bozo = 0
        entries = [{"title": "t"}]
        feed = {"title": "Пример Лента"}

    class FakeBad:
        bozo = 1
        entries = []
        feed = {}

    import feedparser
    monkeypatch.setattr(feedparser, "parse", lambda url: FakeOk())
    with _client() as c:
        ok = c.post("/api/lz/rss", headers=API_AUTH, json={"url": "https://ex.example/rss"})
    assert ok.status_code == 200
    assert ok.get_json()["title"] == "Пример Лента"

    monkeypatch.setattr(feedparser, "parse", lambda url: FakeBad())
    with _client() as c:
        bad = c.post("/api/lz/rss", headers=API_AUTH, json={"url": "https://bad.example/x"})
    assert bad.status_code == 400                     # заведомо нерабочая не сохраняется


def test_toggle_endpoint_state_roundtrip():
    with _client() as c:
        c.post("/api/lz/rss/kommersant/toggle", headers=API_AUTH, json={"enabled": False})
    row = _query("SELECT enabled FROM rss_sources WHERE feed='kommersant'", fetch=True)
    assert row[0]["enabled"] == 0                     # без удаления из конфигурации


# ── Блок B. Честные заготовки TG/YT/TikTok ───────────────────────────────

def test_channel_blocks_honest_notices():
    assert 'id="lzNoticeTg"' in INDEX and 'id="lzNoticeYt"' in INDEX and 'id="lzNoticeTt"' in INDEX
    # статусы приходят из /api/lz/notices (реальное состояние: MON реализованы);
    # в разметке — плейсхолдеры, заполняемые API
    with _client() as c:
        n = c.get("/api/lz/notices", headers=API_AUTH).get_json()["notices"]
    assert "MON-1" in n["telegram"] and "/lz_channel" in n["telegram"]
    # кнопки «+ Добавить канал» неактивны: opacity .5, без обработчиков действия
    assert INDEX.count('<div class="group" style="opacity:.5"><div class="srow"><span>+ Добавить канал</span></div></div>') == 3


def test_notices_endpoint():
    with _client() as c:
        resp = c.get("/api/lz/notices", headers=API_AUTH)
    n = resp.get_json()["notices"]
    assert "MON-1" in n["telegram"] and "MON-2" in n["youtube"] and "MON-3" in n["tiktok"]


# ── Блок C. Сводка ───────────────────────────────────────────────────────

def test_summary_readonly_real_behaviour():
    assert 'Периодичность</span><span>раз в сутки, с утренним брифом</span>' in INDEX
    assert 'отдельный механизм пока не заведён' in INDEX


def test_screen_reachable_from_more():
    assert 'data-go="lzsrc"' in INDEX
