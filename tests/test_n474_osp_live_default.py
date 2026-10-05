#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #474 (P0): живой поиск ОСП по умолчанию + гейт актуальности.

Инцидент OSP-2026-10-05-PLAGUE-01: ОСП выдал успокаивающий прогноз по
уже случившемуся событию (чума, Шелехов 2–4.10). Две причины в коде:
(1) белый список событийности слеп к эпидемиологии/ЧС; (2) поиск глушился
непустым кэшем новостей (generic-фолбэк /news/fresh).

Уровни гвардов:
1. РЕАЛЬНОЕ ИСПОЛНЕНИЕ mlog: test-блоки n474 в dept/osp.mlog (пропуск
   вневременных, якорь-перебивка, риск-маркеры, обе ветки гейта) и в
   dept/utils.mlog (дефолты бюджета и TTL).
2. Бюджетная форма (utils.mlog): единый шов TavilySearch — кэш ответа
   (tavily_cache), дневной счётчик (tavily_usage), маркер "(budget)",
   fail-open на отказах БД; честные причины бюджета у всех четырёх
   вызовов (ОСП live, ОСП market-фолбэк, Эксперт, ЛЗ); уборка кэша —
   питоновский слой (collect_tavily), не mlog (irreversible-sink).
3. Гейт актуальности: директивы обеих веток в контексте, fresh_gate
   вплетён после Dialog; attempted-флаг не даёт гейту судить вневременные.

Мутации (команды в отчёте PR): вернуть условие пустого кэша; снять
"(budget)"-ветку у любого из четырёх вызовов; снять fresh_gate из сборки
контекста; убрать якорь-перебивку из OSPSkipLiveSearch — каждая валит
минимум один тест этого файла.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSP_MLOG = open(os.path.join(REPO_ROOT, "dept", "osp.mlog"), encoding="utf-8").read()
UTILS_MLOG = open(os.path.join(REPO_ROOT, "dept", "utils.mlog"), encoding="utf-8").read()
EXPERT_MLOG = open(os.path.join(REPO_ROOT, "dept", "expert.mlog"), encoding="utf-8").read()
LZ_MLOG = open(os.path.join(REPO_ROOT, "dept", "lz.mlog"), encoding="utf-8").read()
NEWS_PY = open(os.path.join(REPO_ROOT, "proxy", "news.py"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\n// ═", start + 10)
    return source[start:nxt]


# ── 1. Реальное исполнение mlog-тестов ────────────────────────────────────

def test_mlog_test_blocks_n474_pass():
    proc = subprocess.run(
        ["./bin/mlog", "test", "dept/osp.mlog"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    combined = (proc.stdout + proc.stderr)
    assert proc.returncode == 0, combined
    assert "tests passed" in combined and "0/0" not in combined
    assert "❌" not in combined, combined
    for name in (
        "n474 default ON: чума в Иркутске — поиск обязателен",
        "n474 якорь текущего момента перебивает вневременной маркер",
        "n474 гейт: риск-вопрос, поиск отказал — вероятностей нет",
    ):
        assert name in combined, f"test-блок #474 не найден: {name}"


def test_mlog_test_blocks_utils_budget_defaults():
    proc = subprocess.run(
        ["./bin/mlog", "test", "dept/utils.mlog"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    combined = (proc.stdout + proc.stderr)
    assert proc.returncode == 0, combined
    assert "❌" not in combined, combined
    assert "n474 бюджет: env не задан — дефолт 30 вызовов/день" in combined


# ── 2. Бюджетная форма в едином шве TavilySearch ─────────────────────────

def test_budget_seam_in_tavily_search_only():
    body = _pattern_body(UTILS_MLOG, "TavilySearch")
    # кэш ответа по запросу
    assert "tavily_cache" in body
    assert "datetime('now', '-' || ?2 || ' minutes')" in body
    # дневной счётчик по UTC-дню
    assert "tavily_usage" in body
    assert "WHERE day = date('now')" in body
    # маркер исчерпания бюджета
    assert 'return "(budget)"' in body
    # env-имена из наряда (через env_or: env бросает ENV_NOT_FOUND)
    assert 'env_or("OSP_TAVILY_DAILY_BUDGET", "")' in UTILS_MLOG
    assert 'env_or("OSP_TAVILY_CACHE_MIN", "")' in UTILS_MLOG
    # fail-open: все обращения к БД обёрнуты TryVal
    for db_call in ("db_execute", "query("):
        pass  # шов целиком внутри TryVal — проверяем по ключевым строкам ниже
    assert body.count("TryVal(try db_execute") == 4, "CREATE×2 + INSERT×2 — все в TryVal"
    assert "TryVal(try query(" in body
    # DELETE из mlog запрещён (irreversible-sink, наряд #474 — уборка в python)
    assert "DELETE FROM" not in body


def test_tavily_cache_cleanup_in_python_collector():
    # физическая уборка протухшего кэша — в trusted-слое сборщика
    assert "DELETE FROM tavily_cache WHERE created_at < datetime('now', '-1 day')" in NEWS_PY
    # молчаливый пропуск, если таблицы ещё нет
    assert "cache cleanup skipped" in NEWS_PY


def test_budget_cause_honest_in_all_four_callers():
    # ОСП live search
    live = _pattern_body(OSP_MLOG, "OSPLiveSearchBlock")
    assert 'if response == "(budget)"' in live
    assert "дневной бюджет Tavily исчерпан" in live
    # ОСП market-фолбэк
    market = _pattern_body(OSP_MLOG, "OSPMarketDataBlock")
    assert 'if response == "(budget)"' in market
    assert "дневной бюджет Tavily исчерпан" in market
    # Эксперт
    expert = _pattern_body(EXPERT_MLOG, "ExpertTavilySearch")
    assert 'if response == "(budget)"' in expert
    assert "дневной бюджет Tavily исчерпан" in expert
    # ЛЗ
    lz = _pattern_body(LZ_MLOG, "LZTavilySearch")
    assert 'if response == "(budget)"' in lz
    assert "дневной бюджет Tavily исчерпан" in lz


def test_expert_honest_no_fresh_data_marker():
    body = _pattern_body(EXPERT_MLOG, "BuildExpertContext")
    # #474 A.3: пустой живой поиск — не тишина, а честная пометка
    assert "свежих данных живой поиск не дал" in body
    footer = _pattern_body(EXPERT_MLOG, "ExpertSourcesFooter")
    # источник приписывается только при реальной выдаче
    assert 'contains(context, "•")' in footer


# ── 3. Гейт актуальности ─────────────────────────────────────────────────

def test_freshness_gate_directives():
    body = _pattern_body(OSP_MLOG, "OSPFreshnessGate")
    # свежие данные есть → раздел «Что произошло сейчас»
    assert "Что произошло сейчас" in body
    assert "не в дисклеймере" in body
    # данных нет → запрет вероятностей и успокоительных выводов
    assert "СВЕЖИХ ДАННЫХ НЕТ" in body
    assert "нужна проверка свежих событий" in body
    assert "экспозиция минимальна" in body
    # свежесть — только по живому поиску, отказ распознаётся по скобке-причине
    assert 'starts_with(live_raw, "(") == false' in body


def test_freshness_gate_wired_in_context():
    body = _pattern_body(OSP_MLOG, "BuildOSPContext")
    assert "let fresh_gate = OSPFreshnessGate(query, live_raw, live_attempted)" in body
    # вплетён в сборку контекста после Dialog (высокое внимание в конце)
    line = [l for l in body.splitlines() if "=== Dialog ===" in l and "fresh_gate" in l]
    assert line, "fresh_gate обязан вплетаться в строку сборки контекста"
    assert "ПОВТОР: ДАТА" in body  # повтор даты остаётся последним


def test_gate_does_not_judge_atemporal_questions():
    body = _pattern_body(OSP_MLOG, "OSPFreshnessGate")
    # attempted=false → гейт молчит (иначе «теория вероятности» ловила бы
    # запрет прогнозов, не будучи событийным вопросом)
    assert 'if attempted == false then { return "" }' in body


def test_risk_markers_cover_plague_class():
    body = _pattern_body(OSP_MLOG, "OSPIsCurrentRiskQuestion")
    # классы, ослепившие белый список #423 (инцидент #474)
    for marker in ("вероятност", "эпидем", "вспышк", "карантин", "катастроф", "авари"):
        assert f'contains(t, "{marker}")' in body, f"риск-маркер обязателен: {marker}"


def test_osp_dept_profile_documents_inversion():
    # комментарий-инцидент в шве — чтобы переворот не «причесали» обратно
    assert "OSP-2026-10-05-PLAGUE-01" in OSP_MLOG
