#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#266: гвард ОСП-ставок — имя таблицы asymmetric_bet, реальный прогон SQL.

Аудит #244: INSERT/UPDATE в dept/osp.mlog били в несуществующую
asymmetric_bets (v4.1-легаси) вместо живой asymmetric_bet (app.mlog:178).
Наряд #266 — поправить имя и значение статуса, прогнать SQL реально.

Гварды:
- живой код (не комментарии) не содержит обращений к asymmetric_bets;
- INSERT из dept/osp.mlog, исполненный в sqlite с живой схемой
  app.mlog:178, реально вставляет запись со статусом 'OPEN';
- UPDATE из dept/osp.mlog (OSPUpdateBetStatus) реально обновляет запись;
- закомментированная v4.1-схема не восстановлена.
"""
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSP = (ROOT / "dept" / "osp.mlog").read_text(encoding="utf-8")
APP = (ROOT / "app.mlog").read_text(encoding="utf-8")


def _live_sql(pattern: str) -> str:
    """SQL-строка из живой (не комментарий) строки dept/osp.mlog."""
    for ln in OSP.splitlines():
        if ln.strip().startswith("//"):
            continue
        m = re.search(pattern, ln)
        if m:
            return m.group(1)
    raise AssertionError(f"не найден живой SQL по шаблону {pattern}")


def _seed_db() -> sqlite3.Connection:
    """in-memory БД с точной живой схемой asymmetric_bet из app.mlog."""
    m = re.search(r"CREATE TABLE IF NOT EXISTS asymmetric_bet \(([^\n]*)\)[;\"]", APP)
    assert m, "CREATE TABLE asymmetric_bet не найден в app.mlog"
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(f"CREATE TABLE IF NOT EXISTS asymmetric_bet ({m.group(1)})")
    return con


def test_no_live_asymmetric_bets_references():
    """Живой код не бьёт в asymmetric_bets (легаси-строка в комментарии — ок)."""
    bad = []
    for path in [ROOT / "app.mlog", ROOT / "dept" / "osp.mlog",
                 ROOT / "dogfood_staging.mlog"] + sorted((ROOT / "dept").glob("*.mlog")) + \
            sorted((ROOT / "proxy").glob("*.py")):
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ln.strip().startswith("//") or ln.strip().startswith("#"):
                continue
            if "asymmetric_bets" in ln:
                bad.append(f"{path.name}:{i}")
    assert not bad, f"живые обращения к asymmetric_bets (таблицы нет): {bad}"


def test_insert_executes_for_real():
    sql = _live_sql(r'(INSERT INTO asymmetric_bet[^"]*VALUES[^"]*)"')
    assert "asymmetric_bet " in sql or sql.startswith("asymmetric_bet"), sql
    assert "'OPEN'" in sql, f"статус должен быть 'OPEN' (живой DEFAULT), got: {sql}"
    con = _seed_db()
    con.execute(sql, ["Тестовая асимметричная ставка: растущий дефицит золота"])
    row = con.execute("SELECT thesis, status FROM asymmetric_bet").fetchone()
    assert row is not None, "INSERT не вставил запись"
    assert row["status"] == "OPEN"
    assert "золота" in row["thesis"]


def test_update_executes_for_real():
    sql = _live_sql(r'(UPDATE asymmetric_bet[^"]*WHERE[^"]*)"')
    con = _seed_db()
    con.execute("INSERT INTO asymmetric_bet (thesis, status) VALUES (?, 'OPEN')",
                ["исходная ставка"])
    bet_id = con.execute("SELECT id FROM asymmetric_bet").fetchone()["id"]
    con.execute(sql, ["CLOSED", "итог: +12%", str(bet_id)])
    row = con.execute("SELECT status, outcome_note FROM asymmetric_bet").fetchone()
    assert row["status"] == "CLOSED"
    assert row["outcome_note"] == "итог: +12%"


def test_legacy_v41_schema_not_restored():
    """Закомментированная v4.1-схема не активирована (наряд: не восстанавливать)."""
    for ln in OSP.splitlines():
        if "CREATE TABLE asymmetric_bets" in ln:
            assert ln.strip().startswith("//"), "v4.1-схема восстановлена живым кодом — запрещено нарядом #266"
