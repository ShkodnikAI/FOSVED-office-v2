#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #514: дубли паттернов между dept-файлами — одно авторское место на имя.

Дефект (бут-логи прода 13.10): SearchArchive (dept/utils ↔ dept/legal),
DISCLAIMER_TOP/BOTTOM (dept/legal ↔ dept/engineering) определялись дважды,
порядок «who wins» был НЕДЕТЕРМИНИРОВАН — поведение офиса различалось между
рестартами без изменений кода. Скрытая опасность: app.mlog /search парсит
JSON именно utils-версии — при выигравшей legal-версии /search падал бы
на parse_json.

Гварды:
- во всех dept/*.mlog каждое имя pattern объявлено ровно один раз
  (детерминированность резолва: нет дублей — нет зависимости от порядка);
- SearchArchive — только dept/utils (сигнатура с одним query_text);
- отдел-специфичные версии носят dept-имена (ADR-0014: голос отдела);
- старые общие имена DISCLAIMER_TOP/DISCLAIMER_BOTTOM не остались нигде.

Живая приёмка (за аудитором): бут-лог прода без duplicate-pattern warnings;
два подряд бута дают одинаковый набор активных паттернов.
"""
import glob
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPT = os.path.join(REPO, "dept")

PATTERN_RE = re.compile(r"^pattern (\w+)\(", re.M)


def _all_patterns():
    seen = {}
    for f in sorted(glob.glob(os.path.join(DEPT, "*.mlog"))):
        name = os.path.basename(f)
        for m in PATTERN_RE.finditer(open(f, encoding="utf-8").read()):
            seen.setdefault(m.group(1), []).append(name)
    return seen


def test_no_duplicate_pattern_names_across_dept_files():
    dups = {k: v for k, v in _all_patterns().items() if len(v) > 1}
    assert not dups, f"дубли паттернов (порядок бута влияет на резолв): {dups}"


def test_search_archive_single_authoritative_in_utils():
    pats = _all_patterns()
    assert pats.get("SearchArchive") == ["utils.mlog"], \
        "SearchArchive должен иметь одно авторское место — dept/utils (его JSON парсит app.mlog /search)"
    src = open(os.path.join(DEPT, "utils.mlog"), encoding="utf-8").read()
    m = re.search(r"pattern SearchArchive\((\w+): String\)", src)
    assert m, "сигнатура utils SearchArchive изменилась — app.mlog /search ждёт (query_text: String)"
    assert m.group(1) == "query_text"


def test_dept_specific_versions_named_with_dept_context():
    pats = _all_patterns()
    for name in ("LegalSearchArchive", "EngineeringSearchArchive",
                 "LegalDisclaimerTop", "LegalDisclaimerBottom",
                 "EngineeringDisclaimerTop", "EngineeringDisclaimerBottom",
                 "DesignDisclaimerTop", "DesignDisclaimerBottom",
                 "LegalApplyDisclaimer", "QaApplyDisclaimer",
                 "LegalQuarterlyMethodologyReview", "EngineeringQuarterlyMethodologyReview",
                 "DesignQuarterlyMethodologyReview", "QaQuarterlyMethodologyReview",
                 "DesignWrapWithDisclaimer", "EngineeringWrapWithDisclaimer"):
        assert name in pats, f"нет dept-специфичного паттерна {name}"


def test_old_generic_names_gone():
    for f in sorted(glob.glob(os.path.join(DEPT, "*.mlog"))):
        src = open(f, encoding="utf-8").read()
        for m in PATTERN_RE.finditer(src):
            assert m.group(1) not in ("DISCLAIMER_TOP", "DISCLAIMER_BOTTOM"), \
                f"{os.path.basename(f)}: старое общее имя {m.group(1)} осталось"


def test_app_search_call_compatible_with_utils_version():
    app = open(os.path.join(REPO, "app.mlog"), encoding="utf-8").read()
    assert "let search_result = SearchArchive(query_text)" in app, \
        "вызов /search в app.mlog изменился — проверить совместимость с utils-сигнатурой"
