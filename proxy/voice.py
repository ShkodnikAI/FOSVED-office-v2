"""FO-008: голосовые эндпоинты — TTS (edge-tts) и STT (Whisper Groq/OpenAI).

Вырезано из llm_proxy.py вербатим (стренглер, шаг 2; наряд #68, стоп-гейт SG-F2).
"""
import os
import re
import json
import time
import uuid
import subprocess

import requests as http_requests

from flask import request, jsonify

from proxy.core import (
    app,
    log,
    http_requests,
    _log_audit,
    WHISPER_API_KEY,
    WHISPER_PROVIDER,
)
from proxy.providers import call_llm
from proxy.telegram import _tg_send_voice, _tg_get_file, _tg_download_file, _ALL_EMOJI

def _pct(value, default):
    """MINIAPP-3 (#290): нормализация rate/volume в edge-tts формат «+N%».

    Пустое/отсутствующее → default (прежнее поведение). Строка с '%' — как есть.
    Число или числовая строка ('40', '+40') → «+40%». Мусор → default."""
    if value is None:
        return default
    s = str(value).strip().replace(" ", "")
    if not s:
        return default
    if s.endswith("%") and s[:-1].lstrip("+-").isdigit():
        return s
    if s.lstrip("+-").isdigit():
        return f"{int(s):+d}%"
    return default


def _hz(value, default=""):
    """MINIAPP-3 (#290): нормализация pitch в edge-tts формат «+NHz».

    Пустое/отсутствующее → default (параметр не передаётся вовсе)."""
    if value is None:
        return default
    s = str(value).strip().replace(" ", "")
    if not s:
        return default
    if s.endswith("Hz") and s[:-2].lstrip("+-").isdigit():
        return s
    if s.lstrip("+-").isdigit():
        return f"{int(s):+d}Hz"
    return default


def _clean_text_for_tts(text):
    """Strip emoji, Markdown syntax, special chars for clean edge-tts voice output.

    Keeps: letters (all scripts), digits, basic sentence punctuation (. , - : ;).
    Removes: emoji, *, _ `, #, ▸ ◦ ───, quotes (" " « »), ‑, •, etc.
    """
    if not text:
        return ""
    t = _ALL_EMOJI.sub(' ', text)            # remove all emoji
    t = re.sub(r'[*_`#~|>]', ' ', t)          # remove Markdown syntax chars
    t = re.sub(r'[«»""\u201C\u201D\u201E\u2018\u2019]', '', t)  # remove all quotes
    t = re.sub(r'───+|──+|─+', '', t)         # remove decorative lines
    t = re.sub(r'[▸◦▪●○◆◇▪▸►←→↑↓]', '', t)  # remove bullet/arrow chars
    t = re.sub(r'[═─━─]', '', t)              # remove box-drawing lines
    t = re.sub(r'[✓✗✘✔✖]', '', t)            # remove check/cross marks
    t = re.sub(r'\s{2,}', ' ', t)             # collapse whitespace
    t = re.sub(r'(?<=\S)\s*[.!?]\s*[.!?]+', '.', t)  # collapse multiple sentence ends
    t = t.strip()
    return t

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: TTS ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/tts")
def tts_endpoint():
    """Text-to-speech via edge-tts, send voice to Telegram."""
    d = request.get_json(force=True)
    text = d.get("text", "")
    voice = d.get("voice", "ru-RU-SvetlanaNeural")
    chat_id = d.get("chat_id", "")
    speech = bool(d.get("speech", False))  # FO-0111/013 фаза 3: voice-render

    if not text:
        return jsonify({"status": "error", "message": "text is required"}), 400
    if not chat_id:
        return jsonify({"status": "error", "message": "chat_id is required"}), 400

    if speech:
        text = voice_render(text)

    timestamp = int(time.time())
    tmp_path = f"/tmp/tts_{timestamp}_{uuid.uuid4().hex[:6]}.mp3"

    try:
        # Run edge-tts subprocess.
        # MINIAPP-3 (#290): speed/volume/pitch из kv (прокинуты app.mlog) или body.
        # Пустые/отсутствующие → прежнее поведение: rate '+20%', volume/pitch не задаются.
        rate = _pct(d.get("speed") or d.get("rate"), "+20%")
        volume = _pct(d.get("volume"), "")
        pitch = _hz(d.get("pitch"), "")
        cmd = [
            "edge-tts",
            "--voice", voice,
            "--rate", rate,
            "--text", text,
            "--write-media", tmp_path
        ]
        if volume:
            cmd += ["--volume", volume]
        if pitch:
            cmd += ["--pitch", pitch]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error(f"edge-tts failed: {result.stderr}")
            _log_audit("tts_error", {"voice": voice, "error": result.stderr[:500]})
            return jsonify({"status": "error", "message": "edge-tts synthesis failed", "detail": result.stderr[:500]}), 500

        # Send voice to Telegram
        msg_id = _tg_send_voice(chat_id, tmp_path)

        _log_audit("tts", {"chat_id": chat_id, "voice": voice, "text_len": len(text), "tg_msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except FileNotFoundError:
        _log_audit("tts_error", {"error": "edge-tts not installed"})
        return jsonify({"status": "error", "message": "edge-tts binary not found"}), 500
    except subprocess.TimeoutExpired:
        _log_audit("tts_error", {"error": "timeout"})
        return jsonify({"status": "error", "message": "TTS synthesis timeout"}), 500
    except Exception as e:
        log.error(f"TTS error: {e}")
        _log_audit("tts_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        # Clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as e:
            log.warning(f"[cleanup] temp file remove failed: {e}")

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: STT (WHISPER) ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/stt")
def stt_endpoint():
    """Speech-to-text via Whisper (Groq preferred, OpenAI fallback)."""
    d = request.get_json(force=True)
    file_id = d.get("file_id", "")

    if not file_id:
        return jsonify({"status": "error", "message": "file_id is required"}), 400

    provider = WHISPER_PROVIDER
    audio_data = None

    try:
        # Step 1: Get file path from Telegram
        file_path = _tg_get_file(file_id)
        if not file_path:
            _log_audit("stt_error", {"error": "could not get file path from Telegram", "file_id": file_id})
            return jsonify({"status": "error", "message": "Failed to get file from Telegram"}), 400

        # Step 2: Download audio from Telegram
        audio_data = _tg_download_file(file_path)
        if not audio_data:
            _log_audit("stt_error", {"error": "could not download file from Telegram", "file_path": file_path})
            return jsonify({"status": "error", "message": "Failed to download audio from Telegram"}), 400

        # Step 3: Transcribe via Whisper (общий код с /api/stt/upload, №589 A.1)
        transcribed_text, used_provider = _whisper_transcribe(audio_data)

        _log_audit("stt", {"file_id": file_id, "provider": used_provider, "text_len": len(transcribed_text)})

        return jsonify({"status": "ok", "text": transcribed_text, "provider": used_provider})

    except Exception as e:
        log.error(f"STT error (provider={provider}): {e}")
        _log_audit("stt_error", {"error": str(e)[:500], "file_id": file_id})
        return jsonify({"status": "error", "message": str(e)}), 500


def _whisper_transcribe(audio_data, filename="audio.ogg"):
    """№589 A.1: общий код распознавания — Whisper (Groq preferred, OpenAI
    fallback). Принимает байты аудио; возвращает (text, provider).
    Поведение /stt (Telegram file_id → скачивание → сюда) не меняется."""
    provider = WHISPER_PROVIDER
    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY", WHISPER_API_KEY)
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        model = "whisper-large-v3"
    else:
        api_key = os.environ.get("OPENAI_API_KEY", WHISPER_API_KEY)
        url = "https://api.openai.com/v1/audio/transcriptions"
        model = "whisper-1"

    # Prepare multipart form
    files = {
        "file": (filename, bytes(audio_data), "audio/ogg"),
    }
    data = {"model": model}
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = http_requests.post(url, headers=headers, files=files, data=data, timeout=60)
        resp.raise_for_status()
        resp_data = resp.json()
        return resp_data.get("text", ""), provider
    except Exception as e:
        log.error(f"STT error (provider={provider}): {e}")
        # Try fallback provider if primary failed
        if provider == "groq":
            fallback_key = os.environ.get("OPENAI_API_KEY", "")
            if not fallback_key:
                raise
            files = {"file": (filename, bytes(audio_data), "audio/ogg")}
            data = {"model": "whisper-1"}
            headers = {"Authorization": f"Bearer {fallback_key}"}
            resp = http_requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=60)
            resp.raise_for_status()
            resp_data = resp.json()
            text = resp_data.get("text", "")
            _log_audit("stt", {"provider": "openai", "model": "whisper-1", "text_len": len(text), "fallback": True})
            return text, "openai"
        raise


# ── №589 A.1: голос из Mini App ─────────────────────────────────────────
_STT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 МБ
_STT_UPLOAD_MIMES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav")


@app.post("/api/stt/upload")
def stt_upload_endpoint():
    """№589 A.1: микрофон Mini App — multipart/form-data (поле audio) → тот же
    Whisper, что /stt. Лимиты: 10 МБ; длительность (≤120 с) контролирует клиент
    (MediaRecorder), сервер держит аудио только в памяти запроса — на диск
    не пишет и в лог не пишет. Ответ {status, text}; ошибки {status, message}."""
    f = request.files.get("audio")
    if f is None or not f.filename and not f.mimetype:
        return jsonify({"status": "error", "message": "audio file is required"}), 400
    mime = (f.mimetype or "").split(";")[0].strip()
    if mime and mime not in _STT_UPLOAD_MIMES:
        return jsonify({"status": "error", "message": f"неподдерживаемый тип аудио: {mime}"}), 415
    audio_data = f.read()
    if not audio_data:
        return jsonify({"status": "error", "message": "пустое аудио"}), 400
    if len(audio_data) > _STT_UPLOAD_MAX_BYTES:
        return jsonify({"status": "error", "message": "аудио больше 10 МБ"}), 413
    try:
        text, used_provider = _whisper_transcribe(audio_data, filename=f.filename or "audio.ogg")
        return jsonify({"status": "ok", "text": text, "provider": used_provider})
    except Exception as e:  # noqa: BLE001 — код ошибки без тела (№589 A.1)
        log.error(f"STT upload error: {e.__class__.__name__}")
        return jsonify({"status": "error", "message": "не удалось распознать аудио"}), 502

def voice_render(text):
    """FO-013 фаза 3 (Astra-паттерн): переписать отчёт в устную речь лёгким LLM-вызовом.

    Паттерн astra_analysis.md: не вычитание символов (clean), а пересказ устной
    формой отдельным дешёвым вызовом. Провал LLM → деградация к чистому тексту.
    """
    base = _clean_text_for_tts(text)
    try:
        result = call_llm(
            "yana",
            [{"role": "system",
              "content": "Ты готовишь текст для озвучки. Перескажи его устной речью: "
                         "короткие фразы, без markdown, без эмодзи, без маркеров (✓/◈/⚡), "
                         "числа словами-цифрами как в дикторе. Сохрани все факты и цифры. "
                         "Только сам текст озвучки."},
             {"role": "user", "content": text[:6000]}],
            command="voice_confirm",
        )
        reply = (result or {}).get("reply") or ""
        if reply and "[Oshibka]" not in reply and len(reply) >= 80:
            return _clean_text_for_tts(reply)[:3500]
        log.warning(f"voice_render weak reply (len={len(reply)}) — fallback to clean text")
    except Exception as e:
        log.warning(f"voice_render failed — fallback to clean text: {e}")
    return base
