#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #499 A.5: живой сквозной прогон mlog → HTTP → python-рендер PDF.

Реальный путь прода: GenerateAnalysisCard (dept/visual.mlog, бинарь 0.30.0)
шлёт POST /render-card-pdf на 127.0.0.1:4000, python-сторона верстает PDF
pymupdf'ом со встроенным DejaVu Sans. Поднимаем минимальный WSGI-стаб на
127.0.0.1:4000, который использует ПРОДАКШН-функцию вёрстки
(_render_card_pdf_fitz из proxy/routes_tail) и резолвит относительные пути
от cwd mlog-пробника.

Проверки:
- полный отчёт → карточка рендерится, в PDF извлекается кириллица,
  страница 360×504, шрифт DejaVu встроен;
- короткий ответ без структуры → карточка не создаётся (гейт A.3);
- при недоступном рендере карточка честно не создаётся (card_render_fail).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n499-card-pdf")
os.environ.setdefault("API_SECRET", "test-secret-123")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "tg-wh-secret")
os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")

from proxy.routes_tail import _render_card_pdf_fitz  # noqa: E402

PROBE_SRC = ROOT / "scripts" / "probe499card.mlog"


def _wsgi_stub(base_dir: str):
    """WSGI-стаб: /render-card-pdf использует прод-вёрстку, путь — от base_dir."""
    def app(environ, start_response):
        if environ.get("PATH_INFO") != "/render-card-pdf":
            start_response("404 Not Found", [("Content-Type", "application/json")])
            return [json.dumps({"status": "error", "error": "unknown path"}).encode()]
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
            payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
        except Exception as e:  # noqa: BLE001
            start_response("400 Bad Request", [("Content-Type", "application/json")])
            return [json.dumps({"status": "error", "error": str(e)}).encode()]
        fpath = str(payload.get("path", ""))
        card = payload.get("card") or {}
        target = Path(fpath)
        if not target.is_absolute():
            target = Path(base_dir) / target
        if not any(str(card.get(k) or "").strip() for k in ("verdict", "theses", "probs")):
            start_response("422 Unprocessable Entity", [("Content-Type", "application/json")])
            return [json.dumps({"status": "error", "error": "card body is empty (A.3)"}).encode()]
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = _render_card_pdf_fitz(card, str(target))
        except Exception as e:  # noqa: BLE001
            start_response("500 Internal Server Error", [("Content-Type", "application/json")])
            return [json.dumps({"status": "error", "error": str(e)[:300]}).encode()]
        start_response("200 OK", [("Content-Type", "application/json")])
        return [json.dumps({"status": "ok", "path": str(target), "size": size}).encode()]
    return app


def _start_stub(base_dir: str):
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 4000, _wsgi_stub(base_dir), threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _mlog():
    p = ROOT / "bin" / "mlog"
    return p if p.exists() else None


@pytest.fixture()
def stub_server(tmp_path):
    try:
        srv = _start_stub(str(tmp_path))
    except OSError:
        pytest.skip("порт 127.0.0.1:4000 занят — сквозной прогон перенесён")
    yield srv
    srv.shutdown()


def test_live_mlog_to_proxy_render_full_card_cyrillic(tmp_path, stub_server):
    """mlog 0.30.0 → POST /render-card-pdf → PDF с кириллицей на диске."""
    import fitz
    mlog = _mlog()
    if not mlog:
        pytest.skip("bin/mlog отсутствует")
    (tmp_path / "visuals").mkdir()
    dept_dir = tmp_path / "dept"
    dept_dir.mkdir()
    for f in ("utils.mlog", "visual.mlog"):
        shutil.copy(ROOT / "dept" / f, dept_dir / f)
    probe = tmp_path / "probe.mlog"
    probe.write_text(
        PROBE_SRC.read_text(encoding="utf-8").replace(
            "sqlite:/tmp/n499card/test.db", f"sqlite:{tmp_path}/test.db"),
        encoding="utf-8")
    env = dict(os.environ)
    env["METALOGOS_HTTP_ALLOW_PRIVATE"] = "1"  # штатный внутренний канал mlog→:4000
    r = subprocess.run([mlog, "run", str(probe)], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=300, env=env)
    out = r.stdout + r.stderr
    assert "R1=" in out and "R2=" in out, f"проба не отработала: {out[-600:]}"
    assert "R1=visuals/card_report_doc-full.pdf" in out, f"полный отчёт не дал карточку: {out[-600:]}"
    assert "R2=\n" in out, "короткий ответ не должен давать карточку (A.3)"
    pdfs = list((tmp_path / "visuals").glob("*.pdf"))
    assert [p.name for p in pdfs] == ["card_report_doc-full.pdf"], \
        f"должен быть ровно один PDF полного отчёта, найдено: {[p.name for p in pdfs]}"
    doc = fitz.open(str(pdfs[0]))
    page = doc[0]
    txt = page.get_text("text")
    cyr = [ch for ch in txt if "\u0400" <= ch <= "\u04FF"]
    assert len(cyr) >= 20, "живой PDF карточки не содержит кириллицы"
    assert "Вердикт" in txt and "ТЕЗИСЫ" in txt, "секции тела потеряны в живом прогоне"
    assert "DejaVu" in " ".join(f[3] for f in page.get_fonts()), "DejaVu не встроен"
    assert abs(page.rect.width - 360.0) < 0.5 and abs(page.rect.height - 504.0) < 0.5
    doc.close()


def test_live_mlog_without_proxy_honest_no_card(tmp_path):
    """Без прокси-рендера карточка не создаётся и не отправляется (card_render_fail)."""
    mlog = _mlog()
    if not mlog:
        pytest.skip("bin/mlog отсутствует")
    (tmp_path / "visuals").mkdir()
    dept_dir = tmp_path / "dept"
    dept_dir.mkdir()
    for f in ("utils.mlog", "visual.mlog"):
        shutil.copy(ROOT / "dept" / f, dept_dir / f)
    probe = tmp_path / "probe.mlog"
    probe.write_text(
        PROBE_SRC.read_text(encoding="utf-8").replace(
            "sqlite:/tmp/n499card/test.db", f"sqlite:{tmp_path}/test.db"),
        encoding="utf-8")
    env = dict(os.environ)
    env["METALOGOS_HTTP_ALLOW_PRIVATE"] = "1"
    r = subprocess.run([mlog, "run", str(probe)], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=300, env=env)
    out = r.stdout + r.stderr
    assert "R1= | R2=\n" in out, f"без сервера карточка не должна создаваться: {out[-600:]}"
    assert not list((tmp_path / "visuals").glob("*.pdf")), "PDF не должен рождаться при сбое рендера"
