"""FO-008: голосовые эндпоинты — TTS (edge-tts) и STT (Whisper Groq/OpenAI).

Вырезано из llm_proxy.py вербатим (стренглер, шаг 2; наряд #68, стоп-гейт SG-F2).
"""
import os
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
from proxy.telegram import _tg_send_voice, _tg_get_file, _tg_download_file

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

    if not text:
        return jsonify({"status": "error", "message": "text is required"}), 400
    if not chat_id:
        return jsonify({"status": "error", "message": "chat_id is required"}), 400

    timestamp = int(time.time())
    tmp_path = f"/tmp/tts_{timestamp}_{uuid.uuid4().hex[:6]}.mp3"

    try:
        # Run edge-tts subprocess
        rate = d.get("rate", "+20%")
        cmd = [
            "edge-tts",
            "--voice", voice,
            "--rate", rate,
            "--text", text,
            "--write-media", tmp_path
        ]
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

        # Step 3: Transcribe via Whisper
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
            "file": ("audio.ogg", bytes(audio_data), "audio/ogg"),
        }
        data = {"model": model}
        headers = {"Authorization": f"Bearer {api_key}"}

        resp = http_requests.post(url, headers=headers, files=files, data=data, timeout=60)
        resp.raise_for_status()
        resp_data = resp.json()
        transcribed_text = resp_data.get("text", "")

        _log_audit("stt", {"file_id": file_id, "provider": provider, "model": model, "text_len": len(transcribed_text)})

        return jsonify({"status": "ok", "text": transcribed_text, "provider": provider})

    except Exception as e:
        log.error(f"STT error (provider={provider}): {e}")
        # Try fallback provider if primary failed
        if provider == "groq" and audio_data:
            try:
                fallback_key = os.environ.get("OPENAI_API_KEY", "")
                if not fallback_key:
                    raise ValueError("No OpenAI API key for fallback")
                files = {"file": ("audio.ogg", bytes(audio_data), "audio/ogg")}
                data = {"model": "whisper-1"}
                headers = {"Authorization": f"Bearer {fallback_key}"}
                resp = http_requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=60)
                resp.raise_for_status()
                resp_data = resp.json()
                transcribed_text = resp_data.get("text", "")
                _log_audit("stt", {"file_id": file_id, "provider": "openai", "model": "whisper-1", "text_len": len(transcribed_text), "fallback": True})
                return jsonify({"status": "ok", "text": transcribed_text, "provider": "openai"})
            except Exception as fallback_err:
                log.error(f"STT fallback also failed: {fallback_err}")

        _log_audit("stt_error", {"error": str(e)[:500], "file_id": file_id})
        return jsonify({"status": "error", "message": str(e)}), 500
