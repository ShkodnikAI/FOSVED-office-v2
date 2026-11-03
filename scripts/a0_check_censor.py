#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A0 (наряд #633, эпик #632): CI-ценз содержательных находок mlog check.

Пайплайн (пара check+test — урок аудита §5.2, VERIFICATION_v2.md):
  1. DATABASE_URL=sqlite::memory: bin/mlog check app.mlog --root app.mlog
  2. артефакты режима фильтруются по протоколу аудита:
       - errors 'duplicate pattern' — двойная загрузка паттернов при --root (флэттене);
       - errors 'undefined: …' — от той же двойной загрузки; ноль по ним отдельно
         держит CI-гвард замкнутости точек входа (#604), здесь они не содержательные;
  3. содержательные находки сравниваются по семьям с эталоном
     docs/office/BASELINE_app_mlog.txt;
  4. DATABASE_URL=sqlite::memory: bin/mlog test app.mlog — обязан быть зелёным.

Гейт (exit 1):
  - рост семьи против эталона или новая семья (новая содержательная находка);
  - нераспознанная строка в errors (формат вывода изменился — проверка
    потеряла силу, считаем красным);
  - 'parse error' в выводе check; секция errors не найдена;
  - эталон отсутствует/нечитаем; mlog test не зелёный.
Меньше эталона — зелёный с пометкой «долг уменьшился — обнови эталон»
(обновление эталона — отдельный осознанный коммит, не автомат).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "docs" / "office" / "BASELINE_app_mlog.txt"
CHECK_TIMEOUT = 300
TEST_TIMEOUT = 300

ITEM_RE = re.compile(r"^\s*(\d+): (.+?)\s*$")
SEC_RE = re.compile(r"^(\d+) (errors|warnings):\s*$")
FAMILY_RE = re.compile(r"^\[([A-Z_]+)\]")
TESTS_RE = re.compile(r"(\d+)/(\d+) tests passed")


def run_mlog(args):
    env = dict(os.environ)
    env["DATABASE_URL"] = "sqlite::memory:"
    return subprocess.run(
        ["./bin/mlog"] + args, cwd=str(REPO), env=env,
        capture_output=True, text=True, timeout=CHECK_TIMEOUT,
    )


def parse_sections(text):
    """Возвращает (errors[], warnings[], found_sections)."""
    errors, warnings, active = [], [], set()
    for line in text.splitlines():
        m = SEC_RE.match(line)
        if m:
            active = {m.group(2)}
            continue
        m = ITEM_RE.match(line)
        if m and active:
            (errors if "errors" in active else warnings).append(m.group(2))
    if errors or warnings:
        active.add("items")
    return errors, warnings, active


def load_baseline():
    """dict family -> allowed_count; None если эталон нечитаем."""
    if not BASELINE.is_file():
        return None
    out = {}
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_]+)\s+(\d+)$", line)
        if not m:
            return None
        out[m.group(1)] = int(m.group(2))
    return out or None


def fail(msg, detail=None):
    print(f"A0 CENSOR: FAIL — {msg}")
    if detail:
        print(detail)
    sys.exit(1)


def main():
    # ── 1. mlog check ──────────────────────────────────────────────────
    try:
        r = run_mlog(["check", "app.mlog", "--root", "app.mlog"])
    except subprocess.TimeoutExpired:
        fail("mlog check не завершился за %d c" % CHECK_TIMEOUT)
    out = r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")
    if "parse error" in out:
        fail("parse error в app.mlog — синтаксис сломан",
             "\n".join(l for l in out.splitlines() if "parse error" in l)[:2000])
    errors, warnings, seen = parse_sections(out)
    if not seen:
        fail("секция errors/warnings не найдена — формат вывода mlog изменился",
             out[-1500:])

    # ── 2. фильтр артефактов режима ────────────────────────────────────
    artifacts, substantive, unparsed = [], [], []
    for e in errors:
        if "duplicate pattern" in e or "undefined" in e:
            artifacts.append(e)
        else:
            m = FAMILY_RE.match(e)
            if not m:
                unparsed.append(e)
            else:
                substantive.append((m.group(1), e))
    if unparsed:
        fail("нераспознанные строки в errors — гейт не может подтвердить состав",
             "\n".join(unparsed[:10]))

    # ── 3. сравнение с эталоном ────────────────────────────────────────
    baseline = load_baseline()
    if baseline is None:
        fail(f"эталон {BASELINE.relative_to(REPO)} отсутствует или нечитаем")
    actual = {}
    for fam, _ in substantive:
        actual[fam] = actual.get(fam, 0) + 1

    families = sorted(set(baseline) | set(actual))
    rows, new_fams, grown, shrunk = [], [], [], []
    for fam in families:
        base_n, act_n = baseline.get(fam, 0), actual.get(fam, 0)
        rows.append(f"  {fam:28s} эталон={base_n:3d} факт={act_n:3d} {'  ← РОСТ' if act_n > base_n else ('  ← НОВАЯ' if base_n == 0 else ('  ← меньше' if act_n < base_n else ''))}")
        if base_n == 0 and act_n > 0:
            new_fams.append(fam)
        elif act_n > base_n:
            grown.append((fam, base_n, act_n))
        elif act_n < base_n:
            shrunk.append((fam, base_n, act_n))

    print(f"A0 censor: содержательных {len(substantive)} (эталон {sum(baseline.values())}); "
          f"артефактов режима отфильтровано {len(artifacts)} "
          f"(duplicate pattern/undefined); warnings вне гейта: {len(warnings)}")
    print("\n".join(rows))

    if new_fams or grown:
        det = []
        for fam, b, a in grown:
            det.append(f"  {fam}: {b} → {a}")
        for fam in new_fams:
            det.append(f"  {fam}: новая семья (0 → {actual[fam]})")
        fail("новая содержательная находка — долг вырос (наряд #633)",
             "\n".join(det))
    if shrunk:
        print("  NOTE: долг уменьшился — обнови эталон отдельным коммитом: "
              + ", ".join(f"{f} {b}→{a}" for f, b, a in shrunk))

    # ── 4. mlog test (пара check+test, §5.2) ───────────────────────────
    try:
        t = run_mlog(["test", "app.mlog"])
    except subprocess.TimeoutExpired:
        fail("mlog test не завершился за %d c" % TEST_TIMEOUT)
    tout = t.stdout + ("\n" + t.stderr if t.stderr.strip() else "")
    m = TESTS_RE.search(tout)
    if t.returncode != 0 or not m or m.group(1) != m.group(2) or m.group(1) == "0":
        fail("mlog test app.mlog не зелёный",
             tout[-1500:])
    print(f"A0 censor: mlog test app.mlog — {m.group(0)} ✓")
    print("A0 CENSOR: OK — содержательные находки в пределах эталона "
          f"({len(substantive)} ≤ {sum(baseline.values())}), тесты зелёные")
    sys.exit(0)


if __name__ == "__main__":
    main()
