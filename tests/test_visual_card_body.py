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
    assert 'color_palette("authority", "dark")' in VISUAL_SRC
    assert '"#c9a961"' in VISUAL_SRC, "золотой акцент бренда Fosved не задан"


def test_a3_empty_content_gate():
    assert 'if verdict == "" and theses == "" and probs == "" then' in VISUAL_SRC
    assert '"card_skipped_empty"' in VISUAL_SRC, "пропуск пустой карточки не журналируется"


def test_a4_qa_gate_before_send():
    qa_pos = VISUAL_SRC.index("let qa = infographic_qa(svg)")
    gate_pos = VISUAL_SRC.index('contains(to_string(qa), "passed: false")')
    pdf_pos = VISUAL_SRC.index("let _ = html_to_pdf(html, output_path)")
    send_pos = VISUAL_SRC.index("SendVisualDocument(chat_id, output_path")
    assert qa_pos < gate_pos < pdf_pos < send_pos, \
        "QA-гейт обязан стоять до рендера и отправки, отправка — только после гейта"
    assert '"card_qa_reject"' in VISUAL_SRC, "отклонение QA не журналируется"


def _mlog():
    p = os.path.join(REPO, "bin", "mlog")
    return p if os.path.exists(p) else None


def test_live_probe_full_report_makes_card_short_makes_none(tmp_path):
    """Живой путь на 0.30.0: полный отчёт → PDF-карточка; короткий ответ → ''. """
    mlog = _mlog()
    if not mlog:
        import pytest
        pytest.skip("bin/mlog отсутствует")
    (tmp_path / "visuals").mkdir()
    # импорты резолвятся от cwd: кладём dept/* в tmp; utils/visual без
    # транзитивных импортов — двух файлов достаточно
    dept_dir = tmp_path / "dept"
    dept_dir.mkdir()
    for f in ("utils.mlog", "visual.mlog"):
        shutil.copy(os.path.join(REPO, "dept", f), dept_dir / f)
    # копия пробника с db в tmp (оригинальный probe держит фиксированный /tmp)
    probe = tmp_path / "probe.mlog"
    probe.write_text(
        open(PROBE_SRC, encoding="utf-8").read().replace(
            "sqlite:/tmp/n499card/test.db", f"sqlite:{tmp_path}/test.db"),
        encoding="utf-8")
    env = dict(os.environ)
    r = subprocess.run([mlog, "run", str(probe)], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=300, env=env)
    out = r.stdout + r.stderr
    assert "R1=" in out and "R2=" in out, f"проба не отработала: {out[-600:]}"
    assert "card_report_doc-full" in out, "полный отчёт не дал карточку"
    assert "R2=\n" in out, "короткий ответ не должен давать карточку (A.3)"
    pdfs = list((tmp_path / "visuals").glob("*.pdf"))
    assert any("doc-full" in p.name for p in pdfs), "PDF карточки не создан"
    assert not any("doc-short" in p.name for p in pdfs), "пустая карточка создана"
