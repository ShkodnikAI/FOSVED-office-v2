#!/usr/bin/env python3
"""#450: non-root через сброс привилегий в entrypoint (замечание 1 аудита #451).

Инцидент-контекст: PR #458 вернул non-root (USER office) — но постоянный диск
Render монтируется ПОВЕРХ /var/data при запуске, chown в Dockerfile действует
только на слой образа, база на диске создана root → риск readonly database.
Хотфикс #460 снял USER целиком. Контракт этого гварда:

  1. Контейнер стартует от root, но entrypoint ПЕРВЫМ делом делает chown
     персистентных путей (DATABASE_PATH, /var/forge) и exec gosu office.
  2. gosu установлен в образе.
  3. USER office в Dockerfile не раскомментирован (сброс — в entrypoint,
     иначе chown диска невозможно выполнить).
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_entrypoint_has_root_bootstrap_block():
    assert 'if [ "$(id -u)" = "0" ]; then' in ENTRYPOINT, (
        "entrypoint: нет root-bootstrap блока — постоянный диск Render "
        "останется root-owned, офис не сможет писать в базу (#450)"
    )


def test_entrypoint_chown_covers_persistent_paths():
    chown_line = next(
        l for l in ENTRYPOINT.splitlines() if l.strip().startswith("chown -R office:office")
    )
    assert "${DATABASE_PATH:-/var/data}" in chown_line, "chown не покрывает DATABASE_PATH"
    assert "/var/forge" in chown_line, "chown не покрывает FORGE"


def test_entrypoint_drops_privileges_via_gosu():
    assert 'exec gosu office bash "$0"' in ENTRYPOINT, (
        "нет сброса привилегий: процессы поедут от root — non-root контракт #450 нарушен"
    )
    # bootstrap-блок обязан быть ПЕРЕД всей бут-логикой (VERSION, seed, backup…)
    bootstrap_pos = ENTRYPOINT.index('if [ "$(id -u)" = "0" ]')
    assert bootstrap_pos < ENTRYPOINT.index("=== Fosved Office v2 Starting ==="), (
        "root-bootstrap не первая логика entrypoint: часть бута уедет от root"
    )


def test_gosu_installed_in_image():
    # apt-get install разбит на строки с продолжением `\` — берём весь блок
    # от apt-get install до очистки списков и ищем gosu в нём целиком
    lines = DOCKERFILE.splitlines()
    block, in_block = [], False
    for line in lines:
        if "apt-get install" in line:
            in_block = True
        if in_block:
            block.append(line)
            if "rm -rf /var/lib/apt/lists" in line:
                break
    assert any("gosu" in l for l in block), "gosu не установлен в образе"


def test_dockerfile_user_office_not_uncommented():
    active = [
        l.strip()
        for l in DOCKERFILE.splitlines()
        if l.strip().startswith("USER ")
    ]
    assert "USER office" not in active, (
        "USER office активен — chown персистентного диска от root в entrypoint "
        "не сможет выполниться (сброс привилегий — контракт #450/замечание 1)"
    )


def test_entrypoint_syntax_valid():
    rc = subprocess.run(["bash", "-n", str(ROOT / "entrypoint.sh")], capture_output=True)
    assert rc.returncode == 0, f"entrypoint.sh: синтаксис bash сломан: {rc.stderr.decode()}"
