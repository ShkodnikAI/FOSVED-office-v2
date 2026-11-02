"""Наряд #612 (хвост приёмки #604): идемпотентность миграций боевого app.mlog.

Два старта `bin/mlog serve` дополненной копии app.mlog на ОДНОЙ И ТОЙ ЖЕ
SQLite-БД (форма test_prod_boot.py: profile legacy, env из entrypoint.sh):
  - первый старт — на пустой БД: без `[SQL_ERROR]` для ALTER и без
    «duplicate column name» (каждая колонка добавляется ровно один раз —
    14 идентичных дублей удалены, 45 ALTER под гардом AlterColIfMissing);
  - второй старт — колонки уже есть: гард даёт «skip», в логе нет
    «duplicate column name» (раньше ~20 строк caught-error на каждый старт).
Мутация (проверялась вручную, вывод в PR #): возврат одной строки к сырому
`db_execute("ALTER ...")` делает второй старт красным — «duplicate column
name» возвращается в лог.
"""
import os
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MLOG = ROOT / "bin" / "mlog"
PROFILE_LINE = "profile legacy { egress: permissive_with_audit }"

pytestmark = pytest.mark.skipif(not MLOG.exists() or os.name != "posix", reason="нужен bin/mlog (Linux)")


def _augmented(tmp: pathlib.Path) -> pathlib.Path:
    src = (ROOT / "app.mlog").read_text(encoding="utf-8")
    if not re.search(r"^profile legacy", src, re.M):
        src = PROFILE_LINE + "\n" + src
    out = tmp / "app_serve_candidate.mlog"
    out.write_text(src, encoding="utf-8")
    return out


def _env(tmp: pathlib.Path) -> dict:
    s = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    census = re.search(r'METALOGOS_ENV_ALLOWLIST_CENSUS="([^"]+)"', s).group(1)
    names = ["app.mlog", "consensus.mlog"] + [p.name for p in sorted((ROOT / "dept").glob("*.mlog"))]
    env = dict(os.environ)
    env.update({
        "METALOGOS_SERVE_ALLOW_EXEC": "1",
        "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
        "METALOGOS_SERVE_BACKEND": "vm",
        "METALOGOS_DATA_DIR": ".",
        "METALOGOS_ENV_ALLOWLIST": census,
        "METALOGOS_SENSITIVE_PATH_ALLOWLIST": ",".join(names),
        "CRON_SECRET": "migrations-idempotent-test",
        "DATABASE_URL": f"sqlite:{tmp / 'office.db'}",
    })
    return env


def _serve_port() -> int:
    m = re.search(r"mlogserver\s*\{[^}]*?port:\s*(\d+)", (ROOT / "app.mlog").read_text(encoding="utf-8"), re.S)
    return int(m.group(1)) if m else 10001


def _port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _boot_once(tmp: pathlib.Path, aug: pathlib.Path, env: dict, log: pathlib.Path) -> None:
    """Один бут serve до /health, затем аккуратное завершение."""
    with open(log, "w") as fh:
        p = subprocess.Popen([str(MLOG), "serve", str(aug)], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(90):
            if p.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{_serve_port()}/health", timeout=2) as resp:
                    ok = resp.status == 200
                    break
            except Exception:
                time.sleep(1)
        assert ok, (
            f"mlog serve не поднялся / /health не ответил ({log.name}): "
            + " | ".join(
                l for l in log.read_text(errors="ignore").splitlines()
                if re.search(r"^error|violated|SQL_ERROR", l)
            )[:5]
        )
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
    # порт должен освободиться до следующего бута (тот же mlogserver-порт)
    for _ in range(30):
        if not _port_busy(_serve_port()):
            return
        time.sleep(1)
    pytest.fail(f"порт {_serve_port()} не освободился после завершения первого бута")


def _dup_lines(log: pathlib.Path) -> list:
    return [l for l in log.read_text(errors="ignore").splitlines() if "duplicate column name" in l]


def _alter_sql_error_lines(log: pathlib.Path) -> list:
    return [
        l for l in log.read_text(errors="ignore").splitlines()
        if "SQL_ERROR" in l and "ALTER" in l
    ]


def test_first_boot_fresh_db_no_alter_sql_error(tmp_path):
    """Первый старт на пустой БД: ALTER отрабатывает чисто — ни caught-дублей,
    ни SQL_ERROR по ALTER (до наряда: ~20 строк на каждый старт)."""
    os.chmod(MLOG, 0o755)
    aug = _augmented(tmp_path)
    env = _env(tmp_path)
    port = _serve_port()
    if _port_busy(port):
        pytest.skip(f"порт {port} занят — сервер уже запущен в этом окружении")
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("migrations-test\n", encoding="utf-8")
    log = tmp_path / "boot1.log"
    try:
        _boot_once(tmp_path, aug, env, log)
        dups = _dup_lines(log)
        assert not dups, f"первый бут на пустой БД дал дубли колонок ({len(dups)}): " + dups[0][:160]
        errs = _alter_sql_error_lines(log)
        assert not errs, f"первый бут дал SQL_ERROR по ALTER ({len(errs)}): " + errs[0][:160]
    finally:
        if created:
            version.unlink(missing_ok=True)


def test_second_boot_no_duplicate_column(tmp_path):
    """Второй старт на ТОЙ ЖЕ БД: гард даёт skip — «duplicate column name»
    в логе нет (мутация: один сырой db_execute возвращает строку в лог)."""
    os.chmod(MLOG, 0o755)
    aug = _augmented(tmp_path)
    env = _env(tmp_path)
    port = _serve_port()
    if _port_busy(port):
        pytest.skip(f"порт {port} занят — сервер уже запущен в этом окружении")
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("migrations-test\n", encoding="utf-8")
    log1 = tmp_path / "boot1.log"
    log2 = tmp_path / "boot2.log"
    try:
        _boot_once(tmp_path, aug, env, log1)
        _boot_once(tmp_path, aug, env, log2)
        dups = _dup_lines(log2)
        assert not dups, f"второй бут дал дубли колонок ({len(dups)}): " + dups[0][:160]
    finally:
        if created:
            version.unlink(missing_ok=True)
