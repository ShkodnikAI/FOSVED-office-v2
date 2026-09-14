#!/usr/bin/env python3
"""FO-049 tests: недельная метрика нарядной дисциплины (диспатч #161).

Покрывает python-зеркало mlog-логики narad_stats (dept/narad.mlog):
- пустая неделя / отсутствие таблицы → пустая строка (честная деградация);
- доля first-try и вердикт (>=%50 — «дисциплина ок», иначе — «процесс
  требует внимания»);
- доработки и средний цикл в строке.
Запись метрик приёмкой (first_try/rework/lead) покрыта test_narad3v3.mlog.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-fo49-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import llm_proxy  # noqa: E402,F401
from proxy import narad_queue as nq  # noqa: E402
from proxy.core import _query  # noqa: E402

STATS_SQL = (
    "CREATE TABLE IF NOT EXISTS narad_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "narad_id TEXT, dept TEXT, first_try INTEGER DEFAULT 0, rework_count INTEGER DEFAULT 0, "
    "lead_seconds INTEGER, accepted_by TEXT, created_at TEXT DEFAULT (datetime('now')))"
)


@pytest.fixture(autouse=True)
def stats_table():
    _query(STATS_SQL)
    _query("DELETE FROM narad_stats")
    yield
    _query("DELETE FROM narad_stats")


def _row(nid, first_try, rework, lead, days_ago=0):
    _query("INSERT INTO narad_stats (narad_id, dept, first_try, rework_count, lead_seconds, accepted_by, created_at) "
           "VALUES (?, 'dev', ?, ?, ?, 'owner', datetime('now', ?))",
           (nid, first_try, rework, lead, f'-{days_ago} days'))


def test_empty_week_returns_empty_string():
    assert nq.narad_stats_week_line() == ""


def test_share_and_verdict_ok():
    _row("N1", 1, 0, 3600)
    _row("N2", 1, 0, 7200)
    _row("N3", 1, 0, 1800)
    _row("N4", 0, 2, 90000)
    line = nq.narad_stats_week_line()
    assert "закрыто 4" in line, line
    assert "с первой попытки 3 из 4 (75%)" in line, line
    assert "доработок 2" in line
    assert "дисциплина ок" in line


def test_low_share_attention_verdict():
    _row("N1", 1, 0, 3600)
    _row("N2", 0, 1, 7200)
    _row("N3", 0, 1, 7200)
    line = nq.narad_stats_week_line()
    assert "(33%)" in line, line
    assert "процесс требует внимания" in line, line


def test_lead_time_formatting():
    _row("N1", 1, 0, 5400)  # 1ч 30м
    line = nq.narad_stats_week_line()
    assert "средний цикл 1ч 30м" in line, line


def test_missing_table_returns_empty_string(monkeypatch):
    real_query = nq._query

    def broken_query(sql, params=(), fetch=False):
        if "narad_stats" in sql:
            raise RuntimeError("no such table")
        return real_query(sql, params, fetch)

    monkeypatch.setattr(nq, "_query", broken_query)
    assert nq.narad_stats_week_line() == ""
