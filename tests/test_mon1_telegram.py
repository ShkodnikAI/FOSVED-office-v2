#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MON-1 tests (#171): Telegram-монитор ЛЗ.

Покрытие:
- kill-switch: TG_MONITOR_ENABLED != "1" → main() = 0 без каких-либо зависимостей;
- отсутствие ключей при включённом флаге → честный exit 1;
- classify_media: лёгкий профиль (классификация без загрузки);
- fetch_channel_posts: честная деградация (posts, error — ровно одно непусто);
- poll_once: дедуп UNIQUE(channel_id, message_id) через INSERT OR IGNORE,
  FloodWaitError уважается (sleep .seconds, канал пропускается, такт живёт);
- lz_channel_posts DDL из app.mlog ИСПОЛНЯЕТСЯ в in-memory SQLite (DDL-guard);
- busy_timeout=5000 на соединении монитора;
- telegram_monitor не импортирует telethon на верхнем уровне (CI без сети).
"""
import ast
import os
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-mon1-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import telegram_monitor as tm  # noqa: E402


# ── Kill-switch и ключи ────────────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TG_MONITOR_ENABLED", raising=False)
    assert tm.main() == 0  # чистый exit без telethon/ключей


def test_enabled_without_keys_honest_fail(monkeypatch):
    monkeypatch.setenv("TG_MONITOR_ENABLED", "1")
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    assert tm.main() == 1


def test_telethon_import_is_lazy():
    """telethon НЕ импортируется на верхнем уровне (CI без сети, kill-switch без пакета)."""
    src = (REPO_ROOT / "telegram_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_imports |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_imports.add(node.module.split(".")[0])
    assert "telethon" not in top_imports


# ── Классификация медиа (лёгкий профиль) ──────────────────────────────────

def test_classify_media_light_profile():
    assert tm.classify_media(NS(photo=1, video=None, document=None)) == "photo"
    assert tm.classify_media(NS(photo=None, video=1, document=None)) == "video"
    assert tm.classify_media(NS(photo=None, video=None, document=NS(mime_type="application/pdf"))) == "document:application/pdf"
    assert tm.classify_media(NS(photo=None, video=None, document=1)) == "document"
    assert tm.classify_media(NS(photo=None, video=None, document=None, message="текст")) == "text"


# ── Фейковый клиент (мок-telethon, без сети) ──────────────────────────────

class _Msg(NS):
    pass


def _fake_client(channels):
    """channels: {entity_id: [msgs]}; get_entity/iter_messages — как Telethon."""
    class FakeClient:
        def get_entity(self, eid):
            key = str(eid)
            if key not in channels:
                raise ValueError(f"no entity {key}")
            return NS(title=f"title-{key}")
        def iter_messages(self, entity, limit):
            key = str(getattr(entity, "title", "")).replace("title-", "")
            msgs = channels.get(key, [])
            return list(msgs[:limit])
    return FakeClient()


def test_fetch_honest_degradation():
    ok_posts, ok_err = tm.fetch_channel_posts(_fake_client({"@ok": [_Msg(id=1, message="пост", photo=None, video=None, document=None, voice=None, audio=None, date=None)]}), "@ok", "Канал", 50)
    assert ok_err is None and len(ok_posts) == 1 and ok_posts[0][1] == "1"
    bad_posts, bad_err = tm.fetch_channel_posts(_fake_client({}), "@missing", "Нет", 50)
    assert bad_posts == [] and bad_err is not None


# ── poll_once: дедуп + flood-wait ─────────────────────────────────────────

def _mkconn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "fosved.db"))
    conn.execute("PRAGMA busy_timeout = 5000")
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS lz_telegram_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, channel_name TEXT, category TEXT)")
        conn.execute(tm.DDL_LZ_CHANNEL_POSTS)
        conn.execute("INSERT INTO lz_telegram_channels (channel_id, channel_name) VALUES ('@a', 'A')")
        conn.execute("INSERT INTO lz_telegram_channels (channel_id, channel_name) VALUES ('@b', 'B')")
    return conn


def _msgs(*ids):
    return [_Msg(id=i, message=f"текст {i}", photo=None, video=None,
                 document=None, voice=None, audio=None, date=None) for i in ids]


class FloodWaitError(Exception):
    """Мимикрия под telethon.errors.FloodWaitError (монитор различает по __name__)."""

    def __init__(self, seconds):
        self.seconds = seconds


def test_poll_once_dedup_and_floodwait(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_CHANNEL_PAUSE_SEC", "0")
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    conn = _mkconn(tmp_path)

    class FloodClient:
        def get_entity(self, eid):
            if str(eid) == "@a":
                raise FloodWaitError(30)
            return NS(title="title-@b")
        def iter_messages(self, entity, limit):
            return _msgs(11, 12)

    client = FloodClient()
    s1 = tm.poll_once(client, conn)
    # @a → flood_wait (пропущен), @b → 2 поста
    assert s1["channels"] == 2 and s1["inserted"] == 2
    assert ("@a", "flood_wait", 30) in [(e[0], e[1], e[2]) for e in s1["errors"]]
    assert 30 in sleeps  # FloodWaitError.seconds уважен

    # второй такт: дедуп — 0 вставок
    s2 = tm.poll_once(FloodClient(), conn)
    assert s2["inserted"] == 0

    # повторный fill: 3-й пост добавляется
    class GrowClient(FloodClient):
        def iter_messages(self, entity, limit):
            return _msgs(11, 12, 13)
    s3 = tm.poll_once(GrowClient(), conn)
    assert s3["inserted"] == 1


# ── DDL-guard: lz_channel_posts из app.mlog исполняется в SQLite ─────────

def test_app_mlog_ddl_executes_and_dedups():
    src = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    match = None
    for m in __import__("re").finditer(r'db_execute\("CREATE TABLE IF NOT EXISTS lz_channel_posts[^"]*"\)', src):
        match = m.group(0)
        break
    assert match, "lz_channel_posts DDL отсутствует в app.mlog"
    sql = match[len('db_execute("'):-2]
    conn = sqlite3.connect(":memory:")
    conn.execute(sql)
    with conn:
        conn.execute(tm.INSERT_POST, ("@c", "5", "C", "текст", "text", None))
        cur = conn.execute(tm.INSERT_POST, ("@c", "5", "C", "дубль", "text", None))
    assert cur.rowcount == 0  # UNIQUE(channel_id, message_id) — дубль отсечён
    n = conn.execute("SELECT COUNT(*) FROM lz_channel_posts").fetchone()[0]
    assert n == 1


def test_busy_timeout_pragma(tmp_path):
    conn = tm.db_connect(str(tmp_path / "x.db"))
    v = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert v == 5000
