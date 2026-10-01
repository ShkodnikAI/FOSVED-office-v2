#!/usr/bin/env python3
"""Наряд #442 A.3: строгий аудит guard-вызовов mlog-роутов в app.mlog.

Политика: каждый `route` в mlogserver-блоке обязан вызывать проверку
доступа в теле, кроме явного whitelist:
  "/"            — публичный статус;
  "/health"      — liveness;
  "/version"     — версия/коммит;
  "/webhook/telegram" — Telegram (собственная проверка секрета header'ом).

Признаки guard-вызова в теле роута (любой из):
  query_param("secret")     — cron/expert-гвард (H(CRON_SECRET), обе формы);
  query_param("t")          — веб-гвард владельца (ReposAccessGuard, №442);
  RequireInternalAuth()     — внутренний гвард (INTERNAL_API_TOKEN);
  ReposAccessGuard()        — явный вызов веб-гварда №442.

Реакция на отказ обязана быть в теле: подстрока "403" или "401".

Exit code 0 — все роуты защищены; 1 — есть незащищённые (CI падает);
2 — app.mlog не найден / не распарсился.

Использование:
  python3 scripts/check_route_guards.py [путь-к-app.mlog]
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APP = REPO_ROOT / "app.mlog"

WHITELIST = {"/", "/health", "/version", "/webhook/telegram"}

GUARD_MARKERS = (
    'query_param("secret")',
    'query_param("t")',
    "RequireInternalAuth(",
    "ReposAccessGuard(",
)

ROUTE_RE = re.compile(r'route\s+"([^"]+)"\s+method=(\w+)\s*\{')


def parse_routes(src: str):
    """(line_no, path, method, body) для каждого route-блока верхнего уровня.

    Скобки считаются честно: вложенные { } (if/each/pattern-вызовы)
    увеличивают глубину, конец тела — закрывающая скобка нулевого уровня.
    """
    lines = src.splitlines()
    routes = []
    i = 0
    while i < len(lines):
        m = ROUTE_RE.search(lines[i])
        if m:
            start = i
            depth = 1
            j = i
            while depth > 0 and j + 1 < len(lines):
                j += 1
                depth += lines[j].count("{") - lines[j].count("}")
            body = "\n".join(lines[start + 1:j + 1])
            routes.append((start + 1, m.group(1), m.group(2), body))
            i = j
        i += 1
    return routes


def audit(app_path: Path):
    """Возвращает список (path, method, line) незащищённых роутов."""
    if not app_path.exists():
        raise FileNotFoundError(f"{app_path} не найден")
    src = app_path.read_text(encoding="utf-8")
    routes = parse_routes(src)
    if not routes:
        raise ValueError("route-блоки не распознаны — файл не тот?")
    open_routes = []
    for line_no, path, method, body in routes:
        if path in WHITELIST:
            continue
        has_guard = any(mk in body for mk in GUARD_MARKERS)
        has_rejection = ("403" in body) or ("401" in body)
        if not (has_guard and has_rejection):
            open_routes.append((path, method, line_no))
    return open_routes


def main() -> int:
    app_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_APP
    try:
        open_routes = audit(app_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ROUTE-GUARDS AUDIT: FAIL ({e})", file=sys.stderr)
        return 2
    if open_routes:
        print("ROUTE-GUARDS AUDIT: FAIL — незащищённые mlog-роуты (№442 A.3):")
        for path, method, line_no in sorted(open_routes, key=lambda r: r[2]):
            print(f"  line {line_no}: {method} {path}")
        print(
            "Каждый route обязан вызывать гвард (query_param(\"secret\") / "
            "query_param(\"t\") / RequireInternalAuth / ReposAccessGuard) "
            "и отвечать 401/403, либо быть в whitelist: "
            + ", ".join(sorted(WHITELIST))
        )
        return 1
    total = len(parse_routes(app_path.read_text(encoding="utf-8")))
    print(f"ROUTE-GUARDS AUDIT: OK — все {total} mlog-роутов защищены или в whitelist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
