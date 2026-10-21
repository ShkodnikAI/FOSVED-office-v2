#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-11 tests (#204): альбомная ориентация (Главная, Наряды, Чат).

Гварды:
- media-запрос широкой раскладки существует (№590: ≥900px любой ориентации +
  700–899px в альбомной; прежний (orientation: landscape) and (min-width: 700px)
  расширен, правило №204 сохранено внутри);
- боковая навигация: док превращается в левую панель 76px (скрытие нижнего
  вида, border-right, те же 5 пунктов — DOM не трогается);
- Главная — двухколоночная сетка 1.1fr/1fr с явным размещением герой+статистика
  слева, внимание+отчёты справа;
- Наряды/Чат — ограничение ширины, пузыри чата не растягиваются;
- портрет не затронут: все альбомные правила внутри media-блока;
- состояние сохраняется: никаких JS-обработчиков resize/orientation —
  чистый CSS, возврат в портрет восстанавливает вид автоматически.
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

# №590 A.1: условие расширено — ≥900px (любая ориентация) ИЛИ 700–899px в альбомной
m = re.search(r"@media \(min-width: 900px\), \(orientation: landscape\) and \(min-width: 700px\) and \(max-width: 899\.9px\)\{(.*?)\n\}", INDEX, re.S)
LAND = m.group(1) if m else ""


def test_landscape_media_block_exists():
    assert LAND, "media-блок широкой раскладки не найден"
    assert "(min-width: 900px), (orientation: landscape) and (min-width: 700px) and (max-width: 899.9px)" in INDEX
    # №590 A.1: ограничение 480px снято внутри блока
    assert "#app{max-width:none}" in LAND
    assert "#app{max-width:1440px}" in INDEX  # рабочий холст с центровкой на ≥900


def test_side_rail_from_dock():
    # док переезжает влево: фиксированная колонка 76px, вертикальная, граница справа
    assert "#app{padding-left:76px}" in LAND
    assert ".dock{position:fixed;left:0;top:0;bottom:0;width:76px;height:100vh" in LAND
    assert "grid-template-columns:1fr" in LAND
    assert "border-right:1px solid var(--line)" in LAND
    assert "padding:16px 0" in LAND


def test_home_two_columns():
    assert '.screen[data-tab="home"] .scroll{display:grid;grid-template-columns:1.1fr 1fr' in LAND
    # герой+статистика слева, внимание+отчёты справа
    assert '.screen[data-tab="home"] .hero{grid-column:1;grid-row:1}' in LAND
    assert '.screen[data-tab="home"] .stats{grid-column:1;grid-row:2}' in LAND
    assert '.screen[data-tab="home"] .sec:first-of-type{grid-column:2;grid-row:1' in LAND
    assert '.screen[data-tab="home"] #homeAlerts{grid-column:2;grid-row:2}' in LAND
    assert '.screen[data-tab="home"] #homeReports{grid-column:2;grid-row:4}' in LAND


def test_narads_chat_adapted_not_stretched():
    assert '.screen[data-tab="narads"] .scroll,\n  .screen[data-tab="chat"],' in LAND
    assert 'max-width:760px;margin:0 auto;width:100%' in LAND
    assert ".msg-row .bubble{max-width:520px}" in LAND


def test_portrait_untouched():
    # все широкие правила — внутри media-блоков; снаружи layout без изменений
    outside = INDEX.replace(LAND, "")
    outside = outside.replace("#app{max-width:1440px}", "")
    assert "padding-left:76px" not in outside
    assert ".dock{position:fixed;left:0" not in outside
    assert "grid-template-columns:1.1fr 1fr" not in outside


def test_no_js_orientation_handlers_state_preserved():
    # чистый CSS: ни resize/orientationchange слушателей, ни перерисовок —
    # возврат в портрет восстанавливает вид и сохраняет состояние (открытый
    # чат/деталь наряда остаются)
    assert "addEventListener(\"resize\"" not in INDEX
    assert "addEventListener(\"orientationchange\"" not in INDEX
    assert "screen.orientation" in INDEX and "so.lock" in INDEX  # блокировка — из FORGE-UI-4


def test_other_screens_covered_by_common_principle():
    # остальные экраны получили боковую навигацию (общий #app padding) и
    # центрирование контента тем же правилом
    for tab in ("archive", "more", "settings", "projects", "integrations", "lzsrc", "shopset"):
        assert f'.screen[data-tab="{tab}"] .scroll' in LAND, tab
