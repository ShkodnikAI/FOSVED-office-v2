#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #424 (P1): восстановление регулярного сбора новостей.

Гварды:
- RSS_FEEDS: Reuters удалён (мёртвая, живая проверка 2026-09-29), замена
  Guardian World; 5 белорусских лент news_by (гос + независимые);
- DEPT_CATEGORIES: osp видит news_by (smoke-кейс 2 наряда: /news/fresh
  по Беларуси возвращает news_by-записи);
- dept/schedules.mlog: слот collect-news в реестре нативного крона;
- dept/scheduler.mlog: целевой паттерн CollectNewsSlot — HTTP-вызов
  /cron/collect-news с секретом (по образцу NightTickSlot);
- docs/render-dashboard.md: ложная строка «collect-news — нет источников»
  снята, таблица native cron содержит слот.

Мутационные проверки (команды в отчёте PR): возврат Reuters, снятие
news_by-категории, удаление слота из реестра, флип enabled: false —
каждая валит минимум один тест этого файла.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_PY = open(os.path.join(REPO_ROOT, "proxy", "news.py"), encoding="utf-8").read()
SCHEDULES_MLOG = open(os.path.join(REPO_ROOT, "dept", "schedules.mlog"), encoding="utf-8").read()
SCHEDULER_MLOG = open(os.path.join(REPO_ROOT, "dept", "scheduler.mlog"), encoding="utf-8").read()
DASHBOARD_MD = open(os.path.join(REPO_ROOT, "docs", "render-dashboard.md"), encoding="utf-8").read()


def test_reuters_removed_replacement_present():
    # живая проверка 2026-09-29: feeds.reuters.com не отвечает (ConnectionError)
    assert '"reuters"' not in NEWS_PY, "мёртвый Reuters должен быть удалён"
    # URL может оставаться только внутри # комментария (факт живой проверки)
    for line in NEWS_PY.splitlines():
        if "feeds.reuters.com" in line:
            assert line.strip().startswith("#"), f"reuters вне комментария: {line.strip()}"
    assert "theguardian.com/world/rss" in NEWS_PY, "замена news_en — Guardian World"
    assert '"guardian_world"' in NEWS_PY


def test_by_feeds_present_and_categorized():
    for feed_id, url in (
        ("belta", "https://www.belta.by/rss"),
        ("sputnik_by", "https://sputnik.by/export/rss2/archive/index.xml"),
        ("minsknews", "https://minsknews.by/feed/"),
        ("zerkalo", "https://news.zerkalo.io/rss/all.rss"),
        ("onliner", "https://people.onliner.by/feed"),
    ):
        assert f'"{feed_id}"' in NEWS_PY, f"белорусская лента {feed_id} обязана быть"
        seg = NEWS_PY[NEWS_PY.index(f'"{feed_id}"'):]
        seg = seg[: seg.index("},") + 2]
        assert '"category": "news_by"' in seg, f"{feed_id}: категория news_by"
        assert url in seg, f"{feed_id}: URL"
    # баланс гос/независимых зафиксирован в комментарии
    assert "государственные" in NEWS_PY and "независимые" in NEWS_PY


def test_osp_sees_news_by():
    assert '"osp": ("news_ru", "geopolitics", "news_en", "news_by")' in NEWS_PY


def test_slot_in_registry():
    assert '{ name: "collect-news"' in SCHEDULES_MLOG
    seg = SCHEDULES_MLOG[SCHEDULES_MLOG.index('{ name: "collect-news"'):]
    seg = seg[: seg.index("}") + 1]
    assert 'cron: "0 */6 * * *"' in seg, "частота — раз в 6 часов (лимиты Tavily)"
    assert 'tz: "Europe/Moscow"' in seg
    assert 'target: "CollectNewsSlot"' in seg
    assert 'catch_up: "skip"' in seg, "пробуждение free-инстанса не догоняет окна"
    assert "enabled: true" in seg, "прямое решение владельца в тексте наряда #424"
    # целевой расклад в шапке реестра — 8 слотов
    assert "8 слотов" in SCHEDULES_MLOG


def test_collect_news_slot_pattern():
    assert "pattern CollectNewsSlot" in SCHEDULER_MLOG
    body = SCHEDULER_MLOG[SCHEDULER_MLOG.index("pattern CollectNewsSlot"):]
    body = body[: body.index("\npattern ")]
    assert "http://127.0.0.1:4000/cron/collect-news" in body
    assert 'env("CRON_SECRET")' in body, "секрет — как в NightTickSlot"
    assert "http_get" in body
    assert "AuditLog" in body


def test_dashboard_fixed():
    assert "collect-news — нет источников" not in DASHBOARD_MD, "ложное утверждение снято"
    assert "| collect-news |" in DASHBOARD_MD, "слот в таблице native cron"
    assert "`0 */6 * * *`" in DASHBOARD_MD


def test_collect_route_untouched():
    # роут /cron/collect-news существовал и остаётся — наряд только возвращает слот
    assert 'app.route("/cron/collect-news", methods=["GET"])' in open(
        os.path.join(REPO_ROOT, "proxy", "routes_tail.py"), encoding="utf-8"
    ).read()
