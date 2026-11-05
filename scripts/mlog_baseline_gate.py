#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI-ценз содержательных находок `mlog check app.mlog --root app.mlog` (наряд #633, A0 эпика #632).

Логика (протокол фильтрации — docs/office/VERIFICATION_v2.md, наряд #633):
  1. Запускает `DATABASE_URL=sqlite::memory: ./bin/mlog check app.mlog --root app.mlog`.
  2. Отфильтровывает АРТЕФАКТЫ РЕЖИМА: `duplicate pattern` и `undefined` от двойной
     загрузки при --root (не содержательные), плюс шумовые строки логов.
  3. Классифицирует содержательные находки по семействам
     ([SECRET_EGRESS_NETWORK] -> SECRET_EGRESS и т.п., суффикс _NETWORK снимается).
  4. Сравнивает счётчики семейств с эталоном docs/office/BASELINE_app_mlog.txt
     (пересчитан на main e6d4577, mlog 0.38.0: 37 содержательных находок).
  5. Выход 1 (CI красный) если: семейство выросло, появилось НОВОЕ семейство,
     найден `parse error` или неизвестный класс находки.

Режимы:
  python3 scripts/mlog_baseline_gate.py                # штатный гейт CI
  python3 scripts/mlog_baseline_gate.py --selftest     # мутация: ПДн-литерал в db_execute -> красный
  python3 scripts/mlog_baseline_gate.py --check-output F [--baseline F]
                                                       # разбор готового вывода check (для тестов)
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# #655: MLOG_BIN — проверка КАНДИДАТА Metalogos на стенде офиса (rc_stand_check.sh);
# пусто/не задано → боевой бинарь, как в CI.
MLOG = os.environ.get("MLOG_BIN") or os.path.join(REPO, "bin", "mlog")
APP = os.path.join(REPO, "app.mlog")
DEFAULT_BASELINE = os.path.join(REPO, "docs", "office", "BASELINE_app_mlog.txt")

MUTATION_MARKER = "Паспорт 1234 567890"  # словарь literal_confidentiality (semantic.rs, ADR-0161 §3)

ERR_BLOCK_RE = re.compile(r"^(\d+) errors:")
WARN_BLOCK_RE = re.compile(r"^(\d+) warnings:")
ERR_LINE_RE = re.compile(r"^\s*(\d+):\s+(.*)$")
FAMILY_RE = re.compile(r"\[([A-Z][A-Z0-9_]+)\]")

# Артефакты режима (двойная загрузка --root) — не содержательные, протокол VERIFICATION_v2.md
REGIME_MARKERS = ("duplicate pattern", "undefined")
# Шумовые строки рантайма (не находки)
NOISE_MARKERS = ("[REDACT]", "[audit-event]", "[db] Connected", "Persistence enabled", "[kv_store]")


def normalize_family(tag):
    return tag[:-len("_NETWORK")] if tag.endswith("_NETWORK") else tag


def parse_check_output(text):
    """Возвращает (content: {family: [(line_no, snippet)]}, regime: int, parse_error: bool)."""
    content = {}
    regime = 0
    parse_error = "parse error" in text
    in_errors = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if ERR_BLOCK_RE.match(line):
            in_errors = True
            continue
        if WARN_BLOCK_RE.match(line):
            in_errors = False
            continue
        if not in_errors:
            continue
        m = ERR_LINE_RE.match(line)
        if not m:
            continue
        body = m.group(2)
        if any(x in line for x in NOISE_MARKERS):
            continue
        if any(x in body for x in REGIME_MARKERS):
            regime += 1
            continue
        fm = FAMILY_RE.search(body)
        if not fm:
            # Нумерованная ошибка без распознанного класса — незнакомая находка:
            # не прячем её, гейт обязан зацепить новый класс (fail-safe).
            content.setdefault("__UNKNOWN__", []).append((m.group(1), body[:160]))
            continue
        content.setdefault(normalize_family(fm.group(1)), []).append((m.group(1), body[:160]))
    return content, regime, parse_error


def parse_baseline(path):
    base = {}
    total = None
    meta = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                meta.append(line)
                continue
            m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*(\d+)$", line)
            if m:
                if m.group(1) == "TOTAL":
                    total = int(m.group(2))  # контрольная сумма, не семейство
                else:
                    base[m.group(1)] = int(m.group(2))
    return base, total, meta


def run_check(mlog_file, root_file):
    env = dict(os.environ)
    env["DATABASE_URL"] = "sqlite::memory:"
    proc = subprocess.run(
        [MLOG, "check", mlog_file, "--root", root_file],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=600,
    )
    return proc.stdout + proc.stderr


def compare(content, baseline, total_baseline=None):
    """Возвращает (ok, rows, fail_lines)."""
    rows = []
    fails = []
    families = sorted(set(content) | set(baseline))
    for fam in families:
        actual = len(content.get(fam, []))
        if fam == "__UNKNOWN__":
            rows.append((fam, "-", actual, "FAIL"))
            for _, snip in content.get(fam, [])[:3]:
                fails.append(f"неизвестный класс находки: {snip}")
            continue
        if fam not in baseline:
            rows.append((fam, "-", actual, "FAIL"))
            fails.append(f"НОВОЕ семейство {fam}: {actual} (эталона нет)")
            continue
        limit = baseline[fam]
        if actual > limit:
            rows.append((fam, limit, actual, "FAIL"))
            fails.append(f"рост {fam}: {limit} -> {actual}")
            for no, snip in content.get(fam, [])[limit:][:3]:
                fails.append(f"  новая находка #{no}: {snip}")
        else:
            note = "OK" if actual == limit else f"OK (улучшение, -{limit - actual}: эталон можно ужесточить)"
            rows.append((fam, limit, actual, note))
    total_actual = sum(len(v) for v in content.values())
    if total_baseline is not None and total_actual > total_baseline:
        fails.append(f"итог вырос: {total_baseline} -> {total_actual}")
    ok = not fails
    return ok, rows, fails


def gate(check_text, baseline_path):
    baseline, total_baseline, meta = parse_baseline(baseline_path)
    content, regime, parse_error = parse_check_output(check_text)
    print(f"артефактов режима отфильтровано: {regime}")
    ok, rows, fails = compare(content, baseline, total_baseline)
    total_actual = sum(len(v) for v in content.values())
    print(f"{'семейство':<24}{'эталон':>8}{'факт':>7}  вердикт")
    for fam, limit, actual, note in rows:
        print(f"{fam:<24}{str(limit):>8}{actual:>7}  {note}")
    print(f"итого содержательных: {total_actual} (эталон {total_baseline if total_baseline is not None else sum(baseline.values())})")
    if parse_error:
        fails.append("parse error в app.mlog — блокирующая ошибка синтаксиса")
    if ok and not parse_error:
        print("GATE GREEN: содержательных находок не больше эталона #633")
        return 0
    print("GATE RED:")
    for f in fails:
        print(f"  - {f}")
    return 1


def selftest():
    """Мутация (наряд #633 «сделано, когда»): ПДн-литерал в db_execute -> гейт ОБЯЗАН краснеть."""
    src = open(APP, encoding="utf-8").read()
    target = 'db_execute("CREATE TABLE IF NOT EXISTS dialog_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, dept TEXT, content TEXT, '
    if target not in src:
        print("SELFTEST INCONCLUSIVE: якорная строка InitDB/dialog_history не найдена — app.mlog изменился, обнови selftest")
        return 2
    mutated = src.replace(
        target,
        target + f"owner_doc TEXT DEFAULT '{MUTATION_MARKER}', ",
        1,
    )
    tmp_path = os.path.join(REPO, ".n633_mutation_tmp.mlog")
    baseline_path = DEFAULT_BASELINE
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(mutated)
        text = run_check(tmp_path, tmp_path)
        rc = gate(text, baseline_path)
        if rc != 0:
            print("SELFTEST OK: мутация (ПДн-литерал в db_execute) поймана — гейт красный, как требует наряд #633")
            return 0
        print("SELFTEST FAIL: мутация НЕ поймана — гейт пропустил новую содержательную находку")
        return 1
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=DEFAULT_BASELINE)
    ap.add_argument("--check-output", help="разобрать готовый вывод mlog check вместо запуска")
    ap.add_argument("--selftest", action="store_true", help="мутационный самотест гейта")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if args.check_output:
        with open(args.check_output, encoding="utf-8") as f:
            text = f.read()
    else:
        if not os.access(MLOG, os.X_OK):
            print(f"GATE ERROR: {MLOG} не найден/не исполняем")
            sys.exit(2)
        print("запуск: DATABASE_URL=sqlite::memory: bin/mlog check app.mlog --root app.mlog")
        text = run_check(APP, APP)
    sys.exit(gate(text, args.baseline))


if __name__ == "__main__":
    main()
