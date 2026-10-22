#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #597: без ежедневных повторов — реестр сообщённого для ЛЗ и событий
брифа, «новых находок нет» вместо пересказа.

Гварды (по наряду):
- A.1: нормализация ключей (repo/release/news: hash и URL без query/fragment);
- A.1: сбой отправки = «не сообщено» (в реестре нет записи);
- A.2: два прогона подряд на одних данных — второй без повторов: модель НЕ
  вызывается, владелец получает «новых находок нет»; пометка [ОБНОВЛЕНИЕ]
  при значимом росте звёзд (≥30% и ≥+500);
- A.3: модель-заглушка вернула абзац со старой ссылкой — его нет в итоге,
  в подвале «скрыто повторов: N»;
- бриф: второй прогон на тех же новостях — «За ночь новых событий нет».
"""
import importlib
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n597-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')
os.environ.setdefault('CRON_SECRET', 'cron-test-secret')

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import reported as rpt  # noqa: E402

CLIENT = flask_app.test_client()


@pytest.fixture()
def clean_registry():
    _query("DELETE FROM reported_items")
    yield
    _query("DELETE FROM reported_items")


# ──────────────────────────── A.1: ключи ────────────────────────────

def test_a1_key_normalization():
    assert rpt.norm_repo_key("OmniGent/Omni") == "repo:omnigent/omni"
    assert rpt.norm_repo_key("  White-Ops/Tool ") == "repo:white-ops/tool"
    assert rpt.norm_release_key("Anthropic/SDK", "v1.15.0") == "release:anthropic/sdk@v1.15.0"
    # новость с хэшем — по хэшу
    assert rpt.norm_news_key(hash_="abc123", url="https://x.io/a?utm=1#top") == "news:abc123"
    # без хэша — нормализованный URL без query/fragment, host в нижнем
    k = rpt.norm_news_key(url="HTTPS://News.Example.io/story/123?utm_source=x#frag")
    assert k == "news:u:https://news.example.io/story/123"
    # хвостовой слэш не создаёт ложной новизны
    assert rpt.norm_news_key(url="https://x.io/a/") == rpt.norm_news_key(url="https://x.io/a")


def test_a1_no_mark_on_send_failure(clean_registry, monkeypatch):
    """Сбой отправки = «не сообщено»: ключи в реестре не появляются."""
    import proxy.lz_github as lz

    def failing_send(owner_id, text, **kw):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(lz, "_github_search", lambda q, per_page=3: [{
        "name": "omnigent/omni", "stars": 1200, "lang": "Python",
        "desc": "agent framework", "url": "https://github.com/omnigent/omni"}])
    monkeypatch.setattr(lz, "_github_releases", lambda repo: [])
    monkeypatch.setattr(lz, "_build_github_queries", lambda: ["q"])
    monkeypatch.setattr(lz, "call_llm", lambda dept, messages: {"reply": "1. 🔥 [x](https://github.com/omnigent/omni)\n\nитог", "provider": "stub"})
    monkeypatch.setattr(lz, "_tg_send_message", failing_send)

    r = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r.status_code in (200, 500)  # сбой отправки может дать 500 — главное запись в реестре
    assert not rpt.is_reported("lz_daily", "repo:omnigent/omni"), \
        "ключ записан в реестр при СБОЕ отправки"


def test_a1_marked_after_successful_send(clean_registry, monkeypatch):
    """Успешная отправка → ключи в реестре."""
    import proxy.lz_github as lz

    monkeypatch.setattr(lz, "_github_search", lambda q, per_page=3: [{
        "name": "omnigent/omni", "stars": 1200, "lang": "Python",
        "desc": "agent framework", "url": "https://github.com/omnigent/omni"}])
    monkeypatch.setattr(lz, "_github_releases", lambda repo: [])
    monkeypatch.setattr(lz, "_build_github_queries", lambda: ["q"])
    monkeypatch.setattr(lz, "call_llm", lambda dept, messages: {
        "reply": "1. 🔥 OmniGent — агентный фреймворк https://github.com/omnigent/omni", "provider": "stub"})
    monkeypatch.setattr(lz, "_tg_send_message", lambda owner_id, text, **kw: 4242)

    r = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert rpt.is_reported("lz_daily", "repo:omnigent/omni")
    lv = rpt.get_last_value("lz_daily", "repo:omnigent/omni")
    assert lv and lv.get("stars") == 1200


# ──────────────────────────── A.2: отбор нового ──────────────────────

def _lz_scan_mocks(monkeypatch, stars=1200):
    import proxy.lz_github as lz
    monkeypatch.setattr(lz, "_github_search", lambda q, per_page=3: [{
        "name": "omnigent/omni", "stars": stars, "lang": "Python",
        "desc": "agent framework", "url": "https://github.com/omnigent/omni"}])
    monkeypatch.setattr(lz, "_github_releases", lambda repo: [])
    monkeypatch.setattr(lz, "_build_github_queries", lambda: ["q"])


def test_a2_two_runs_no_model_on_second(clean_registry, monkeypatch):
    """Два прогона на одних данных: первый — полный отчёт (модель вызвана),
    второй — «новых находок нет», модель НЕ вызывается."""
    import proxy.lz_github as lz

    _lz_scan_mocks(monkeypatch, stars=1200)
    calls = {"n": 0}

    def stub_llm(dept, messages):
        calls["n"] += 1
        return {"reply": "1. 🔥 OmniGent — агентный фреймворк https://github.com/omnigent/omni", "provider": "stub"}

    monkeypatch.setattr(lz, "call_llm", stub_llm)
    monkeypatch.setattr(lz, "_tg_send_message", lambda owner_id, text, **kw: 1)

    r1 = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert calls["n"] == 1
    assert "LZ DAILY REPORT" in r1.get_json()["report"]

    r2 = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r2.status_code == 200, r2.get_data(as_text=True)
    assert calls["n"] == 1, "модель вызвана ВТОРОЙ раз на тех же данных"
    rep2 = r2.get_json()["report"]
    assert "новых находок нет" in rep2 and "просмотрено 1 репозиториев" in rep2, rep2


def test_a2_significant_stars_growth_is_update(clean_registry, monkeypatch):
    """Звёзды +30% и ≥+500 → элемент проходит как [ОБНОВЛЕНИЕ]; меньший рост
    → по-прежнему скрыт."""
    import proxy.lz_github as lz

    # первый прогон: 1000★
    _lz_scan_mocks(monkeypatch, stars=1000)
    monkeypatch.setattr(lz, "call_llm", lambda dept, messages: {
        "reply": "1. 🔥 OmniGent https://github.com/omnigent/omni", "provider": "stub"})
    monkeypatch.setattr(lz, "_tg_send_message", lambda owner_id, text, **kw: 1)
    r1 = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r1.status_code == 200

    # второй прогон: 1600★ (+600 = 60% ≥30% и ≥+500) → ОБНОВЛЕНИЕ, модель вызвана
    _lz_scan_mocks(monkeypatch, stars=1600)
    prompts = {}

    def cap_llm(dept, messages):
        prompts["user"] = messages[-1]["content"]
        return {"reply": "1. 🔥 OmniGent [ОБНОВЛЕНИЕ] https://github.com/omnigent/omni", "provider": "stub"}

    monkeypatch.setattr(lz, "call_llm", cap_llm)
    r2 = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r2.status_code == 200
    assert "[ОБНОВЛЕНИЕ: было 1000★, стало 1600★]" in prompts["user"], prompts["user"][:400]
    assert "новых находок нет" not in r2.get_json()["report"]

    # третий прогон: 1700★ (+100 < 500) → снова «новых находок нет»
    _lz_scan_mocks(monkeypatch, stars=1700)
    calls = {"n": 0}

    def cnt_llm(dept, messages):
        calls["n"] += 1
        return {"reply": "x https://github.com/omnigent/omni", "provider": "stub"}

    monkeypatch.setattr(lz, "call_llm", cnt_llm)
    r3 = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r3.status_code == 200
    assert calls["n"] == 0, "малый рост звёзд не должен пробуждать модель"
    assert "новых находок нет" in r3.get_json()["report"]


# ──────────────────────────── A.3: страховка ─────────────────────────

def test_a3_stale_block_hidden(clean_registry, monkeypatch):
    """Модель вернула абзац со старой ссылкой — его нет в отчёте, в подвале
    «скрыто повторов: N»."""
    import proxy.lz_github as lz

    _lz_scan_mocks(monkeypatch, stars=1200)

    def stub_llm(dept, messages):
        # первый абзац — новый элемент (нет в реестре на момент ответа),
        # второй — пересказ уже сообщённого (mcp-hangar из позавчерашнего)
        return {"reply": ("1. 🔥 OmniGent — агентный фреймворк https://github.com/omnigent/omni\n\n"
                          "2. 📦 mcp-hangar — реестр MCP-серверов https://github.com/tool-hang/mcp-hangar"),
                "provider": "stub"}

    monkeypatch.setattr(lz, "call_llm", stub_llm)
    # помечаем mcp-hangar как сообщённый 2 дня назад
    rpt.mark_reported("lz_daily", "repo:tool-hang/mcp-hangar", {"stars": 300})

    monkeypatch.setattr(lz, "_tg_send_message", lambda owner_id, text, **kw: 1)
    r = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r.status_code == 200, r.get_data(as_text=True)
    report = r.get_json()["report"]
    assert "mcp-hangar" not in report, "старый абзац остался в отчёте"
    assert "скрыто повторов: 1" in report, report[-300:]
    assert "OmniGent" in report, "новый абзац не должен пострадать"


# ──────────────────────────── бриф: события ──────────────────────────

def _seed_news(title, url, hash_):
    _query("INSERT INTO news_cache (source, title, summary, url, category, published, collected, hash) "
           "VALUES ('tass', ?, 's', ?, 'news_ru', datetime('now'), datetime('now'), ?)",
           (title, url, hash_))


def _clear_fresh_news():
    # чужие тесты сеют свежие строки в общую тест-БД — изолируем свои прогоны
    _query("DELETE FROM news_cache WHERE collected > datetime('now', '-12 hours')")


def test_brief_events_second_run_filtered(clean_registry):
    """Бриф: первый прогон включает новость и ПОМЕЧАЕТ её; второй прогон —
    «За ночь новых событий нет»."""
    from proxy.news import get_night_news_items
    _clear_fresh_news()
    _seed_news("CATL построила завод", "https://example.io/catl?utm=1", "h-catl-1")

    text1, items1 = get_night_news_items()
    assert "CATL" in text1 and len(items1) == 1
    # «отправка» прошла успешно → помечаем (так же делает бриф)
    rpt.mark_many("brief_events", [it["key"] for it in items1])

    text2, items2 = get_night_news_items()
    assert "За ночь новых событий нет" in text2 and items2 == [], (text2, items2)


def test_brief_marks_only_after_send(clean_registry, monkeypatch):
    """Бриф: сбой отправки (msg_id falsy) → события НЕ помечаются."""
    import proxy.routes_sched as rs
    _clear_fresh_news()
    _seed_news("DeepSeek раунд", "https://example.io/ds", "h-ds-1")
    _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")
    monkeypatch.setattr(rs, "call_llm", lambda dept, messages: {
        "reply": "ТЕСТ-БРИФ №597", "provider": "stub"})
    monkeypatch.setattr(rs, "_tg_send_formatted", lambda owner_id, text, **kw: None)  # сбой

    CLIENT.post("/scheduler/morning-brief", json={"owner_id": "12345"})
    assert not rpt.is_reported("brief_events", rpt.norm_news_key("h-ds-1")), \
        "событие помечено при сбое отправки брифа"
