#!/usr/bin/env python3
"""Детектор мёртвых вызовов mlog→Flask (системная проверка, наряд #365).

Ищет все http_post/http_get("http://127.0.0.1:4000/...") в app.mlog и
dept/*.mlog и сверяет каждый путь с реально зарегистрированными Flask-роутами
proxy/*.py + llm_proxy.py. Пути с <param>-сегментами сопоставляются посегментно.

Выход: список мёртвых вызовов (404-пути). Пустой список = все вызовы живы.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PY_FILES = [
    "llm_proxy.py",
    "proxy/routes_core.py", "proxy/routes_tail.py", "proxy/routes_sched.py",
    "proxy/routes_admin.py", "proxy/voice.py", "proxy/guardian.py",
    "proxy/lz_github.py", "proxy/chain_parallel.py",
]
MLOG_FILES = ["app.mlog"] + sorted(str(p) for p in (REPO_ROOT / "dept").glob("*.mlog"))

ROUTE_RE = re.compile(r'@app\.(?:route|get|post|put|delete)\(\s*["\']([^"\']+)["\']')
CALL_RE = re.compile(r'http://127\.0\.0\.1:4000(/[A-Za-z0-9_\-/<>.]+)')


def flask_routes():
    routes = set()
    for rel in PY_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for m in ROUTE_RE.finditer(text):
            routes.add(m.group(1))
    return routes


def matches(route, path):
    """Сопоставление конкретного вызова с шаблоном роута (<param> = сегмент)."""
    rp, pp = route.strip("/").split("/"), path.strip("/").split("/")
    if len(rp) != len(pp):
        return False
    return all(seg.startswith("<") or seg == actual for seg, actual in zip(rp, pp))


def mlog_calls():
    calls = {}
    for rel in MLOG_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for m in CALL_RE.finditer(text):
            calls.setdefault(m.group(1), []).append(rel)
    return calls


def main():
    routes = flask_routes()
    calls = mlog_calls()
    dead = {}
    for path, where in sorted(calls.items()):
        if not any(matches(r, path) for r in routes):
            dead[path] = where
    print(f"Flask-роутов: {len(routes)}; вызовов mlog→:4000: {len(calls)}")
    if dead:
        print("МЁРТВЫЕ ВЫЗОВЫ (роута во Flask нет):")
        for path, where in dead.items():
            print(f"  {path}  ←  {', '.join(where)}")
        sys.exit(1)
    print("Мёртвых вызовов нет — все пути живы.")


if __name__ == "__main__":
    main()
