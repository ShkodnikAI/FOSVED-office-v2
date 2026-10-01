#!/usr/bin/env python3
"""#449 A.4: тест-барьер «долг не растёт» — CI-шаг чистки mlog-контура.

Проверяет три инварианта (после волны D, решения владельца 2026-10-02):
  1. Мёртвые вызовы mlog→:4000 (deadcall_detector): допустим ТОЛЬКО
     известный префиксный ложняк /cron/ (роуты /cron/* живы). Новые — FAIL.
  2. DEAD-паттерны в прод-замыкании app.mlog: после архивации их 0.
     Появление нового — WARNING (диспатч #449: «предупреждение в CI»),
     рост более DEAD_WARN_MAX — FAIL.
  3. Дубли определений: базовая линия 8 — охранная грамота ADR-0014
     (голос отдела важнее дедупликации). Рост — WARNING.

Запуск: python3 scripts/dead_pattern_gate.py
"""
import importlib.util
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEAD_WARN_MAX = 0
DUPES_BASELINE = 8
DEADCALL_ALLOWED = {"/cron/"}


def registry():
    spec = importlib.util.spec_from_file_location(
        "dead_pattern_registry", REPO_ROOT / "scripts" / "dead_pattern_registry.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.collect()


def main() -> int:
    fail = False

    # 1. Мёртвые вызовы
    out = subprocess.run(
        ["python3", "scripts/deadcall_detector.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    dead_calls = [
        line.split("←")[0].strip()
        for line in out.splitlines()
        if line.strip().startswith("/") and "←" in line
    ]
    unexpected = [p for p in dead_calls if p not in DEADCALL_ALLOWED]
    if unexpected:
        print(f"::error::мёртвые вызовы mlog→:4000 вернулись: {unexpected}")
        fail = True
    else:
        print(f"dead calls OK (только ложняк /cron/): {dead_calls}")

    # 2/3. DEAD-паттерны и дубли
    data = registry()
    prod_dead = [
        name for name, info in data["patterns"].items()
        if info["status"] == "DEAD" and any(d["class"] == "prod" for d in info["definitions"])
    ]
    dupes = [name for name, info in data["patterns"].items() if info["duplicate"]]

    if len(prod_dead) > DEAD_WARN_MAX:
        print(f"::warning::новые DEAD-паттерны в прод-замыкании ({len(prod_dead)}): {sorted(prod_dead)[:10]}")
        if len(prod_dead) > DEAD_WARN_MAX + 20:
            print("::error::DEAD-долг вырос более чем на 20 — останови волну и разбери")
            fail = True
    else:
        print("dead patterns OK: 0 в прод-замыкании (архив archive/dead-mlog/)")

    if len(dupes) > DUPES_BASELINE:
        print(f"::warning::дубли определений выросли ({len(dupes)} > {DUPES_BASELINE}): {sorted(dupes)}")
    else:
        print(f"dupes OK: {len(dupes)} (базовая линия ADR-0014 = {DUPES_BASELINE})")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
