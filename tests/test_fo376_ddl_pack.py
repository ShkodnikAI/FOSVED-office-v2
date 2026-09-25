"""Наряд №376 (P2): гвард DDL-пачки QA/Dev/Design — 16 таблиц в InitDB.

Факт до пачки: 16 таблиц (qa 7, dev 5, design 4) писались/читались кодом
(dept/qa.mlog, dept/dev.mlog, dept/design.mlog), но не создавались нигде —
свежий деплой с пустой БД падал на первом INSERT. Живая БД имела их только
исторически.

Фикс: исполняемый CREATE TABLE IF NOT EXISTS в InitDB (app.mlog). Схема снята
с живой БД 2026-09-25 (нулевой дрейф с историческими таблицами).

Гварды:
1. Статика: 16 statements в app.mlog, по 7/5/4 на отдел.
2. SQLite-валидность: каждый statement исполняется на in-memory sqlite.
3. Дрейф: если живая БД доступна — множество колонок из DDL == множество
   колонок живой таблицы (skip, если БД нет — CI-песочницы).
"""
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")

DDL_PACK = {
    "qa": [
        "test_runs", "defect_records", "incidents", "ai_eval_runs",
        "security_audits", "qa_assessments", "cross_dept_tasks",
    ],
    "dev": [
        "tech_radar_entries", "architecture_decisions", "code_repositories",
        "dev_estimate_verifications", "dev_rule_violations",
    ],
    "design": [
        "design_artifacts", "design_decisions", "user_research_sessions",
        "design_verification",
    ],
}
ALL_TABLES = DDL_PACK["qa"] + DDL_PACK["dev"] + DDL_PACK["design"]


def _statements() -> dict:
    """Извлечение CREATE TABLE IF NOT EXISTS <name> (...) из app.mlog."""
    found = {}
    for m in re.finditer(r'db_execute\("CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\)"\)', APP, re.S):
        found[m.group(1)] = f"CREATE TABLE IF NOT EXISTS {m.group(1)} ({m.group(2)})"
    return found


def test_all_16_tables_in_initdb():
    stmts = _statements()
    missing = [t for t in ALL_TABLES if t not in stmts]
    assert not missing, f"нет CREATE TABLE IF NOT EXISTS для: {missing}"


def test_per_dept_counts():
    block = APP[APP.index("Наряд №376 (P2): DDL-пачка"):APP.index("конец DDL-пачки №376")]
    for dept, tables in DDL_PACK.items():
        for t in tables:
            assert t in block, f"{t} не найден в секции {dept} DDL-пачки"


def test_statements_are_valid_sqlite():
    stmts = _statements()
    con = sqlite3.connect(":memory:")
    for t in ALL_TABLES:
        con.execute(stmts[t])  # бросит исключение при невалидном SQL
    # идемпотентность: повторный прогон не падает
    for t in ALL_TABLES:
        con.execute(stmts[t])
    con.close()


def test_no_column_drift_vs_live_db():
    db = REPO_ROOT / "data" / "fosved.db"
    if not db.exists():
        import pytest
        pytest.skip("живая БД недоступна (CI-песочница) — дрейф-гвард локальный")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    stmts = _statements()
    drifted = []
    for t in ALL_TABLES:
        live_cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        if not live_cols:
            drifted.append(f"{t}: нет в живой БД")
            continue
        # колонки из DDL
        m = sqlite3.connect(":memory:")
        m.execute(stmts[t])
        ddl_cols = {r[1] for r in m.execute(f"PRAGMA table_info({t})")}
        if ddl_cols != live_cols:
            drifted.append(f"{t}: DDL={sorted(ddl_cols)} live={sorted(live_cols)}")
        m.close()
    con.close()
    assert not drifted, "дрейф схемы DDL vs живая БД:\n" + "\n".join(drifted)
