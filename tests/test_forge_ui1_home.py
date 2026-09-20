#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-1 tests (#194): экран «Главная» по макету.

Гварды чек-листа (проверяемые статически):
- логотип-кроп .avatar + подпись office;
- герой с явным белым текстом и затемнением;
- stats-карточки с градиентным числом;
- порядок навигации ровно 5: Главная, Наряды, Чат, Настройки, Ещё (без Архива);
- иконки дока — SVG (не эмодзи);
- маппинг реальных API (kpis.tasks_week/cost_today, /api/narads, /api/archive) —
  расхождение форматов задокументировано прямо в JS.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = (REPO_ROOT / "miniapp" / "index.html").read_text(encoding="utf-8")


def test_topbar_avatar_and_office():
    assert '.avatar{width:36px;height:36px;border-radius:9px;background-image:url(/miniapp-spa/assets/fosved-logo-2026.jpg);background-size:220% auto;background-position:50% 28%' in INDEX
    assert '<div class="brand-name">FOSVED</div><div class="brand-sub">office</div>' in INDEX
    assert "диспетчерская офиса" not in INDEX  # решение владельца


def test_hero_white_text_both_themes():
    assert '.hero{position:relative;height:150px;border-radius:14px;overflow:hidden;background-image:url(/miniapp-spa/assets/fosved-logo-2026.jpg);background-size:cover;background-position:50% 22%' in INDEX
    assert 'linear-gradient(180deg,rgba(10,10,12,0) 40%,rgba(10,10,12,.95) 100%)' in INDEX
    assert "color:#fff" in INDEX  # явный белый — не наследование


def test_stats_gradient_numbers():
    assert '<div class="stat"><div class="stat-num">—</div><div class="stat-lbl">открыто нарядов</div></div>' in INDEX
    assert 'background:linear-gradient(135deg,var(--red),var(--red-light));-webkit-background-clip:text;background-clip:text;color:transparent' in INDEX


def test_attention_and_reports():
    assert 'Ничего не требует твоего решения.' in INDEX
    assert ".report-dot{flex:0 0 auto;width:7px;height:7px;border-radius:50%;margin-top:7px;background:linear-gradient(135deg,var(--red),var(--red-light))}" in INDEX


def test_dock_five_items_order_no_archive():
    dock = INDEX.split('<nav class="dock"')[1].split("</nav>")[0]
    order = re.findall(r'data-go="([a-z]+)"', dock)
    assert order == ["home", "narads", "chat", "settings", "more"]
    assert "repeat(5,1fr)" in INDEX
    # архив доступен из «Ещё» и ссылки «все»
    assert INDEX.count('data-go="archive"') >= 2


def test_dock_icons_svg_not_emoji():
    dock = INDEX.split('<nav class="dock"')[1].split("</nav>")[0]
    assert dock.count("<svg") == 5
    # цвета иконок задаются CSS-правилом (stroke:var(--nav-*))
    assert ".dock button svg{stroke:var(--nav-inactive)}" in INDEX
    assert ".dock button.on svg{stroke:var(--nav-active)}" in INDEX


def test_real_api_mapping_documented():
    assert "/api/narads" in INDEX
    assert "/api/archive" in INDEX
    assert "kpis.tasks_week" in INDEX and "kpis.cost_today" in INDEX
    assert "Бэкенд НЕ правим" in INDEX  # требование наряда зафиксировано в коде
