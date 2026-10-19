#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unicode-гигиена публикаций: чекер скрытых символов REMOVABLE/REVIEW (наряд #578).

Классы символов — из Shelter-Humanizer, src/shelter_humanizer/unicode_check.py
@ 008ae35, MIT. Дисклеймер источника перенесён дословно по смыслу: это
ограниченная инспекция русской прозы, НЕ детектор ИИ-текста и НЕ полная
реализация UTS #39.

Политика (A.2 наряда #578):
- REMOVABLE — удалять; --fix удаляет ТОЛЬКО их;
- REVIEW — флаговать человеку: bidi-метки и изоляторы легитимны в RTL-цитатах,
  автоудаление запрещено;
- отчёт не называет текст «чистым» — формулировка вердикта:
  «REMOVABLE найдено/удалено N, REVIEW требует взгляда M»;
- двухколейность #577: по машиночитаемым артефактам офиса (наряды, worklog,
  якоря «файл:строка») --fix без явного запроса владельца не запускать.

Exit codes: 0 — REMOVABLE не найдено или все удалены --fix;
            1 — найдены REMOVABLE (в режиме сканирования);
            2 — ошибка запуска (нет пути, файл не читается).
REVIEW на exit code не влияет.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REMOVABLE = {
    "\u200b": "Пробел нулевой ширины",
    "\u2060": "Невидимый соединитель слов",
    "\ufeff": "BOM / невидимый знак внутри текста",
    "\u00ad": "Мягкий перенос",
    "\u202a": "Управление направлением текста",
    "\u202b": "Управление направлением текста",
    "\u202c": "Управление направлением текста",
    "\u202d": "Переопределение направления текста",
    "\u202e": "Переопределение направления текста",
}

REVIEW = {
    "\u200e": "Метка направления слева направо",
    "\u200f": "Метка направления справа налево",
    "\u061c": "Арабская метка направления",
    "\u2066": "Изолятор направления текста",
    "\u2067": "Изолятор направления текста",
    "\u2068": "Изолятор направления текста",
    "\u2069": "Конец изолятора направления",
    "\u180e": "Монгольский разделитель",
    "\u2800": "Пустой символ Брайля",
    "\u3164": "Корейский заполнитель",
    "\u115f": "Корейский заполнитель",
    "\u1160": "Корейский заполнитель",
    "\ufffd": "Символ замены: исходный знак мог быть потерян при декодировании",
    "\u034f": "Невидимый соединитель комбинируемых знаков",
}

DEFAULT_EXTS = {".md", ".txt", ".html", ".htm"}
CONTEXT = 30


def _u(code: str) -> str:
    return "U+{:04X}".format(ord(code))


def _context(text: str, pos: int) -> str:
    lo = max(0, pos - CONTEXT)
    hi = min(len(text), pos + CONTEXT + 1)
    return text[lo:hi].replace("\n", "\\n").replace("\r", "\\r")


def _line_col(text: str, pos: int) -> tuple[int, int]:
    line = text.count("\n", 0, pos) + 1
    col = pos - (text.rfind("\n", 0, pos) + 1) + 1
    return line, col


def scan_text(text: str) -> dict:
    """Найти REMOVABLE/REVIEW вхождения: кодпоинт, имя, строка:колонка, контекст."""
    removable, review = [], []
    for pos, ch in enumerate(text):
        entry = {
            "codepoint": _u(ch),
            "line": _line_col(text, pos)[0],
            "col": _line_col(text, pos)[1],
            "context": _context(text, pos),
        }
        if ch in REMOVABLE:
            entry["name"] = REMOVABLE[ch]
            removable.append(entry)
        elif ch in REVIEW:
            entry["name"] = REVIEW[ch]
            review.append(entry)
    return {"removable": removable, "review": review}


def collect_files(paths: list[str], exts: set[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(
                f for f in sorted(p.rglob("*"))
                if f.is_file() and f.suffix.lower() in exts
            )
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(f"путь не найден: {p}")
    seen, unique = set(), []
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def strip_removable(text: str) -> tuple[str, int]:
    cleaned = "".join(ch for ch in text if ch not in REMOVABLE)
    return cleaned, len(text) - len(cleaned)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Чекер скрытых Unicode-символов для публикаций (наряд #578)")
    parser.add_argument("paths", nargs="+", help="файлы или каталоги")
    parser.add_argument("--fix", action="store_true",
                        help="удалить только REMOVABLE; REVIEW не трогается")
    parser.add_argument("--json", action="store_true", help="JSON-вывод для пайплайнов")
    parser.add_argument("--ext", default=",".join(sorted(DEFAULT_EXTS)),
                        help="расширения для обхода каталогов, через запятую")
    args = parser.parse_args(argv)

    exts = {e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
            for e in args.ext.split(",") if e.strip()}
    try:
        files = collect_files(args.paths, exts)
    except FileNotFoundError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    if not files:
        print("ОШИБКА: текстовые файлы не найдены", file=sys.stderr)
        return 2

    total_removed, total_review, errors = 0, 0, []
    report_files = []
    for path in files:
        try:
            text = read_text(path)
        except (UnicodeDecodeError, OSError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        found = scan_text(text)
        n_rem, n_rev = len(found["removable"]), len(found["review"])
        total_review += n_rev
        entry = {
            "path": str(path),
            "removable": found["removable"],
            "review": found["review"],
            "removable_count": n_rem,
            "review_count": n_rev,
        }
        if args.fix and n_rem:
            cleaned, removed = strip_removable(text)
            path.write_text(cleaned, encoding="utf-8", newline="")
            entry["removed"] = removed
            total_removed += removed
        report_files.append(entry)

    if args.fix:
        verdict = f"REMOVABLE удалено {total_removed}, REVIEW требует взгляда {total_review}"
    else:
        verdict = (f"REMOVABLE найдено {sum(f['removable_count'] for f in report_files)}, "
                   f"REVIEW требует взгляда {total_review}")

    if args.json:
        print(json.dumps({
            "verdict": verdict,
            "files": report_files,
            "errors": errors,
        }, ensure_ascii=False, indent=2))
    else:
        for entry in report_files:
            if entry["removable_count"] or entry["review_count"]:
                print(f"{entry['path']}: REMOVABLE={entry['removable_count']} "
                      f"REVIEW={entry['review_count']}")
                for item in entry["removable"] + entry["review"]:
                    print(f"  {item['codepoint']} {item['name']} "
                          f"@ {item['line']}:{item['col']} …{item['context']}…")
        for err in errors:
            print(f"ПРЕДУПРЕЖДЕНИЕ (файл пропущен): {err}", file=sys.stderr)
        print(verdict)

    if errors:
        return 2
    if not args.fix and sum(f["removable_count"] for f in report_files):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
