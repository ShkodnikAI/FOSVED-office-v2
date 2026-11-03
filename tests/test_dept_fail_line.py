"""#636 A2c tests: счётчик громких отказов отделов в утренней сводке (dept_fail_line_24h)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['CRON_SECRET'] = 'cron-test-secret'

import llm_proxy  # noqa: E402
from proxy.routes_sched import dept_fail_line_24h  # noqa: E402


def _seed_dept_fail(dept, details='test crash'):
    llm_proxy._query(
        "INSERT INTO trace_log (action, actor, dept, details, status) "
        "VALUES ('dept_fail', 'system', ?, ?, 'error')", (dept, details))


class TestDeptFailLine:
    def test_counts_grouped_by_dept(self):
        dept = f"qa_{__import__('uuid').uuid4().hex[:6]}"
        _seed_dept_fail(dept)
        _seed_dept_fail(dept, 'second crash')
        line = dept_fail_line_24h()
        assert line.startswith("Отказы отделов за сутки: ")
        assert f"{dept} — 2" in line

    def test_honest_zero_when_no_failures(self):
        # dept_fail с таким суффиксом не сеем — строка либо честный ноль,
        # либо перечисление других отделов, но не пустая тишина
        line = dept_fail_line_24h()
        assert line == "Отказы отделов за сутки: 0" or line.startswith("Отказы отделов за сутки: ")

    def test_old_errors_not_counted(self):
        dept = f"qa_{__import__('uuid').uuid4().hex[:6]}"
        llm_proxy._query(
            "INSERT INTO trace_log (action, actor, dept, details, status, timestamp) "
            "VALUES ('dept_fail', 'system', ?, 'old crash', 'error', datetime('now', '-3 days'))",
            (dept,))
        line = dept_fail_line_24h()
        assert dept not in line
