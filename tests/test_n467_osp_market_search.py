#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #467 (P1): ОСП без текущих рыночных данных.

Уровни:
1. РЕАЛЬНОЕ ИСПОЛНЕНИЕ mlog: test-блоки OSPMarketAsset/OSPNowDate/
   OSPMarketSource в dept/osp.mlog (распознавание активов, формат даты).
   Мутации (вывод в отчёте PR): снять домен financial/monetary из
   OSPNeedsLiveSearch → инцидент-гвард валится; убрать «золот» из
   OSPMarketAsset → тест актива валится.
2. Статические гварды: рыночные вопросы получают живой поиск ПО УМОЛЧАНИЮ
   (перевёрнутое правило #474 — OSPSkipLiveSearch не содержит рыночных
   слов, OSPNeedsLiveSearch больше не существует); рыночная
   секция в BuildOSPContext между live и FRED; причина отказа FRED —
   r.body (текст сервера) с фолбэком на r.note; Tavily-фолбэк
   «<актив> price today»; шов AvKey() в utils.mlog (env только там).
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSP_MLOG_PATH = os.path.join(REPO_ROOT, "dept", "osp.mlog")
OSP_MLOG = open(OSP_MLOG_PATH, encoding="utf-8").read()
UTILS_MLOG = open(os.path.join(REPO_ROOT, "dept", "utils.mlog"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\ntest ", start + 10)
    return source[start:nxt]


def _test_block(source: str, marker: str) -> str:
    """Тело test-блока по имени."""
    start = source.index(f'test "{marker}"')
    nxt = source.find("\ntest ", start + 10)
    return source[start:nxt if nxt != -1 else len(source)]


# ── 1. Реальное исполнение test-блоков ──────────────────────────────────

def test_mlog_test_blocks_pass():
    mlog = os.path.join(REPO_ROOT, "bin", "mlog")
    os.chmod(mlog, 0o755)
    proc = subprocess.run(
        [mlog, "test", OSP_MLOG_PATH],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "tests passed" in combined and "0/0" not in combined
    assert "❌" not in combined, combined
    for name in ("цена золота — forex XAU/USD", "биткоин — crypto bitcoin", "«Европа» не ловится"):
        assert name in combined, f"test-блок #467 не найден: {name}"


# ── 2. Рыночные вопросы получают live search по умолчанию (#474) ─────────

# Инцидент-гварды #467 обновлены нарядом #474: белый список удалён,
# рыночные домены/слова больше не нужны — поиск выполняется для КАЖДОГО
# анализа ОСП, пропуск только для вневременных (OSPSkipLiveSearch).

def test_needs_live_search_whitelist_removed():
    # перевёрнутое правило #474: старого паттерна нет нигде
    assert "OSPNeedsLiveSearch" not in OSP_MLOG
    # исключения вневременные — рыночных слов в списке пропуска нет:
    # «цена золота» не может быть пропущена
    body = _pattern_body(OSP_MLOG, "OSPSkipLiveSearch")
    for market_marker in ("цена", "курс", "котировк", "золот", "биткоин", "доллар"):
        assert f'contains(t, "{market_marker}")' not in body, (
            f"рыночное слово в списке пропуска запрещено: {market_marker}")


# ── 3. Рыночная секция в контексте ───────────────────────────────────────

def test_market_block_wired_in_context():
    body = _pattern_body(OSP_MLOG, "BuildOSPContext")
    assert "let market_block = OSPMarketDataBlock(query)" in body
    # секция вплетается в строку сборки после fred_data
    # (гварды #423 требуют Live Search между News и FRED — не нарушаем)
    line = [l for l in body.splitlines() if "=== News ===" in l and "live_block" in l]
    assert line, "market_block обязан вплетаться в строку сборки контекста"
    l = line[0]
    assert "+ live_block + fred_data + market_block" in l
    assert l.index("+ fred_data + market_block") < l.index("=== Corrections ===")


def test_market_data_block_fallback_chain():
    body = _pattern_body(OSP_MLOG, "OSPMarketDataBlock")
    # MCP get_* — первый приоритет
    assert "McpMarketsCall(\"osp\", tool, args_json" in body
    # без ключа AV прямой вызов не делается, причина честная
    assert "ALPHAVANTAGE_API_KEY не установлен" in body
    # фолбэк Tavily «<актив> price today»
    assert '" price today"' in body
    assert "TavilySearch(" in body and "TavilyFormatBlock(" in body
    # дата и источник в строке данных (#467: «с датой и источником»)
    assert "OSPNowDate()" in body
    assert "источник: " in body


def test_market_data_block_honest_cause():
    body = _pattern_body(OSP_MLOG, "OSPMarketDataBlock")
    # при отказе — точная причина: body сервера, иначе note (#467 A.2)
    assert "let cause = r_body" in body
    assert 'if trim(cause) == "" then { let cause = r_note }' in body


def test_fred_failure_reason_is_server_text():
    body = _pattern_body(OSP_MLOG, "BuildOSPContext")
    # #467 A.2: причина отказа FRED — r.body (текст сервера), общий note — фолбэк
    assert "let fred_cause = r.body" in body
    assert 'if trim(fred_cause) == "" then { let fred_cause = r.note }' in body
    assert ': недоступно (" + fred_cause' in body
    # старый общий текст не используется напрямую
    assert '": недоступно (" + r.note + ")"' not in body


# ── 4. Шов AvKey и распознавание активов ─────────────────────────────────

def test_avkey_seam_in_utils():
    # №312/№419: env-чтения — только в utils.mlog
    assert "pattern AvKey() -> String {" in UTILS_MLOG
    assert 'return env("ALPHAVANTAGE_API_KEY")' in UTILS_MLOG
    body = _pattern_body(OSP_MLOG, "OSPMarketDataBlock")
    assert "AvKey()" in body
    # прямой env("ALPHAVANTAGE...") в osp.mlog запрещён
    assert 'env("ALPHAVANTAGE' not in OSP_MLOG


def test_market_asset_conventions():
    # «евро» одиночкой не ловится (ловушка «Европа/Europe»)
    asset = _pattern_body(OSP_MLOG, "OSPMarketAsset")
    assert asset.count('contains(t, "евро")') >= 1
    # пара «евро» всегда с ценовым маркером-условием
    for line in asset.splitlines():
        if 'contains(t, "евро")' in line:
            assert "курс" in line or "цена" in line or "стоит" in line or "usd" in line.lower() or "доллар" in line, line
