#!/usr/bin/env python3
"""FO-043 tests: метрика формата правок — недельный срез (наряд #150, B.2).

Покрывает python-зеркало mlog-паттерна ForgeEditStatsWeekly (dept/forge.mlog):
- after_reread = успехи по тому же task+path после reject (не считаются first-try);
- доля first-try < 50% → вердикт «менять формат, а не модель» (§15);
- пустая неделя / отсутствие таблицы → пустая строка (честная деградация).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-fo43-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import llm_proxy  # noqa: E402,F401
from proxy import forge_backup as fb  # noqa: E402
from proxy.core import _query  # noqa: E402


@pytest.fixture(autouse=True)
def stats_table():
    _query("CREATE TABLE IF NOT EXISTS forge_edit_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, stage_id TEXT, path TEXT, outcome TEXT, fuzzy TEXT, created_at TEXT DEFAULT (datetime('now')))")
    _query("DELETE FROM forge_edit_stats")
    yield
    _query("DELETE FROM forge_edit_stats")


def _row(task, path, outcome, days_ago=0):
    _query("INSERT INTO forge_edit_stats (task_id, stage_id, path, outcome, fuzzy, created_at) "
           "VALUES (?, '1', ?, ?, '', datetime('now', ?))",
           (task, path, outcome, f'-{days_ago} days'))


def test_share_counts_after_reread_correctly():
    """first_try после reject того же task+path → after_reread, не first-try."""
    _row("1", "a.py", "reject")
    _row("1", "a.py", "first_try")   # после reject → after_reread
    _row("2", "b.py", "first_try")   # чистый first-try
    _row("3", "c.py", "fuzzy")
    _row("4", "d.py", "reject")
    line = fb.forge_edit_stats_week_line()
    assert "с первой попытки 1" in line, line
    assert "после перечитывания 1" in line
    assert "нечётко 1" in line
    assert "отказов 2" in line
    # (1 first + 1 reread) / 5 попыток = 40% → порог не пройден
    assert "менять формат" in line, line


def test_high_share_positive_verdict():
    _row("1", "a.py", "first_try")
    _row("2", "b.py", "first_try")
    _row("3", "c.py", "first_try")
    _row("4", "d.py", "reject")
    line = fb.forge_edit_stats_week_line()
    assert "75%" in line, line
    assert "формат ок" in line


def test_fuzzy_after_reject_counts_as_reread():
    _row("1", "a.py", "reject")
    _row("1", "a.py", "fuzzy")
    line = fb.forge_edit_stats_week_line()
    assert "после перечитывания 1" in line, line
    assert "нечётко 0" in line


def test_empty_week_returns_empty_string():
    assert fb.forge_edit_stats_week_line() == ""


def test_missing_table_returns_empty_string(monkeypatch):
    _query("DROP TABLE IF EXISTS forge_edit_stats_missing")
    # таблица отсутствует целиком — except-ветка даёт пустую строку
    real_query = fb._query

    def broken_query(sql, params=(), fetch=False):
        if "forge_edit_stats" in sql:
            raise RuntimeError("no such table")
        return real_query(sql, params, fetch)

    monkeypatch.setattr(fb, "_query", broken_query)
    assert fb.forge_edit_stats_week_line() == ""
