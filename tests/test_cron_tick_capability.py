"""Наряд #649 (B.1): регрессия тика нативного cron на capability-гейте.

Инцидент 03.11 (Metalogos-#1735, прод 0.38.0): каждый тик встроенного cron
отказывал `IRREVERSIBLE_NO_GRANT: 'http_post'` на ВАЛИДНОЙ декларации
`profile capability { allow_carrier: … }` — ночной цикл, ночной отчёт,
утренний бриф, ответ Админа и слоты ЛЗ молча умерли. Исправлено в v0.38.1
(permit-roster снова доходит до нативного тика: fresh_program_context +
merge_interpreter).

Тест поднимает МИНИМАЛЬНЫЙ харнесс на `bin/mlog serve` (по образцу
test_prod_boot.py): декларация http_post, нативный слот cron раз в минуту,
паттерн слота делает http_post на локальную заглушку; бэкенд VM (как прод).
Ожидание на v0.38.1: заглушка получила запрос, в выводе serve нет
IRREVERSIBLE_NO_GRANT. Мутация: без декларации заглушка молчит, а в выводе
есть IRREVERSIBLE_NO_GRANT — гейт остаётся закрытым по умолчанию.
"""
import http.server
import os
import pathlib
import re
import socket
import subprocess
import threading
import time
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MLOG = ROOT / "bin" / "mlog"

pytestmark = pytest.mark.skipif(not MLOG.exists() or os.name != "posix", reason="нужен bin/mlog (Linux)")

HARNESS = """// Минимальный харнесс теста тика (#649 B.1): слот cron раз в минуту,
// паттерн слота делает http_post на локальную заглушку.
profile capability {{ allow_carrier: "http_post" }}

db {{ url: "sqlite:{db}" }}

memory {{ persist: "{memory}" }}

pattern TickPost() -> String {{
  let r = try http_post("http://127.0.0.1:{stub}/tick", "{{\\"from\\":\\"tick\\"}}", "application/json", {{accept: "application/json"}})
  return "posted"
}}

flow Main {{
  input: String = "" -> TickPost -> output
}}

mlogserver {{
  port: {port}
  host: "127.0.0.1"
  route "/health" method=GET {{
    return respond("200 {{\\"status\\":\\"ok\\"}}")
  }}
  route "/register" method=GET {{
    let job = cron_add("* * * * *", "TickPost", "UTC", "run_once")
    return respond("200 registered " + to_string(json_get(job, "id", "?")))
  }}
}}
"""

# Мутация: декларация allow_carrier снята — гейт обязан остаться закрытым.
HARNESS_MUT = """// Минимальный харнесс теста тика (#649 B.1, мутация): БЕЗ декларации.
db {{ url: "sqlite:{db}" }}

memory {{ persist: "{memory}" }}

pattern TickPost() -> String {{
  let r = try http_post("http://127.0.0.1:{stub}/tick", "{{\\"from\\":\\"tick\\"}}", "application/json", {{accept: "application/json"}})
  return "posted"
}}

flow Main {{
  input: String = "" -> TickPost -> output
}}

mlogserver {{
  port: {port}
  host: "127.0.0.1"
  route "/health" method=GET {{
    return respond("200 {{\\"status\\":\\"ok\\"}}")
  }}
  route "/register" method=GET {{
    let job = cron_add("* * * * *", "TickPost", "UTC", "run_once")
    return respond("200 registered " + to_string(json_get(job, "id", "?")))
  }}
}}
"""


class _Stub(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        _Stub.hits += 1
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self.do_POST()

    def log_message(self, *args):  # тишина в pytest-выводе
        pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_stub() -> http.server.HTTPServer:
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run_scenario(tmp: pathlib.Path, template: str, expect_grant_refusal: bool):
    """Общий сценарий: serve харнесса, регистрация слота, ожидание тика."""
    _Stub.hits = 0
    stub_srv = _start_stub()
    stub_port = stub_srv.server_address[1]
    serve_port = _free_port()
    harness = template.format(
        db=tmp / "h.db", memory=tmp / "mem.db", stub=stub_port, port=serve_port
    )
    app = tmp / "tick_harness.mlog"
    app.write_text(harness, encoding="utf-8")
    os.chmod(MLOG, 0o755)
    env = dict(os.environ)
    env.update({
        "METALOGOS_SERVE_BACKEND": "vm",
        # http_post на 127.0.0.1 — loopback: SSRF-гвард требует явного флага
        # (только тест; в проде цели тиков — внешние адреса).
        "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
        "METALOGOS_DATA_DIR": str(tmp),
    })
    log = tmp / "serve.log"
    with open(log, "w") as fh:
        p = subprocess.Popen([str(MLOG), "serve", str(app)], cwd=tmp, env=env, stdout=fh, stderr=subprocess.STDOUT)
    try:
        # 1) /health отвечает
        up = False
        for _ in range(90):
            if p.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{serve_port}/health", timeout=2) as resp:
                    up = resp.status == 200
                    break
            except Exception:
                time.sleep(1)
        assert up, "serve не поднялся; лог: " + log.read_text(errors="ignore")[-800:]

        # 2) регистрируем нативный слот раз в минуту
        with urllib.request.urlopen(f"http://127.0.0.1:{serve_port}/register", timeout=5) as resp:
            assert resp.status == 200

        # 3) ждём тик (гранулярность cron — минута, окно 90 с по наряду)
        deadline = time.time() + 90
        while time.time() < deadline and _Stub.hits == 0:
            time.sleep(2)
        text = log.read_text(errors="ignore")

        if expect_grant_refusal:
            # Мутация: заглушка молчит, в логе есть отказ гейта
            assert _Stub.hits == 0, "мутация: без декларации http_post не должен дойти до заглушки"
            assert "IRREVERSIBLE_NO_GRANT" in text, "мутация: ожидался IRREVERSIBLE_NO_GRANT в выводе serve"
        else:
            assert _Stub.hits >= 1, "тик не дошёл до заглушки за 90 с; лог: " + text[-800:]
            assert "IRREVERSIBLE_NO_GRANT" not in text, "отказ capability-гейта в выводе serve (Metalogos-#1735 не исправлен?)"
    finally:
        stub_srv.shutdown()
        p.terminate()
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()


def test_cron_tick_carrier_passes_with_declaration(tmp_path):
    """v0.38.1: тик нативного cron видит allow_carrier — http_post доходит."""
    _run_scenario(tmp_path, HARNESS, expect_grant_refusal=False)


def test_cron_tick_carrier_refused_without_declaration(tmp_path):
    """Мутация B.1: без декларации гейт отказывает ДО действия (fail-closed)."""
    _run_scenario(tmp_path, HARNESS_MUT, expect_grant_refusal=True)
