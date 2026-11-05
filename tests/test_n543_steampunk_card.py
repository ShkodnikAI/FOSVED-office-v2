#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #543 → #640 п.6: карточка Визуала — заголовок целиком, все сценарии.

Палитра: стимпанк (#543, 17.10) заменена Monolith F (решение владельца
04.11, наряд #640 п.6) — тест гвардит ТЕКУЩУЮ палитру.

Гварды:
- A.1 пиксельный тест: рендер карточки с палитрой Monolith F (поля card) →
  PNG через page.get_pixmap: фон (W/2, H−20) = #0A0D12 ±2; шапка (10, 36) =
  #24282E ±2; центр шестерни (W−40, 36) = #24282E ±2; зуб (W−22, 36) =
  #3A3F46 ±2;
- A.1 палитра через поля card: python НЕ хардкодит цвета (статгвард: ни
  одного стимпанк-hex в routes_tail.py; фолбэки — прежняя тема);
- A.2 заголовок: полная тема «OSP: прогноз на ближайшие 6 месяцев, будет
  ли обвал доллара» → в PDF нет «дол» в конце строки, слово «доллара»
  присутствует целиком (page.get_text); ширина переноса шапки уменьшена
  на 40 pt под шестерню (статгвард);
- A.3 сценарии: 4 строки (45/20/10/25) → строки про сумму нет; 3 строки
  (45/20/10) → dim-строка «Сумма сценариев: 75%»; mlog собирает до 6
  строк (CardCollectProbs 6.0 — статгвард);
- обратная совместимость: карточка без новых полей рендерится (фолбэки).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n543-card")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import fitz  # noqa: E402
import llm_proxy  # noqa: E402,F401
from proxy.routes_tail import _render_card_pdf_fitz  # noqa: E402

VISUAL_SRC = (ROOT / "dept" / "visual.mlog").read_text(encoding="utf-8")
TAIL_SRC = (ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")

TOPIC_FULL = "OSP: прогноз на ближайшие 6 месяцев, будет ли обвал доллара"

MONOLITH = {
    "accent": "#24282E", "paper": "#0A0D12", "ink": "#EEF0F2",
    "dim": "#9AA0A8", "rule": "#3A3F46", "title": "#FFC04D",
    "heading": "#E0B56A", "verdict_c": "#FFCF7A",
}


def _card(**over):
    base = {
        "badge": "ОСП", "topic": TOPIC_FULL, "confidence": "средняя",
        "created_at": "2026-10-17", "verdict": "Наблюдать, хеджировать валютные риски.",
        "theses": "Курс стабилен\nВолатильность снизится",
        "probs": "Укрепление — 45%\nУмеренное укрепление — 20%\nБоковик — 10%",
        "domains": "", "terms": "", "check_date": "",
    }
    base.update(MONOLITH)
    base.update(over)
    return base


def _render_png(card, tmp_path):
    out = str(tmp_path / "card.pdf")
    _render_card_pdf_fitz(card, out)
    doc = fitz.open(out)
    page = doc[0]
    pix = page.get_pixmap(alpha=False)
    return doc, page, pix


def _close(pix, x, y, hex_color, tol=2):
    m = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    got = pix.pixel(int(x), int(y))[:3]
    assert all(abs(g - e) <= tol for g, e in zip(got, m)), \
        f"пиксель ({x},{y}): {got} != {m} ({hex_color})"


# ── A.1: пиксельный тест палитры и орнамента ────────────────────────────

def test_a1_pixel_background_and_header(tmp_path):
    doc, page, pix = _render_png(_card(), tmp_path)
    W, H = page.rect.width, page.rect.height
    assert (W, H) == (360.0, 504.0)
    _close(pix, W / 2, H - 20, "#0A0D12")   # фон карточки — тёмный камень
    _close(pix, 10, 36, "#24282E")          # шапка — каменная грань


def test_a1_pixel_gear_ornament(tmp_path):
    doc, page, pix = _render_png(_card(), tmp_path)
    W = page.rect.width
    _close(pix, W - 40, 36, "#24282E")      # центр шестерни — цвет шапки
    _close(pix, W - 22, 36, "#3A3F46")      # зуб шестерни — rule


def test_a1_palette_not_hardcoded_in_python():
    """#543 → #640 п.6: цвета передаются полями card — hex палитры в python запрещены."""
    for hexc in ("#24282E", "#0A0D12", "#EEF0F2", "#9AA0A8", "#E0B56A", "#FFC04D", "#FFCF7A"):
        assert hexc not in TAIL_SRC, f"палитра захардкожена в python: {hexc}"


def test_a1_mlog_palette_fields():
    """mlog-шаблон несёт палитру Monolith F (#640 п.6) и передаёт поля card."""
    for lit in ('"#24282E"', '"#0A0D12"', '"#EEF0F2"', '"#9AA0A8"', '"#3A3F46"',
                '"#FFC04D"', '"#E0B56A"', '"#FFCF7A"'):
        assert lit in VISUAL_SRC, f"нет цвета {lit} в dept/visual.mlog"
    assert "pattern RenderCardPdfViaProxy" in VISUAL_SRC
    sig = VISUAL_SRC[VISUAL_SRC.index("pattern RenderCardPdfViaProxy"):]
    assert "title: String, heading: String, verdict_c: String" in sig, \
        "палитра не передаётся полями card"


# ── A.2: заголовок целиком ──────────────────────────────────────────────

def test_a2_full_topic_no_midword_cut(tmp_path):
    doc, page, pix = _render_png(_card(), tmp_path)
    lines = [ln.rstrip() for ln in page.get_text().splitlines() if ln.strip()]
    # «дол» не стоит в конце ни одной строки
    assert not any(ln.endswith("дол") for ln in lines), lines[:6]
    # полное слово присутствует
    assert "доллара" in page.get_text(), lines[:6]
    # последнее слово первой строки заголовка целое (не заканчивается на …)
    title_rows = [ln for ln in lines if ln.startswith("OSP:")]
    assert title_rows, lines[:6]
    assert not title_rows[0].endswith("…"), title_rows


def test_a2_header_wrap_width_reduced_for_gear():
    """Ширина текста шапки уменьшена на 40 pt (зубья не налезают на текст)."""
    assert "W - 36.0 - 40.0" in TAIL_SRC, "клиренс шестерни не применён"


# ── A.3: все сценарии + строка суммы ────────────────────────────────────

def test_a3_four_scenarios_sum_100_no_sum_line(tmp_path):
    probs = "Укрепление — 45%\nУмеренное укрепление — 20%\nБоковик — 10%\nОслабление — 25%"
    doc, page, pix = _render_png(_card(probs=probs), tmp_path)
    text = page.get_text()
    assert "Ослабление — 25%" in text
    assert "Сумма сценариев" not in text


def test_a3_three_scenarios_sum_75_gets_dim_line(tmp_path):
    probs = "Укрепление — 45%\nУмеренное укрепление — 20%\nБоковик — 10%"
    doc, page, pix = _render_png(_card(probs=probs), tmp_path)
    text = page.get_text()
    assert "Сумма сценариев: 75%" in text, text[:400]


def test_a3_mlog_collects_up_to_six_lines():
    assert "CardCollectProbs(body_text, 6.0, 46.0)" in VISUAL_SRC, \
        "CardCollectProbs по-прежнему режет 3 строки"


# ── Обратная совместимость ──────────────────────────────────────────────

def test_legacy_card_without_new_fields_renders(tmp_path):
    card = _card()
    for k in ("title", "heading", "verdict_c"):
        card.pop(k)
    doc, page, pix = _render_png(card, tmp_path)
    text = page.get_text()
    assert "OSP: прогноз" in text and "доллара" in text   # заголовок отрисован целиком
    assert "Вердикт:" in text
