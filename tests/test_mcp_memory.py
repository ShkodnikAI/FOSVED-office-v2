"""FO-021 tests: Memory-MCP — JSON-RPC envelope, изоляция spaces (громкая ошибка),
taint (секреты не покидают офис), env-redact, read-only по умолчанию, лог mcp_call."""
import json
import os
import sqlite3
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['FOSVED_MCP_ALLOW_WRITE'] = '1'

import llm_proxy  # noqa: E402
from proxy import mcp_server  # noqa: E402
from proxy.redact import redact_obj, redact_text  # noqa: E402


@pytest.fixture(autouse=True)
def _seed_space():
    """Гарантированный контейнер 'finance' с одной записью факта."""
    mcp_server.ensure_tables()
    llm_proxy._query("DELETE FROM guardian_rules WHERE source='seed'", fetch=False)
    with mcp_server._conn() as c:
        c.execute("INSERT INTO facts (dept, content) VALUES (?, ?)", ["finance", f"cashflow резерв {uuid.uuid4().hex}"])
    yield
    os.environ['FOSVED_MCP_ALLOW_WRITE'] = '1'


def rpc(method, params=None, req_id=1, client=None):
    return mcp_server.handle_request({"jsonrpc": "2.0", "id": req_id, "method": method,
                                      "params": params or {}}, client_id=client)


class TestProtocol:
    def test_initialize_returns_instructions(self):
        res = rpc("initialize", {"clientInfo": {"name": "claude-code"}})
        assert res["result"]["serverInfo"]["name"] == "fosved-memory"
        assert "spaces" in res["result"]["instructions"]

    def test_tools_list(self):
        res = rpc("tools/list")
        names = {t["name"] for t in res["result"]["tools"]}
        assert {"search_memory", "list_memory", "graph", "add_memory"} <= names

    def test_unknown_method(self):
        assert rpc("bogus/xyz")["error"]["code"] == -32601

    def test_ping(self):
        assert "error" not in rpc("ping")


class TestSpaces:
    def test_known_space_search(self):
        res = rpc("tools/call", {"name": "search_memory", "arguments": {"query": "cashflow резерв", "space": "finance"}})
        data = json.loads(res["result"]["content"][0]["text"])
        assert data["space"] == "finance" and data["count"] >= 1
        assert data["matches"][0]["relevance_pct"] >= 50

    def test_cross_space_unknown_is_loud_error(self):
        res = rpc("tools/call", {"name": "list_memory", "arguments": {"space": "nosuchspace"}})
        assert res["error"]["code"] == -32000
        assert "не существует" in res["error"]["message"]

    def test_owner_space_has_profile(self):
        res = rpc("tools/call", {"name": "search_memory", "arguments": {"query": "что-то", "space": "owner"}})
        data = json.loads(res["result"]["content"][0]["text"])
        assert "profile" in data and data["profile"] is not None


class TestTaintAndRedact:
    def test_redact_obj_deep(self):
        obj = {"ok": 1, "telegram_bot_api_key": "1234567890abcdef", "nested": {"db_password": "supersecret99", "name": "x"}}
        out = redact_obj(obj)
        assert out["telegram_bot_api_key"] == "[REDACTED]"
        assert out["nested"]["db_password"] == "[REDACTED]"
        assert out["nested"]["name"] == "x" and out["ok"] == 1

    def test_redact_text_nonjson_passthrough(self):
        assert redact_text("plain text with SECRET inside") == "plain text with SECRET inside"

    def test_tool_response_never_contains_secret(self):
        """Даже если бы секрет попал в результат — redact на выходе наружу его вырезает."""
        secret = "sk-live-abcdef123456"
        llm_proxy._query("INSERT INTO mcp_memory (space, content, tags) VALUES ('owner', ?, '[]')",
                         [f"токен бота {secret} для теста"], fetch=False)
        res = rpc("tools/call", {"name": "search_memory", "arguments": {"query": "токен бота", "space": "owner"}})
        text = res["result"]["content"][0]["text"]
        assert secret not in text


class TestReadOnly:
    def test_add_memory_denied_when_readonly(self, monkeypatch):
        monkeypatch.setenv("FOSVED_MCP_ALLOW_WRITE", "0")
        res = rpc("tools/call", {"name": "add_memory", "arguments": {"text": "x", "space": "owner"}})
        assert res["error"]["code"] == -32002
        assert "read-only" in res["error"]["message"]

    def test_add_memory_works_when_enabled(self):
        res = rpc("tools/call", {"name": "add_memory", "arguments": {"text": f"заметка {uuid.uuid4().hex}", "space": "owner"}})
        assert "result" in res, f"unexpected response: {res}"
        assert res["result"]["content"][0]["text"]


class TestGuardianAndAudit:
    def test_mcp_call_logged(self):
        before = llm_proxy._query("SELECT COUNT(*) as c FROM audit_log WHERE action='mcp_call'", fetch=True)[0]["c"]
        rpc("tools/call", {"name": "list_memory", "arguments": {"space": "owner"}}, client="test-agent-1")
        after = llm_proxy._query("SELECT COUNT(*) as c FROM audit_log WHERE action='mcp_call'", fetch=True)[0]["c"]
        assert after == before + 1
        row = llm_proxy._query("SELECT details FROM audit_log WHERE action='mcp_call' ORDER BY id DESC LIMIT 1", fetch=True)[0]
        assert "test-agent-1" in row["details"]

    def test_guardian_deny_blocks_call(self, monkeypatch):
        """Guardian FO-015: deny на mcp__graph гасит вызов внешнего агента."""
        llm_proxy._query("DELETE FROM guardian_rules WHERE permission='mcp__graph'", fetch=False)
        llm_proxy.guardian_add_rule("mcp-agent", "mcp__graph", "deny", source="test")
        try:
            res = rpc("tools/call", {"name": "graph", "arguments": {"entity": "x", "space": "owner"}})
            assert res["error"]["code"] == -32001
        finally:
            llm_proxy._query("DELETE FROM guardian_rules WHERE permission='mcp__graph' AND source='test'", fetch=False)


class TestHttpTransport:
    def test_http_endpoint_jsonrpc(self):
        client = llm_proxy.app.test_client()
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
                           headers={"X-MCP-Client": "cursor"})
        assert resp.status_code == 200
        names = {t["name"] for t in resp.get_json()["result"]["tools"]}
        assert "search_memory" in names

    def test_http_health(self):
        client = llm_proxy.app.test_client()
        resp = client.get("/mcp/health")
        assert resp.status_code == 200
        assert "count" in resp.get_json()


class TestStdio:
    def test_stdio_roundtrip(self):
        import subprocess
        env = {**os.environ, "DATABASE_PATH": "/tmp/fosved-test-db"}
        proc = subprocess.run(
            [sys.executable, "proxy/mcp_server.py", "--stdio"],
            input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
            capture_output=True, text=True, timeout=60, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        line = [l for l in proc.stdout.split("\n") if l.strip()][-1]
        res = json.loads(line)
        assert res["id"] == 1 and any(t["name"] == "search_memory" for t in res["result"]["tools"])
