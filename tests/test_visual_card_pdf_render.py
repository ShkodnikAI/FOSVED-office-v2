#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #499 A.5: серверная вёрстка PDF-карточки Визуала с кириллицей.

Корень прод-дефекта «карточка анализа пустая» (репродукция 13.10 на
бинаре 0.30.0): движковый html_to_pdf срезает SVG-разметку и пишет текст
сырыми UTF-8-байтами базовым Helvetica без /Encoding — кириллица не имеет
глифов (0 кириллических символов при извлечении, mojibake при рендере).

Гварды:
- POST /render-card-pdf верстает тёмную карточку 360×504 pymupdf'ом со
  встроенным DejaVu Sans: извлечённый текст содержит кириллицу, страница
  ровно 360×504 (A.5);
- пустое тело карточки → 422, пустой PDF не рождается (A.3 на стороне
  python — дубль mlog-гейта);
- 400 без path/card; 403 за пределами рабочих каталогов (тот же гард,
  что у /send-document);
- сбой шрифта/рендера → честный 500 с причиной;
- в mlog-исходнике GenerateAnalysisCard больше нет html_to_pdf: delivery
  путь — RenderCardPdfViaProxy → /render-card-pdf, сбой → card_render_fail
  и карточка не отправляется.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n499-card-pdf")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import fitz  # noqa: E402
import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402
from proxy.routes_tail import _render_card_pdf_fitz, _wrap_pdf_text  # noqa: E402

VISUAL_SRC = (ROOT / "dept" / "visual.mlog").read_text(encoding="utf-8")

FULL_CARD = {
    "badge": "ОТЧЁТ",
    "topic": "Дизель США: консолидированная сводка",
    "status": "sent",
    "confidence": "3.0",
    "created_at": "2026-10-13 08:17:35",
    "verdict": "наблюдать за рынком — риски сбалансированы",
    "theses": "Запасы дизтоплива в ARA упали на 8 процентов за неделю.\nРоссийский экспорт дизеля в США вырос в октябре.",
    "probs": "база 60 процентов, риск дефицита 30 процентов",
    "domains": "reuters.com · eia.gov",
    "check_date": "Проверка прогноза: 2026-11-12 по фактическим запасам EIA.",
}


def _client():
    return flask_app.test_client()


def test_a5_render_card_ok_cyrillic_visible(tmp_path):
    """Счастливый путь: карточка верстается, кириллица извлекается, лист 360×504."""
    out_dir = tmp_path / "visuals"
    r = _client().post("/render-card-pdf", json={
        "path": str(out_dir / "card_report_doc-full.pdf"),
        "card": dict(FULL_CARD),
    })
    assert r.status_code == 200, f"ожидался 200, получено {r.status_code}: {r.get_json()}"
    body = r.get_json()
    assert body["status"] == "ok" and body["size"] > 0, "рендер не отчитался ok/размером"
    pdf_path = Path(body["path"])
    assert pdf_path.is_file(), "PDF-файл не создан"
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    assert abs(page.rect.width - 360.0) < 0.5 and abs(page.rect.height - 504.0) < 0.5, \
        f"лист должен быть 360×504, получено {page.rect}"
    txt = page.get_text("text")
    cyr = [ch for ch in txt if "\u0400" <= ch <= "\u04FF"]
    assert len(cyr) >= 20, f"кириллица не извлекается из PDF (>{len(cyr)} глифов)"
    for probe in ("ОТЧЁТ", "Вердикт", "ТЕЗИСЫ", "ВЕРОЯТНОСТИ", "ИСТОЧНИКИ", "FOSVED OFFICE"):
        assert probe in txt, f"в PDF нет секции {probe!r} — тело карточки потеряно"
    # шрифт с кириллицей реально встроен (не голый Helvetica base-14)
    fonts = " ".join(f[3] for f in page.get_fonts())
    assert "DejaVu" in fonts, f"DejaVu не встроен, шрифты: {fonts}"
    assert "Helvetica" not in fonts, "голый Helvetica недопустим — это путь html_to_pdf"
    doc.close()


def test_a5_empty_body_rejected_422_no_file(tmp_path):
    """Пустое тело (A.3) → 422 и файла нет: пустая карточка не рендерится даже напрямую."""
    out = tmp_path / "visuals" / "card_empty.pdf"
    r = _client().post("/render-card-pdf", json={
        "path": str(out),
        "card": {"badge": "ОТЧЁТ", "topic": "Тема", "status": "sent"},
    })
    assert r.status_code == 422, f"ожидался 422, получено {r.status_code}"
    assert not out.exists(), "пустой PDF не должен создаваться"


def test_a5_missing_args_400():
    r = _client().post("/render-card-pdf", json={"path": ""})
    assert r.status_code == 400
    r = _client().post("/render-card-pdf", json={"path": "visuals/x.pdf", "card": "строка вместо dict"})
    assert r.status_code == 400


def test_a5_path_guard_403(tmp_path):
    r = _client().post("/render-card-pdf", json={
        "path": "/etc/n499-evil.pdf", "card": dict(FULL_CARD),
    })
    assert r.status_code == 403, "путь вне рабочих каталогов обязан отклоняться"


def test_a5_render_failure_is_honest_500(tmp_path, monkeypatch):
    """Сбой вёрстки → 500 с причиной, а не молчаливый пустой файл."""
    def boom(card, out_path):
        raise RuntimeError("font engine unavailable")
    monkeypatch.setattr("proxy.routes_tail._render_card_pdf_fitz", boom)
    r = _client().post("/render-card-pdf", json={
        "path": str(tmp_path / "visuals" / "card_boom.pdf"), "card": dict(FULL_CARD),
    })
    assert r.status_code == 500
    assert "font engine unavailable" in r.get_json()["error"]


def test_a5_wrap_respects_width_and_marks_truncation():
    """Перенос по измеренной ширине: строка помещается, усечение помечено '…'."""
    font = fitz.Font(fontfile="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    max_w = 324.0
    short = "короткая строка"
    assert len(_wrap_pdf_text(short, font, 10.0, max_w, 3)) == 1
    long_line = " verylongunbreakabletoken" * 5
    rows = _wrap_pdf_text(long_line, font, 10.0, max_w, 2)
    assert len(rows) <= 2 and rows[-1].endswith("…"), "усечение должно помечаться многоточием"
    for row in rows:
        assert font.text_length(row, fontsize=10.0) <= max_w, "строка шире лимита"


def test_a5_no_html_to_pdf_in_card_delivery_path():
    """В GenerateAnalysisCard больше нет html_to_pdf — delivery через прокси-рендер."""
    start = VISUAL_SRC.index("pattern GenerateAnalysisCard(")
    end = VISUAL_SRC.index("pattern ", start + 10)
    card_body = VISUAL_SRC[start:end]
    assert "html_to_pdf(" not in card_body, \
        "карточка не должна рендериться движковым html_to_pdf (кириллица теряется)"
    assert "RenderCardPdfViaProxy(output_path" in card_body, "нет вызова python-рендера"
    assert '"card_render_fail"' in card_body, "сбой рендера не журналируется"
    # порядок: QA-гейт → рендер → только потом отправка
    qa = card_body.index('contains(to_string(qa), "passed: false")')
    render = card_body.index("RenderCardPdfViaProxy(output_path")
    send = card_body.index("SendVisualDocument(chat_id, output_path")
    assert qa < render < send, "QA-гейт обязан стоять до рендера и отправки"
