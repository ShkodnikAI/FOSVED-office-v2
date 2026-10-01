#!/usr/bin/env python3
"""Сравнение реализаций 8 дублирующихся паттернов (#449 A.2)."""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATTERN_DEF_RE = re.compile(r"^(\s*)pattern\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

DUPES = ["ApplyDisclaimer", "DISCLAIMER_BOTTOM", "DISCLAIMER_TOP", "EnforceHardRules",
         "QuarterlyMethodologyReview", "RunQuarterlyMethodologyReview", "SearchArchive",
         "WrapWithDisclaimer"]
DEFS = {
    "ApplyDisclaimer": [("dept/legal.mlog", 1034), ("dept/qa.mlog", 1685)],
    "DISCLAIMER_BOTTOM": [("dept/design.mlog", 48), ("dept/engineering.mlog", 78), ("dept/legal.mlog", 79)],
    "DISCLAIMER_TOP": [("dept/design.mlog", 46), ("dept/engineering.mlog", 76), ("dept/legal.mlog", 77)],
    "EnforceHardRules": [("dept/legal.mlog", 228), ("dept/qa.mlog", 324)],
    "QuarterlyMethodologyReview": [("dept/engineering.mlog", 1074), ("dept/qa.mlog", 1642)],
    "RunQuarterlyMethodologyReview": [("dept/design.mlog", 1410), ("dept/legal.mlog", 854)],
    "SearchArchive": [("dept/engineering.mlog", 980), ("dept/legal.mlog", 992), ("dept/utils.mlog", 312)],
    "WrapWithDisclaimer": [("dept/design.mlog", 1643), ("dept/engineering.mlog", 191)],
}


def body(path: str, line: int) -> str:
    lines = (REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
    start = line - 1
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "}" and not lines[i].startswith((" ", "\t")):
            return "\n".join(lines[start:i + 1])
    return "\n".join(lines[start:])


identical, differing = [], []
for name, sites in DEFS.items():
    texts = {p: body(p, l) for p, l in sites}
    uniq = set(t.strip() for t in texts.values())
    if len(uniq) == 1:
        identical.append(name)
        print(f"IDENTICAL: {name} ({len(sites)} сайтов)")
    else:
        differing.append((name, texts))
        print(f"DIFFERING: {name}")
        files = list(texts)
        for a, b in zip(files, files[1:]):
            if texts[a].strip() != texts[b].strip():
                print(f"   {a} != {b}")
print()
print("Идентичны:", len(identical), differing_count := len(differing))
