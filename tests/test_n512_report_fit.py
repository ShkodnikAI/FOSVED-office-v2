#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #512: страница отчёта вписывается в габариты Telegram (320–390px).

Репродукция 16.10 (Playwright, 360px): doc.scrollWidth=700 при client 390 —
WebView показывает зум-аут («увеличенный масштаб», слова владельца 13.10).
Провокаторы:
1) .table-wrap/.rich-table генерируются auto_enricher.format_tables, но
   стилей в report_css.txt не было — таблицы растягивали документ;
2) .ach-table (4 колонки длинного текста) — table-layout:auto не сжимался;
3) .metrics-grid с inline grid-template-columns из auto_enricher — min-content
   грид-колонок шире вьюпорта;
4) длинные pre/code без переноса.

Фикс: CSS-блок «#512» в report_css.txt (overflow-x на обёртке, fixed layout,
overflow-wrap:anywhere, pre-wrap для моноширинных) + авто-колонки метрик
в auto_enricher (inline-гриды убраны).

Гвард — детерминированный статический (§512 A.3): браузера в CI нет, поэтому
проверяется НАЛИЧИЕ фиксов в источниках; живое вписывание доказано
Playwright-репродукцией локально (до: 700px; после: 320/360/390 = 0 offenders).
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(REPO, "report_css.txt")
ENRICHER = os.path.join(REPO, "auto_enricher.py")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def test_table_wrap_has_horizontal_scroll():
    css = _read(CSS)
    m = re.search(r"\.table-wrap\{[^}]*\}", css)
    assert m, "нет правила .table-wrap в report_css.txt"
    assert "overflow-x:auto" in m.group(0), ".table-wrap без overflow-x:auto — таблица растянет документ"


def test_rich_table_fixed_layout_and_wrap():
    css = _read(CSS)
    m = re.search(r"\.rich-table\{[^}]*\}", css)
    assert m, "нет правила .rich-table в report_css.txt"
    assert "table-layout:fixed" in m.group(0), ".rich-table без table-layout:fixed"
    assert "width:100%" in m.group(0)
    td = re.search(r"\.rich-table th,\.rich-table td\{[^}]*\}", css)
    assert td and "overflow-wrap:anywhere" in td.group(0), "ячейки rich-table без переноса"


def test_ach_table_fixed_and_wraps():
    css = _read(CSS)
    m = re.search(r"\.ach-table\{[^}]*\}", css)
    assert m, "нет правила .ach-table"
    assert "table-layout:fixed" in m.group(0)
    cells = re.search(r"\.ach-table th,\.ach-table td\{[^}]*\}", css)
    assert cells and "overflow-wrap:anywhere" in cells.group(0)


def test_metrics_grid_auto_columns_no_inline_override():
    css = _read(CSS)
    m = re.search(r"\.metrics-grid\{[^}]*\}", css)
    assert m and "auto-fit" in m.group(0), ".metrics-grid без auto-fit в CSS"
    src = _read(ENRICHER)
    for i, line in enumerate(src.splitlines(), 1):
        if "metrics-grid" in line and "style=" in line and "grid-template-columns" in line:
            raise AssertionError(
                f"auto_enricher.py:{i}: inline grid-template-columns на metrics-grid "
                "возвращён — перебивает CSS и выталкивает страницу за габариты")


def test_pre_code_wraps():
    css = _read(CSS)
    m = re.search(r"\.report-body pre,\.report-body code\{[^}]*\}", css)
    assert m, "нет правила pre/code"
    assert "pre-wrap" in m.group(0) and "overflow-wrap:anywhere" in m.group(0)


def test_report_body_breaks_long_words():
    css = _read(CSS)
    assert re.search(r"\.report-body\{[^}]*overflow-wrap:break-word", css), \
        ".report-body без overflow-wrap:break-word"
