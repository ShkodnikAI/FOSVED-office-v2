#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #536 A.4: mlog-тест RequireInternalAuth (заголовок + сравнение).

Адаптирован #546 A.1 (рецепт Metalogos-#1317): сравнение — SecretMatches
(hash_only с обеих сторон), ct_eq по сырой строке молча ломался на
токен-подобных значениях. Поднимает реальный `bin/mlog serve` (0.32.0) на
МИНИМАЛЬНОМ харнессе, в который программно вставлен НАСТОЯЩИЙ текст pattern
RequireInternalAuth (+ SecretMatches), извлечённый из app.mlog (статическая
гвард ниже проверяет: заголовок, hash_only-обёртка, вызов SecretMatches).

Кейсы по тексту наряда:
- верный заголовок  → 200
- верный заголовок, похожий на токен (gh#1317) → 200 (#546)
- неверный заголовок → 401
- без заголовка      → 401
- при пустом env     → 200 (auth-off: expected == "" → "ok")

Мутации:
- #536: «сравнение → true» — харнесс с мутацией отвечает 200 на неверный
  токен: кейсы 401 поймали бы мутацию (мета-тест падает, если НЕпойман);
- #546: «вернуть redact(..., "all")» — на токен-подобном верном токене
  мутант отвечает 401 (значение замаскировано): кейс 200 поймает.
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
# gh#1317-класс «похож на токен» (≥24 b64-класса, цифра И hex-буква)
TOKENLIKE = "abcdefgh1369abcdefghi13ab"
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


def _extract_secret_matches():
    """Настоящий pattern SecretMatches (#546 A.1) из app.mlog.

    RequireInternalAuth с #546 вызывает SecretMatches — без него харнесс
    падает UNDEFINED_FUNCTION при компиляции."""
    src = open(APP_MLOG, encoding="utf-8").read()
    m = re.search(r"pattern SecretMatches\(.*?\n\}", src, re.S)
    assert m, "pattern SecretMatches не найден в app.mlog"
    return m.group(0)


def _harness(pattern_text, port):
    """Минимальный mlogserver-файл с настоящими паттернами."""
    return (
        "// #536 A.4 + #546: автогенерируемый харнесс — НАСТОЯЩИЕ паттерны из app.mlog\n"
        + _extract_secret_matches() + "\n\n"
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
def serve_with_tokenlike():
    s = _Serve(_extract_pattern(), TOKENLIKE)
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


def test_tokenlike_header_200(serve_with_tokenlike):
    # #546: верный токен-подобный заголовок → 200 (gh#1317 ломал ct_eq)
    r = requests.get(serve_with_tokenlike.url + "/auth-probe",
                     headers={"X-Internal-Token": TOKENLIKE}, timeout=5)
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


# ── Мутации: сравнение→true (#536) и «вернуть all» (#546) обязаны пасть ───


def test_mutation_always_ok_is_killed():
    """Мутант «сравнение → true» должен вести себя иначе (200 на неверный токен).

    Если мутант неотличим от оригинала — кейсы 401 нечувствительны к этому
    классу регрессии, и мета-тест падает («тест обязан упасть» на мутации).
    """
    mutant = re.sub(
        r'if SecretMatches\(token, "INTERNAL_API_TOKEN"\) then \{ return "ok" \}',
        'return "ok"', _extract_pattern())
    assert mutant != _extract_pattern(), "мутация сравнение→true не применилась"
    s = _Serve(mutant, TOKEN)
    try:
        r = requests.get(s.url + "/auth-probe",
                         headers={"X-Internal-Token": "wrong-value"}, timeout=5)
        assert r.status_code == 200, (
            "мутант сравнение→true неотличим от оригинала (неверный токен не "
            "пропущен) — кейсы 401 не поймали бы мутацию")
    finally:
        s.stop()


def test_mutation_all_policy_is_killed(serve_with_tokenlike):
    """Мутант #546 «вернуть redact(..., \"all\")» обязан пасть на токен-подобном.

    Оригинал: верный токен-подобный заголовок → 200 (fixture).
    Мутант: тот же запрос → 401 (redact("all") маскирует значение, gh#1317).
    """
    ok = requests.get(serve_with_tokenlike.url + "/auth-probe",
                      headers={"X-Internal-Token": TOKENLIKE}, timeout=5)
    assert ok.status_code == 200
    mutant = _extract_pattern().replace(
        'redact(request_header("X-Internal-Token"), "hash_only")',
        'redact(request_header("X-Internal-Token"), "all")')
    assert mutant != _extract_pattern(), "мутация hash_only→all не применилась"
    s = _Serve(mutant, TOKENLIKE)
    try:
        r = requests.get(s.url + "/auth-probe",
                         headers={"X-Internal-Token": TOKENLIKE}, timeout=5)
        assert r.status_code == 401, (
            "мутант redact(...,\"all\") неотличим на токен-подобном значении — "
            "регрессия gh#1317 не была бы поймана")
    finally:
        s.stop()


# ── Статическая гвард: в app.mlog заголовок + hash_only + SecretMatches ──


def test_app_mlog_pattern_uses_header_and_secret_matches():
    pat = _extract_pattern()
    assert 'request_header("X-Internal-Token")' in pat, \
        "app.mlog: RequireInternalAuth не читает заголовок X-Internal-Token"
    assert 'redact(request_header("X-Internal-Token"), "hash_only")' in pat, \
        "app.mlog: заголовок без hash_only-обёртки (gh#1317 — регрессия #546)"
    assert 'SecretMatches(token, "INTERNAL_API_TOKEN")' in pat, \
        "app.mlog: сравнение не через SecretMatches (#546 A.1)"
    assert 'query_param("token")' not in pat, \
        "app.mlog: RequireInternalAuth всё ещё читает токен из query (утечка #536)"
    assert 'expected == "" then { return "ok" }' in pat, \
        "app.mlog: ветка auth-off (expected == \"\") исчезла — запрет #536"
