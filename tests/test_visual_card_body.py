#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #499: тело карточки Визуала (96–474) заполняется из отчёта.

Гварды:
- GenerateAnalysisCard("report", …) выбирает raw_text из miniapp_responses
  (прежде тело карточки не получало содержимое вовсе) (A.1);
- выборка разделов: вердикт/вывод, ключевые тезисы, вероятности сценариев,
  источники-домены, дата проверки прогноза (A.1);
- вёрстка: CardWrapText — перенос по ширине с лимитом строк (svg_text не
  переносит), курсор тела с потолком до подвала (A.2);
- тёмная тема FOSVED: color_palette("authority", "dark"), золотой акцент
  бренда (A.2);
- нет содержимого — карточка не создаётся и не отправляется: честный
  пустой возврат + audit-запись (A.3);
- гейт infographic_qa ДО рендера/отправки: "passed: false" → карточка не
  уходит в чат (A.4);
- живой прогон на бинаре 0.30.0: полный отчёт → PDF; короткий ответ → "".
"""
import os

import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISUAL = os.path.join(REPO, "dept", "visual.mlog")
PROBE_SRC = os.path.join(REPO, "scripts", "probe499card.mlog")

sys.path.insert(0, REPO)

with open(VISUAL, encoding="utf-8") as f:
    VISUAL_SRC = f.read()


def test_a1_report_branch_selects_raw_text():
    assert "SELECT title AS topic, confidence, 'sent' AS status, created_at, raw_text FROM miniapp_responses" in VISUAL_SRC, \
        "report-ветка должна выбирать raw_text — источник тела карточки"
    assert 'json_get(first, "raw_text", "")' in VISUAL_SRC


def test_a1_section_extractors_present():
    for pat in ("pattern CardSectionLine(", "pattern CardCollectTheses(",
                "pattern CardCollectProbs(", "pattern CardCollectDomains(",
                "pattern CardWrapText("):
        assert pat in VISUAL_SRC, f"нет вспомогательного паттерна {pat}"
    # все разделы наряда извлекаются
    assert '"ердикт"' in VISUAL_SRC, "вердикт не извлекается"
    assert '"роверка прогноза"' in VISUAL_SRC, "дата проверки прогноза не извлекается"
    assert "ИСТОЧНИКИ: " in VISUAL_SRC and "ТЕЗИСЫ" in VISUAL_SRC and "ВЕРОЯТНОСТИ" in VISUAL_SRC


def test_a2_body_in_canvas_and_wrapped():
    assert 'svg_canvas(360.0, 504.0, "0 0 360 504", [header, status_bar, body_group, footer])' in VISUAL_SRC, \
        "тело карточки не входит в svg_canvas"
    assert '"translate(0.0,96.0)"' in VISUAL_SRC, "тело не позиционировано в область 96–474"
    assert "y < 356.0" in VISUAL_SRC, "нет потолка курсора — строки могут вылезти за подвал"
    assert "CardWrapText(" in VISUAL_SRC, "перенос по ширине не применяется"


def test_a2_dark_theme():
    # #543: тёмная тема — стимпанк-палитра явными константами в шаблоне
    # (фон #1C140E — тёмный орех); color_palette больше не источник темы
    assert '"#1C140E"' in VISUAL_SRC, "тёмный фон карточки не задан"
    assert '"#c9a961"' in VISUAL_SRC, "золотой акцент бренда Fosved не задан"


def test_a3_empty_content_gate():
    assert 'if verdict == "" and theses == "" and probs == "" then' in VISUAL_SRC
    assert '"card_skipped_empty"' in VISUAL_SRC, "пропуск пустой карточки не журналируется"


def test_a4_qa_gate_before_send():
    qa_pos = VISUAL_SRC.index("let qa = infographic_qa(svg)")
    gate_pos = VISUAL_SRC.index('contains(to_string(qa), "passed: false")')
    render_pos = VISUAL_SRC.index("RenderCardPdfViaProxy(output_path")
    send_pos = VISUAL_SRC.index("SendVisualDocument(chat_id, output_path")
    assert qa_pos < gate_pos < render_pos < send_pos, \
        "QA-гейт обязан стоять до рендера и отправки, отправка — только после гейта"
    assert '"card_qa_reject"' in VISUAL_SRC, "отклонение QA не журналируется"


def test_a5_render_fail_blocks_send():
    """#499 A.5: сбой python-рендера — карточка не отправляется и журналируется."""
    render_pos = VISUAL_SRC.index("RenderCardPdfViaProxy(output_path")
    fail_pos = VISUAL_SRC.index('if rendered != "ok" then')
    send_pos = VISUAL_SRC.index("SendVisualDocument(chat_id, output_path")
    assert render_pos < fail_pos < send_pos, "гейт card_render_fail обязан стоять до отправки"
    assert '"card_render_fail"' in VISUAL_SRC, "сбой рендера не журналируется"
    assert "html_to_pdf(" not in VISUAL_SRC[VISUAL_SRC.index("pattern GenerateAnalysisCard("):
                                           VISUAL_SRC.index("pattern ", VISUAL_SRC.index("pattern GenerateAnalysisCard(") + 10)], \
        "движковый html_to_pdf удалён из пути карточки (кириллица теряется)"


def _mlog():
    p = os.path.join(REPO, "bin", "mlog")
    return p if os.path.exists(p) else None


# Живые прогоны (бинарь 0.30.0) перенесены в tests/test_visual_card_live_proxy.py:
# с #499 A.5 карточку верстает python-сторона (/render-card-pdf), поэтому
# сквозной путь проверяется со стаб-сервером на :4000, а честный отказ — без него.
