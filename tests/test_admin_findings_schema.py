#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#265: гвард единой схемы admin_findings (ADR-0004).

Гварды:
- три CREATE (app.mlog, dogfood_staging.mlog, proxy/core.py) обязаны иметь
  идентичный список колонок — канон python-схемы (category/file/fix),
  расхождение = гонка двух CREATE (побеждает та, что выполнилась первой при буте).
  dept/app.mlog исключён из гварда (#283): мёртвый дубль, ни один импорт
  на него не ссылался — файл удалён;
- ни один INSERT INTO admin_findings в коде не вправе упоминать
  старые колонки file_path/fix_suggestion;
- python-читатели admin_findings не ссылаются на file_path.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA_SOURCES = [ROOT / "app.mlog",
                  ROOT / "dogfood_staging.mlog", ROOT / "proxy" / "core.py"]
ROUTES_ADMIN = ROOT / "proxy" / "routes_admin.py"
DEPT_MLOGS = sorted((ROOT / "dept").glob("*.mlog"))

# Список колонок из CREATE в одну строку: жадно до последней ")",
# за которой следует терминатор языка (/*mlog*/) или ";" (/*python*/).
CREATE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS admin_findings \(([^\n]*)\)[;\"]")


def _columns(text: str) -> list:
    m = CREATE_RE.search(text)
    assert m, "CREATE TABLE IF NOT EXISTS admin_findings не найден"
    return [c.strip().lower() for c in m.group(1).split(",")]


def test_three_creates_have_identical_columns():
    canon = _columns(SCHEMA_SOURCES[2].read_text(encoding="utf-8"))
    joined = " ".join(canon)
    assert "category text" in joined, "канон должен содержать category (ADR-0004)"
    assert "file text" in joined, "канон должен содержать file (ADR-0004)"
    assert "fix text" in joined, "канон должен содержать fix (ADR-0004)"
    assert "file_path" not in joined, "канон не должен содержать file_path (ADR-0004)"
    for src in SCHEMA_SOURCES[:2]:
        cols = _columns(src.read_text(encoding="utf-8"))
        assert cols == canon, (
            f"{src.name}: схема admin_findings расходится с каноном core.py "
            f"(ADR-0004).\n  {src.name}: {cols}\n  canon: {canon}")


def test_no_legacy_columns_in_inserts():
    legacy = re.compile(
        r"INSERT INTO admin_findings[^\"']*(?:file_path|fix_suggestion)", re.I)
    offenders = []
    for src in SCHEMA_SOURCES[:2] + DEPT_MLOGS + sorted((ROOT / "proxy").glob("*.py")):
        if legacy.search(src.read_text(encoding="utf-8")):
            offenders.append(src.name)
    assert not offenders, f"INSERT в admin_findings со старыми колонками: {offenders}"


def test_no_legacy_columns_in_python_readers():
    sel = re.compile(r"SELECT[^;()]*file_path[^;()]*FROM\s+admin_findings", re.I | re.S)
    bad = sel.search(ROUTES_ADMIN.read_text(encoding="utf-8"))
    assert not bad, (
        f"routes_admin.py читает admin_findings.file_path (канон — file): "
        f"{bad.group(0)[:120]}")
