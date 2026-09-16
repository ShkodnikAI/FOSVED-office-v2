#!/usr/bin/env python3
"""SHOP-2 tests (диспатч #172): web-MCP сервер mcp_servers/web.

Покрытие (паттерн test_fo014_mcp_tools.py — локальный HTTP-stub):
  1. Протокол legacy-MCP: initialize / tools/list / unknown → -32602 /
     мусор во входе молча пропускается (ping отвечает).
  2. fetch_page: title + текст без тегов/скриптов; обрезка max_chars;
     refresh=true обходит кэш (счётчик хитов stub'а растёт).
  3. fetch_json: парсинг; не-JSON → ok:false kind:"not_json".
  4. robots.txt: Disallow → ok:false kind:"robots_disallow".
  5. 404 → ok:false "HTTP 404"; сеть-мусор → честный отказ, не падение.
  6. SSRF-гейт: приватный адрес запрещён БЕЗ тестовой лазейки; ftp → bad_scheme.
  7. Кэш: повтор → cached:true, сеть не бьётся; rate-limit: пауза ≥ интервала.
  8. Гварды сборки: render.yaml ALLOWLIST += mcp_servers/web;
     dev.mlog содержит мост McpWebCall/McpWebServerCmd на тот же путь.
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
WEB_SERVER = BASE / "mcp_servers" / "web"
RENDER_YAML = BASE / "render.yaml"
DEV_MLOG = BASE / "dept" / "dev.mlog"


# ── stdio-хелпер ─────────────────────────────────────────────────────────
class McpProc:
    def __init__(self, env=None):
        self.p = subprocess.Popen(
            [str(WEB_SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=env, cwd=str(BASE))

    def rpc(self, payload):
        self.p.stdin.write(json.dumps(payload) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        return json.loads(line)

    def initialize(self):
        self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26"}})
        self.p.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def call(self, name, args, rid=3):
        return self.rpc({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                         "params": {"name": name, "arguments": args}})

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def result_data(resp):
    assert "result" in resp, resp
    assert resp["result"].get("isError") is False, resp
    return json.loads(resp["result"]["content"][0]["text"])


# ── локальный HTTP-stub ──────────────────────────────────────────────────
PAGE_HTML = ("<html><head><title>Тестовая карточка</title></head><body>"
             "<script>var x = 'скрипт уходит';</script>"
             "<style>.a { color: red; }</style>"
             "<h1>Кофемолка Bosch TSM6</h1><p>Цена: 129,90 р.</p>"
             "<div>Гарантия 24 месяца</div>"
             "<p>Описание: компактная электрическая кофемолка с нержавеющими "
             "ножами и прозрачной крышкой, вместимость 75 граммов зерна, "
             "мощность 180 ватт, защита от включения без крышки, прорезиненные "
             "ножки и шнур длиной один метр двадцать сантиметров, цвет белый "
             "с серыми вставками, гарантия производителя двадцать четыре "
             "месяца с даты продажи.</p></body></html>")
API_JSON = {"product": {"name": "Кофемолка", "price": 129.9}, "in_stock": True}


class _Stub(BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        _Stub.hits[self.path] = _Stub.hits.get(self.path, 0) + 1
        if self.path.startswith("/page"):
            self._send(200, PAGE_HTML)
        elif self.path.startswith("/api"):
            self._send(200, json.dumps(API_JSON), "application/json")
        elif self.path.startswith("/robots.txt"):
            self._send(200, "User-agent: *\nDisallow: /private\n", "text/plain")
        elif self.path.startswith("/private"):
            self._send(200, "<html><body>secret</body></html>")
        elif self.path.startswith("/missing"):
            self._send(404, "nope", "text/plain")
        elif self.path.startswith("/text"):
            self._send(200, "just text, not json", "text/plain")
        else:
            self._send(404, "nf", "text/plain")


@pytest.fixture()
def stub_url():
    _Stub.hits = {}
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class _StubNoRobots(BaseHTTPRequestHandler):
    """Хост БЕЗ robots.txt: /robots.txt → 404, страница /page → 200."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/page"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404")


@pytest.fixture()
def stub_norobots_url():
    srv = HTTPServer(("127.0.0.1", 0), _StubNoRobots)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _env_with_private():
    return dict(os.environ, FOSVED_MCP_WEB_ALLOW_PRIVATE="1",
                WEB_MIN_INTERVAL="0")


# ── 1. Протокол ──────────────────────────────────────────────────────────
def test_initialize_tools_list_unknown_tool():
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        resp = m.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in resp["result"]["tools"]]
        assert names == ["fetch_page", "fetch_json"]
        assert all("inputSchema" in t for t in resp["result"]["tools"])
        assert m.call("no_such_tool", {}, rid=9)["error"]["code"] == -32602
    finally:
        m.close()


def test_garbage_input_is_skipped_ping_answers():
    m = McpProc(_env_with_private())
    try:
        m.p.stdin.write("это совсем не json\n")
        m.p.stdin.flush()
        r = m.rpc({"jsonrpc": "2.0", "id": 7, "method": "ping"})
        assert r["result"] == {}
    finally:
        m.close()


# ── 2/3/4/5. fetch_page / fetch_json / robots / ошибки ──────────────────
def test_fetch_page_extracts_title_and_text(stub_url):
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        d = result_data(m.call("fetch_page", {"url": f"{stub_url}/page"}))
        assert d["ok"] is True and d["status"] == 200
        assert d["title"] == "Тестовая карточка"
        assert "Кофемолка Bosch TSM6" in d["content"]
        assert "129,90 р." in d["content"]
        assert "скрипт уходит" not in d["content"] and ".a { color" not in d["content"]
    finally:
        m.close()


def test_fetch_json_parses_and_rejects_non_json(stub_url):
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        d = result_data(m.call("fetch_json", {"url": f"{stub_url}/api"}))
        assert d["ok"] is True and d["data"]["product"]["price"] == 129.9
        d2 = result_data(m.call("fetch_json", {"url": f"{stub_url}/text"}, rid=4))
        assert d2["ok"] is False and d2["kind"] == "not_json"
    finally:
        m.close()


def test_robots_disallow_is_refused(stub_url):
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        d = result_data(m.call("fetch_page", {"url": f"{stub_url}/private"}))
        assert d["ok"] is False and d["kind"] == "robots_disallow"
        assert _Stub.hits.get("/private", 0) == 0  # запрос НЕ ушёл на страницу
    finally:
        m.close()


def test_robots_missing_404_allows_with_note(stub_norobots_url):
    """Урок SHOP-3: непарсенный robotparser в 3.12 даёт can_fetch=False —
    404 robots должен РАЗРЕШАТЬ с note, а не запрещать весь хост."""
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        d = result_data(m.call("fetch_page", {"url": f"{stub_norobots_url}/page"}))
        assert d["ok"] is True, d
        assert "robots_note" in d and "404" in d["robots_note"]
    finally:
        m.close()


def test_http_404_is_honest_refusal(stub_url):
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        d = result_data(m.call("fetch_page", {"url": f"{stub_url}/missing"}))
        assert d["ok"] is False and "HTTP 404" in d["error"] and d["kind"] == "http_404"
    finally:
        m.close()


def test_max_chars_truncates_and_refresh_bypasses_cache(stub_url):
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        # floor сервера 200 — ниже поднимается (защита от глупых значений)
        d = result_data(m.call("fetch_page", {"url": f"{stub_url}/page", "max_chars": 10}))
        assert len(d["content"]) <= 200
        d2 = result_data(m.call("fetch_page",
                                {"url": f"{stub_url}/page", "max_chars": 5000,
                                 "refresh": True}, rid=4))
        assert len(d2["content"]) > 200 and "cached" not in d2
        assert _Stub.hits.get("/page", 0) >= 2  # refresh реально бил в сеть
    finally:
        m.close()


# ── 6. SSRF-гейт ─────────────────────────────────────────────────────────
def test_private_ip_refused_without_test_escape(stub_url):
    env = {k: v for k, v in os.environ.items()
           if k != "FOSVED_MCP_WEB_ALLOW_PRIVATE"}
    env["WEB_MIN_INTERVAL"] = "0"
    m = McpProc(env)
    try:
        m.initialize()
        d = result_data(m.call("fetch_page", {"url": f"{stub_url}/page"}))
        assert d["ok"] is False and d["kind"] == "ssrf"
        d2 = result_data(m.call("fetch_page", {"url": "ftp://example.com/x"}, rid=4))
        assert d2["ok"] is False and d2["kind"] == "bad_scheme"
        d3 = result_data(m.call("fetch_page",
                                {"url": "http://нет-такого-хоста-гарантированно.by/x"}, rid=5))
        assert d3["ok"] is False and d3["kind"] == "dns"
    finally:
        m.close()


# ── 7. Кэш и rate-limit ──────────────────────────────────────────────────
def test_cache_second_call_hits_memory(stub_url):
    m = McpProc(_env_with_private())
    try:
        m.initialize()
        d1 = result_data(m.call("fetch_json", {"url": f"{stub_url}/api"}))
        d2 = result_data(m.call("fetch_json", {"url": f"{stub_url}/api"}, rid=4))
        assert "cached" not in d1
        assert d2.get("cached") is True
        assert _Stub.hits.get("/api", 0) == 1  # сеть билась ровно один раз
    finally:
        m.close()


def test_rate_limit_enforces_min_interval(stub_url):
    env = dict(os.environ, FOSVED_MCP_WEB_ALLOW_PRIVATE="1", WEB_MIN_INTERVAL="1")
    m = McpProc(env)
    try:
        m.initialize()
        t0 = time.monotonic()
        result_data(m.call("fetch_json", {"url": f"{stub_url}/api"}))
        result_data(m.call("fetch_json", {"url": f"{stub_url}/api?x=1"}, rid=4))
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.9, "второй запрос к тому же хосту прошёл без паузы"
    finally:
        m.close()


# ── 8. Гварды сборки: ALLOWLIST и мост ───────────────────────────────────
def test_render_yaml_allowlist_has_web():
    txt = RENDER_YAML.read_text(encoding="utf-8")
    assert "mcp_servers/github,mcp_servers/filesystem,mcp_servers/markets,mcp_servers/web" in txt


def test_dev_mlog_bridge_targets_web_server():
    txt = DEV_MLOG.read_text(encoding="utf-8")
    assert "pattern McpWebServerCmd" in txt
    assert 'return "mcp_servers/web"' in txt
    assert "pattern McpWebCall" in txt
