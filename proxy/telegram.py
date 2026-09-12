"""FO-008: адаптер Telegram Bot API + текстовые хелперы форматирования.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 2; наряд #68, стоп-гейт SG-F2).
"""
import os
import re
import threading
import json
import time
import uuid

import requests as http_requests

from proxy.core import log, _log_error, TELEGRAM_BOT_TOKEN, http_requests

# ── Text formatting helpers for Telegram ────────────────────────────

# Emoji used as section markers — kept in visual text, stripped for TTS
_MARKER_EMOJI = re.compile(
    r'[\U0001F4C5\U0001F324\U0001F3E2\U0001F30D\U0001F50D\U000026A1'  # 📅🌤🏢🌍🔍⚡
    r'\U0001F4CC\U0001F4AC\U0001F527\U00002705\U0000274C'                # 📌💬🔧✅❌
    r'\U0001F5E3\U0001F4CB\U0001F4CA\U0001F4C8\U0001F4C9'                # 🗣📋📊📈📉
    r'\U00002B50\U0001F680\U0001F389\U0001F514\U000023F0'                # ⭐🚀🎉🔔⏰
    r'\U0001F4E6\U0001F4DD\U0001F3AF\U0001F4A1\U0001F517'                # 📦📝🎯💡🔗
    r'\U0001F4C1\U0001F4C4\U0001F4C2\U0001F504\U00002699'                # 📁📄📂🔄⚙
    r'\U0001F4D6\U0001F3DB\U0001F3E0\U0001F310\U0001F30F'                # 📖🏛🏠🌐🌍
    r'\U0001F6E1\U00002696\U00002764\U00002753\U00002139'                # 🛡⚛❓❗
    r'\U0001F534\U0001F7E0\U0001F7E1\U0001F7E2\U0001F535\U0001F7E3'  # 🔴🟠🟡🟢🔵🟣
    r'\U000025B6\U000025AA\U000025CF\U000025CB\U00002500\U00002501'  # ▸▪●○──━
    r'\U000025C6\U00002666\U00002737\U0000203C\U000000A9\U00002122]'  # ◆♠✳‼©®
    r'[\U0001F300-\U0001F9FF]'                                            # catch-all: common emoji
)

# All emoji (broadest match) — for TTS
_ALL_EMOJI = re.compile(
    r'[\U00002600-\U000027BF]'   # Misc symbols, dingbats
    r'|[\U0001F000-\U0001FAFF]'  # All emoji blocks
    r'|[\U0000FE00-\U0000FE0F]'  # Variation selectors
    r'|[\U0000200D]'             # Zero-width joiner
    r'|[\U0001F900-\U0001F9FF]'  # Supplemental symbols
    r'|[\U0001FA00-\U0001FA6F]'  # Chess, symbols
    r'|[\U0001FA70-\U0001FAFF]'  # Symbols extended
)

def _escape_mdv2(text):
    """Escape text for Telegram MarkdownV2 parse_mode.
    
    Characters that MUST be escaped: _ * [ ] ( ) ~ ` > # + - = | { } . !
    Inside inline code or code blocks, no escaping needed.
    Strategy: find code blocks/spans first, escape around them.
    
    For safety, this uses a simple approach: escape everything except
    emoji (which Telegram renders natively) and content inside backticks.
    """
    if not text:
        return ""
    
    # Split by backtick-delimited code spans
    parts = re.split(r'(`[^`]+`)', text)
    escaped_parts = []
    for part in parts:
        if part.startswith('`') and part.endswith('`'):
            # Code span — keep as-is
            escaped_parts.append(part)
        else:
            # Escape MarkdownV2 special chars, but preserve emoji and newlines
            # MDV2 special: _ * [ ] ( ) ~ ` > # + - = | { } . !
            escaped = re.sub(r'(?<!\\)([_*\[\]\(\)~`>#\+\-=|{}\.!])', r'\\\1', part)
            # Un-escape emoji (they were incorrectly escaped)
            escaped = _ALL_EMOJI.sub(lambda m: m.group(), escaped)
            # Un-escape escaped newlines
            escaped = escaped.replace('\\\n', '\n')
            # Fix double-escaped backslashes before emoji
            escaped = re.sub(r'\\(\\[\U0001F000-\U0001FAFF\U00002600-\U000027BF])', r'\1', escaped)
            escaped_parts.append(escaped)
    
    return ''.join(escaped_parts)


def _tg_send_formatted(chat_id, text, dept=None):
    """Send message with MarkdownV2 formatting for Yana/Admin, plain for others.
    
    Tries MarkdownV2 first; if Telegram rejects it (400), falls back to plain text.
    This ensures messages always get delivered even if formatting is imperfect.
    """
    if not text:
        return None
    
    # Use MarkdownV2 for formatted departments
    if dept in ("yana", "admin"):
        mdv2_text = _escape_mdv2(text)
        msg_id = _tg_send_message(chat_id, mdv2_text, parse_mode="MarkdownV2")
        if msg_id is not None:
            return msg_id
        # Fallback: Telegram rejected formatting, send plain
        log.warning(f"MarkdownV2 rejected for dept={dept}, falling back to plain text")
    
    return _tg_send_message(chat_id, text)

# ──────────────────────────── TELEGRAM HELPERS ────────────────────────────
def _tg_send_message(chat_id, text, parse_mode=None):
    """Send a text message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send message")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = http_requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
    except Exception as e:
        log.error(f"Telegram sendMessage failed: {e}")
    return None

def _tg_send_voice(chat_id, voice_path):
    """Send a voice file via Telegram Bot API using multipart upload."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send voice")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"
    try:
        with open(voice_path, "rb") as f:
            resp = http_requests.post(url, data={"chat_id": chat_id}, files={"voice": f}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
    except Exception as e:
        log.error(f"Telegram sendVoice failed: {e}")
    return None

def _tg_send_report_with_button(chat_id, text, button_text="Otkryt otchet", button_url=None):
    """Send text with an inline button via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send report")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    reply_markup = {
        "inline_keyboard": [[{"text": button_text, "url": button_url or "https://t.me/FosvedMiniApp"}]]
    }
    payload = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
    try:
        resp = http_requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            return data["result"].get("message_id")
    except Exception as e:
        log.error(f"Telegram sendReport failed: {e}")
    return None

def _tg_get_file(file_id):
    """Get file path from Telegram Bot API given a file_id."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
    try:
        resp = http_requests.get(url, params={"file_id": file_id}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok") and data.get("result", {}).get("file_path"):
            return data["result"]["file_path"]
    except Exception as e:
        log.error(f"Telegram getFile failed: {e}")
    return None

def _tg_download_file(file_path):
    """Download a file from Telegram Bot API given its file_path."""
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    try:
        resp = http_requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        log.error(f"Telegram file download failed: {e}")
    return None


def _tg_send_photo(chat_id, photo_path, caption=None):
    """Send a photo via Telegram Bot API using multipart upload."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send photo")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            payload = {'chat_id': chat_id}
            if caption:
                payload['caption'] = caption[:1000]
            resp = http_requests.post(url, data=payload, files={'photo': f}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get('ok'):
            return data['result'].get('message_id')
    except Exception as e:
        log.error(f"Telegram sendPhoto failed: {e}")
    return None


def _tg_send_document(chat_id, file_path, caption=None):
    """Send a document via Telegram Bot API using multipart upload."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, cannot send document")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
            resp = http_requests.post(url, data=data, files={"document": f}, timeout=60)
            resp.raise_for_status()
            j = resp.json()
            if j.get("ok"):
                return j["result"].get("message_id")
            log.error(f"sendDocument not ok: {j}")
    except Exception as e:
        log.error(f"Telegram sendDocument failed: {e}")
    return None

def _safe_filename_part(s, maxlen=40):
    """Make a filesystem/Telegram-safe filename fragment from arbitrary text."""
    s = (s or "").strip()
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_ ":
            out.append(ch)
        else:
            out.append(" ")
    cleaned = " ".join("".join(out).split())
    cleaned = cleaned.replace(" ", "_")
    return cleaned[:maxlen] or "report"


def _send_chat_action_loop(chat_id, action="typing", interval=5):
    """Send typing/action indicator to Telegram in a loop. Returns a stop event."""
    stop = threading.Event()

    def _loop():
        while not stop.is_set():
            try:
                _tg_send_chat_action(chat_id, action)
            except Exception as e:
                _log_error(f"chat_action send failed for {chat_id}: {e}", source="typing", dept="system", kind="external")
            stop.wait(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return stop

def _tg_send_chat_action(chat_id, action):
    """Send a chat action to Telegram (typing, upload_photo, etc.)."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendChatAction"
    try:
        http_requests.post(url, json={"chat_id": chat_id, "action": action}, timeout=10)
    except Exception as e:
        _log_error(f"sendChatAction failed for {chat_id}: {e}", source="typing", dept="system", kind="external")


# ═══ FO-013: промежуточные статусы и кусочная отправка (issue #73) ══════════
_TG_STATUS_MIN_INTERVAL = 10.0   # анти-спам: статус-сообщение не чаще, сек
_status_last = {}
_status_lock = threading.Lock()


def tg_status(chat_id, text, dept=None, force=False):
    """Промежуточный статус («маршрутизирую», «OSP анализирует») с анти-спамом.

    Возврат: True — отправлено, False — срезано лимитом частоты.
    typing-индикатор отдельным лимитом не гнобится — он не пишёт сообщений.
    """
    if not chat_id:
        return False
    now = time.monotonic()
    with _status_lock:
        last = _status_last.get(str(chat_id), 0.0)
        if not force and (now - last) < _TG_STATUS_MIN_INTERVAL:
            return False
        _status_last[str(chat_id)] = now
    mid = _tg_send_formatted(chat_id, text, dept=dept)
    return mid is not None


def tg_split_long(text, limit=3800):
    """Резать длинный текст на смысловые куски ≤ limit (по границам абзацев).

    Фаза 2 FO-013: llm_proxy сам владеет Telegram API — длинный ответ уходит
    кусками по мере готовности. Задел склейки с №275: куски — цельные абзацы.
    """
    text = text or ""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        candidate = (cur + "\n\n" + block) if cur else block
        if len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            parts.append(cur)
            cur = ""
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit + 1)
            if cut < limit * 0.5:
                cut = block.rfind(". ", 0, limit)
            if cut < limit * 0.5:
                cut = limit
                parts.append(block[:cut].rstrip())
                block = block[cut:].lstrip()
            else:
                parts.append(block[:cut + 1].rstrip())
                block = block[cut + 1:].lstrip()
        cur = block
    if cur:
        parts.append(cur)
    return parts


def tg_send_long(chat_id, text, dept=None, limit=3800):
    """Отправка длинного ответа кусками. Возврат: список message_id."""
    parts = tg_split_long(text, limit)
    ids = []
    for i, part in enumerate(parts):
        mid = _tg_send_formatted(chat_id, part, dept=dept)
        if mid is not None:
            ids.append(mid)
        if i < len(parts) - 1:
            time.sleep(0.6)  # анти-флуд Telegram
    return ids
