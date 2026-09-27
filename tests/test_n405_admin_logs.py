#!/usr/bin/env python3
"""Наряд #405: Админ читает журналы офиса (error_log/audit_log/trace_log).

Запуск: python3 -m pytest tests/test_n405_admin_logs.py -v

Контракт (#405):
  A.1 — AdminLogDigest(hours): error_log группировка по dept/kind + последние 10
        с detail (усечено, redact); audit_log нестатусные действия; trace_log
        со status != ok; честное «записей нет».
  A.2 — команда /admin errors [часы] (дефолт 24).
  A.3 — подмешивание в свободный вопрос по маркерам («ошибк», «сбой», «лог»,
        «упал», «не работает»).
  A.4 — запрет выдумывания путей/компонентов в промпте Админа.
  A.5 — сверка колонки в admin.mlog (бывшая :905): audit_log СХЕМАСООВМЕСТНА —
        в proxy/core.py:379 audit_log(id, timestamp, action, actor, dept,
        details, status), фильтр по `timestamp` корректен; ошибка была бы с
        error_log — там `ts`, и AdminLogDigest использует именно `ts`.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n405-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")
CORE = (REPO_ROOT / "proxy" / "core.py").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def _digest_seg():
    i0 = ADMIN.index("pattern AdminLogDigest")
    i1 = ADMIN.index("pattern AdminLogsIfRelevant")
    return ADMIN[i0:i1]


def test_digest_reads_all_three_journals():
    seg = _digest_seg()
    assert "FROM error_log" in seg and "ts > datetime('now'" in seg, (
        "error_log читается по колонке ts (не timestamp)")
    assert "FROM audit_log" in seg and "status != 'ok'" in seg
    assert "FROM trace_log" in seg and "status != 'ok'" in seg


def test_digest_is_readonly_and_redacts():
    seg = _digest_seg()
    for bad in ("INSERT INTO error_log", "INSERT INTO audit_log",
                "INSERT INTO trace_log", "UPDATE error_log", "DELETE FROM audit_log"):
        assert bad not in seg, f"журналы только для чтения: {bad} недопустим"
    assert 'redact(substring(to_string(json_get(row, "detail", ""))' in seg, (
        "detail прогоняется через redact перед выводом")


def test_honest_empty_and_clamp():
    seg = _digest_seg()
    assert "записей нет" in seg
    assert "if h <= 0.0 then { let h = 24.0 }" in seg
    assert "if h > 168.0 then { let h = 168.0 }" in seg
    assert "?1" in seg and "hours" in seg, "часы идут связанным параметром"


def test_command_wired_in_app_mlog():
    assert 'if query == "errors" or starts_with(query, "errors ") then' in APP
    assert "AdminLogDigest(hours)" in APP
    assert "/errors [часы]" in APP, "help /admin должен упоминать /errors"


def test_mixed_into_free_question_and_no_hallucination():
    seg = ADMIN[ADMIN.index("pattern AdminLogsIfRelevant"):ADMIN.index("pattern HandleAdmin")]
    for kw in ('"ошибк"', '"сбой"', '"лог"', '"упал"', '"не работает"'):
        assert kw in seg, f"маркер {kw} не проверяется"
    handle_seg = ADMIN[ADMIN.index("pattern HandleAdmin"):]
    assert "AdminLogsIfRelevant(query)" in handle_seg
    assert "ЗАПРЕТ ВЫДУМЫВАТЬ ИНФРАСТРУКТУРУ" in handle_seg, (
        "A.4: запрет выдуманных путей/компонентов в промпте Админа")


def test_a5_column_schema_verified():
    """A.5: audit_log действительно имеет колонку timestamp (фильтр корректен);
    error_log — ts (AdminLogDigest использует её)."""
    assert "CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT" in CORE
    assert "CREATE TABLE IF NOT EXISTS error_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT" in CORE
