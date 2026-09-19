#!/usr/bin/env python3
"""FO-014: MCP-инструменты офиса (github + filesystem, ADR-0132 v1).

Тесты:
  1. Оба office-owned stdio-сервера говорят legacy-диалектом MCP
     (контракт tests/fixtures/mcp_echo_server.py из Metalogos №268):
     initialize / notifications/initialized / tools/list / tools/call.
  2. github-сервер: create_issue + list_check_runs против stub REST
     (GITHUB_API_BASE), отказ = {"ok": false, "error": ...} без падения.
  3. filesystem-сервер: песочница — read/write/list внутри корня,
     выход за корень (traversal, absolute) — громкий отказ.
  4. Гейт ядра: mcp_call вне allowlist отвергнут (MCP_NOT_ALLOWLISTED),
     разрешённый spawn попадает в METALOGOS_AUDIT_LOG_PATH.
  5. Бинарник офиса содержит mcp_call (вход наряда).
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
GH_SERVER = BASE / "mcp_servers" / "github"
FS_SERVER = BASE / "mcp_servers" / "filesystem"
MLOG = BASE / "bin" / "mlog"


# ── stdio-хелпер: поговорить с сервером по legacy-MCP ────────────────────
class McpProc:
    def __init__(self, cmd):
        self.p = subprocess.Popen(
            [str(cmd)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, cwd=str(BASE))

    def rpc(self, payload):
        self.p.stdin.write(json.dumps(payload) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("server closed stdout")
        return json.loads(line)

    def initialize(self):
        r = self.rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-03-26",
                                 "clientInfo": {"name": "pytest"}}})
        assert r["result"]["serverInfo"]["name"]
        # notification: без ответа — следующий ответ придёт на следующий rpc
        self.p.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def tools_list(self):
        return self.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    def call(self, name, args, rid=3):
        return self.rpc({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                         "params": {"name": name, "arguments": args}})

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def result_text(resp):
    assert "result" in resp, resp
    assert resp["result"].get("isError") is False, resp
    return resp["result"]["content"][0]["text"]


# ── 1. Протокол ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("server", [GH_SERVER, FS_SERVER])
def test_initialize_and_tools_list(server):
    m = McpProc(server)
    try:
        m.initialize()
        resp = m.tools_list()
        names = [t["name"] for t in resp["result"]["tools"]]
        assert names, "tools/list пуст"
        assert all("inputSchema" in t for t in resp["result"]["tools"])
    finally:
        m.close()


@pytest.mark.parametrize("server", [GH_SERVER, FS_SERVER])
def test_unknown_tool_is_32602(server):
    m = McpProc(server)
    try:
        m.initialize()
        resp = m.call("no_such_tool", {}, rid=9)
        assert resp["error"]["code"] == -32602
    finally:
        m.close()


# ── 2. github-сервер против stub REST ────────────────────────────────────
class _StubGH(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.endswith("/issues"):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._json(201, {"number": 777, "html_url": "https://github.com/x/y/issues/777",
                             "state": "open", "title": data["title"]})
        else:
            self._json(404, {"message": "not found"})

    def do_GET(self):
        if "ghost" in self.path:
            self._json(404, {"message": "no such ref"})
        elif "/check-runs" in self.path:
            self._json(200, {"check_runs": [
                {"name": "Python tests", "status": "completed", "conclusion": "success"},
                {"name": "Docker build", "status": "completed", "conclusion": "failure"},
            ]})
        elif "/issues/5" in self.path:
            self._json(200, {"number": 5, "title": "t", "state": "open",
                             "html_url": "u", "body": "b"})
        else:
            self._json(404, {"message": "nf"})


@pytest.fixture()
def stub_gh():
    srv = HTTPServer(("127.0.0.1", 0), _StubGH)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_github_flow(stub_gh):
    """create_issue → ok:true + url; list_check_runs → summary; отказ REST → ok:false."""
    env = dict(os.environ, GITHUB_TOKEN="t0k3n", GITHUB_API_BASE=stub_gh)
    p = subprocess.Popen([str(GH_SERVER)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env)
    try:
        def rpc(payload):
            p.stdin.write(json.dumps(payload) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())

        rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26"}})
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()

        r = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "create_issue",
                            "arguments": {"repo": "x/y", "title": "FO-014 demo", "body": "b"}}})
        data = json.loads(result_text(r))
        assert data["ok"] is True and data["number"] == 777
        assert "issues/777" in data["url"]

        r = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "list_check_runs",
                            "arguments": {"repo": "x/y", "ref": "main"}}})
        data = json.loads(result_text(r))
        assert data["ok"] is True and data["count"] == 2
        assert "Docker build=completed/failure" in data["summary"]

        r = rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                 "params": {"name": "create_issue",
                            "arguments": {"repo": "без-слеша", "title": "x"}}})
        data = json.loads(result_text(r))
        assert data["ok"] is False and "owner/name" in data["error"]

        r = rpc({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                 "params": {"name": "list_check_runs",
                            "arguments": {"repo": "x/y", "ref": "ghost"}}})
        data = json.loads(result_text(r))
        assert data["ok"] is False and "HTTP 404" in data["error"]
    finally:
        p.stdin.close()
        p.wait(timeout=5)


def test_github_without_token_reports_not_crashes():
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN_METALOGOS")}
    env["GITHUB_API_BASE"] = "http://127.0.0.1:1"  # никуда не дойдёт
    p = subprocess.Popen([str(GH_SERVER)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env)
    try:
        def rpc(payload):
            p.stdin.write(json.dumps(payload) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())

        rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26"}})
        r = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "list_issues", "arguments": {"repo": "x/y"}}})
        data = json.loads(result_text(r))
        assert data["ok"] is False and "GITHUB_TOKEN" in data["error"]
    finally:
        p.stdin.close()
        p.wait(timeout=5)


# ── 3. filesystem-сервер: песочница ─────────────────────────────────────
def make_fs(tmp_path):
    env = dict(os.environ, FOSVED_MCP_FS_ROOT=str(tmp_path))
    p = subprocess.Popen([str(FS_SERVER)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, env=env)

    def rpc(payload):
        p.stdin.write(json.dumps(payload) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26"}})
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    p.stdin.flush()
    return p, rpc


def fs_call(rpc, name, args, rid=5):
    return json.loads(result_text(rpc(
        {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
         "params": {"name": name, "arguments": args}})))


def test_fs_write_read_list(tmp_path):
    p, rpc = make_fs(tmp_path)
    try:
        w = fs_call(rpc, "write_file", {"path": "docs/a.md", "content": "# hello"})
        assert w["ok"] is True and w["bytes"] == 7
        r = fs_call(rpc, "read_file", {"path": "docs/a.md"})
        assert r["ok"] is True and r["content"] == "# hello"
        l = fs_call(rpc, "list_dir", {"path": ""})
        assert l["ok"] is True and l["items"][0]["name"] == "docs"
        mk = fs_call(rpc, "mkdir", {"path": "x/y"})
        assert mk["ok"] is True
    finally:
        p.stdin.close()
        p.wait(timeout=5)


def test_fs_sandbox_denies_traversal_and_absolute(tmp_path):
    p, rpc = make_fs(tmp_path)
    try:
        out = fs_call(rpc, "read_file", {"path": "../../../etc/passwd"})
        assert out["ok"] is False and "песочниц" in out["error"]
        out = fs_call(rpc, "write_file",
                      {"path": "/etc/evil.txt", "content": "no"})
        assert out["ok"] is False and "песочниц" in out["error"]
        out = fs_call(rpc, "read_file", {"path": "нет-такого.txt"})
        assert out["ok"] is False and "не найден" in out["error"]
    finally:
        p.stdin.close()
        p.wait(timeout=5)


# ── 4. Гейты ядра: allowlist + аудит + вход наряда ──────────────────────
def test_mlog_binary_has_mcp_builtins():
    out = subprocess.run([str(MLOG), "--version"], capture_output=True, text=True)
    assert "0." in out.stdout
    # вход FO-014: бинарник офиса содержит mcp_call (Metalogos №268)
    strings = subprocess.run(["strings", str(MLOG)], capture_output=True, text=True)
    assert "mcp_call" in strings.stdout


def run_mlog_fixture(source: str, allowlist: str, audit_path, tmp_path):
    """Прогнать mlog run фикстуры с офисным бинарником и office-owned сервером."""
    fx = tmp_path / "fx.mlog"
    fx.write_text(source, encoding="utf-8")
    env = dict(os.environ,
               METALOGOS_ALLOW_EXEC="1",
               METALOGOS_MCP_ALLOWLIST=allowlist,
               METALOGOS_AUDIT_LOG_PATH=str(audit_path))
    return subprocess.run([str(MLOG), "run", str(fx)], capture_output=True,
                          text=True, env=env, cwd=str(BASE), timeout=120)


def test_allowlisted_mcp_call_is_audited(tmp_path):
    audit = tmp_path / "audit.log"
    # литерал в файле: "{\"path\":\"\"}" — валидный JSON-объект в mlog-строке
    args_literal = '"{\\"path\\":\\"\\"}"'
    src = f'''
pattern T(x: String) -> String {{
  let _ = mcp_call("mcp_servers/filesystem", [], "list_dir", {args_literal})
  return "ok"
}}
flow Main {{ input: String = "" -> T -> output }}
'''
    r = run_mlog_fixture(src, "mcp_servers/filesystem", audit, tmp_path)
    assert "ok" in r.stdout, r.stdout + r.stderr
    assert audit.exists(), "spawn не попал в METALOGOS_AUDIT_LOG_PATH"
    body = audit.read_text()
    assert "mcp_servers/filesystem" in body


def test_non_allowlisted_server_rejected_by_gate(tmp_path):
    audit = tmp_path / "audit.log"
    src = """
pattern T(x: String) -> String {
  return mcp_call("python3", ["-c", "print(1)"], "x", "{}")
}
flow Main { input: String = "" -> T -> output }
"""
    r = run_mlog_fixture(src, "mcp_servers/github,mcp_servers/filesystem", audit, tmp_path)
    assert "MCP_NOT_ALLOWLISTED" in (r.stdout + r.stderr), r.stdout + r.stderr
    # отказ гейта ДО spawn — аудит не пишется, сервер не запускался
    assert not audit.exists() or "python3" not in audit.read_text()


def test_serve_route_body_needs_exec_gate(tmp_path):
    """Без METALOGOS_SERVE_ALLOW_EXEC=1 mcp_call в теле роута отвергнут гейтом ядра
    (route exec: denied). Офис включает гейт только вместе с allowlist (render.yaml)."""
    args_literal = '"{\\"path\\":\\"\\"}"'
    src = f'''mlogserver {{
  route "/t" method=GET {{
    let body = mcp_call("mcp_servers/filesystem", [], "list_dir", {args_literal})
    return respond(escape_html(body))
  }}
}}
'''
    fx = tmp_path / "route.mlog"
    fx.write_text(src, encoding="utf-8")
    env = dict(os.environ, METALOGOS_MCP_ALLOWLIST="mcp_servers/filesystem")
    env.pop("METALOGOS_SERVE_ALLOW_EXEC", None)
    env.pop("PORT", None)
    p = subprocess.Popen(["bash", "-c",
                          f"exec {MLOG} serve {fx} 2>&1 | tee {tmp_path}/serve.log"],
                         env=env, stdout=subprocess.DEVNULL, start_new_session=True)
    import time
    import urllib.request
    try:
        time.sleep(4)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/t", timeout=10) as r:
                body = r.read().decode()
        except urllib.error.HTTPError as e:
            body = e.read().decode()
        log = (tmp_path / "serve.log").read_text()
        assert "route exec: denied" in log, log[-800:]
        assert "mcp_call" not in body or "denied" in body.lower() or body.strip() == ""
    finally:
        # Убиваем ВСЮ группу: bash-пайп порождает дочерний mlog serve —
        # одного terminate() bash'а мало, mlog осиротеет и будет держать
        # лок тестовой БД, ломая следующие полные прогоны (кейс 2026-09-19).
        import signal, os as _os
        try:
            _os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            p.kill()
        p.wait(timeout=10)
