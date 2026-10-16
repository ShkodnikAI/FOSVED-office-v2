#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #515: html_to_pdf теряет кириллицу системно → compression/memorable/
reference/spec на python-вёрстку (/render-svg-pdf).

Root cause #499: движковый html_to_pdf (src/builtins/pdf.rs) срезает все теги
и пишет кириллицу сырыми UTF-8-байтами базовым Helvetica без /Encoding —
команды /visual compression|memorable|reference|spec выдавали битые PDF.

Фикс: MuPDF открывает SVG как документ (примитивы svg_canvas/chart_*/svg_text)
и конвертирует в PDF с сохранением юникода (живой прогон: «Апрель»/«Май» в
get_text, 33-51 кириллических глифов в PDF реальных генераторов).

Гварды:
- живые вызовы html_to_pdf отсутствуют в dept/visual.mlog;
- три генератора идут через RenderSvgPdfViaProxy с гардом svg_render_fail;
- endpoint: ok/400/403; кириллица сохраняется в PDF-тексте.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n515-test'
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '')

import llm_proxy  # noqa: E402,F401
from proxy import routes_tail  # noqa: E402
from proxy.core import app as flask_app  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VISUAL = os.path.join(REPO, "dept", "visual.mlog")
SRC = open(VISUAL, encoding="utf-8").read()

SVG_CYR = ('<svg xmlns="http://www.w3.org/2000/svg" width="300" height="120" '
           'viewBox="0 0 300 120">'
           '<rect x="0" y="0" width="300" height="120" fill="#ffffff" />'
           '<text x="20" y="40" font-size="14" fill="#111111">Сжатие: анализ дизтоплива</text>'
           '<text x="20" y="70" font-size="12" fill="#333333">Вероятности: база 55%</text>'
           '</svg>')


@pytest.fixture()
def client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_no_live_html_to_pdf_in_visual():
    import re
    lines = [l for l in SRC.splitlines() if "html_to_pdf(" in l and not l.strip().startswith("//")]
    assert not lines, f"живые вызовы html_to_pdf остались: {lines}"


def test_three_generators_use_svg_proxy_with_fail_gate():
    for gen, marker in (("compression", "visuals/compression_"),
                        ("memorable", "visuals/infographic_"),
                        ("reference", "visuals/ref_")):
        i = SRC.index(marker)
        block = SRC[i:i + 1200]
        assert "RenderSvgPdfViaProxy(output_path" in block, f"{gen}: не через python-вёрстку"
        assert 'svg_render_fail' in block, f"{gen}: нет гарда честного отказа"
        assert "html_to_pdf" not in block or "html_to_pdf(" not in block.replace("// ", ""), \
            f"{gen}: движковый html_to_pdf остался"


def test_render_svg_pdf_via_proxy_pattern_exists():
    assert "pattern RenderSvgPdfViaProxy(fpath: String, svg: String, width: Float, height: Float)" in SRC


def test_endpoint_renders_cyrillic(client, tmp_path):
    r = client.post('/render-svg-pdf', json={
        "path": str(tmp_path / "out.pdf"), "svg": SVG_CYR})
    assert r.status_code == 200, r.get_data(as_text=True)
    import fitz
    d = fitz.open(str(tmp_path / "out.pdf"))
    txt = d[0].get_text("text")
    d.close()
    assert "Сжатие: анализ дизтоплива" in txt, "кириллица потеряна в PDF-тексте"
    assert "55%" in txt


def test_endpoint_empty_svg_400(client):
    r = client.post('/render-svg-pdf', json={"path": "/tmp/x.pdf", "svg": ""})
    assert r.status_code == 400


def test_endpoint_path_outside_roots_403(client):
    r = client.post('/render-svg-pdf', json={"path": "/etc/passwd.pdf", "svg": SVG_CYR})
    assert r.status_code == 403
