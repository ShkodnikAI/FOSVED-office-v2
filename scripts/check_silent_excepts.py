#!/usr/bin/env python3
"""FO-007: Проверка молчаливых except-блоков в llm_proxy.py.

Политика (наряд FO-007, issue #67): молчаливый `pass` в except запрещён —
минимум log.warning с тегом; для внешних вызовов — событие в error_log.

Exit code 0 — нарушений нет; 1 — найдены молчаливые except (CI падает).
"""

import re
import sys
from pathlib import Path

TARGETS = ["llm_proxy.py"]

# Допустимые «тихие» варианты: глушение конкретных, заведомо безобидных
# исключений ЗАПРЕЩЕНО по умолчанию. Исключения перечисляются здесь явно
# с комментарием-обоснованием (файл:строка в комментарии не нужен —
# контекст ищется по соседнему тексту).
ALLOWED_CONTEXTS = []


def find_silent_excepts(src: str):
    """Вернуть список (line_no, snippet) молчаливых except-блоков.

    Молчаливый = тело блока (до следующего except/finally/else на том же
    уровне или конца блока) состоит только из pass/.../ комментариев.
    """
    lines = src.splitlines()
    results = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)except\b[^:]*:\s*$", lines[i])
        if not m:
            # однострочный `except X: pass`
            m1 = re.match(r"^\s*except\b[^:]*:\s*pass\s*(#.*)?$", lines[i])
            if m1:
                results.append((i + 1, lines[i].strip()))
            i += 1
            continue
        indent = len(m.group(1))
        body = []
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if line.strip() == "":
                body.append(line)
                j += 1
                continue
            cur_indent = len(line) - len(line.lstrip())
            if cur_indent <= indent:
                break
            body.append(line)
            j += 1
        meaningful = [l.strip() for l in body if l.strip() and not l.strip().startswith("#")]
        if meaningful and all(l == "pass" or l == "..." for l in meaningful):
            results.append((i + 1, lines[i].strip()))
        i = j if j > i + 1 else i + 1
    return results


def main() -> int:
    failures = []
    for target in TARGETS:
        path = Path(__file__).resolve().parent.parent / target
        src = path.read_text(encoding="utf-8")
        for line_no, snippet in find_silent_excepts(src):
            context = src.splitlines()[max(0, line_no - 4) : line_no + 2]
            allowed = any(ctx in context for ctx in ALLOWED_CONTEXTS)
            if not allowed:
                failures.append(f"{target}:{line_no}: {snippet}")
    if failures:
        print("FAIL: found silent except blocks (policy FO-007: log.warning required)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK: no silent except blocks in", ", ".join(TARGETS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
