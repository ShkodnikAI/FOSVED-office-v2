#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MON-1 (#171): Telethon-монитор Telegram-каналов ЛЗ — 4-й процесс офиса.

⚠️  ОБЯЗАТЕЛЬНО использовать ОТДЕЛЬНЫЙ Telegram-аккаунт (не основной личный):
    сессия = полный доступ к аккаунту, плюс риск лимитов на основном аккаунте.
    Разовый вход: scripts/telegram_login.py (Render Shell / локально).

Контракт наряда (#171 / MON-1):
- kill-switch: TG_MONITOR_ENABLED != "1" → лог + чистый exit(0) — без правок кода;
- лёгкий профиль: медиа НЕ тянем, media_type только классифицируем;
- поллинг lz_telegram_channels раз в 5 мин (TG_POLL_INTERVAL_SEC);
- первичная заливка ограничена (последние N=50 постов на канал, TG_INITIAL_FILL_LIMIT);
- flood-wait: уважаем FloodWaitError.seconds, пауза между каналами;
- соединение: busy_timeout=5000 (WAL уже включён в проекте);
- дедуп: lz_channel_posts UNIQUE(channel_id, message_id) + INSERT OR IGNORE.
"""
import logging
import os
import signal
import sqlite3
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tg-monitor] %(levelname)s %(message)s",
)
log = logging.getLogger("tg-monitor")

# ── Конфигурация (env-изирована, kill-switch без правки кода) ──────────────
TG_MONITOR_ENABLED = lambda: os.environ.get("TG_MONITOR_ENABLED", "0") == "1"
TG_POLL_INTERVAL_SEC = lambda: int(os.environ.get("TG_POLL_INTERVAL_SEC", "300"))
TG_INITIAL_FILL_LIMIT = lambda: int(os.environ.get("TG_INITIAL_FILL_LIMIT", "50"))
TG_CHANNEL_PAUSE_SEC = lambda: float(os.environ.get("TG_CHANNEL_PAUSE_SEC", "2"))
SESSION_DIR = lambda: os.environ.get("TELEGRAM_SESSION_DIR", "/var/data/telegram_session")


def db_path():
    """БД офиса: DATABASE_PATH — каталог (fosved.db внутри)."""
    base = os.environ.get("DATABASE_PATH", os.path.join(str(_base_dir()), "data"))
    return os.path.join(base, "fosved.db")


def _base_dir():
    return os.path.dirname(os.path.abspath(__file__))


def db_connect(path):
    """Соединение монитора: busy_timeout=5000 (наряд MON-1; WAL уже включён)."""
    conn = sqlite3.connect(path, timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


DDL_LZ_CHANNEL_POSTS = """
CREATE TABLE IF NOT EXISTS lz_channel_posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  channel_name TEXT,
  text TEXT,
  media_type TEXT,
  date TEXT,
  scanned_at TEXT DEFAULT (datetime('now')),
  UNIQUE(channel_id, message_id)
)
"""

INSERT_POST = """
INSERT OR IGNORE INTO lz_channel_posts
  (channel_id, message_id, channel_name, text, media_type, date)
VALUES (?, ?, ?, ?, ?, ?)
"""

# ── Классификация медиа (лёгкий профиль: НЕ скачиваем ничего) ─────────────


def classify_media(msg) -> str:
    """media_type без загрузки: только классификация атрибутов сообщения."""
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "video", None):
        return "video"
    if getattr(msg, "voice", None):
        return "voice"
    if getattr(msg, "audio", None):
        return "audio"
    doc = getattr(msg, "document", None)
    if doc is not None:
        mime = ""
        try:
            mime = getattr(doc, "mime_type", "") or ""
        except Exception:
            mime = ""
        return "document:" + mime if mime else "document"
    return "text"


def _normalize_entity_id(channel_id):
    """Telethon принимает @username-строки и int-ids (в т.ч. -100... префикс)."""
    s = str(channel_id).strip()
    if s.startswith("@") or s.startswith("t.me") or s.startswith("https://"):
        return s
    try:
        return int(s)
    except ValueError:
        return s


# ── Сбор (клиент передаётся параметром — тестируется моком без сети) ──────


def fetch_channel_posts(client, channel_id, channel_name, limit):
    """Посты канала (последние limit) в виде кортежей для INSERT_POST.

    Никогда не бросает наружу сетевые/права-ошибки: возвращает (posts, error),
    где ровно один из элементов пуст — честная деградация MON-контракта.
    """
    entity_id = _normalize_entity_id(channel_id)
    try:
        entity = client.get_entity(entity_id)
        title = getattr(entity, "title", None) or channel_name or str(channel_id)
        posts = []
        for m in client.iter_messages(entity, limit=limit):
            posts.append((
                str(channel_id),
                str(m.id),
                title,
                (getattr(m, "message", None) or "")[:8000],
                classify_media(m),
                _iso(getattr(m, "date", None)),
            ))
        return posts, None
    except Exception as e:  # noqa: BLE001 — MON-контракт: {"ok": false} вместо падения такта
        if type(e).__name__ == "FloodWaitError":
            return [], e
        return [], e


def _iso(dt):
    if dt is None:
        return None
    try:
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return str(dt)


def poll_once(client, conn, limit=None):
    """Один такт поллинга по всем каналам lz_telegram_channels.

    Возвращает сводку {channels, inserted, errors: [(channel_id, kind, detail)]}.
    FloodWaitError уважается: спим ровно .seconds, канал пропускаем.
    """
    limit = limit or TG_INITIAL_FILL_LIMIT()
    channels = conn.execute(
        "SELECT channel_id, channel_name FROM lz_telegram_channels ORDER BY id"
    ).fetchall()
    summary = {"channels": len(channels), "inserted": 0, "errors": []}
    for channel_id, channel_name in channels:
        posts, err = fetch_channel_posts(client, channel_id, channel_name, limit)
        if err is not None:
            if type(err).__name__ == "FloodWaitError":
                wait_s = int(getattr(err, "seconds", 30))
                log.warning("flood-wait %ss на %s — пауза, канал пропущен", wait_s, channel_id)
                summary["errors"].append((str(channel_id), "flood_wait", wait_s))
                time.sleep(wait_s)
                continue
            log.warning("сбор %s не удался: %s", channel_id, err)
            summary["errors"].append((str(channel_id), type(err).__name__, str(err)[:200]))
            continue
        with conn:
            for row in posts:
                cur = conn.execute(INSERT_POST, row)
                summary["inserted"] += cur.rowcount if cur.rowcount > 0 else 0
        if TG_CHANNEL_PAUSE_SEC() > 0:
            time.sleep(TG_CHANNEL_PAUSE_SEC())
    return summary


# ── Жизненный цикл процесса ────────────────────────────────────────────────

_stop = {"flag": False}


def _handle_term(signum, frame):
    log.info("сигнал %s — чистое завершение", signum)
    _stop["flag"] = True


def ensure_table(conn):
    """Идемпотентно создаёт lz_channel_posts (зеркало DDL в app.mlog InitDB)."""
    with conn:
        conn.execute(DDL_LZ_CHANNEL_POSTS)


def main():
    if not TG_MONITOR_ENABLED():
        log.info("MON-1 выключен (TG_MONITOR_ENABLED != \"1\") — kill-switch, exit 0")
        return 0
    api_id = os.environ.get("TELEGRAM_API_ID", "")
    api_hash = os.environ.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        log.error("TELEGRAM_API_ID/TELEGRAM_API_HASH не заданы — монитор не стартует "
                  "(чеклист владельца #171: my.telegram.org, ОТДЕЛЬНЫЙ аккаунт)")
        return 1
    try:
        from telethon import TelegramClient
    except ImportError:
        log.error("telethon не установлен (requirements.txt: Telethon>=1.36)")
        return 1

    sdir = SESSION_DIR()
    os.makedirs(sdir, exist_ok=True)
    try:
        os.chmod(sdir, 0o700)
    except OSError:
        pass
    session_path = os.path.join(sdir, "lz_monitor")

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    client = TelegramClient(session_path, int(api_id), api_hash,
                            device_model="fosved-lz-monitor")
    client.connect()
    if not client.is_user_authorized():
        log.error("сессия не авторизована — запусти scripts/telegram_login.py "
                  "в Render Shell (ОТДЕЛЬНЫЙ аккаунт!)")
        return 1
    log.info("MON-1 активен: сессия %s, поллинг %ss, заливка %s постов/канал",
             sdir, TG_POLL_INTERVAL_SEC(), TG_INITIAL_FILL_LIMIT())

    conn = db_connect(db_path())
    ensure_table(conn)
    while not _stop["flag"]:
        started = time.time()
        try:
            summary = poll_once(client, conn)
            log.info("такт: каналов=%s вставлено=%s ошибок=%s (%.1fs)",
                     summary["channels"], summary["inserted"],
                     len(summary["errors"]), time.time() - started)
            for ch, kind, detail in summary["errors"]:
                log.info("  ошибка %s/%s: %s", ch, kind, detail)
        except sqlite3.Error as e:
            log.error("sqlite такта: %s", e)
        # спим интервал, но просыпаемся на SIGTERM каждые 5с
        waited = 0.0
        interval = TG_POLL_INTERVAL_SEC()
        while waited < interval and not _stop["flag"]:
            time.sleep(5)
            waited += 5
    conn.close()
    client.disconnect()
    log.info("MON-1 остановлен чисто")
    return 0


if __name__ == "__main__":
    sys.exit(main())
