"""Наряд #442 A.3: тест-барьер на незащищённые mlog-роуты.

Новый mlog-роут в app.mlog обязан вызывать проверку доступа в теле
(query_param("secret") / query_param("t") / RequireInternalAuth /
ReposAccessGuard) и отвечать 401/403, либо попасть в whitelist
аудитора ("/", "/health", "/version", "/webhook/telegram").

Барьер двухуровневый:
  1. строгий CLI-аудитор scripts/check_route_guards.py (exit 0 — зелёный,
     1 — есть незащищённые роуты) — тот же файл может гонять CI-джоба;
  2. прямой ассерт: 8 роутов /repos* содержат ReposAccessGuard()
     первой строкой тела (регресс именно защищаемой зоны №442).

Аудитор строгий нарочно: на новом незащищённом роуте тест падает.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "app.mlog"
AUDITOR = REPO_ROOT / "scripts" / "check_route_guards.py"

REPOS_ROUTES = [
    "/repos",
    "/repos/project",
    "/repos/task",
    "/repos/task/preview-up",
    "/repos/task/preview-down",
    "/repos/task/decide",
    "/repos/repo",
    "/repos/file",
]


def _route_bodies(src: str, path: str):
    """Тела всех route-блоков с данным путём (обычно один)."""
    from scripts.check_route_guards import parse_routes

    return [body for _line, p, _m, body in parse_routes(src) if p == path]


def test_app_mlog_exists():
    assert APP.exists(), "app.mlog не найден в корне репозитория"


def test_auditor_script_exists():
    assert AUDITOR.exists(), "scripts/check_route_guards.py не найден"


def test_auditor_green_on_current_app():
    """Строгий аудит: 0 незащищённых роутов (exit 0)."""
    proc = subprocess.run(
        [sys.executable, str(AUDITOR), str(APP)],
        capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"аудитор нашёл незащищённые роуты (rc={proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "OK" in proc.stdout


def test_auditor_fails_on_unprotected_route(tmp_path):
    """Мутационная самопроверка аудитора: роут без гварда → exit 1."""
    src = APP.read_text(encoding="utf-8")
    mutated = src.replace(
        'mlogserver {',
        'mlogserver {\n  route "/test442/unprotected" method=GET {\n'
        '    return respond("hi")\n  }\n',
        1,
    )
    assert mutated != src, "не удалось вставить мутационный роут"
    mutated_app = tmp_path / "app.mlog"
    mutated_app.write_text(mutated, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(AUDITOR), str(mutated_app)],
        capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 1
    assert "/test442/unprotected" in proc.stdout


@pytest.mark.parametrize("path", REPOS_ROUTES)
def test_repos_routes_guarded(path):
    """Зона №442: каждый /repos* роут вызывает ReposAccessGuard и отвечает 403."""
    src = APP.read_text(encoding="utf-8")
    bodies = _route_bodies(src, path)
    assert bodies, f"роут {path} исчез из app.mlog — восстановить или пересмотреть тест"
    for body in bodies:
        assert "ReposAccessGuard(" in body, (
            f"роут {path} не вызывает ReposAccessGuard — FORGE открыт интернету "
            f"(регресс наряда #442)"
        )
        assert "403" in body, f"роут {path} не отвечает 403 при отказе гварда"
        # гвард обязан стоять ДО любого эффекта: query/Forge* после return-гварда
        guard_pos = body.find("ReposAccessGuard(")
        tail = body[guard_pos:]
        assert tail.find("return respond(\"403 Forbidden\")") > -1, (
            f"роут {path}: нет раннего return 403 после гварда"
        )


def test_whitelist_routes_present():
    """Whitelist-роуты на месте (если исчезли — аудитор охраняет лишнее)."""
    src = APP.read_text(encoding="utf-8")
    for path in ("/", "/health", "/version", "/webhook/telegram"):
        assert _route_bodies(src, path), f"whitelist-роут {path} отсутствует"
