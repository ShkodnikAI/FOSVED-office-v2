#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #590: широкая раскладка Mini App (планшет/компьютер) + полноэкранный режим.

Гварды:
- A.1: условие ≥900px (любая ориентация) + 700–899px только альбом; 480px снято
  внутри блока; рабочий холст 1440px с центровкой; телефон ≤699px — пиксель в
  пиксель (Playwright-сравнение, допуск 0);
- A.2: главная ≥1200px — три колонки; архив/наряды — сетка auto-fill 320px;
  чат — отделы слева 240px, переписка справа; настройки/интеграции — центр 760px;
- B.1: кнопка полноэкранного режима только на tdesktop/macos/web/weba при наличии
  requestFullscreen; toggle по isFullscreen + fullscreenChanged;
- B.2: страница отчёта ≥900px — колонка ≤860px по центру, таблицы/графики ≤1200px.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
with open(REPO_ROOT / "miniapp" / "index.html", encoding="utf-8") as _f:
    INDEX = _f.read()

m = re.search(r"@media \(min-width: 900px\), \(orientation: landscape\) and \(min-width: 700px\) and \(max-width: 899\.9px\)\{(.*?)\n\}", INDEX, re.S)
WIDE = m.group(1) if m else ""


def test_a1_media_condition():
    assert WIDE, "media-блок широкой раскладки не найден"
    assert "(min-width: 900px), (orientation: landscape) and (min-width: 700px) and (max-width: 899.9px)" in INDEX
    # 480px снято; холст 1440px с центровкой
    assert "#app{max-width:none}" in WIDE
    assert "#app{max-width:1440px}" in INDEX
    # прежние правила FORGE-UI-11 сохранены (боковой док, 2 колонки главной, пузыри)
    assert "#app{padding-left:76px}" in WIDE
    assert "grid-template-columns:1.1fr 1fr" in WIDE
    assert ".msg-row .bubble{max-width:520px}" in WIDE


def test_a2_screens():
    # главная ≥1200: три колонки
    assert "@media (min-width: 1200px)" in INDEX
    assert ".screen[data-tab=\"home\"] .scroll{grid-template-columns:1fr 1fr 1fr" in INDEX
    # архив/наряды — сетка карточек, кап 760 для них снят
    assert "repeat(auto-fill,minmax(320px,1fr))" in INDEX
    assert '.screen[data-tab="archive"] .scroll,\n  .screen[data-tab="narads"] .scroll{max-width:1200px}' in INDEX
    # чат: отделы слева 240px, переписка справа; сетка только у видимого экрана
    assert ".screen.on[data-tab=\"chat\"]{display:grid;grid-template-columns:240px 1fr" in INDEX
    assert '#chatQuick{grid-column:1' in INDEX
    assert '#chatMessages{grid-column:2' in INDEX
    # настройки/интеграции/источники ЛЗ/магазин — центр 760px (сохранено)
    assert '.screen[data-tab="settings"] .scroll' in WIDE


def test_b1_fullscreen():
    assert 'id="fsBtn"' in INDEX and "\u2e25" in INDEX
    assert "{tdesktop:1,macos:1,web:1,weba:1}[tg.platform]" in INDEX
    assert 'typeof tg.requestFullscreen==="function"' in INDEX
    assert "tg.exitFullscreen()" in INDEX and "tg.requestFullscreen()" in INDEX
    assert "fullscreenChanged" in INDEX
    # юнит-логика: кнопка скрыта по умолчанию, показывается только по платформе+методу
    assert 'fb.hidden=false' in INDEX


def test_b2_report_page_wide():
    css = (REPO_ROOT / "report_css.txt").read_text(encoding="utf-8")
    assert "@media (min-width: 900px)" in css
    assert ".report-container{width:100%;max-width:860px" in css
    assert ".report-body table{max-width:1200px}" in css
    # на телефоне без изменений: базовый кап 480 не тронут
    assert ".report-container { max-width: 480px;" in css


def test_a3_phone_layout_pixel_identical():
    """A.3: 390×844 до/после — совпадение изображений, допуск 0."""
    pytest.importorskip("playwright", reason="playwright не установлен в окружении")
    out = Path("/tmp/n590_shots")
    out.mkdir(exist_ok=True)
    subprocess.run(["git", "-C", str(REPO_ROOT), "show", "main:miniapp/index.html"],
                   stdout=open(out / "before.html", "w"), check=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, src in (("before", out / "before.html"), ("after", REPO_ROOT / "miniapp" / "index.html")):
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.goto(f"file://{src}")
            pg.wait_for_timeout(1200)
            pg.screenshot(path=str(out / f"phone_{name}.png"))
            pg.close()
        b.close()
    from PIL import Image, ImageChops
    a = Image.open(out / "phone_before.png").convert("RGB")
    b = Image.open(out / "phone_after.png").convert("RGB")
    assert ImageChops.difference(a, b).getbbox() is None, \
        "телефонная раскладка (390×844) изменилась — запрет прохода нарушен"
