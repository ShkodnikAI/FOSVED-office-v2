#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #578: гварды Unicode-гигиены публикаций.

A.1 — scripts/unicode_hygiene.py компилируется, списки классов полны;
A.2 — политика в докстринге: --fix трогает только REMOVABLE, вердикт
      никогда не называет текст «чистым»;
A.3 — seed watchlist hidden-unicode-in-llm-output по паттерну #566,
      идемпотентный, домен Computational, внутри LZWatchSeedCategory;
Runtime-блок — синтетический корпус: находки точны, --fix удаляет ровно
REMOVABLE, чистый текст даёт exit 0.

Стиль по конвенции test_n566/test_n556: якорные проверки + реальный прогон.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "unicode_hygiene.py"
SCRIPT_SRC = SCRIPT.read_text(encoding="utf-8")
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")

REMOVABLE_CPS = ["\u200b", "\u2060", "\ufeff", "\u00ad",
                 "\u202a", "\u202b", "\u202c", "\u202d", "\u202e"]
REVIEW_CPS = ["\u200e", "\u200f", "\u061c", "\u2066", "\u2067", "\u2068", "\u2069",
              "\u180e", "\u2800", "\u3164", "\u115f", "\u1160", "\ufffd", "\u034f"]


def _code_lines(text):
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def test_a1_script_compiles_and_lists_full():
    compile(SCRIPT_SRC, "unicode_hygiene.py", "exec")
    for cp in REMOVABLE_CPS:
        # в исходнике символы записаны escape-последовательностями
        assert f"\\u{ord(cp):04x}" in SCRIPT_SRC, f"REMOVABLE не хватает {cp!r}"
    for cp in REVIEW_CPS:
        assert f"\\u{ord(cp):04x}" in SCRIPT_SRC, f"REVIEW не хватает {cp!r}"


def test_a2_policy_in_docstring():
    assert "--fix" in SCRIPT_SRC and "ТОЛЬКО" in SCRIPT_SRC.upper()
    # вердикт никогда не говорит «чистый»
    assert "не называет текст «чистым»" in SCRIPT_SRC
    assert "REVIEW требует взгляда" in SCRIPT_SRC
    # двухколейность #577 перенесена
    assert "двухколейность" in SCRIPT_SRC.lower()
    assert "файл:строка" in SCRIPT_SRC


def test_a3_seed_watchlist_pattern_566():
    code = _code_lines(LZ)
    seed = ("INSERT INTO watchlist_entries (topic, domain, status) SELECT "
            "'hidden-unicode-in-llm-output', 'Computational', 'active' "
            "WHERE NOT EXISTS (SELECT 1 FROM watchlist_entries "
            "WHERE topic = 'hidden-unicode-in-llm-output')")
    assert seed in code, "seed #578 отсутствует или не идемпотентен"
    # внутри LZWatchSeedCategory — вызывается из app.mlog автоматически
    pattern_start = code.index("pattern LZWatchSeedCategory()")
    pattern_end = code.index("}", code.index("return \"seeded\"", pattern_start))
    assert seed in code[pattern_start:pattern_end], "seed не внутри LZWatchSeedCategory"
    # статус сигнала: tracking-кандидат 1/3, не алерт (правило №1)
    assert "1/3" in LZ


def _run(args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True, cwd=cwd, timeout=60)


def test_runtime_findings_precise(tmp_path):
    target = tmp_path / "corpus.txt"
    target.write_text(
        "a\u200bb\n"
        "\u202ae\u202cf\n"
        "x\u00ady\n"
        "rtl\u200fg\n"
        "iso\u2066h\u2069\n",
        encoding="utf-8")
    r = _run([str(target), "--json"], cwd=tmp_path)
    assert r.returncode == 1, "найдены REMOVABLE — exit должен быть 1"
    data = json.loads(r.stdout)
    rem = [i["codepoint"] for i in
           [f for f in data["files"] if f["path"] == str(target)][0]["removable"]]
    rev = [i["codepoint"] for i in
           [f for f in data["files"] if f["path"] == str(target)][0]["review"]]
    assert sorted(rem) == sorted(["U+200B", "U+202A", "U+202C", "U+00AD"])
    assert sorted(rev) == sorted(["U+200F", "U+2066", "U+2069"])
    assert "REVIEW требует взгляда 3" in data["verdict"]
    assert "чист" not in data["verdict"].lower()


def test_runtime_fix_removes_only_removable(tmp_path):
    target = tmp_path / "corpus.txt"
    original = "a\u200bb\nrtl\u200fg\nx\u00ady\n"
    target.write_text(original, encoding="utf-8")
    r = _run([str(target), "--fix"], cwd=tmp_path)
    assert r.returncode == 0
    cleaned = target.read_text(encoding="utf-8")
    assert "\u200b" not in cleaned and "\u00ad" not in cleaned, "REMOVABLE не удалены"
    assert "\u200f" in cleaned, "REVIEW-символ удалён --fix — ЗАПРЕЩЕНО"
    assert "REMOVABLE удалено 2, REVIEW требует взгляда 1" in r.stdout


def test_runtime_clean_text_exit_zero(tmp_path):
    target = tmp_path / "clean.txt"
    target.write_text("Обычный русский текст: числа 2 000 ₽, ссылка https://example.org\n",
                      encoding="utf-8")
    r = _run([str(target), "--json"], cwd=tmp_path)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["files"][0]["removable_count"] == 0
    assert data["files"][0]["review_count"] == 0
