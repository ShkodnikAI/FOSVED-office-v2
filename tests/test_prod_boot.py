"""Барьер прод-старта: то, что делает entrypoint.sh, должно проходить в тестах.

Инцидент 2026-10-06 (деплой 491a915): #486 добавил в WebhookBody решение `if`
по ответу http_get без одностороннего redact. Metalogos 0.28.0 →
`mlog audit` rc=1 (UNTRUSTED_DECISION) → прод откатывается на легаси-бинарь /
`mlog serve` отказывается стартовать → /health FAIL → цикл рестартов.
CI был зелёным: `mlog check` проверяет только синтаксис, smoke поднимает только
Flask. Этот тест повторяет прод-путь: дополненная копия app.mlog
(`profile legacy {…}`), `mlog audit` (прод принимает 0 или 2), `mlog serve` с
переписью env из entrypoint.sh, ответ /health.
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
        "METALOGOS_SERVE_BACKEND": "interpreter",
        "METALOGOS_DATA_DIR": ".",
        "METALOGOS_ENV_ALLOWLIST": census,
        "METALOGOS_SENSITIVE_PATH_ALLOWLIST": ",".join(names),
        "CRON_SECRET": "prod-boot-test",
        "DATABASE_URL": f"sqlite:{tmp / 'office.db'}",
    })
    return env


def _serve_port() -> int:
    # mlog serve слушает порт из блока mlogserver в app.mlog (PORT игнорирует)
    m = re.search(r"mlogserver\s*\{[^}]*?port:\s*(\d+)", (ROOT / "app.mlog").read_text(encoding="utf-8"), re.S)
    return int(m.group(1)) if m else 10001


def _port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_audit_accepts_prod_candidate(tmp_path):
    os.chmod(MLOG, 0o755)
    aug = _augmented(tmp_path)
    r = subprocess.run([str(MLOG), "audit", str(aug)], cwd=ROOT, capture_output=True, text=True, timeout=240)
    errors = [l for l in (r.stdout + r.stderr).splitlines() if "[ERROR]" in l]
    assert r.returncode in (0, 2), (
        f"mlog audit rc={r.returncode} — прод откатится на легаси-бинарь; ошибки: " + " | ".join(errors[:5])
    )


def test_serve_starts_and_health_answers(tmp_path):
    os.chmod(MLOG, 0o755)
    aug = _augmented(tmp_path)
    env = _env(tmp_path)
    port = _serve_port()
    if _port_busy(port):
        pytest.skip(f"порт {port} занят — сервер уже запущен в этом окружении")
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("prod-boot-test\n", encoding="utf-8")
    log = tmp_path / "serve.log"
    with open(log, "w") as fh:
        p = subprocess.Popen([str(MLOG), "serve", str(aug)], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(60):
            if p.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
                    ok = resp.status == 200
                    break
            except Exception:
                time.sleep(1)
        tail = [l for l in log.read_text(errors="ignore").splitlines() if re.search(r"^error|violated", l)]
        assert ok, "mlog serve не поднялся / /health не ответил: " + " | ".join(tail[:5])
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
        if created:
            version.unlink(missing_ok=True)
