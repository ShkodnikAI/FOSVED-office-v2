#!/usr/bin/env python3
"""Наряд #365: приём документов — роут /download-telegram-file + запасной путь.

Было: app.mlog звал http://127.0.0.1:4000/download-telegram-file, роута во
Flask не было (мёртвый вызов) → «Ошибка: скачивание файла не удалось» на любой
документ. Плюс при неудаче скачивания код выходил сразу, не доходя до
запасного /extract-document.

Проверка:
- роут существует и жив (400/200 с корректным JSON, не 404);
- успех → {status: ok, data: <base64>} (контракт app.mlog — поле data);
- неудача скачивания → честная ошибка (не 500);
- в app.mlog нет досрочного выхода при неудаче скачивания (запасной путь).
"""
import base64
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-365')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-naryad365-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import proxy.routes_core as rc  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация хвостовых роутов
from proxy.core import _query, app  # noqa: E402


def _cleanup():
    for row in _query("SELECT id FROM audit_log WHERE action LIKE 'telegram_file_%'",
                      (), fetch=True):
        _query("DELETE FROM audit_log WHERE id=?", (row["id"],))


def test_route_alive_not_404():
    """Роут существует: без file_path → 400 с JSON (до наряда был бы 404)."""
    client = app.test_client()
    resp = client.post("/download-telegram-file", json={})
    assert resp.status_code == 400, f"ожидался 400 (живой роут), получен {resp.status_code}"
    body = resp.get_json()
    assert body["status"] == "error"
    assert "file_path" in body["message"]


def test_success_returns_base64_data_field():
    """Контракт app.mlog: {status: ok, data: base64}."""
    client = app.test_client()
    payload = b"%PDF-1.4 naryad-365 probe"
    orig = rc._tg_download_file
    rc._tg_download_file = lambda file_path: payload
    try:
        resp = client.post("/download-telegram-file",
                           json={"file_path": "documents/doc.pdf"})
    finally:
        rc._tg_download_file = orig
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert base64.b64decode(body["data"]) == payload
    # аудит-след
    row = _query("SELECT details FROM audit_log WHERE action='telegram_file_downloaded' "
                 "ORDER BY id DESC LIMIT 1", (), fetch=True)
    assert row, "нет audit-следа telegram_file_downloaded"


def test_download_failure_is_graceful_error():
    """Неудача скачивания → {status: error} 200, не 500, не тихий null."""
    client = app.test_client()
    orig = rc._tg_download_file
    rc._tg_download_file = lambda file_path: None
    try:
        resp = client.post("/download-telegram-file",
                           json={"file_path": "documents/gone.pdf"})
    finally:
        rc._tg_download_file = orig
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "error"
    row = _query("SELECT details FROM audit_log WHERE action='telegram_file_download_error' "
                 "ORDER BY id DESC LIMIT 1", (), fetch=True)
    assert row, "нет audit-следа telegram_file_download_error"


def test_mlog_no_early_return_on_download_failure():
    """A.2: неудача скачивания больше не выходит досрочно — идёт в fallback."""
    app_text = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    # старый досрочный выход удалён
    assert "Ошибка: скачивание файла не удалось." not in app_text, \
        "досрочный выход при неудаче скачивания всё ещё в app.mlog"
    # pdf_b64 инициализируется пустым и заполняется только при успехе скачивания
    assert 'let pdf_b64 = ""' in app_text
    # ветка заполнения — по != ("()") (успех), иначе pdf_b64 остаётся пустым
    idx = app_text.find('let pdf_b64 = ""')
    window = app_text[idx:idx + 400]
    assert 'redact("()", "hash_only")' in window
    assert '!= redact' in window
    # комментарий наряда на месте
    assert "НАРЯД #365" in app_text


def test_detector_no_dead_download_call():
    """Детектор мёртвых вызовов: /download-telegram-file жив (mlog→Flask)."""
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "deadcall_detector.py")],
                          capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    assert "Flask-роутов" in out, f"детектор не запустился: {out[:300]}"
    for line in out.splitlines():
        if "/download-telegram-file" in line:
            assert "МЁРТВЫЕ" not in line and "←" not in line, \
                f"/download-telegram-file числится мёртвым: {line}"


def _test_cleanup_guard():
    """Санити: тесты не оставляют мусора в audit_log."""
    _cleanup()
