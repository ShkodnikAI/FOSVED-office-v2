#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #468 (P2): честные подвалы «Источники» и блок «Вердикт».

Уровни:
1. РЕАЛЬНОЕ ИСПОЛНЕНИЕ mlog: test-блоки OSPSourcesFooter в dept/osp.mlog
   (FRED только при реальных данных; при отказе — точная причина).
   Мутации (вывод в отчёте PR): восстановить безусловную FRED-строку →
   тесты «все ряды отказали»/«отказ без причины» валятся.
2. auto_enricher.wrap_verdict — реальные python-тесты: блок «Вердикт»
   только при непустом содержимом; чужие секции не втягиваются; разделы
   Вердикт/Verdict/Итог/Confidence отчётов ОСП находятся.
3. Статические гварды Эксперта/ЛЗ (критерий «данные реально вошли»):
   - expert.mlog: live-секция и строка источника добавляются только при
     live != "" (пустой live == отказ, источник не рисуется);
   - lz.mlog: отсечение маркеров отказа (гвард #427 A.2 не сломан).
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import auto_enricher  # noqa: E402

OSP_MLOG_PATH = os.path.join(REPO_ROOT, "dept", "osp.mlog")
OSP_MLOG = open(OSP_MLOG_PATH, encoding="utf-8").read()
EXPERT_MLOG = open(os.path.join(REPO_ROOT, "dept", "expert.mlog"), encoding="utf-8").read()
LZ_MLOG = open(os.path.join(REPO_ROOT, "dept", "lz.mlog"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\ntest ", start + 10)
    return source[start:nxt]


# ── 1. mlog test-блоки OSPSourcesFooter ─────────────────────────────────

def test_mlog_footer_blocks_pass():
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
    # test-блоки #468 реально исполняются
    for name in ("FRED с полученным рядом", "FRED все ряды отказали", "FRED отказ без скобки-причины"):
        assert name in combined, f"test-блок #468 не найден: {name}"


def test_footer_no_unconditional_fred_line():
    # дефект #468: строка источника НЕ может добавляться по факту одного заголовка
    body = _pattern_body(OSP_MLOG, "OSPSourcesFooter")
    assert '"=== FRED (макроданные) ==="' in body  # вырезка тела блока
    # причина отказа выводится дословно
    assert "FRED недоступен: " in body
    # без скобки-причины — честная общая строка
    assert "FRED недоступен (данные не получены)" in body
    # при данных — прежнее имя источника
    assert "· FRED (макроданные: доходность облигаций, ставка ФРС, инфляция)" in body


# ── 2. auto_enricher.wrap_verdict ────────────────────────────────────────

def test_verdict_found_with_content():
    text = "Анализ завершён.\n\n## Вердикт\nПрогноз основан на текущей цене золота и ставке ФРС.\n\n---\n**Источники:** FRED"
    out = auto_enricher.wrap_verdict(text)
    assert 'verdict-title' in out
    assert 'Прогноз основан на текущей цене золота' in out
    # хвост документа не потерян
    assert '**Источники:**' in out


def test_verdict_empty_header_no_block():
    # инцидент #468: заголовок есть, содержимого нет — блока быть не должно
    text = "Отчёт окончен.\n\nВердикт:\n\n---\n**Источники:** FRED"
    out = auto_enricher.wrap_verdict(text)
    assert 'verdict-block' not in out
    assert '**Источники:**' in out


def test_verdict_dash_placeholder_no_block():
    text = "Отчёт окончен.\n\n## Вердикт\n—\n\n## Источники\nнет данных"
    out = auto_enricher.wrap_verdict(text)
    assert 'verdict-block' not in out


def test_verdict_confidence_section_found():
    # наряд #468: regex находит реальный вердикт отчётов ОСП (Confidence/Вердикт)
    text = "Часть анализа.\n\n**Confidence:** medium — ключевые вероятности калиброваны.\n\nХвост."
    out = auto_enricher.wrap_verdict(text)
    assert 'verdict-title' in out
    assert 'medium — ключевые вероятности калиброваны' in out


def test_verdict_does_not_swallow_foreign_sections():
    text = "Вводная.\n\nВердикт:\nСогласованное распределение сценариев.\n\n## Confidence\ndetails о калибровке\n\n## Источники\nFRED недоступен"
    out = auto_enricher.wrap_verdict(text)
    assert 'Согласованное распределение сценариев.' in out
    assert 'details о калибровке' not in out.split('verdict-body')[1].split('</div>')[0]
    assert 'FRED недоступен' not in out.split('verdict-body')[1].split('</div>')[0]


def test_verdict_ito_word_not_triggered():
    # «Итого» (не «Итог») не должно триггерить блок вердикта
    text = "Вводная часть отчёта здесь.\n\nИтого: 3 сценария рассмотрено.\n\nФинальный абзац анализа, достаточно длинный для блока вердикта, чтобы сработать."
    out = auto_enricher.wrap_verdict(text)
    if 'verdict-block' in out:
        # если блок нарисован — только из «последнего абзаца», не из «Итого»
        assert '3 сценария' not in out.split('verdict-body')[1].split('</div>')[0]


def test_verdict_english_word():
    text = "Report body.\n\nVerdict: keep rates unchanged.\n\n---"
    out = auto_enricher.wrap_verdict(text)
    assert 'verdict-title' in out and 'keep rates unchanged' in out


# ── 3. Эксперт и ЛЗ — критерий «данные реально вошли» ────────────────────

def test_expert_footer_honest():
    footer = _pattern_body(EXPERT_MLOG, "ExpertSourcesFooter")
    # источник показывается только при наличии заголовка live-секции,
    # которая добавляется только при live != "" (см. BuildExpertContext)
    assert 'contains(context, "=== Live Search (двухфазный) ===")' in footer
    ctx = _pattern_body(EXPERT_MLOG, "BuildExpertContext")
    assert 'if live != "" then { let live_section =' in ctx, \
        "live-секция обязана добавляться только при непустом live (пустой live == отказ Tavily)"
    # отказ-путь ExpertTavilySearch возвращает "" (не текст-заглушку)
    search = _pattern_body(EXPERT_MLOG, "ExpertTavilySearch")
    assert 'return ""' in search


def test_lz_footer_rejections_still_filtered():
    footer = _pattern_body(LZ_MLOG, "LZSourcesFooter")
    # гвард #427 A.2: маркеры-отказы не являются источниками
    for marker in ('[tavily:', '[оценка недоступна', 'не нашёл релевантных результатов'):
        assert marker in footer, f"отсечение отказа не должно потеряться: {marker}"
