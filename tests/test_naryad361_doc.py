#!/usr/bin/env python3
"""naryad-361: /send-document — доставка файла Визуала в Telegram как документа.

Проверки (LLM/TG замоканы, транспорт живой):
- реальный файл → 200 ok, _tg_send_document вызван с верными аргументами;
- путь вне рабочих каталогов → 403 (не произвольное чтение);
- несуществующий файл → 404;
- сбой Telegram → 502.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-naryad361-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import app, _log_audit  # noqa: E402
import proxy.routes_tail as rt  # noqa: E402


def test_send_document_ok(monkeypatch, tmp_path):
    f = tmp_path / "card_analysis_1.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    calls = {}

    def fake_send_doc(chat_id, file_path, caption=None):
        calls['args'] = (chat_id, file_path, caption)
        return 4242

    monkeypatch.setattr(rt, '_tg_send_document', fake_send_doc)
    client = app.test_client()
    resp = client.post('/send-document', json={
        'path': str(f), 'chat_id': '555000', 'caption': 'Визуал: карточка анализа',
    })
    body = resp.get_json()
    assert resp.status_code == 200 and body['status'] == 'ok', body
    assert body['tg_msg_id'] == 4242
    assert calls['args'][0] == '555000'
    assert calls['args'][1] == str(f)
    assert calls['args'][2] == 'Визуал: карточка анализа'


def test_send_document_path_outside_roots(monkeypatch):
    # /etc не входит в allowed roots (cwd офиса, /tmp) — 403 до проверки файла
    monkeypatch.setattr(rt, '_tg_send_document', lambda *a, **k: 1)
    client = app.test_client()
    resp = client.post('/send-document', json={'path': '/etc/passwd', 'chat_id': '555000'})
    assert resp.status_code == 403, resp.get_json()


def test_send_document_missing_file(monkeypatch):
    monkeypatch.setattr(rt, '_tg_send_document', lambda *a, **k: 1)
    client = app.test_client()
    resp = client.post('/send-document', json={'path': '/tmp/vis361/negative_case_no_file.pdf', 'chat_id': '555000'})
    assert resp.status_code == 404, resp.get_json()


def test_send_document_tg_failure(monkeypatch, tmp_path):
    f = tmp_path / "infographic_lz_1.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(rt, '_tg_send_document', lambda *a, **k: None)
    client = app.test_client()
    resp = client.post('/send-document', json={'path': str(f), 'chat_id': '555000'})
    assert resp.status_code == 502, resp.get_json()
