#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #475 (P0): кэш новостей не увидел чуму в Иркутске 2–4 октября.

Диагноз (кодово доказан, A.1): get_fresh_news искал SQLite LIKE по точной
словоформе; LIKE в SQLite регистрозависим для кириллицы и lower() там
ASCII-only ('Иркутске' LIKE '%иркутске%' = 0), словоформы не матчатся
('чумы' ≠ 'чума'). Итог: релевантных записей нет → срабатывал generic-фолбэк
(24 ч по категории) → news непуст → ОСП (до #474) пропускал живой поиск.

Фикс A.2: стем-матч в Python (основы слов, регистронезависимо для
кириллицы), сортировка по числу совпавших основ, фолбэк прежний.
Фикс A.3: монитор свежести в /admin errors (AdminLogDigest) — сбор не
запускался > 3 ч или кэш пуст. Попутно починен латент-баг #405:
undefined-переменная `s` вместо `[hs]` в SQL-параметрах AdminLogDigest
(UNDEFINED_VARIABLE в рантайме 0.28.0 — /admin errors падал целиком).

Мутации (команды в отчёте PR): вернуть LIKE-поиск; снять -3 hours окно
монитора; убрать строку НОВОСТИ из AdminLogDigest — каждая валит минимум
один тест этого файла.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_PY = open(os.path.join(REPO_ROOT, "proxy", "news.py"), encoding="utf-8").read()
ADMIN_MLOG = open(os.path.join(REPO_ROOT, "dept", "admin.mlog"), encoding="utf-8").read()
SCHEDULES_MLOG = open(os.path.join(REPO_ROOT, "dept", "schedules.mlog"), encoding="utf-8").read()

from proxy.news import _stem, _doc_stems, get_fresh_news, _extract_keywords


# ── 1. Стеммер: словоформы и регистр кириллицы ────────────────────────────

def test_stem_wordforms_collapse():
    assert _stem("чума") == _stem("чумы") == _stem("чумой") == _stem("ЧУМА")
    assert _stem("иркутске") == _stem("Иркутска") == _stem("иркутск")
    assert _stem("эпидемии") == _stem("эпидемия") == _stem("эпидемию")
    assert _stem("вероятность") == _stem("вероятности")


def test_stem_case_insensitive_cyrillic():
    # ядро инцидента: 'Иркутске' в заголовке vs 'иркутске' в запросе
    assert _stem("Иркутске") == _stem("иркутске")


def test_doc_stems_finds_plague_in_uppercase_title():
    doc = _doc_stems("В ШЕЛЕХОВЕ ПОДТВЕРЖДЁН СЛУЧАЙ ЛЁГОЧНОЙ ЧУМЫ: карантин в Иркутске")
    for st in ("чум", "иркутск", "карантин", "шелехов"):
        assert st in doc or any(d.startswith(st) for d in doc), st


def test_extract_keywords_skips_stopwords():
    kws = _extract_keywords("вероятность эпидемии лёгочной чумы в Иркутске")
    assert "вероятность" in kws and "чумы" in kws and "иркутске" in kws
    assert "в" not in kws


# ── 2. get_fresh_news: стем-матч вместо LIKE ──────────────────────────────

def _row(title, summary=""):
    return ("РИА Новости", title, summary, "https://example.com/a", "2026-10-04T09:00:00", None)


def test_get_fresh_news_matches_by_stems_not_exact_form():
    plague = _row("В Иркутске подтверждён случай чумы: 200 контактов на карантине",
                  "Случай лёгочной чумы в Шелехове, завтра — экстренное заседание")
    generic = _row("Курс доллара вырос на фоне отчетности", "Экономические итоги недели")
    rows48 = [generic, plague]
    with patch("proxy.news._query", return_value=rows48) as q:
        out = get_fresh_news("вероятность эпидемии лёгочной чумы в Иркутске", dept="osp")
    assert "чумы" in out and "Иркутске" in out, "релевантная запись обязана найтись по основам"
    assert "доллара" not in out, "нерелевантная запись фильтруется"
    # стем-матч идёт по 48-часовому окну (один запрос без LIKE)
    sql = q.call_args[0][0]
    assert "LIKE" not in sql, "LIKE-поиск обязан быть снят (#475 A.2)"
    assert "-48 hours" in sql


def test_get_fresh_news_case_insensitive_uppercase_cache():
    # заголовок в кэше КАПСОМ — SQLite LIKE его не взял бы никогда
    rows48 = [_row("ЧУМА В ИРКУТСКЕ: КОМЕНДАНТСКИЙ ЧАС В БОЛЬНИЦАХ")]
    with patch("proxy.news._query", return_value=rows48):
        out = get_fresh_news("эпидемия чумы в Иркутске", dept="osp")
    assert "ЧУМА В ИРКУТСКЕ" in out


def test_get_fresh_news_scores_by_stem_count():
    hi = _row("Чума в Иркутске: карантин и эпидемия", "")
    lo = _row("Чума: историческая справка", "")
    with patch("proxy.news._query", return_value=[lo, hi]):
        out = get_fresh_news("эпидемия чумы в Иркутске", dept="osp")
    # запись с бóльшим числом совпавших основ — первой
    assert out.index("Чума в Иркутске") < out.index("историческая справка")


def test_get_fresh_news_fallback_generic_latest():
    # ни одна основа не совпала → фолбэк: свежее по категориям (24 ч)
    fresh = _row("Обычная новость дня", "")
    with patch("proxy.news._query", return_value=[fresh]) as q:
        out = get_fresh_news("зюганов вулкан марсианский", dept="osp")
    assert "Обычная новость дня" in out
    sql = q.call_args[0][0]
    assert "-24 hours" in sql, "фолбэк обязан остаться 24-часовым"


def test_get_fresh_news_empty_cache_returns_empty():
    with patch("proxy.news._query", side_effect=[[], []]):
        assert get_fresh_news("чума в Иркутске", dept="osp") == ""


# ── 3. Монитор свежести в /admin errors (#475 A.3) ────────────────────────

def test_admin_log_digest_has_news_freshness_monitor():
    body_start = ADMIN_MLOG.index("pattern AdminLogDigest")
    body_end = ADMIN_MLOG.index("\npattern ", body_start + 10)
    body = ADMIN_MLOG[body_start:body_end]
    assert "НОВОСТИ: кэш пуст" in body
    assert "НОВОСТИ: свежих записей (>3 ч) нет" in body
    assert "-3 hours" in body
    assert "FROM news_cache" in body
    # сообщение снабжает админа местом первопричины — слот collect-news
    assert "collect-news" in body


def test_admin_log_digest_undefined_s_fixed():
    # латент-баг #405: параметр SQL был `s]` (UNDEFINED_VARIABLE в рантайме)
    body_start = ADMIN_MLOG.index("pattern AdminLogDigest")
    body_end = ADMIN_MLOG.index("\npattern ", body_start + 10)
    body = ADMIN_MLOG[body_start:body_end]
    assert ", s])" not in body, "undefined-переменная s обязана быть заменена на [hs]"
    assert body.count("[hs])") == 9, "7 исходных вызовов + 2 новых (монитор новостей)"


def test_collect_news_slot_registered():
    # A.1: слот сбора в реестре нативного крона — причина (1) проверяется
    # по last_run/next_run прода, регистрация здесь (см. test_n424)
    assert '{ name: "collect-news"' in SCHEDULES_MLOG
