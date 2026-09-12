"""FO-006 tests: таблица facts, ops консолидации, /context_cmd, /cron/consolidate-memory."""
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['CRON_SECRET'] = 'cron-test-secret'

import llm_proxy  # noqa: E402
import proxy.routes_tail as _rt  # noqa: E402 — FO-008: функции живут здесь


@pytest.fixture
def client():
    llm_proxy.app.config['TESTING'] = True
    with llm_proxy.app.test_client() as c:
        yield c


def _seed_fact(dept, content, status='active'):
    llm_proxy._query(
        "INSERT INTO facts (dept, chat_id, content, status, source_dialog_ids, confidence, created_at, updated_at) "
        "VALUES (?, '0', ?, ?, '[]', 0.9, datetime('now'), datetime('now'))",
        (dept, content, status))
    rows = llm_proxy._query("SELECT id FROM facts WHERE dept=? AND content=?", (dept, content), fetch=True)
    return rows[0]["id"]


def _seed_dialog(dept, role, content, day):
    llm_proxy._query(
        "INSERT INTO dialog_history (chat_id, role, dept, content, created_at) VALUES ('0', ?, ?, ?, ?)",
        (role, dept, content, f"{day} 12:00:00"))


class TestFactsTable:
    def test_table_exists(self):
        rows = llm_proxy._query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'", fetch=True)
        assert rows

    def test_seed_and_query(self):
        tag = uuid.uuid4().hex[:8]
        fid = _seed_fact("qa", f"fact {tag}")
        rows = llm_proxy._query("SELECT content FROM facts WHERE id=? AND status='active'", (fid,), fetch=True)
        assert rows and rows[0]["content"] == f"fact {tag}"


class TestExtractJsonBlock:
    def test_plain_json(self):
        assert llm_proxy._extract_json_block('{"ops": []}') == {"ops": []}

    def test_fenced_json(self):
        assert llm_proxy._extract_json_block('```json\n{"ops": [{"op":"ADD"}]}\n```') == {"ops": [{"op": "ADD"}]}

    def test_json_with_noise(self):
        assert llm_proxy._extract_json_block('Вот результат: {"ops": [{"op":"ADD"}]} — готово') == {"ops": [{"op": "ADD"}]}

    def test_garbage_returns_none(self):
        assert llm_proxy._extract_json_block('совсем не json') is None


class TestConsolidateDeptDay:
    def test_add_update_delete_noop(self, monkeypatch):
        dept = f"qa_{uuid.uuid4().hex[:6]}"
        day = "2026-09-10"
        _seed_dialog(dept, "user", "Напомни: отчёт по пятницам", day)
        _seed_dialog(dept, "assistant", "Принято, отчёт по пятницам", day)
        old_id = _seed_fact(dept, "старая версия факта")

        ops = {"ops": [
            {"op": "ADD", "content": "отчёт по пятницам", "confidence": 0.9},
            {"op": "UPDATE", "target_id": old_id, "content": "обновлённый факт"},
            {"op": "DELETE", "target_id": old_id},  # UPDATE уже superseded — DELETE применится поверх
            {"op": "NOOP"},
        ]}
        monkeypatch.setattr(_rt, "call_llm", lambda d, m: {
            "reply": json.dumps(ops, ensure_ascii=False), "provider": "test", "model": "test", "tokens_in": 1, "tokens_out": 1})

        res = llm_proxy._consolidate_dept_day(dept, day)
        assert res["created"] == 1 and res["updated"] == 1 and res["deleted"] == 1 and res["noop"] == 1
        # ADD создал активный факт
        rows = llm_proxy._query("SELECT id FROM facts WHERE dept=? AND content='отчёт по пятницам' AND status='active'", (dept,), fetch=True)
        assert rows

    def test_llm_failure_not_crash(self, monkeypatch):
        dept = f"qa_{uuid.uuid4().hex[:6]}"
        day = "2026-09-10"
        _seed_dialog(dept, "user", "привет", day)

        def boom(d, m):
            raise RuntimeError("network down")
        monkeypatch.setattr(_rt, "call_llm", boom)
        res = llm_proxy._consolidate_dept_day(dept, day)
        assert res.get("error") == "llm_failed"

    def test_unparseable_reply(self, monkeypatch):
        dept = f"qa_{uuid.uuid4().hex[:6]}"
        day = "2026-09-10"
        _seed_dialog(dept, "user", "привет", day)
        monkeypatch.setattr(_rt, "call_llm", lambda d, m: {
            "reply": "мне кажется вы имели в виду...", "provider": "t", "model": "t"})
        res = llm_proxy._consolidate_dept_day(dept, day)
        assert res.get("error") == "unparseable_reply"

    def test_no_dialogs_skipped(self):
        res = llm_proxy._consolidate_dept_day("empty_dept_xyz", "2026-09-10")
        assert res.get("skipped") == "no_dialogs"

    def test_consolidation_trace_written(self, monkeypatch):
        dept = f"qa_{uuid.uuid4().hex[:6]}"
        day = "2026-09-10"
        _seed_dialog(dept, "user", "факт дня", day)
        ops = {"ops": [{"op": "ADD", "content": "атомарный факт", "confidence": 0.9}]}
        monkeypatch.setattr(_rt, "call_llm", lambda d, m: {
            "reply": json.dumps(ops), "provider": "test", "model": "m", "tokens_in": 5, "tokens_out": 7})
        llm_proxy._consolidate_dept_day(dept, day)
        # Трейс FO-004 с trace_type=memory_consolidation записан
        trace_dir = llm_proxy._TRACE_DIR
        found = False
        for name in os.listdir(trace_dir):
            if name.endswith(".jsonl"):
                content = open(os.path.join(trace_dir, name), encoding="utf-8").read()
                if "memory_consolidation" in content and dept in content:
                    found = True
                    break
        assert found, "consolidation counter must appear in FO-004 traces"


class TestConsolidateEndpoint:
    def test_auth_required(self, client):
        r = client.post("/cron/consolidate-memory?secret=wrong", json={"days": 1})
        assert r.status_code == 403

    def test_run_no_dialogs(self, client):
        r = client.post("/cron/consolidate-memory?secret=cron-test-secret",
                        json={"days": 1, "dept": "nonexistent_dept"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"


class TestContextCmd:
    def test_facts_in_context(self, client):
        dept = f"qa_{uuid.uuid4().hex[:6]}"
        _seed_fact(dept, "ключевой факт контекста")
        r = client.post("/context_cmd", json={"dept": dept, "chat_id": "0"})
        assert r.status_code == 200
        data = r.get_json()
        assert any("ключевой факт контекста" in f["content"] for f in data.get("facts", []))
