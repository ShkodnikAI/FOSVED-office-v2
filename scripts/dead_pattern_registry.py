#!/usr/bin/env python3
"""Реестр мёртвых паттернов mlog (#449 A.1) — воспроизводимая фактура для решений владельца.

НАЗНАЧЕНИЕ
    Скрипт НЕ удаляет и не изменяет код. Он строит реестр определений паттернов
    mlog по подсистемам и классифицирует каждый по фактической достижимости:

      DEAD        — 0 вызовов в рабочем коде, 0 в тестах, 0 упоминаний
                    вне определений (код/конфиг/скрипты/доки не упоминают).
      TEST_ONLY   — вызовы только в тестовых .mlog (test_*.mlog).
      STRING_ONLY — 0 кодовых вызовов, но имя упоминается в строках/конфиге/
                    скриптах — ручная проверка (возможна динамическая диспетчеризация).
      DOC_ONLY    — упоминания только в прозаических .md (docs/, *.md корня).
      ALIVE       — есть кодовый вызов в рабочем коде.

    Отдельно фиксируются дубли определений (одно имя в 2+ файлах — #449 A.2)
    и паттерны в файлах вне import-замыкания app.mlog (недостижимы из прода).

МЕТОД (воспроизводимость)
    1. Файлы: все *.mlog репозитория (корень, dept/, tests/, library/).
    2. Прод-путь: транзитивное замыкание `import X` от app.mlog. mlog-импорт
       `import dept/utils` -> dept/utils.mlog.
    3. Классификация файлов: prod (в замыкании), test (test_*.mlog), harness
       (dogfood_staging.mlog — производный артефакт, не прод), probe (probe*.mlog),
       unimported (остальные).
    4. Определения: ^\\s*pattern\\s+ИМЯ\\s*\\( в каждом файле (файл:строка).
    5. Лексер вызовов: посимвольный проход — двойные кавычки с \\-экранированием
       (строки mlog), // комментарии вне строк (URL "https://" не ломает разбор).
       Вызов = \\bИМЯ\\s*\\( вне строк/комментариев, не на строке определения.
    6. Упоминания (консервативная перепроверка, чтобы не похоронить живое):
       текстовый поиск ИМЯ по .mlog/.py/.json/.sh/.yml/.toml кода и конфига
       (data/, memories/, forge-tmp/, uploads/, node_modules/, .git исключены),
       отдельно по .md-прозе. Упоминание строки не «оживляет» паттерн — оно
       лишь переводит его из DEAD в STRING_ONLY для ручной проверки.

    Консервативизм: сомнение трактуется в пользу ЖИВОГО (меньше ложных «мёртвых»).
    Числа могут отличаться от аудита 2026-09-30 (иной набор файлов) — метод выше.

ЗАПУСК
    python3 scripts/dead_pattern_registry.py            # текстовый реестр
    python3 scripts/dead_pattern_registry.py --json     # машинный вывод
    python3 scripts/dead_pattern_registry.py --subsystem osp   # фильтр по файлу

Exit code: 0 всегда (реестр — не гейт). A.4 (CI-барьер по новым паттернам) —
отдельная работа после решений владельца по группам.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Каталоги/файлы, исключаемые из упоминаний (рантайм-данные, артефакты, чужие деревья)
EXCLUDE_DIRS = {
    ".git", "node_modules", "data", "data_smoke", "memories", "forge-tmp",
    "uploads", "__pycache__", ".venv", "venv", "archive",
}
CODE_EXTS = {".mlog", ".py", ".json", ".sh", ".yml", ".yaml", ".toml"}
DOC_EXTS = {".md", ".txt"}

PATTERN_DEF_RE = re.compile(r"^\s*pattern\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_/.-]+)\s*$", re.MULTILINE)
CALL_TOKEN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
DEF_CONTEXT_RE = re.compile(r"\bpattern\s*$")


# ── лексер: код без строк и комментариев ─────────────────────────────────────
def strip_strings_and_comments(src: str) -> tuple[str, list[tuple[int, int]]]:
    """Вернуть (исходник со строками и //комментариями, заменёнными пробелами).

    Возвращает также список (start, end) диапазонов строковых литералов —
    для подсчёта строковых упоминаний отдельно от кода.
    """
    out = []
    spans = []
    i, n = 0, len(src)
    in_string = False  # остаётся True только при незакрытой строке до EOF

    while i < n:
        ch = src[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append(" ")
                i += 1
                continue
            out.append(" " if ch != "\n" else "\n")
            i += 1
            continue
        # вне строки
        if ch == '"':
            start = i
            i += 1
            closed = False
            # докручиваем строку до конца, чтобы зафиксировать span
            while i < n:
                if src[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if src[i] == '"':
                    i += 1
                    closed = True
                    break
                i += 1
            spans.append((start, i))
            out.append(" " * (i - start))
            in_string = not closed  # незакрытая строка: хвост файла — строка
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            # комментарий до конца строки
            j = src.find("\n", i)
            if j == -1:
                j = n
            out.append(" " * (j - i))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out), spans


def string_spans_text(src: str, spans: list[tuple[int, int]]) -> str:
    """Текст всех строковых литералов одной строкой (для упоминаний)."""
    return "\n".join(src[a:b] for a, b in spans)


# ── файлы и замыкание ────────────────────────────────────────────────────────
def discover_mlog_files() -> list[Path]:
    files = sorted(REPO_ROOT.glob("*.mlog"))
    for sub in ("dept", "tests", "library", "miniapp", "lib", "config"):
        d = REPO_ROOT / sub
        if d.is_dir():
            files.extend(sorted(d.glob("*.mlog")))
    return files


def classify_file(path: Path, prod_closure: set[Path]) -> str:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if path in prod_closure:
        return "prod"
    if path.name.startswith("test_"):
        return "test"
    if path.name.startswith("probe"):
        return "probe"
    if path.name.startswith("dogfood"):
        return "harness"
    return "unimported"  # существует, но в замыкание app.mlog не входит


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
            cand.append(target)  # на случай явного .mlog
            for c in cand:
                if c in by_posix:
                    stack.append(by_posix[c])
                    break
                # mlog-импорт может быть относительным (dept/X из dept/)
                alt = (cur.parent / c).relative_to(REPO_ROOT).as_posix()
                if alt in by_posix:
                    stack.append(by_posix[alt])
                    break
    return seen


# ── сбор реестра ─────────────────────────────────────────────────────────────
def collect() -> dict:
    all_files = discover_mlog_files()
    prod_closure = build_prod_closure(REPO_ROOT / "app.mlog", all_files)

    file_class = {p: classify_file(p, prod_closure) for p in all_files}

    # определения
    defs: dict[str, list[dict]] = {}  # name -> [{file, line, class}]
    for p in all_files:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ln, line in enumerate(src.splitlines(), 1):
            m = PATTERN_DEF_RE.match(line)
            if m:
                defs.setdefault(m.group(1), []).append(
                    {"file": p.relative_to(REPO_ROOT).as_posix(),
                     "line": ln, "class": file_class[p]}
                )

    # кодовые вызовы: prod/harness/probe/unimported-файлы отдельно от тестов
    code_texts: dict[str, dict[Path, str]] = {"code": {}, "test": {}}
    string_text_by_file: dict[Path, str] = {}
    for p in all_files:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        stripped, spans = strip_strings_and_comments(src)
        cls = file_class[p]
        bucket = "test" if cls == "test" else "code"
        code_texts[bucket][p] = stripped
        if spans:
            string_text_by_file[p] = string_spans_text(src, spans)

    # ОДИН проход по каждому файлу: все токены-вызовы NAME( вне строк/комментов,
    # кроме строк определения ("pattern NAME("). Потом lookup O(1) на имя.
    def build_call_index(texts) -> dict:
        index: dict[str, int] = {}
        for _p, text in texts.items():
            for line in text.splitlines():
                for m in CALL_TOKEN_RE.finditer(line):
                    if DEF_CONTEXT_RE.search(line[: m.start()]):
                        continue  # строка определения, не вызов
                    name = m.group(1)
                    index[name] = index.get(name, 0) + 1
        return index

    call_index_code = build_call_index(code_texts["code"])
    call_index_test = build_call_index(code_texts["test"])

    # упоминания вне .mlog-кода: код/конфиг/скрипты (консервативная перепроверка)
    mention_corpus_code: list[tuple[str, str]] = []  # (relpath, text)
    mention_corpus_docs: list[tuple[str, str]] = []
    for p in REPO_ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(REPO_ROOT).parts):
            continue
        ext = p.suffix.lower()
        if ext in CODE_EXTS and ext != ".mlog":
            try:
                mention_corpus_code.append(
                    (p.relative_to(REPO_ROOT).as_posix(), p.read_text(encoding="utf-8", errors="replace"))
                )
            except OSError:
                pass
        elif ext in DOC_EXTS:
            try:
                mention_corpus_docs.append(
                    (p.relative_to(REPO_ROOT).as_posix(), p.read_text(encoding="utf-8", errors="replace"))
                )
            except OSError:
                pass

    string_corpus = [
        (p.relative_to(REPO_ROOT).as_posix(), t) for p, t in string_text_by_file.items()
    ]

    registry = {}
    for name, sites in sorted(defs.items()):
        calls_prod = call_index_code.get(name, 0)
        calls_test = call_index_test.get(name, 0)

        str_hits = [f for f, t in string_corpus if re.search(re.escape(name), t)]
        py_hits = [f for f, t in mention_corpus_code if re.search(r"\b%s\b" % re.escape(name), t)]
        doc_hits = [f for f, t in mention_corpus_docs if re.search(r"\b%s\b" % re.escape(name), t)]

        if calls_prod > 0:
            status = "ALIVE"
        elif calls_test > 0:
            status = "TEST_ONLY"
        elif str_hits or py_hits:
            status = "STRING_ONLY"
        elif doc_hits:
            status = "DOC_ONLY"
        else:
            status = "DEAD"

        # Дубли считаем ТОЛЬКО по прод-файлам (замыкание app.mlog): копии в
        # тестовых фикстурах — не конфликт неймспейса, а часть теста (#449 A.2).
        prod_files = {s["file"] for s in sites if s["class"] == "prod"}
        test_files = {s["file"] for s in sites if s["class"] == "test"}
        dup = len(prod_files) > 1
        test_copy = not dup and bool(test_files)
        in_unimported = any(s["class"] in ("unimported", "probe") for s in sites)

        registry[name] = {
            "status": status,
            "calls_prod": calls_prod,
            "calls_test": calls_test,
            "definitions": sites,
            "duplicate": dup,
            "test_copy": test_copy,
            "in_unimported_file": in_unimported,
            "string_refs": sorted(str_hits)[:5],
            "py_refs": sorted(py_hits)[:5],
            "doc_refs": sorted(doc_hits)[:5],
        }

    return {
        "files": {p.relative_to(REPO_ROOT).as_posix(): file_class[p] for p in all_files},
        "patterns": registry,
        "totals": {
            "files_total": len(all_files),
            "prod_files": sum(1 for c in file_class.values() if c == "prod"),
            "patterns_total": len(defs),
        },
    }


# ── вывод ────────────────────────────────────────────────────────────────────
def render_text(data: dict, subsystem_filter: str | None) -> str:
    lines = []
    t = data["totals"]
    lines.append("# Реестр мёртвых паттернов mlog (#449 A.1)")
    lines.append("")
    lines.append(f"Файлов .mlog: {t['files_total']} (прод-замыкание app.mlog: {t['prod_files']}); "
                 f"определений паттернов: {t['patterns_total']}")
    lines.append("")
    reg = data["patterns"]

    by_status: dict[str, list[str]] = {}
    for name, info in reg.items():
        by_status.setdefault(info["status"], []).append(name)

    lines.append("## Сводка по статусам")
    for st in ("ALIVE", "TEST_ONLY", "STRING_ONLY", "DOC_ONLY", "DEAD"):
        names = by_status.get(st, [])
        lines.append(f"- **{st}**: {len(names)}")
    dups = [n for n, i in reg.items() if i["duplicate"]]
    test_copies = [n for n, i in reg.items() if i.get("test_copy")]
    lines.append(f"- **Дубли определений в прод-файлах** (имя в 2+ файлах замыкания app.mlog): {len(dups)}"
                 + (": " + ", ".join(sorted(dups)) if dups else ""))
    lines.append(f"- **Копии определений только в тестовых фикстурах**: {len(test_copies)} (не конфликт прод-неймспейса)")
    unimported = [n for n, i in reg.items() if i["in_unimported_file"]]
    lines.append(f"- **Определения в файлах вне прод-замыкания** (недостижимы из app.mlog): {len(unimported)}")
    lines.append("")

    lines.append("## DEAD — кандидаты в архив (0 вызовов, 0 упоминаний)")
    lines.append("")
    dead = {n: reg[n] for n in by_status.get("DEAD", [])}
    # группировка по файлу определения (подсистема)
    by_file: dict[str, list[str]] = {}
    for name, info in sorted(dead.items()):
        primary = sorted(info["definitions"], key=lambda s: s["file"])[0]["file"]
        by_file.setdefault(primary, []).append(name)
    if not by_file:
        lines.append("(пусто)")
    for f in sorted(by_file):
        lines.append(f"### {f} — {len(by_file[f])}")
        lines.append(", ".join(sorted(by_file[f])))
        lines.append("")
    lines.append("")

    for st in ("TEST_ONLY", "STRING_ONLY", "DOC_ONLY"):
        names = by_status.get(st, [])
        lines.append(f"## {st} — {len(names)} (ручная проверка)")
        lines.append("")
        for name in sorted(names):
            info = reg[name]
            extra = ""
            if info["string_refs"]:
                extra = " строки: " + ", ".join(info["string_refs"][:3])
            if info["py_refs"]:
                extra += " py/json: " + ", ".join(info["py_refs"][:3])
            if info["doc_refs"]:
                extra += " md: " + ", ".join(info["doc_refs"][:3])
            where = ", ".join(s["file"] for s in info["definitions"])
            lines.append(f"- {name} [{where}]{extra}")
        lines.append("")

    if subsystem_filter:
        lines.append(f"## Фильтр подсистемы: {subsystem_filter}")
        lines.append("")
        for name, info in sorted(reg.items()):
            files = {s["file"] for s in info["definitions"]}
            if any(subsystem_filter in f for f in files):
                lines.append(f"- {name}: {info['status']} "
                             f"(prod={info['calls_prod']}, test={info['calls_test']})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Реестр мёртвых паттернов mlog (#449 A.1)")
    ap.add_argument("--json", action="store_true", help="машинный JSON-вывод")
    ap.add_argument("--subsystem", help="фильтр по подстроке файла определения")
    args = ap.parse_args()

    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_text(data, args.subsystem))
    return 0


if __name__ == "__main__":
    sys.exit(main())
