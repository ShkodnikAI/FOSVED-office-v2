#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #423 (P0): живой Tavily-поиск в обычном пути ОСП.

ОБНОВЛЕНО нарядом #474 (инцидент OSP-2026-10-05-PLAGUE-01): белый список
событийности (#423/#467) заменён перевёрнутым правилом — живой поиск
выполняется для КАЖДОГО анализа ОСП, пропуск — только для явно
вневременных вопросов (OSPSkipLiveSearch, короткий список исключений);
условие пустого кэша новостей снято. Гварды #423, пережившие переворот:
честная деградация с точными причинами, BY-дополнение запроса, подвал
источников, 12 гейтов ОСП не затронуты, один транспорт Tavily.
Специфичные гварды #474 — в tests/test_n474_osp_live_default.py.

Мутационные проверки (команды в отчёте PR): снятие условия OSPSkipLiveSearch
с вызова поиска, снятие TavilyKey-гварда, снятие BY-дополнения и снятие
Live-блока из подвала — каждая валит минимум один тест этого файла.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSP_MLOG = open(os.path.join(REPO_ROOT, "dept", "osp.mlog"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    """Тело pattern <name> — от объявления до следующего pattern на том же уровне."""
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\n// ═", start + 10)
    return source[start:nxt]


def test_patterns_exist():
    assert "pattern OSPSkipLiveSearch" in OSP_MLOG
    assert "pattern OSPLiveSearchBlock" in OSP_MLOG
    # #474: старый белый список удалён — не осталось ни паттерна, ни вызова
    assert "OSPNeedsLiveSearch" not in OSP_MLOG


def test_factpack_default_on_in_build_context():
    """#480 A.6: живой поиск ОСП — через командную работу с ЛЗ; условие
    OSPSkipLiveSearch и позиция секции (между news-блоком и FRED)
    сохранены — поменялся только поставщик данных."""
    body = _pattern_body(OSP_MLOG, "BuildOSPContext")
    # #474: поиск по умолчанию — единственное условие вызова, инвертированный список
    assert "if OSPSkipLiveSearch(query) == false then" in body
    # условие пустого кэша новостей СНЯТО (глушило поиск при живом фолбэке)
    assert "length(trim(news)) == 0.0" not in body, (
        "условие пустого кэша новостей обязано быть снято (#474 A.1)")
    # TEAM-1 #480: секция — консультация с ЛЗ, не собственный Tavily
    assert 'TeamConsult("osp", "lz", "factpack"' in body
    # собственный live-вызов из автоматического пути УБРАН (остался /osp tavily)
    assert "OSPLiveSearchBlock(query)" not in body
    # live-часть для гейта извлекается по маркерам разведсводки
    assert 'TeamExtractSection(consult, "[LIVE]", "[NEWS]")' in body
    idx_if = body.index("if OSPSkipLiveSearch")
    idx_section = body.index('TeamConsult("osp", "lz", "factpack"')
    idx_fred_comment = body.index("FRED (McpMarketsCall)")
    assert idx_if < idx_section < idx_fred_comment, "Разведсводка ЛЗ должна стоять между news-блоком и FRED"
    # секция вплетается в строку сборки контекста между News и FRED
    ctx_line = [l for l in body.splitlines() if "=== News ===" in l and "factpack_block" in l]
    assert ctx_line, "factpack_block должен вплетаться в строку сборки контекста"
    line = ctx_line[0]
    assert line.index("+ news + factpack_block + fred_data") > line.index("=== News ===")
    assert line.index("+ news + factpack_block + fred_data") < line.index("=== Corrections ===")


def test_honest_degradation_exact_causes():
    body = _pattern_body(OSP_MLOG, "OSPLiveSearchBlock")
    for cause in (
        "ключ Tavily не задан",
        "сеть Tavily недоступна",
        "ответ Tavily не распознан",
        "живой поиск вернул 0 результатов",
    ):
        assert cause in body, f"точная причина обязана быть: {cause}"
    # общее «недоступен» без причины — запрещено (A.3 наряда)
    assert "Tavily недоступен" not in body


def test_key_guard_before_http_call():
    body = _pattern_body(OSP_MLOG, "OSPLiveSearchBlock")
    idx_key = body.index("trim(TavilyKey())")
    idx_http = body.index("TavilySearch(q, \"osp\")")
    assert idx_key < idx_http, "проверка ключа обязана стоять ДО сетевого вызова"


def test_by_query_enrichment():
    body = _pattern_body(OSP_MLOG, "OSPLiveSearchBlock")
    assert '+ " Беларусь"' in body
    for marker in ("беларус", "минск", "лукашенко"):
        assert f'contains(t, "{marker}")' in body


def test_skip_list_is_short_and_inverted():
    """#474 A.1: пропуск — короткий список явно вневременных классов;
    якорь текущего момента перебивает вневременной маркер."""
    body = _pattern_body(OSP_MLOG, "OSPSkipLiveSearch")
    for marker in ("теория", "методолог", "история", "концепц"):
        assert f'contains(t, "{marker}")' in body, f"вневременной маркер: {marker}"
    # якорь-перебивка: событийное слово возвращает false ДО списка исключений
    idx_anchor = body.index('contains(t, "сейчас")')
    idx_list = body.index('contains(t, "теория")')
    assert idx_anchor < idx_list, "якорь текущего момента обязан перебивать исключения"


def test_footer_reflects_factpack():
    """#480 A.6: подвал показывает ЛЗ как источник разведсводки —
    с результатами имя, при отказе точная причина (правило #423 A.3)."""
    body = _pattern_body(OSP_MLOG, "OSPSourcesFooter")
    assert '"=== Консультация: lz/factpack ==="' in body
    assert "ЛЗ (разведсводка)" in body
    # с результатами — имя; при отказе — точная причина (не глушим)
    assert "ЛЗ (разведсводка): " in body
    assert 'contains(fact_body, "•")' in body


def test_gates_untouched():
    # 12 гейтов ОСП и финальный safety не трогаются ни #423, ни #474
    gates = _pattern_body(OSP_MLOG, "OSPCheckQualityGates")
    safety = _pattern_body(OSP_MLOG, "OSPFinalSafetyCheck")
    assert "g1_" in gates and "g12_noUncalib" in gates, "12 гейтов должны остаться в исходном объёме"
    assert 'return "PASS"' in safety


def test_transport_is_shared_tavily_search():
    # один путь к Tavily (office#354): прямого http-вызова api.tavily.com в
    # osp.mlog нет (упоминание — только в комментарии к OSPTavilySearch)
    for line in OSP_MLOG.splitlines():
        if "api.tavily.com" in line:
            assert line.strip().startswith("//"), f"http-вызов Tavily вне utils.mlog: {line.strip()}"
    body = _pattern_body(OSP_MLOG, "OSPLiveSearchBlock")
    assert "TavilySearch(q, \"osp\")" in body
