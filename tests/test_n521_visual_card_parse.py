#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #521: карточка Визуала — детерминированный разбор без сырой разметки.

Прод-скрин владельца 16.10: `**$5 595,42**` в тексте, блок «ВЕРОЯТНОСТИ»
заполнен тезисами и обрывком дисклеймера, вердикт пустой (заголовок с
текстом на следующей строке), заголовок обрезан посреди слова («…до кон»),
«Уверенность: 2.0» и служебный «Статус: sent».

Гварды (статические, по dept/visual.mlog и proxy/routes_tail.py):
- A.1 CardCleanLine: снятие **/__/` и ведущих #/-/•/>; применяется ко всем
  полям (вердикт, тезисы, вероятности, дата проверки, заголовок);
- A.2 CardCollectProbs: строки только внутри раздела сценариев (заголовок
  с «ценари»/«ероятност», регистронезависимо) и только с %; фильтр дублей
  тезисов в GenerateAnalysisCard;
- A.3 CardSectionLine: пустой rest после маркера → первая непустая строка
  ниже (не заголовок);
- A.4 заголовок: CardWrapText 2 строки с «…» на границе слова — и в SVG,
  и в python-вёрстке (_wrap_pdf_text вместо [:80]);
- A.5 статус «sent» убран с карточки; уверенность словом (CardConfLabel:
  шкала 0..4 → низкая/средняя/высокая; low/medium/high → то же).
Живая проверка: scripts/probe499card.mlog на бинаре 0.32.0 + прод-вёрстка —
PDF-текст без **, вердикт присутствует, probs только из раздела (см. отчёт).
"""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISUAL = os.path.join(REPO, "dept", "visual.mlog")
TAIL = os.path.join(REPO, "proxy", "routes_tail.py")

with open(VISUAL, encoding="utf-8") as f:
    SRC = f.read()
with open(TAIL, encoding="utf-8") as f:
    TAIL_SRC = f.read()


def test_a1_clean_line_pattern_exists_and_applied():
    assert "pattern CardCleanLine(raw: String) -> String" in SRC, "нет общей чистки строки"
    block = SRC[SRC.index("pattern CardCleanLine"):SRC.index("pattern CardSectionLine")]
    for lit in ('"**"', '"__"', '"`"'):
        assert lit in block, f"CardCleanLine не снимает {lit}"
    # применяется ко всем полям
    assert "CardCleanLine(s)" in SRC or "CardCleanLine(clean)" in SRC, "чистка не применена к строкам"
    assert "substring(CardCleanLine(s)" in SRC, "SectionLine без чистки"
    assert "CardCleanLine(clean)" in SRC, "тезисы без чистки разметки"
    assert "CardCleanLine(topic)" in SRC, "заголовок без чистки"


def test_a2_probs_only_inside_scenarios_section():
    block = SRC[SRC.index("pattern CardCollectProbs"):SRC.index("pattern CardCollectDomains")]
    assert "in_section" in block, "нет границы раздела сценариев"
    assert 'contains(ls, "ценари")' in block and 'contains(ls, "ероятност")' in block, \
        "заголовок раздела не распознаётся (регистронезависимо)"
    assert 'contains(s, "%")' in block, "берутся строки без процента"
    assert 'contains(s, "ероятност") then {\n          let n' not in block, \
        "старая логика «любая строка с ероятност» осталась"
    # фильтр дублей тезисов
    assert "contains(theses, head)" in SRC, "строки вероятностей не фильтруются против тезисов"


def test_a3_section_line_takes_next_nonempty_line():
    block = SRC[SRC.index("pattern CardSectionLine"):SRC.index("// Ключевые тезисы")]
    assert "take_next" in block, "нет фолбэка на следующую строку"
    assert 'starts_with(s, "#") then { }' in block, "фолбэк не пропускает заголовки"


def test_a4_title_wraps_two_lines_not_cut():
    assert 'CardWrapText(CardCleanLine(topic), 26.0, 2.0)' in SRC, "заголовок SVG не переносится"
    assert "substring(topic, 0.0, 40.0)" not in SRC.split("pattern GenerateCompressionVisual")[0].split("pattern GenerateAnalysisCard")[-1], \
        "SVG-заголовок всё ещё режется посреди слова"
    # python-вёрстка: перенос вместо [:80]; #543 — ширина минус 40 pt под шестерню
    assert "topic = str(card.get(\"topic\") or \"\")\n" in TAIL_SRC.replace("topic = str(card.get(\"topic\") or \"\")\n", "topic = str(card.get(\"topic\") or \"\")\n"), "заголовок python-вёрстки"
    assert 'topic = str(card.get("topic") or "")[:80]' not in TAIL_SRC, "python-вёрстка режет заголовок [:80]"
    assert "_wrap_pdf_text(topic, font_bold, 13.0, W - 36.0 - 40.0, 2)" in TAIL_SRC, "python-вёрстка не переносит заголовок"


def test_a5_no_sent_status_and_word_confidence():
    assert '"Статус: " + status' not in SRC, "SVG-карточка всё ещё печатает служебный статус"
    assert "pattern CardConfLabel(raw: String) -> String" in SRC, "нет перевода уверенности в слово"
    block = SRC[SRC.index("pattern CardConfLabel"):SRC.index("pattern CardSectionLine")]
    for w in ("низкая", "средняя", "высокая"):
        assert f'return "{w}"' in block, f"CardConfLabel без «{w}»"
    assert "Уверенность: " + "conf_label" in SRC.replace('"Уверенность: " + conf_label', 'Уверенность: " + conf_label') or \
        '"Уверенность: " + conf_label' in SRC, "SVG не использует словесную уверенность"
    # python-вёрстка
    assert '"Статус: " + str(card.get("status")' not in TAIL_SRC, "PDF-вёрстка всё ещё печатает статус"
    assert '"Уверенность: " + conf_label' in TAIL_SRC, "PDF-вёрстка не печатает словесную уверенность"


def test_send_path_uses_clean_topic_and_label():
    call = SRC[SRC.index("RenderCardPdfViaProxy(output_path"):SRC.index("if rendered != \"ok\"")]
    assert "CardCleanLine(topic)" in call, "PDF-рендеру уходит грязный заголовок"
    assert "conf_label" in call, "PDF-рендеру уходит сырая уверенность"
