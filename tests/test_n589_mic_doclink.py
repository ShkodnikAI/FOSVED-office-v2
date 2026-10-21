#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #589: микрофон в чате Mini App + переход к отчёту по нажатию.

Гварды:
- A.1: POST /api/stt/upload — мок Whisper 200 → текст; >10 МБ → 413; без Bearer → 401;
  неподдерживаемый MIME → 415; Telegram-путь /stt по file_id не изменён (общий код);
- B.1: GET /api/depts/<id>/dialog — assistant-ответ с отчётом получает doc_id
  (точное совпадение raw_text), обычная реплика — null; схема dialog_history/
  miniapp_responses не меняется;
- B.2/UI: пузыри с doc_id несут data-doc и «Открыть отчёт ›»; микрофон —
  MediaRecorder + /api/stt/upload (UI-гварды разметки).
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n589-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import voice as voice_mod  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def clean_dialog():
    _query("DELETE FROM dialog_history WHERE dept='lz'")
    _query("DELETE FROM miniapp_responses WHERE dept='lz'")
    yield
    _query("DELETE FROM dialog_history WHERE dept='lz'")
    _query("DELETE FROM miniapp_responses WHERE dept='lz'")


# ──────────────────────────── A.1 сервер ────────────────────────────

def test_a1_upload_ok(monkeypatch):
    monkeypatch.setattr(voice_mod, "_whisper_transcribe", lambda data, filename="audio.ogg": ("привет хозяин", "groq"))
    data = {"audio": (io.BytesIO(b"RIFFfakeaudio"), "voice.webm", "audio/webm")}
    r = _client().post("/api/stt/upload", headers=API_AUTH, data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok" and d["text"] == "привет хозяин" and d["provider"] == "groq"


def test_a1_upload_whisper_error(monkeypatch):
    def boom(data, filename="audio.ogg"):
        raise RuntimeError("whisper down")
    monkeypatch.setattr(voice_mod, "_whisper_transcribe", boom)
    data = {"audio": (io.BytesIO(b"x"), "voice.webm", "audio/webm")}
    r = _client().post("/api/stt/upload", headers=API_AUTH, data=data, content_type="multipart/form-data")
    assert r.status_code == 502
    d = r.get_json()
    assert d["status"] == "error"
    assert "whisper down" not in d["message"]  # код ошибки без тела


def test_a1_upload_oversize(monkeypatch):
    big = b"x" * (10 * 1024 * 1024 + 1)
    data = {"audio": (io.BytesIO(big), "voice.webm", "audio/webm")}
    r = _client().post("/api/stt/upload", headers=API_AUTH, data=data, content_type="multipart/form-data")
    assert r.status_code == 413


def test_a1_upload_bad_mime():
    data = {"audio": (io.BytesIO(b"x"), "song.flac", "audio/flac")}
    r = _client().post("/api/stt/upload", headers=API_AUTH, data=data, content_type="multipart/form-data")
    assert r.status_code == 415


def test_a1_upload_no_file():
    r = _client().post("/api/stt/upload", headers=API_AUTH, data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_a1_upload_requires_auth():
    data = {"audio": (io.BytesIO(b"x"), "voice.webm", "audio/webm")}
    r = _client().post("/api/stt/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 401


def test_a1_telegram_path_unchanged():
    """Telegram-путь /stt по file_id живёт как был (запрет прохода)."""
    src = open(os.path.join(REPO_ROOT, "proxy", "voice.py"), encoding="utf-8").read()
    assert '@app.post("/stt")' in src
    assert "file_id is required" in src
    assert "_tg_download_file(file_path)" in src
    # общий код вынесен в функцию и переиспользуется
    assert "def _whisper_transcribe" in src
    assert "_whisper_transcribe(audio_data)" in src


# ──────────────────────────── B.1 doc_id в ленте ────────────────────────────

def _seed_chat():
    _query("INSERT INTO dialog_history (dept, chat_id, role, content) VALUES ('lz', '12345', 'user', 'вопрос про тренды')")
    _query("INSERT INTO dialog_history (dept, chat_id, role, content) VALUES ('lz', '12345', 'assistant', 'ОТЧЁТ ЛЗ ПО ТРЕНДАМ')")
    _query("INSERT INTO dialog_history (dept, chat_id, role, content) VALUES ('lz', '12345', 'assistant', 'обычная реплика без отчёта')")
    _query("INSERT INTO miniapp_responses (id, dept, title, query, raw_text) VALUES ('doc-xyz', 'lz', 'Тренды', 'вопрос про тренды', 'ОТЧЁТ ЛЗ ПО ТРЕНДАМ')")


def test_b1_dialog_doc_id_mapping():
    _seed_chat()
    r = _client().get("/api/depts/lz/dialog", headers=API_AUTH)
    d = r.get_json()
    msgs = d["messages"]
    by_content = {m["content"]: m for m in msgs}
    assert by_content["ОТЧЁТ ЛЗ ПО ТРЕНДАМ"].get("doc_id") == "doc-xyz"
    assert "doc_id" not in by_content["обычная реплика без отчёта"]
    assert "doc_id" not in by_content["вопрос про тренды"]  # user — без doc_id


def test_b1_dialog_time_fallback():
    """Совпадения текста нет → ближайший отчёт в пределах 120 с после created_at."""
    _query("INSERT INTO dialog_history (dept, chat_id, role, content, created_at) VALUES ('lz', '12345', 'assistant', 'ответ-с-отчётом-устаревший', datetime('now','-30 seconds'))")
    _query("INSERT INTO miniapp_responses (id, dept, title, query, raw_text, created_at) VALUES ('doc-time', 'lz', 'T', 'q', 'ДРУГОЙ ТЕКСТ ОТЧЁТА', datetime('now'))")
    r = _client().get("/api/depts/lz/dialog", headers=API_AUTH)
    msgs = r.get_json()["messages"]
    m = next(x for x in msgs if x["content"] == "ответ-с-отчётом-устаревший")
    assert m.get("doc_id") == "doc-time"


def test_b1_no_doc_for_plain_reply():
    _query("INSERT INTO dialog_history (dept, chat_id, role, content) VALUES ('lz', '12345', 'assistant', 'просто ответ')")
    r = _client().get("/api/depts/lz/dialog", headers=API_AUTH)
    m = next(x for x in r.get_json()["messages"] if x["content"] == "просто ответ")
    assert "doc_id" not in m


# ──────────────────────────── B.2/UI гварды ────────────────────────────

def test_b2_ui_markup():
    idx = open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8").read()
    # пузыри с doc_id: data-doc + подпись «Открыть отчёт ›»
    assert "msg-doclink" in idx and "data-doc=\"'+esc(m.doc_id)" in idx.replace('"', '"')
    assert "Открыть отчёт ›" in idx or "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043e\u0442\u0447\u0451\u0442 \u203a" in idx
    # микрофон: MediaRecorder + upload + понятное сообщение при недоступности
    assert "MediaRecorder" in idx and "/api/stt/upload" in idx
    assert "getUserMedia" in idx
    assert "Микрофон недоступен в этом приложении" in idx
    # короткая запись отбрасывается (<0.5 c)
    assert "dur<500" in idx
