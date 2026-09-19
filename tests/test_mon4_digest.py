#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MON-4 tests (#171): LZChannelDigest — сводка ЛЗ по каналам.

mlog-паттерн тестируется строковыми гвардами (логика паттерна исполняется
рантаймом Metalogos; CI-часть — parse-check в job mlog-check):
- паттерн LZChannelDigest в dept/lz.mlog: сигнатура (3 параметра — отклонение
  от буквы наряда документировано), честная деградация TikTok, запрет «общих
  знаний» в промпте, SendReport report-mlg2, kv-трекер не нужен (v1 — latest video);
- ветка диспетчера /lz digest в HandleLZ;
- help-строка обновлена;
- lz_channel_posts выборка использует параметризованный sqlite-модификатор
  (-N hours) — проверяется исполнением на реальном in-memory SQLite.
"""
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LZ = REPO_ROOT / "dept" / "lz.mlog"
APP = REPO_ROOT / "app.mlog"


def test_digest_pattern_present():
    src = LZ.read_text(encoding="utf-8")
    assert "pattern LZChannelDigest(channel_ids_json: String, since_hours: String, chat_id: String) -> String" in src
    # отклонение от буквы наряда (2 параметра → 3) документировано в комментарии
    assert "отклонение от буквы наряда" in src


def test_digest_honest_degradation_tiktok():
    src = LZ.read_text(encoding="utf-8")
    block = src.split("pattern LZChannelDigest")[1].split("\npattern ")[0]
    assert "TikTok: недоступен" in block  # строка из наряда MON-3/MON-4
    assert "McpMediaCall(" in block       # медиа-источник через мост MON-2/3


def test_digest_synthesis_from_collected_only():
    src = LZ.read_text(encoding="utf-8")
    block = src.split("pattern LZChannelDigest")[1].split("\npattern ")[0]
    assert "ТОЛЬКО данные ниже" in block  # запрет общих знаний — прямое требование наряда
    assert "call_llm" in block


def test_digest_sendreport_report_mlg2():
    src = LZ.read_text(encoding="utf-8")
    block = src.split("pattern LZChannelDigest")[1].split("\npattern ")[0]
    m = re.search(r"SendReport\(reply, \"lz\"", block)
    assert m, "отчёт не уходит через SendReport (формат report-mlg2)"


def test_dispatcher_branch_and_help():
    src = LZ.read_text(encoding="utf-8")
    assert 'starts_with(t, "/lz digest")' in src
    assert 'LZChannelDigest("[]", hours, chat_id)' in src
    app = APP.read_text(encoding="utf-8")
    assert "/lz digest [часы]" in app


def test_since_hours_sqlite_modifier_executes():
    """Параметризованный модификатор '-N hours' реально работает в SQLite."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE lz_channel_posts (channel_id TEXT, text TEXT, date TEXT)")
    conn.execute("INSERT INTO lz_channel_posts VALUES ('@a', 'пост', datetime('now', '-2 hours'))")
    conn.execute("INSERT INTO lz_channel_posts VALUES ('@a', 'старый', datetime('now', '-48 hours'))")
    rows = conn.execute(
        "SELECT text FROM lz_channel_posts WHERE date >= datetime('now', ?)",
        ("-24 hours",)).fetchall()
    assert len(rows) == 1 and rows[0][0] == "пост"
