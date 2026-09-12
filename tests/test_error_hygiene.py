"""FO-007 tests: error_log, _log_error (dedup), ротация журналов, политика silent-except."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before llm_proxy import (same contract as test_security.py)
os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import llm_proxy  # noqa: E402


def _count(table, where="1=1", params=()):
    rows = llm_proxy._query(f"SELECT COUNT(*) as c FROM {table} WHERE {where}", params, fetch=True)
    return rows[0]["c"] if rows else 0


class TestLogError:
    """_log_error: строка в error_log + дедуп."""

    def test_inserts_row(self):
        tag = uuid.uuid4().hex[:8]
        llm_proxy._log_error(f"boom {tag}", source="test", dept="qa", kind="unit")
        assert _count("error_log", "source=? AND detail LIKE ?", ("test", f"%boom {tag}%")) == 1

    def test_dedup_within_window(self):
        tag = uuid.uuid4().hex[:8]
        llm_proxy._log_error(f"dup {tag}", source="test", dept="qa", kind="unit")
        llm_proxy._log_error(f"dup {tag}", source="test", dept="qa", kind="unit")
        assert _count("error_log", "source=? AND detail LIKE ?", ("test", f"%dup {tag}%")) == 1

    def test_different_details_not_deduped(self):
        tag = uuid.uuid4().hex[:8]
        llm_proxy._log_error(f"one {tag}", source="test", dept="qa", kind="unit")
        llm_proxy._log_error(f"two {tag}", source="test", dept="qa", kind="unit")
        c = _count("error_log", "source=? AND (detail LIKE ? OR detail LIKE ?)",
                   ("test", f"%one {tag}%", f"%two {tag}%"))
        assert c == 2


class TestRotation:
    """_rotate_service_logs: архивация + удаление старых строк."""

    def test_old_rows_archived_and_deleted(self, tmp_path):
        tag = uuid.uuid4().hex[:8]
        # Вставляем строку и искусственно старим её
        llm_proxy._query(
            "INSERT INTO error_log (ts, source, dept, kind, detail) VALUES ('2000-01-01 00:00:00', 'rot_test', ?, 'unit', ?)",
            ("qa", f"old row {tag}"))
        assert _count("error_log", "detail = ?", (f"old row {tag}",)) == 1

        llm_proxy._rotate_service_logs()

        assert _count("error_log", "detail = ?", (f"old row {tag}",)) == 0
        # Архивный файл содержит строку
        archive = llm_proxy.Path(llm_proxy.DB_PATH) / "archive" / "error_log.jsonl"
        assert archive.exists(), "archive file must be created"
        assert f"old row {tag}" in archive.read_text(encoding="utf-8")

    def test_fresh_rows_survive(self):
        tag = uuid.uuid4().hex[:8]
        llm_proxy._log_error(f"fresh {tag}", source="rot_test", dept="qa", kind="unit")
        llm_proxy._rotate_service_logs()
        assert _count("error_log", "detail LIKE ?", (f"%fresh {tag}%",)) == 1


class TestPolicy:
    """Политика FO-007: ни одного молчаливого except в llm_proxy.py."""

    def test_no_silent_excepts(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
        import check_silent_excepts
        src = open(check_silent_excepts.Path(check_silent_excepts.__file__).parent.parent / "llm_proxy.py",
                   encoding="utf-8").read()
        assert check_silent_excepts.find_silent_excepts(src) == []

    def test_trace_log_table_exists(self):
        # trace_log создан и принимает чекпоинты (раньше сваливались в audit_log)
        rows = llm_proxy._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('trace_log','error_log')",
            fetch=True)
        names = {r["name"] for r in rows}
        assert names == {"trace_log", "error_log"}
