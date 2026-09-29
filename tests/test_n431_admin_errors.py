"""Гвард наряда #431: /admin errors — не-ошибочные статусы, причины отказов,
«ждут снабженца» отдельной строкой.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/431
A.1 — pending/dispatched/queued/skipped/… исключены из выборки ошибок.
A.2 — отказам (refused/failed/…) выводится details (усечено, redact).
A.3 — ожидающие снабженца (shop_supply pending/dispatched,
      collector_not_implemented) — отдельной строкой «Ждут снабженца: N».
Запуск: python -m pytest tests/test_n431_admin_errors.py -v
Живой тест: test_n431v1.mlog (в корне, конвенция репо; 8 проверок).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")

NON_ERROR = "('pending','dispatched','done','queued','skipped','in_work','running','started','collector_not_implemented')"


def _digest_block():
    return ADMIN.split("pattern AdminLogDigest")[1].split("pattern AdminLogsIfRelevant")[0]


def test_non_error_statuses_excluded_from_errors():
    block = _digest_block()
    # оба журнала (audit_log + trace_log) используют один NOT IN-список
    assert block.count(NON_ERROR) >= 4, "не все выборки исключают не-ошибочные статусы"
    assert "Нестатусные действия (audit_log" not in block, "старый заголовок остался"


def test_refusals_show_details():
    block = _digest_block()
    assert block.count("details FROM audit_log") == 1
    assert block.count("details FROM trace_log") == 1
    # усечение 120 + redact — уроки #407 (журналы могут содержать секреты)
    assert 'substring(to_string(json_get(row, "details", "")), 0.0, 120.0)' in block
    assert 'redact(substring(to_string(json_get(row, "details"' in block
    assert block.count("redact(substring(to_string(json_get(row, \"details\"") == 2


def test_waiting_for_supply_line():
    block = _digest_block()
    assert "Ждут снабженца: " in block
    # очередь снабженца + исторический статус — оба считаются ждущими
    assert "(action = 'shop_supply' AND status IN ('pending','dispatched')) OR status = 'collector_not_implemented'" in block


def test_empty_message_mentions_nothing_misleading():
    # пустая выборка остаётся честной
    assert "записей нет (ошибок, сбоев и нестатусных действий не зафиксировано)" in ADMIN
