#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #603 A.2: file_id из Telegram не маскируется (F1).

С 22.09 (наряд №421, c8d2d2f) file_id читался через redact(…, "all"):
энтропийная сеть gh#1317 маскирует base64-подобный прогон ≥24 символов,
наружу уходила маска `[REDACTED:entropy…]` → Telegram отвечал
`getFile failed: status=400 invalid file_id` (прод 20.10/24.10).

Харнесс поднимает реальный `bin/mlog serve` на МИНИМАЛЬНОМ файле, в который
программно вставлена НАСТОЯЩАЯ строка чтения doc_file_id из app.mlog
(статическая гвард внизу проверяет сами строки app.mlog). Значение
сравнивается ВНУТРИ mlog по hash-отпечаткам с обеих сторон (гейты
0.34.1: UNTRUSTED_DECISION требует односторонний redact до решения,
respond — sink/public не принимает untrusted в теле), поэтому egress-
маскирование serve на наблюдение не влияет.

Мутация: «вернуть redact(…, "all")» — мутант отвечает `changed` (значение
замаскировано); мета-тест падает, если мутант неотличим от оригинала.
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

# Репро из наряда #603 A.2 (file_id реального документа; base64-подобный,
# ≥24 символа — класс энтропийной сети gh#1317)
FILE_ID = "BQACAgIAAxkBAAIFq2dXk3mZ8tQhR1vYcN4pL0aB7wE6AAJ0XAACo3pYSvKq9Zx1bC8oHgQ"
PORT_BASE = 10981  # харнесс / мутация — порты +0/+1

pytestmark = pytest.mark.skipif(
    not (os.path.exists(MLOG_BIN) and os.path.exists(APP_MLOG)),
    reason="bin/mlog или app.mlog отсутствуют (нестендовая песочница)")


def _extract_read_line():
    """Настоящая строка чтения doc_file_id из app.mlog (текст = код прода)."""
    src = open(APP_MLOG, encoding="utf-8").read()
    m = re.search(
        r'let doc_file_id = to_string\(json_get\(data, "message\.document\.file_id", ""\)\)',
        src)
    assert m, ("app.mlog: строка чтения doc_file_id без redact(…, \"all\") "
               "не найдена — фикс #603 A.1 исчез?")
    return m.group(0)


def _harness(read_line, port):
    return (
        "// #603 A.2: автогенерируемый харнесс — НАСТОЯЩАЯ строка чтения из app.mlog\n"
        + f"mlogserver {{\n  port: {port}\n  host: \"127.0.0.1\"\n\n"
        + "  route \"/probe\" method=POST {\n"
        + "    let data = json_body()\n"
        + "    " + read_line + "\n"
        # решение по untrusted — только через односторонний redact с обеих
        # сторон; равенство hash-отпечатков ⟺ значение дошло неизменным
        + f'    if redact(doc_file_id, "hash_only") == redact("{FILE_ID}", "hash_only") then {{ return respond("200 raw-ok") }}\n'
        + '    return respond("200 changed")\n'
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

    def __init__(self, read_line):
        self.dir = tempfile.mkdtemp(prefix="n603-fileid-")
        self.port = _free_port(PORT_BASE + os.getpid() % 40)
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_harness(read_line, self.port))
        env = dict(os.environ)
        env.update({
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
        deadline = time.time() + 90
        try:
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    tail = open(log.name, errors="replace").read()[-600:]
                    raise RuntimeError(f"mlog serve умер при старте:\n{tail}")
                try:
                    if requests.get(self.url + "/health", timeout=2).status_code == 200:
                        return
                except requests.RequestException:
                    pass
                time.sleep(0.5)
            raise RuntimeError("mlog serve не поднялся за 90 c")
        except Exception:
            self.stop()
            raise

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


def _probe(serve):
    r = requests.post(serve.url + "/probe",
                      json={"message": {"document": {"file_id": FILE_ID}}}, timeout=10)
    assert r.status_code == 200, r.text
    return r.text


def test_fileid_reaches_harness_unchanged():
    """Фикс #603 A.1: настоящий file_id доходит до обработки неизменным."""
    s = _Serve(_extract_read_line())
    try:
        assert _probe(s) == "raw-ok", "file_id изменился/замаскирован до обработки"
    finally:
        s.stop()


def test_mutation_all_policy_is_killed():
    """Мутант «вернуть redact(…, "all")» обязан пасть (результат — в PR).

    Оригинал: file_id доходит неизменным (raw-ok).
    Мутант: тот же запрос → changed (маска gh#1317) — кейс ловит регрессию #421.
    """
    mutant_line = (
        'let doc_file_id = redact(to_string(json_get(data, "message.document.file_id", "")), "all")'
    )
    s = _Serve(mutant_line)
    try:
        body = _probe(s)
        assert body != "raw-ok", (
            "мутант redact(…,\"all\") неотличим от оригинала — регрессия gh#1317 "
            "не была бы поймана; результат мутации: НЕ пойман")
        assert "changed" in body, f"неожиданный ответ мутанта: {body}"
    finally:
        s.stop()


# ── Статическая гвард: в app.mlog все три file_id читаются без "all" ──────


def _app_src():
    return open(APP_MLOG, encoding="utf-8").read()


def test_app_mlog_fileid_lines_are_not_masked():
    src = _app_src()
    for field in ("message.voice.file_id", "message.document.file_id", "message.photo.0.file_id"):
        assert f'json_get(data, "{field}", "")' in src, f"app.mlog: чтение {field} исчезло"
        assert f'json_get(data, "{field}", "")), "all")' not in src, (
            f"app.mlog: {field} снова под redact(…, \"all\") — регрессия #421/#603 A.1")
    # пустота — рецептом hash_only (как рядом, прецедент :2608)
    assert 'redact(voice_file_id, "hash_only") != redact("", "hash_only")' in src, \
        "app.mlog: проверка пустоты voice_file_id не рецептом hash_only"
    assert 'redact(doc_file_id, "hash_only") != redact("", "hash_only")' in src, \
        "app.mlog: проверка пустоты doc_file_id не рецептом hash_only"
    # в AuditLog file_id не пишется (A.1)
    assert '"voice_received", "voice", ""' in src, \
        "app.mlog: AuditLog voice_received снова пишет file_id"
