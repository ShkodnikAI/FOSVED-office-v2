"""№849 (Metalogos gh#1673, волна 73 — W-M): fail-closed source-атрибуция памяти.

Критерии «сделано, когда» (наряд gh#1673):
- отказ без source: FosvedMemory.remember(None) → ValueError, молчаливые
  дефолты 'manual'/'yana_auto' удалены из вызывающих;
- атрибуция client_id на mcp_memory: source = mcp:<client_id>, константа
  "mcp" удалена, отсутствие client_id — отказ записи (fail-closed, не дефолт);
- legacy-записи (NULL/'manual'/'yana_auto'/'mcp') не переписываются, в выдаче
  помечены legacy-unverified (честность формы №468);
- activity-лог атрибуции: memory_write в audit_log — роль + конкретный клиент
  (двойная атрибуция по memanto-форме).
"""
import json
import os
import pathlib
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n849-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['FOSVED_MCP_ALLOW_WRITE'] = '1'

import llm_proxy  # noqa: E402
from proxy import mcp_server  # noqa: E402
from proxy.core import _query  # noqa: E402
from lib.fosved_memory import FosvedMemory  # noqa: E402


@pytest.fixture()
def mem(tmp_path):
    m = FosvedMemory(str(tmp_path / 'mem849.db'))
    yield m
    m.close()


def rpc(method, params=None, req_id=1, client=None):
    return mcp_server.handle_request({"jsonrpc": "2.0", "id": req_id, "method": method,
                                      "params": params or {}}, client_id=client)


class TestRememberFailClosed:
    """№849.1: source обязателен — None/пустой → ValueError, дефолтов нет."""

    def test_remember_without_source_raises(self, mem):
        with pytest.raises(ValueError):
            mem.remember("факт без источника", "fact")

    def test_remember_blank_source_raises(self, mem):
        with pytest.raises(ValueError):
            mem.remember("факт с пустым источником", "fact", source="   ")

    def test_remember_with_explicit_source_ok(self, mem):
        mid = mem.remember("факт с источником", "fact", source="dept:dev")
        row = mem.db.execute(
            "SELECT source FROM typed_memories WHERE id=?", (mid,)).fetchone()
        assert row["source"] == "dept:dev"

    def test_seed_requires_explicit_source(self, mem):
        with pytest.raises(ValueError):
            mem.seed([{"content": "запись без источника", "type": "fact"}])

    def test_seed_with_source_ok(self, mem):
        n = mem.seed([{"content": "сеяная запись", "type": "fact",
                       "confidence": 0.9, "source": "dept:dev"}])
        assert n == 1


class TestLegacyMarking:
    """№849.4: legacy (NULL/'manual'/'yana_auto'/'mcp') не переписывается,
    в выдаче помечается legacy-unverified."""

    def _insert_legacy(self, mem, source, content):
        mem.db.execute(
            "INSERT INTO typed_memories (content, type, confidence, source, created_at) "
            "VALUES (?,?,?,?,?)", (content, "fact", 0.9, source, 1.0))
        mem.db.commit()

    def test_legacy_sources_marked_in_recall(self, mem):
        for i, src in enumerate((None, 'manual', 'yana_auto', 'mcp')):
            self._insert_legacy(mem, src, f"legacy запись {i} маркер")
        res = mem.recall("legacy запись")
        assert len(res) == 4
        assert {r["source_display"] for r in res} == {"legacy-unverified"}
        # не переписаны — честная миграция
        assert {r["source"] for r in res} == {None, 'manual', 'yana_auto', 'mcp'}

    def test_explicit_source_displayed_as_is(self, mem):
        self._insert_legacy(mem, "mcp:agent-x", "явная атрибуция маркер")
        res = mem.recall("явная атрибуция")
        assert res[0]["source_display"] == "mcp:agent-x"

    def test_answer_marks_legacy_not_question_mark(self, mem):
        self._insert_legacy(mem, None, "старое знание маркер")
        out = mem.answer("старое знание")
        assert "legacy-unverified" in out
        assert "src:?" not in out

    def test_answer_shows_explicit_source(self, mem):
        self._insert_legacy(mem, "dept:dev", "свежее знание маркер")
        out = mem.answer("свежее знание")
        assert "src:dept:dev" in out

    def test_stats_counts_legacy(self, mem):
        self._insert_legacy(mem, None, "легаси для статистики 1")
        self._insert_legacy(mem, "manual", "легаси для статистики 2")
        self._insert_legacy(mem, "dept:dev", "чистая запись для статистики")
        s = mem.stats()
        assert s["legacy_unverified"] == 2


class TestMcpAttribution:
    """№849.2: client_id хендшейка → source = mcp:<client_id>; без client_id — отказ."""

    def test_add_memory_attributes_client(self):
        mcp_server.ensure_tables()
        text = f"заметка с атрибуцией {uuid.uuid4().hex}"
        res = rpc("tools/call", {"name": "add_memory",
                                 "arguments": {"text": text, "space": "owner"}},
                  client="agent-y")
        assert "result" in res, res
        # mcp_memory живёт в custom.db (mcp_server._conn) — читаем из авторитетного store
        with mcp_server._conn() as c:
            row = c.execute("SELECT source FROM mcp_memory WHERE content=?",
                            (text,)).fetchone()
        assert row["source"] == "mcp:agent-y"

    def test_add_memory_without_client_refused(self):
        """Fail-closed: нет client_id — отказ записи, не дефолт."""
        res = rpc("tools/call", {"name": "add_memory",
                                 "arguments": {"text": f"x {uuid.uuid4().hex}",
                                               "space": "owner"}})
        assert res["error"]["code"] == -32000
        assert "client_id" in res["error"]["message"]

    def test_mcp_memory_new_db_default_is_null(self, tmp_path):
        """Константа 'mcp' удалена из DDL: дефолт колонки — NULL (legacy-маркер)."""
        db = str(tmp_path / 'mcp849.db')
        import sqlite3
        from unittest import mock
        with mock.patch.dict(os.environ, {"DATABASE_PATH": db}):
            mcp_server.ensure_tables()
            conn = sqlite3.connect(os.path.join(db, "custom.db"))
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='mcp_memory'").fetchone()[0]
            conn.close()
        assert "'mcp'" not in ddl


class TestRoutesFailClosed:
    """№849.1: молчаливый дефолт 'manual' в /memory/remember удалён —
    без source endpoint отвечает 400."""

    def _client(self):
        return llm_proxy.app.test_client()

    def test_remember_endpoint_without_source_400(self):
        resp = self._client().post("/memory/remember",
                                   json={"content": "запись без источника",
                                         "type": "fact"})
        assert resp.status_code == 400
        assert "source" in resp.get_json()["error"]

    def test_remember_endpoint_with_source_ok(self):
        resp = self._client().post("/memory/remember", json={
            "content": f"запись с источником {uuid.uuid4().hex}",
            "type": "fact", "source": "dept:qa"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "remembered"


class TestAuditAttribution:
    """№849.3: activity-лог атрибуции записи — роль + клиент (memory_write)."""

    def test_memory_write_logged_on_mcp_add(self):
        mcp_server.ensure_tables()
        before = _query("SELECT COUNT(*) c FROM audit_log WHERE action='memory_write'",
                        fetch=True)[0]["c"]
        rpc("tools/call", {"name": "add_memory",
                           "arguments": {"text": f"audit mcp {uuid.uuid4().hex}",
                                         "space": "owner"}},
            client="agent-audit")
        after = _query("SELECT COUNT(*) c FROM audit_log WHERE action='memory_write'",
                       fetch=True)[0]["c"]
        assert after == before + 1
        row = _query("SELECT details FROM audit_log WHERE action='memory_write' "
                     "ORDER BY id DESC LIMIT 1", fetch=True)[0]
        d = json.loads(row["details"])
        assert d["store"] == "mcp_memory" and d["client"] == "agent-audit"
        assert d["source"] == "mcp:agent-audit"

    def test_memory_write_logged_on_route(self):
        before = _query("SELECT COUNT(*) c FROM audit_log WHERE action='memory_write'",
                        fetch=True)[0]["c"]
        llm_proxy.app.test_client().post("/memory/remember", json={
            "content": f"audit route {uuid.uuid4().hex}",
            "type": "fact", "source": "dept:qa"})
        after = _query("SELECT COUNT(*) c FROM audit_log WHERE action='memory_write'",
                       fetch=True)[0]["c"]
        assert after == before + 1
        row = _query("SELECT details FROM audit_log WHERE action='memory_write' "
                     "ORDER BY id DESC LIMIT 1", fetch=True)[0]
        d = json.loads(row["details"])
        assert d["store"] == "typed_memories" and d["source"] == "dept:qa"


class TestSourceHygiene:
    """№849: молчаливые константы 'manual'/'yana_auto'/'mcp' удалены из кода
    (статик-гвард по форме error-hygiene)."""

    def _read(self, *parts):
        root = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return (root.joinpath(*parts)).read_text(encoding="utf-8")

    def test_no_silent_defaults_in_routes_tail(self):
        rt = self._read("proxy", "routes_tail.py")
        assert "data.get('source', 'manual')" not in rt
        assert "source='yana_auto'" not in rt

    def test_no_mcp_constant_in_mcp_server(self):
        ms = self._read("proxy", "mcp_server.py")
        assert "[space, text, tags, \"mcp\"]" not in ms
        assert "DEFAULT 'mcp'" not in ms

    def test_no_seed_default_in_fosved_memory(self):
        fm = self._read("lib", "fosved_memory.py")
        assert "m.get('source', 'seed')" not in fm
