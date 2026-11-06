#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#673 MF-2: карточка анализа Monolith F — PNG 1080×1350, отправка картинкой.

Гварды:
- /render-card-png на фикстуре полного отчёта → PNG ровно 1080×1350 (A.3);
- отчёт без сценариев и индикаторов → колонок нет, размер тот же, блоки
  не накладываются (рендер не падает, подвал на месте);
- PNG не пустой (разброс пикселей) и несёт фон Monolith F (тёплые пиксели
  огненной трещины/золота);
- шрифты: файлы Unbounded/Manrope (OFL) на месте в proxy/fonts/ вместе с
  OFL-лицензией; отсутствие файла шрифта → громкий fallback на DejaVu
  (log.warning) и рендер всё равно successful (A.1);
- /send-photo: 400 без аргументов, 403 вне рабочих каталогов, ok с
  замоканным _tg_send_photo (сеть не трогается);
- PDF-путь не тронут: /render-card-pdf живёт рядом (A.4 запрет);
- mlog-сторона: SendVisualPhoto/RenderCardPngViaProxy объявлены,
  GenerateAnalysisCardEx получает dept для подвала, PNG-first с фолбэком.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n673-monolith")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402
from proxy import routes_tail  # noqa: E402

VISUAL_SRC = (ROOT / "dept" / "visual.mlog").read_text(encoding="utf-8")

FULL_CARD = {
    "badge": "ОТЧЁТ",
    "topic": "Дизель США: консолидированная сводка по рынку",
    "status": "sent",
    "confidence": "3.0",
    "created_at": "2026-11-06 15:30:00",
    "verdict": "наблюдать за рынком — риски сбалансированы, спрос устойчив при текущих ценах",
    "theses": "Запасы ARA упали на 8 процентов.\nЭкспорт вырос в октябре.",
    "probs": "базовый сценарий — 60% (спрос ровный)\nдефицитный сценарий — 30% (забастовки)",
    "domains": "reuters.com · eia.gov",
    "check_date": "2026-11-12",
    "terms": "запасы ARA — 2026-11-12\nэкспорт США — 30.11.2026",
    "dept": "lz",
    "doc_id": "4213",
}


def _client():
    return flask_app.test_client()


def _png_pixels(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(float)


class TestRenderCardPng:
    def test_full_card_is_exactly_1080x1350(self, tmp_path):
        out = tmp_path / "card_full.png"
        r = _client().post('/render-card-png', json={"path": str(out), "card": FULL_CARD})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["status"] == "ok"
        img = Image.open(out)
        assert img.size == (1080, 1350)

    def test_png_is_not_blank_and_carries_monolith_bg(self, tmp_path):
        out = tmp_path / "card_bg.png"
        r = _client().post('/render-card-png', json={"path": str(out), "card": FULL_CARD})
        assert r.status_code == 200
        a = _png_pixels(out)
        # не однотонный: заметный разброс
        assert a.std() > 10.0
        # фон Monolith F на месте: тёплые (огненные/золотые) пиксели есть
        warm = ((a[..., 0] > 120) & (a[..., 0] > a[..., 2] + 40)).mean()
        assert warm > 0.001, "фон/акценты Monolith F не найдены на рендере"

    def test_card_without_scenarios_and_terms_renders(self, tmp_path):
        card = dict(FULL_CARD)
        card["probs"] = ""
        card["terms"] = ""
        card["check_date"] = ""
        out = tmp_path / "card_min.png"
        r = _client().post('/render-card-png', json={"path": str(out), "card": card})
        assert r.status_code == 200, r.get_json()
        img = Image.open(out)
        assert img.size == (1080, 1350)
        a = _png_pixels(out)
        # подвал на месте (светлый текст в зоне baseline 432 pt ≈ ряды 1260-1310)
        assert a[1260:1310].max() > 60

    def test_empty_body_is_422(self, tmp_path):
        card = {k: "" for k in FULL_CARD}
        out = tmp_path / "empty.png"
        r = _client().post('/render-card-png', json={"path": str(out), "card": card})
        assert r.status_code == 422
        assert not out.exists()

    def test_bad_request_and_path_guard(self, tmp_path):
        c = _client()
        assert c.post('/render-card-png', json={"card": FULL_CARD}).status_code == 400
        r = c.post('/render-card-png', json={"path": "/etc/n673-evil.png", "card": FULL_CARD})
        assert r.status_code == 403

    def test_font_fallback_is_loud_but_renders(self, tmp_path, monkeypatch, caplog):
        # файла шрифта нет → DejaVu + громкое предупреждение, рендер успешен
        monkeypatch.setitem(routes_tail._MONOLITH_FONT_CANDIDATES, "heading", "proxy/fonts/No-Such-Font.ttf")
        out = tmp_path / "card_fallback.png"
        import logging
        with caplog.at_level(logging.WARNING, logger=routes_tail.log.name):
            r = _client().post('/render-card-png', json={"path": str(out), "card": FULL_CARD})
        assert r.status_code == 200, r.get_json()
        assert Image.open(out).size == (1080, 1350)
        assert any("monolith fonts missing" in rec.message for rec in caplog.records)

    def test_fonts_and_license_committed(self):
        # A.1: шрифты OFL в репо с файлом лицензии
        fonts = ROOT / "proxy" / "fonts"
        for name in ("Unbounded-SemiBold.ttf", "Unbounded-ExtraBold.ttf",
                     "Manrope-Regular.ttf", "Manrope-Bold.ttf"):
            assert (fonts / name).is_file(), name
        ofl = (fonts / "OFL.txt").read_text(encoding="utf-8")
        assert "Unbounded" in ofl and "Manrope" in ofl
        assert "SIL OPEN FONT LICENSE" in ofl.upper()

    def test_background_asset_committed(self):
        # A.2: фон сгенерирован и закоммичен, ровно 1080×1350
        img = Image.open(ROOT / "proxy" / "assets" / "monolith_bg_1080x1350.png")
        assert img.size == (1080, 1350)


class TestSendPhotoEndpoint:
    def test_requires_args(self):
        c = _client()
        assert c.post('/send-photo', json={"path": "x.png"}).status_code == 400
        assert c.post('/send-photo', json={"chat_id": "1"}).status_code == 400

    def test_path_guard(self, tmp_path):
        r = _client().post('/send-photo', json={"path": "/etc/passwd", "chat_id": "1"})
        assert r.status_code == 403

    def test_sends_photo_via_tg(self, tmp_path, monkeypatch):
        f = tmp_path / "pic.png"
        Image.new("RGB", (10, 10), (1, 2, 3)).save(f)
        sent = {}
        monkeypatch.setattr(routes_tail, "_tg_send_photo",
                            lambda chat_id, path, caption=None: sent.update({"chat_id": chat_id, "path": path, "caption": caption}) or 4242)
        r = _client().post('/send-photo', json={"path": str(f), "chat_id": "777", "caption": "Карточка"})
        assert r.status_code == 200
        assert r.get_json() == {"status": "ok", "tg_msg_id": 4242}
        assert sent["chat_id"] == "777" and sent["path"] == str(f)

    def test_tg_failure_is_502(self, tmp_path, monkeypatch):
        f = tmp_path / "pic2.png"
        Image.new("RGB", (10, 10)).save(f)
        monkeypatch.setattr(routes_tail, "_tg_send_photo", lambda *a, **k: None)
        r = _client().post('/send-photo', json={"path": str(f), "chat_id": "777"})
        assert r.status_code == 502


class TestMlogSide:
    def test_send_visual_photo_pattern_exists(self):
        assert "pattern SendVisualPhoto(chat_id: String, fpath: String, caption: String) -> String" in VISUAL_SRC
        assert 'http_post("http://127.0.0.1:4000/send-photo"' in VISUAL_SRC

    def test_png_first_with_pdf_fallback(self):
        # GenerateAnalysisCardEx: PNG основной путь, сбой → audit + PDF-путь
        assert "pattern GenerateAnalysisCardEx(src_type: String, src_id: String, chat_id: String, dept_hint: String)" in VISUAL_SRC
        assert "RenderCardPngViaProxy(png_path, card_json)" in VISUAL_SRC
        assert 'AuditLog("card_png_fallback"' in VISUAL_SRC
        # PDF-путь не удалён (запрет наряда)
        assert "RenderCardPdfViaProxy(output_path" in VISUAL_SRC
        # авто-хук передаёт настоящий отдел в подвал
        assert 'GenerateAnalysisCardEx("report", doc_id, chat_id, dept)' in VISUAL_SRC
