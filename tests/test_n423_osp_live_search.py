#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #423 (P0): живой Tavily-поиск в обычном пути ОСП.

Статические гварды по dept/osp.mlog — по конвенции тестов этого репо.
Проверяют: паттерны существуют; вызов в BuildOSPContext обёрнут в условие
событийности + пустоты news-кэша; честная деградация называет точные
причины; BY-тематика дополняет запрос; подвал источников отражает Live
Search. Двенадцать гейтов ОСП не затрагиваются (см. test_gates_untouched).

Мутационные проверки (команды в отчёте PR): снятие условия событийности,
снятие TavilyKey-гварда, снятие BY-дополнения и снятие Live-блока из
подвала — каждая валит минимум один тест этого файла.
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
    assert "pattern OSPNeedsLiveSearch" in OSP_MLOG
    assert "pattern OSPLiveSearchBlock" in OSP_MLOG
    assert "-> Bool" in _pattern_body(OSP_MLOG, "OSPNeedsLiveSearch")


def test_live_search_gated_in_build_context():
    body = _pattern_body(OSP_MLOG, "BuildOSPContext")
    # условие событийности + пустоты news-кэша — против лишних трат Tavily
    assert "if OSPNeedsLiveSearch(query, domain) and length(trim(news)) == 0.0 then" in body
    # секция контекста добавляется только внутри условия
    assert "=== Live Search ===" in body
    idx_if = body.index("if OSPNeedsLiveSearch")
    idx_section = body.index("\\n\\n=== Live Search ===")
    idx_fred_comment = body.index("FRED (McpMarketsCall)")
    assert idx_if < idx_section < idx_fred_comment, "Live Search должен стоять между news-блоком и FRED"
    # секция вплетается в строку сборки контекста между News и FRED
    ctx_line = [l for l in body.splitlines() if "=== News ===" in l and "live_block" in l]
    assert ctx_line, "live_block должен вплетаться в строку сборки контекста"
    line = ctx_line[0]
    assert line.index("+ news + live_block + fred_data") > line.index("=== News ===")
    assert line.index("+ news + live_block + fred_data") < line.index("=== Corrections ===")


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


def test_needs_live_search_covers_naryad_triggers():
    body = _pattern_body(OSP_MLOG, "OSPNeedsLiveSearch")
    for domain in ("political", "geopolitical", "military"):
        assert f'"{domain}"' in body
    for marker in ("что происходит", "сейчас", "последние", "новости", "сегодня", "вчера"):
        assert f'contains(t, "{marker}")' in body, f"маркер событийности: {marker}"


def test_footer_reflects_live_search():
    body = _pattern_body(OSP_MLOG, "OSPSourcesFooter")
    assert '"=== Live Search ==="' in body
    assert "Живой поиск (Tavily)" in body
    # с результатами — имя; при отказе — точная причина (не глушим)
    assert "Живой поиск (Tavily): " in body
    assert 'contains(live_body, "•")' in body


def test_gates_untouched():
    # 12 гейтов ОСП и финальный safety не трогаются нарядом #423
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
