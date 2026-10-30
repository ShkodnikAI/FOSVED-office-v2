"""FO-020 tests: review-очередь выведенного — approve/decline/undo.

Наряд #86 (пакет G). Критерии «сделано, когда»:
- «вывод → очередь → approve повышает вес / decline убирает» — end-to-end
  на уровне API/ранжирования (Telegram-кнопки — mlog, см. аудит);
- невыверенное действительно ниже в выдаче (тест ранжирования);
- все решения в audit_log; undo работает.
"""
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo20-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['CRON_SECRET'] = 'cron-test-secret'

import llm_proxy  # noqa: E402
from proxy import review as rv  # noqa: E402
from proxy.core import _query  # noqa: E402
from lib.fosved_memory import FosvedMemory  # noqa: E402


@pytest.fixture()
def clean():
    _query("DELETE FROM facts")
    _query("DELETE FROM knowledge_graph")
    _query("DELETE FROM audit_log")
    _query("DELETE FROM dialog_history")  # персистентная тестовая БД
    yield


def _seed_fact(content, dept="qa", parent_count=2, review_status="pending",
               inference=1, status="active"):
    _query(
        "INSERT INTO facts (dept, chat_id, content, status, source_dialog_ids, confidence, "
        "created_at, updated_at, inference, review_status, parent_count) "
        "VALUES (?, '0', ?, ?, json_array(11, 12, 13, 14), 0.9, datetime('now'), "
        "datetime('now'), ?, ?, ?)",
        (dept, content, status, inference, review_status, parent_count))
    rows = _query("SELECT id FROM facts WHERE content=?", (content,), fetch=True)
    return rows[0]["id"]


def _seed_kg(node_name, description="desc", parent_count=3, review_status="pending"):
    _query(
        "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, "
        "updated_at, valid_from, inference, review_status, parent_count) "
        "VALUES ('pattern', ?, 'f1.py', ?, datetime('now'), datetime('now'), 1, ?, ?)",
        (node_name, description, review_status, parent_count))
    rows = _query("SELECT id FROM knowledge_graph WHERE node_name=?", (node_name,), fetch=True)
    return rows[0]["id"]


# ────────────────────────── пометки inference ──────────────────────────

class TestMarking:
    def test_consolidation_marks_inference(self, clean, monkeypatch):
        """FO-006 ставит inference=1, pending, parent_count=диалоги автоматически."""
        import proxy.routes_tail as rt
        day = "2026-09-11"
        for i in range(3):
            _query("INSERT INTO dialog_history (chat_id, role, dept, content, created_at) "
                   "VALUES ('0', 'user', 'qa', ?, ?)", (f"диалог {i}", f"{day} 10:0{i}:00"))
        ops = json.dumps({"ops": [
            {"op": "ADD", "content": f"выведенный факт {uuid.uuid4().hex[:6]}", "confidence": 0.9}]})
        monkeypatch.setattr(rt, "call_llm", lambda *a, **kw: {"reply": ops})
        res = rt._consolidate_dept_day("qa", day)
        assert res.get("created") == 1
        row = _query("SELECT inference, review_status, parent_count, source_dialog_ids "
                     "FROM facts ORDER BY id DESC LIMIT 1", fetch=True)[0]
        assert row["inference"] == 1
        assert row["review_status"] == "pending"
        assert row["parent_count"] == 3  # 3 диалога-источника
        sources = json.loads(row["source_dialog_ids"])
        assert len(sources) == 3

    def test_kg_scan_marks_inference(self, clean):
        """FO-009 ставит inference=1, pending; parent_count из истории file_path."""
        from proxy.kg import kg_scan_rebuild
        # предыстория: узел уже встречался в двух файлах
        _query("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, "
               "valid_from, valid_to) VALUES ('pattern', 'histnode', 'a.py', 'd1', datetime('now'), datetime('now'))")
        _query("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, "
               "valid_from) VALUES ('pattern', 'histnode', 'b.py', 'd1', datetime('now'))")
        nodes = [{"node_type": "pattern", "node_name": "histnode",
                  "file_path": "c.py", "description": "новая формулировка"}]
        kg_scan_rebuild(nodes, source="test")
        row = _query("SELECT inference, review_status, parent_count FROM knowledge_graph "
                     "WHERE valid_to IS NULL AND node_name='histnode'", fetch=True)[0]
        assert row["inference"] == 1
        assert row["review_status"] == "pending"
        assert row["parent_count"] >= 2  # a.py + b.py (+ возможно c.py)


# ────────────────────────── очередь ──────────────────────────

class TestQueue:
    def test_sorted_by_parent_count_desc(self, clean):
        f1 = _seed_fact("низкий вес вывода", parent_count=1)
        f2 = _seed_fact("сильный вывод", parent_count=5)
        k1 = _seed_kg("strong_node", parent_count=3)
        items = rv.get_review_queue(limit=10)
        assert [i["id"] for i in items[:1]] == [f2]  # сильнейший сверху
        pcs = [i["parent_count"] for i in items]
        assert pcs == sorted(pcs, reverse=True)
        assert {i["source"] for i in items} == {"fact", "kg"}

    def test_source_filter(self, clean):
        _seed_fact("только факт")
        _seed_kg("only_kg")
        items = rv.get_review_queue(limit=10, source="kg")
        assert items and all(i["source"] == "kg" for i in items)

    def test_declined_leave_queue(self, clean):
        fid = _seed_fact("временно в очереди")
        rv.decide_review(fid, "fact", "decline", reason="догадка")
        items = rv.get_review_queue(limit=10, source="fact")
        assert fid not in [i["id"] for i in items]

    def test_queue_depth(self, clean):
        _seed_fact("p1")
        _seed_fact("p2")
        _seed_kg("kp")
        assert rv.queue_depth() == 3


# ────────────────────────── решения ──────────────────────────

class TestDecisions:
    def test_approve_decline_undo_cycle(self, clean):
        """approve → undo → decline → undo; все статусы в БД."""
        fid = _seed_fact("цикл решений")
        r = rv.decide_review(fid, "fact", "approve")
        assert r["review_status"] == "approved"
        st = _query("SELECT review_status FROM facts WHERE id=?", (fid,), fetch=True)[0]
        assert st["review_status"] == "approved"
        r = rv.decide_review(fid, "fact", "undo")
        assert r["review_status"] == "pending"
        r = rv.decide_review(fid, "fact", "decline", reason="не подтверждено")
        assert r["review_status"] == "declined"
        st = _query("SELECT review_status, decline_reason FROM facts WHERE id=?",
                    (fid,), fetch=True)[0]
        assert st["review_status"] == "declined"
        assert "подтверждено" in (st["decline_reason"] or "")
        # soft-delete: строка остаётся
        assert _query("SELECT content FROM facts WHERE id=?", (fid,), fetch=True)
        rv.decide_review(fid, "fact", "undo")
        st = _query("SELECT review_status FROM facts WHERE id=?", (fid,), fetch=True)[0]
        assert st["review_status"] == "pending"

    def test_kg_decisions(self, clean):
        kid = _seed_kg("kg_cycle")
        rv.decide_review(kid, "kg", "approve")
        st = _query("SELECT review_status FROM knowledge_graph WHERE id=?",
                    (kid,), fetch=True)[0]
        assert st["review_status"] == "approved"

    def test_all_decisions_in_audit_log(self, clean):
        """Критерий: все решения в audit_log (кто, когда, что)."""
        fid = _seed_fact("аудит-факт")
        tag = uuid.uuid4().hex[:6]
        rv.decide_review(fid, "fact", "approve", actor="owner")
        rv.decide_review(fid, "fact", "decline", reason="причина-" + tag, actor="owner")
        rows = _query("SELECT action, details FROM audit_log WHERE action LIKE 'review_%' "
                      "ORDER BY id DESC LIMIT 2", fetch=True)
        actions = {r["action"] for r in rows}
        assert {"review_approve", "review_decline"} <= actions
        assert any("причина-" + tag in (r["details"] or "") for r in rows)

    def test_invalid_args_rejected(self, clean):
        with pytest.raises(ValueError):
            rv.decide_review(1, "bananas", "approve")
        with pytest.raises(ValueError):
            rv.decide_review(1, "fact", "maybe")
        with pytest.raises(LookupError):
            rv.decide_review(999999, "fact", "approve")


# ────────────────────────── вес в ранжировании ──────────────────────────

class TestRanking:
    def _mem(self, tmp_path):
        return FosvedMemory(str(tmp_path / "mem.db"))

    def test_pending_lower_than_approved(self, tmp_path):
        """Критерий: невыверенное действительно ниже в выдаче (тест ранжирования)."""
        mem = self._mem(tmp_path)
        mem.remember("одобренный вывод: проект альфа заморожен", mem_type="fact",
                     confidence=0.9, source="test")
        mem.remember("невыверенный вывод: проект альфа заморожен", mem_type="fact",
                     confidence=0.9, source="test")
        # помечаем вторую как pending (как сделал бы FO-006/авто-вывод)
        mem.db.execute("UPDATE typed_memories SET inference=1, review_status='pending' "
                       "WHERE content LIKE 'невыверенный%'")
        mem.db.commit()
        res = mem.recall("проект альфа", limit=5)
        assert len(res) == 2
        by_status = {m["review_status"]: m["relevance"] for m in res}
        assert by_status["pending"] < by_status["approved"]
        assert abs(by_status["pending"] / by_status["approved"] - 0.5) < 0.01  # штраф 0.5

    def test_declined_excluded_from_recall(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.remember("отклонённая запись проекта бета", mem_type="fact", confidence=0.9, source="test:fo020")
        mem.db.execute("UPDATE typed_memories SET review_status='declined' "
                       "WHERE content LIKE 'отклонённая%'")
        mem.db.commit()
        res = mem.recall("проект бета", limit=5)
        assert res == []  # soft-delete: из выдачи убрано

    def test_legacy_rows_full_weight(self, tmp_path):
        """Строки до FO-020 (review_status NULL/default) — полный вес."""
        mem = self._mem(tmp_path)
        mem.remember("легаси-вывод: проект гамма заморожен", mem_type="fact", confidence=0.9, source="test:fo020")
        row = mem.recall("проект гамма", limit=1)[0]
        assert (row["review_status"] or "approved") in ("approved", None)
        assert row["relevance"] > 0


# ────────────────────────── уведомление и API ──────────────────────────

class TestWiring:
    def test_overflow_notification(self, clean, monkeypatch):
        """Очередь > 50 → уведомление владельцу (Telegram send замокан)."""
        sent = []
        monkeypatch.setattr("proxy.telegram._tg_send_message",
                            lambda cid, text, **kw: sent.append((cid, text)))
        for i in range(52):
            _seed_fact(f"переполнение {i}")
        res = rv.notify_queue_overflow_if_needed(threshold=50)
        assert res and res["notified"] is True and res["depth"] == 52
        assert sent and sent[0][0] == "12345"
        assert "52" in sent[0][1]
        # ниже порога — тишина
        _query("DELETE FROM facts")
        assert rv.notify_queue_overflow_if_needed(threshold=50) is None

    def test_queue_and_decide_endpoints(self, clean):
        client = llm_proxy.app.test_client()
        _seed_fact("эндпоинт-факт")
        r = client.post("/review/queue", json={"limit": 5})
        assert r.status_code == 200
        body = r.get_json()
        assert body["count"] >= 1 and body["depth"] >= 1
        item = body["items"][0]
        r2 = client.post("/review/decide", json={
            "item_id": item["id"], "source": item["source"], "decision": "approve"})
        assert r2.status_code == 200
        assert r2.get_json()["review_status"] == "approved"
        # невалидные решения — 400/404
        assert client.post("/review/decide", json={
            "item_id": 1, "source": "fact", "decision": "maybe"}).status_code == 400
        assert client.post("/review/decide", json={
            "item_id": 999999, "source": "fact", "decision": "approve"}).status_code == 404

    def test_facade_exports(self):
        for name in ("get_review_queue", "decide_review", "review_queue_depth",
                     "notify_queue_overflow_if_needed"):
            assert hasattr(llm_proxy, name), f"facade lost {name}"

    def test_review_endpoints_exist(self):
        rules = [str(r) for r in llm_proxy.app.url_map.iter_rules()]
        assert "/review/queue" in rules and "/review/decide" in rules
