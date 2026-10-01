#!/usr/bin/env python3
"""#449 A.1 (волна D): архивация DEAD-паттернов mlog — решение владельца
2026-10-02 (вариант «в архив», не удаление).

Принципы:
- прод-путь = транзитивное замыкание import от app.mlog (как в реестре);
- DEAD = 0 вызовов, 0 упоминаний (реестр scripts/dead_pattern_registry.py);
- перенос БУКВАЛЬНЫЙ: блок вырезается и вставляется в archive/dead-mlog/ verbatim;
- STRING_ONLY / TEST_ONLY / DOC_ONLY не трогаются (решение владельца);
- идемпотентность: повторный прогон — no-op (DEAD=0).

Инварианты валидации после выполнения:
- bin/mlog check по всем файлам — 0 parse errors;
- bin/mlog audit dept/*.mlog — 0 Category-A;
- полный pytest — 0 failed;
- реестр повторно: ALIVE не изменился, DEAD = 0.

Использование: dead_pattern_archive.py [--execute]  (без флага — dry-run)
"""
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_DIR = REPO_ROOT / "archive" / "dead-mlog"

PATTERN_DEF_RE = re.compile(r"^(\s*)pattern\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

IMPORT_RE = re.compile(r'^\s*import\s+([A-Za-z0-9_./-]+)', re.M)


def discover_mlog_files() -> list[Path]:
    files = sorted(REPO_ROOT.glob("*.mlog"))
    for sub in ("dept", "tests", "library", "miniapp", "lib", "config"):
        d = REPO_ROOT / sub
        if d.is_dir():
            files.extend(sorted(d.glob("*.mlog")))
    return files


def build_prod_closure(entry: Path, all_files: list[Path]) -> set[Path]:
    by_posix = {p.relative_to(REPO_ROOT).as_posix(): p for p in all_files}
    seen: set[Path] = set()
    stack = [entry]
    while stack:
        cur = stack.pop()
        if cur in seen or not cur.exists():
            continue
        seen.add(cur)
        try:
            src = cur.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in IMPORT_RE.finditer(src):
            target = m.group(1)
            cand = []
            if not target.endswith(".mlog"):
                cand.append(target + ".mlog")
            cand.append(target)
            for c in cand:
                if c in by_posix:
                    stack.append(by_posix[c])
                    break
                alt = (cur.parent / c).relative_to(REPO_ROOT).as_posix()
                if alt in by_posix:
                    stack.append(by_posix[alt])
                    break
    return seen


def registry_dead_names() -> set[str]:
    """DEAD-имена из реестра (тот же алгоритм, что scripts/dead_pattern_registry.py)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dead_pattern_registry", REPO_ROOT / "scripts" / "dead_pattern_registry.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = mod.collect()
    return {
        name
        for name, info in data["patterns"].items()
        if info["status"] == "DEAD"
        # DEAD-паттерн определён в прод-замыкании; копии в тестовых фикстурах
        # и файлах вне замыкания — отдельно, их архивируем по месту позже
        and any(d["class"] == "prod" for d in info["definitions"])
    }


def pattern_block_end(lines: list[str], start: int) -> int:
    """Индекс строки, закрывающей паттерн: скобочный баланс {/} вне строковых
    литералов и комментариев. Однострочные паттерны ({...} в def-строке)
    возвращают саму def-строку. Урок первого прогона: грубый поиск `}` в
    колонке 0 рвал живой код вокруг однострочных паттернов-констант."""
    depth = 0
    started = False
    for i in range(start, len(lines)):
        line = lines[i]
        in_str = False
        j = 0
        while j < len(line):
            c = line[j]
            if in_str:
                if c == "\\":
                    j += 1  # пропускаем экранированный символ
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                    started = True
                elif c == "}":
                    depth -= 1
                    if started and depth == 0:
                        return i
                elif c == "/" and line[j + 1: j + 2] == "/":
                    break  # комментарий до конца строки
            j += 1
    return len(lines) - 1


def attached_comment_start(lines: list[str], start: int) -> int:
    """Первый индекс блока примыкающих комментариев над def (не секционные ═-шапки)."""
    first = start
    i = start - 1
    while i >= 0:
        s = lines[i].strip()
        if s.startswith("//") and "═" not in s:
            first = i
            i -= 1
        else:
            break
    return first


def main() -> int:
    execute = "--execute" in sys.argv
    all_files = discover_mlog_files()
    closure = build_prod_closure(REPO_ROOT / "app.mlog", all_files)
    dead = registry_dead_names()
    print(f"DEAD по реестру: {len(dead)}")

    # индекс определений DEAD-паттернов по файлам
    plan: dict[Path, list[tuple[int, int, str]]] = {}
    seen_names: set[str] = set()
    for path in all_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        if path not in closure and not rel.startswith(("app", "dept/")):
            continue  # работаем только по прод-файлам (dept/ + корень)
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = PATTERN_DEF_RE.match(line)
            if not m:
                continue
            name = m.group(2)
            if name in dead and name not in seen_names:
                seen_names.add(name)
                end = pattern_block_end(lines, i)
                first = attached_comment_start(lines, i)
                plan.setdefault(path, []).append((first, end, name))

    total = sum(len(v) for v in plan.values())
    print(f"Найдено блоков к переносу: {total} (DEAD без определения в прод-файлах: {len(dead - seen_names)})")

    # валидация: в каждом блоке РОВНО ОДНА def-строка (иначе вырезка переползла
    # на чужой паттерн — стоп до порчи файлов)
    bad = []
    for path, blocks in plan.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        for first, end, name in blocks:
            seg = lines[first:end + 1]
            def_count = sum(1 for l in seg if PATTERN_DEF_RE.match(l))
            if def_count != 1:
                bad.append((path, name, first, end, def_count))
    if bad:
        for path, name, first, end, cnt in bad:
            print(f"ОШИБКА: {path.relative_to(REPO_ROOT)}: блок {name} ({first + 1}-{end + 1}) содержит {cnt} def")
        return 1

    if not execute:
        for path, blocks in sorted(plan.items()):
            rel = path.relative_to(REPO_ROOT).as_posix()
            for first, end, name in blocks:
                print(f"  {rel}: {name} (строки {first + 1}-{end + 1})")
        print("DRY-RUN: без --execute ничего не изменено")
        return 0

    results: dict[str, list[str]] = {}
    for path, blocks in sorted(plan.items()):
        lines = path.read_text(encoding="utf-8").splitlines()
        # вырезаем снизу вверх, чтобы индексы не плыли
        moved: list[str] = []
        for first, end, name in sorted(blocks, key=lambda b: -b[0]):
            moved = lines[first:end + 1] + moved
            del lines[first:end + 1]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        results.setdefault(rel, []).extend(moved)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for rel, moved in results.items():
        out = ARCHIVE_DIR / rel.replace("/", "__").replace(".mlog", ".mlog")
        body = "\n".join(moved).rstrip()
        digest = hashlib.sha256(body.encode()).hexdigest()[:8]
        header = (
            f"// ═══════════════════════════════════════════════════════════════════════\n"
            f"// АРХИВ DEAD-паттернов из {rel} — #449 A.1, решение владельца 2026-10-02\n"
            f"// (вариант «в архив», история git сохранена; файл НЕ импортируется app.mlog\n"
            f"// и не входит в прод-неймспейс). SHA256 фрагмента: {digest}\n"
            f"// Оживёт потребность — переносить назад осознанно, с вызовом и тестом.\n"
            f"// ═══════════════════════════════════════════════════════════════════════\n\n"
        )
        out.write_text(header + body + "\n", encoding="utf-8")
        print(f"archive: {out.relative_to(REPO_ROOT)} (+{len(moved)} строк)")

    print(f"OK: перенесено {total} паттернов из {len(results)} файлов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
