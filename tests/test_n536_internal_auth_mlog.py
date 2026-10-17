#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #536 A.4: mlog-тест RequireInternalAuth (заголовок + ct_eq).

Поднимает реальный `bin/mlog serve` (0.32.0) на МИНИМАЛЬНОМ харнессе, в
который программно вставлен НАСТОЯЩИЙ текст pattern RequireInternalAuth,
извлечённый из app.mlog (статическая гвард ниже проверяет, что в app.mlog
именно request_header("X-Internal-Token") + ct_eq).

Кейсы по тексту наряда:
- верный заголовок  → 200
- неверный заголовок → 401
- без заголовка      → 401
- при пустом env     → 200 (auth-off: expected == "" → "ok")

Мутация по тексту наряда: «заменить ct_eq на true → тест обязан упасть» —
реализована как test_mutation_ct_eq_true_is_killed: харнесс с мутацией
ct_eq(...) → true отвечает 200 на неверный токен, т.е. кейсы кейсов auth
(401) поймали бы мутацию; мета-тест падает, если мутация НЕизменяема
(значит, тесты не чувствительны к этому классу регрессии).
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time

import pytest
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MLOG_BIN = os.path.join(REPO, "bin", "mlog")
APP_MLOG = os.path.join(REPO, "app.mlog")

TOKEN = "tok-n536-test-12345678"
PORT_BASE = 10993  # харнесс / мутация / пустой env — порты +0/+1/+2

pytestmark = pytest.mark.skipif(
    not (os.path.exists(MLOG_BIN) and os.path.exists(APP_MLOG)),
    reason="bin/mlog или app.mlog отсутствуют (нестендовая песочница)")


def _extract_pattern():
    """Настоящий pattern RequireInternalAuth из app.mlog (текст = код прода)."""
    src = open(APP_MLOG, encoding="utf-8").read()
    m = re.search(r"pattern RequireInternalAuth\(\) -> String \{.*?\n\}", src, re.S)
    assert m, "pattern RequireInternalAuth не найден в app.mlog"
    return m.group(0)


def _harness(pattern_text, port):
    """Минимальный mlogserver-файл с настоящим паттерном."""
    return (
        "// #536 A.4: автогенерируемый харнесс (тест) — НАСТОЯЩИЙ паттерн из app.mlog\n"
        + pattern_text + "\n\n"
        + f"mlogserver {{\n  port: {port}\n  host: \"127.0.0.1\"\n\n"
        + "  route \"/auth-probe\" method=GET {\n"
        + "    let auth = RequireInternalAuth()\n"
        + "    if auth == \"unauthorized\" then { return respond(\"401 Unauthorized\") }\n"
        + "    return respond(\"200 auth-ok\")\n"
        + "  }\n"
        + "}\n"
    )


def _free_port(preferred):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class _Serve:
    """subprocess bin/mlog serve + ожидание готовности; гарантированная уборка."""

    def __init__(self, pattern_text, env_token):
        self.dir = tempfile.mkdtemp(prefix="n536-serve-")
        self.port = _free_port(PORT_BASE + os.getpid() % 50)
        # харнесс собираем ЗДЕСЬ — с финальным портом self.port (иначе файл
        # слушает один порт, а readiness-проба стучится в другой)
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_harness(pattern_text, self.port))
        env = dict(os.environ)
        env.update({
            "INTERNAL_API_TOKEN": env_token,
            "METALOGOS_ENV_ALLOWLIST": "INTERNAL_API_TOKEN,CRON_SECRET",
            "METALOGOS_SERVE_BACKEND": "interpreter",
            "METALOGOS_SERVE_ALLOW_EXEC": "1",
            "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
            "METALOGOS_DATA_DIR": self.dir,
        })
        os.chmod(MLOG_BIN, 0o755)
        log = open(os.path.join(self.dir, "serve.log"), "w")
        self.proc = subprocess.Popen(
            [MLOG_BIN, "serve", src], cwd=self.dir, env=env,
            stdout=log, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid)
        self.url = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = open(log.name, errors="replace").read()[-600:]
                raise RuntimeError(f"mlog serve умер при старте:\n{tail}")
            try:
                if requests.get(self.url + "/auth-probe", timeout=2).status_code in (200, 401):
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        raise RuntimeError("mlog serve не поднялся за 60 c")

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture()
def serve_with_token():
    s = _Serve(_extract_pattern(), TOKEN)
    yield s
    s.stop()


@pytest.fixture()
def serve_empty_env():
    s = _Serve(_extract_pattern(), "")
    yield s
    s.stop()


# ── Кейсы наряда ──────────────────────────────────────────────────────────


def test_correct_header_200(serve_with_token):
    r = requests.get(serve_with_token.url + "/auth-probe",
                     headers={"X-Internal-Token": TOKEN}, timeout=5)
    assert r.status_code == 200, r.text


def test_wrong_header_401(serve_with_token):
    r = requests.get(serve_with_token.url + "/auth-probe",
                     headers={"X-Internal-Token": "wrong-value"}, timeout=5)
    assert r.status_code == 401, r.text


def test_missing_header_401(serve_with_token):
    r = requests.get(serve_with_token.url + "/auth-probe", timeout=5)
    assert r.status_code == 401, r.text


def test_empty_env_200_auth_off(serve_empty_env):
    # пустой env → expected == "" → "ok" (dev-стенды, auth-off)
    r = requests.get(serve_empty_env.url + "/auth-probe", timeout=5)
    assert r.status_code == 200, r.text


# ── Мутация по тексту наряда: ct_eq → true обязан быть пойман ────────────


def test_mutation_ct_eq_true_is_killed():
    """Мутант ct_eq(...)→true должен вести себя иначе (200 на неверный токен).

    Если мутант неотличим от оригинала — кейсы 401 нечувствительны к этому
    классу регрессии, и мета-тест падает («тест обязан упасть» на мутации).
    """
    mutant = re.sub(r"ct_eq\(token, expected\)", "true",
                    _extract_pattern())
    assert mutant != _extract_pattern(), "мутация ct_eq → true не применилась"
    s = _Serve(mutant, TOKEN)
    try:
        r = requests.get(s.url + "/auth-probe",
                         headers={"X-Internal-Token": "wrong-value"}, timeout=5)
        assert r.status_code == 200, (
            "мутант ct_eq→true неотличим от оригинала (неверный токен не "
            "пропущен) — кейсы 401 не поймали бы мутацию")
    finally:
        s.stop()


# ── Статическая гвард: в app.mlog именно заголовок + ct_eq ───────────────


def test_app_mlog_pattern_uses_header_and_ct_eq():
    pat = _extract_pattern()
    assert 'request_header("X-Internal-Token")' in pat, \
        "app.mlog: RequireInternalAuth не читает заголовок X-Internal-Token"
    assert "ct_eq(token, expected)" in pat, \
        "app.mlog: сравнение не constant-time (ct_eq отсутствует)"
    assert 'query_param("token")' not in pat, \
        "app.mlog: RequireInternalAuth всё ещё читает токен из query (утечка #536)"
    assert 'expected == "" then { return "ok" }' in pat, \
        "app.mlog: ветка auth-off (expected == \"\") исчезла — запрет #536"
