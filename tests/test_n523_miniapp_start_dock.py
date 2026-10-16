#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #523: Mini App старт с tgWebApp-hash и целые иконки dock.

Дефекты (прод-скрины владельца 16.10):
1) Telegram открывает Mini App с launch-параметрами в hash
   (#tgWebAppData=…&tgWebAppVersion=…) — старт брал hash как вкладку,
   ни один .screen не совпадал → пустое тело до первого перехода;
2) иконки «Настройки» (точка r=3) и «Чат» (незамкнутая дуга) — обрывки.

Гварды:
- стартовый блок содержит tgWebApp-гвард и выбор вкладки только из
  существующих .screen[data-tab] (A.1/A.2);
- каждый #dock button svg содержит замкнутый контур: path с z,
  rect, либо ≥2 circle (вариант «Ещё» — три точки, санкционирован)
  (B.2) — ловит повтор «одиночной точки» и «незамкнутой дуги»;
- «Чат» — замкнутое облачко (path с z), «Настройки» — шестерня
  (path с z + центральная окружность) (B.1).
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(REPO, "miniapp", "index.html")


def _html():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


def test_start_guards_tgwebapp_hash():
    html = _html()
    assert 'indexOf("tgWebApp")!==0' in html, "старт не отфильтровывает tgWebApp-хэш"
    assert 'go(_tab);refresh();' in html, "старт не через гвард-выбор вкладки"
    assert '.getAttribute("data-tab")===_rawHash' in html, "вкладка выбирается только из существующих .screen"


def test_dock_icons_all_closed_contours():
    html = _html()
    dock = re.search(r'<nav class="dock" id="dock">(.*?)</nav>', html, re.S)
    assert dock, "нет #dock"
    btns = re.findall(r"<button[^>]*>(.*?)</button>", dock.group(1), re.S)
    assert len(btns) == 5, f"в dock 5 кнопок, найдено {len(btns)}"
    for body in btns:
        name = re.sub(r"<[^>]+>", "", body).strip()
        svgs = re.findall(r"<svg[^>]*>(.*?)</svg>", body, re.S)
        assert svgs, f"{name}: нет svg"
        for svg in svgs:
            paths = re.findall(r"<path[^>]*d=\"([^\"]+)\"", svg)
            has_z = any(re.search(r"[zZ]\s*$", d) for d in paths)
            has_rect = "<rect" in svg
            n_circles = svg.count("<circle")
            assert has_z or has_rect or n_circles >= 2, (
                f"{name}: нет замкнутого контура (path-z/rect/≥2 circle) — «точка»/«дуга»"
            )


def test_chat_icon_is_closed_bubble():
    html = _html()
    m = re.search(r'data-go="chat"><svg[^>]*>(.*?)</svg>', html, re.S)
    assert m, "нет иконки Чат"
    svg = m.group(1)
    d = re.search(r'<path[^>]*d="([^"]+)"', svg)
    assert d and re.search(r"[zZ]\s*$", d.group(1)), "Чат: path не замкнут (дуга)"


def test_settings_icon_is_full_gear():
    html = _html()
    m = re.search(r'data-go="settings"><svg[^>]*>(.*?)</svg>', html, re.S)
    assert m, "нет иконки Настройки"
    svg = m.group(1)
    assert "<circle" in svg, "Настройки: нет центральной окружности"
    d = re.search(r'<path[^>]*d="([^"]+)"', svg)
    assert d and re.search(r"[zZ]\s*$", d.group(1)), "Настройки: контур шестерни не замкнут"
    assert d.group(1).count("a") >= 6, "Настройки: шестерня без зубцов (одиночный круг)"


def test_start_block_placement_after_init():
    """Гвард стоит в конце boot-скрипта (после инициализации API_BASE) —
    go(_tab) вызывается после построения DOM (скрипт в конце body)."""
    html = _html()
    pos_guard = html.find('go(_tab);refresh();')
    assert pos_guard > html.find('id="dock"'), "старт-вызов раньше разметки dock"
    assert pos_guard > html.find('id="apiBaseInput"'), "старт-вызов раньше инициализации настроек"
