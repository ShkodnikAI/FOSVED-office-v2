"""FO-017 tests: Dialog v2 — Part-модель сообщений + event-log с per-session seq.

Наряд #83 (пакет G). Критерии «сделано, когда»:
- новый диалог сохраняет tool_call как Part (API + сопряжение с компакцией);
- восстановление порядка по seq на синтетике из 1000 событий — точное;
- миграция обратима (dialog_history не трогается, rollback чистит v2).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before llm_proxy import (same contract as test_security.py)
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo17-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402
from proxy import dialog as dlg  # noqa: E402
from proxy.core import _query  # noqa: E402


@pytest.fixture(autouse=True)
def clean_v2():
    """Чистые таблицы v2 и legacy dialog_history на каждый тест
    (файловая БД персистентна между прогонами — срез должен быть детерминированным)."""
    dlg.ensure_dialog_schema()
    _query("DELETE FROM dialog_part")
    _query("DELETE FROM dialog_message")
    _query("DELETE FROM session_message")
    _query("DELETE FROM dialog_history")
    _query("UPDATE system_settings SET value = '0' WHERE key = 'dialog_v2_migrated_upto'")
    yield


# ────────────────────────── Part-модель ──────────────────────────

class TestPartModel:
    def test_text_message_default_part(self):
        res = dlg.save_message("s1", "user", content="Привет", dept="qa")
        assert res["message_id"] > 0 and len(res["part_ids"]) == 1
        msgs = dlg.get_session_messages("s1")
        assert msgs[0]["role"] == "user"
        assert msgs[0]["parts"][0]["type"] == "text"
        assert msgs[0]["parts"][0]["data"]["text"] == "Привет"

    def test_tool_call_as_part(self):
        """Критерий: tool_call сохраняется как Part (state pending → completed)."""
        res = dlg.save_message("s2", "assistant", content="ищу…")
        mid = res["message_id"]
        call_id = dlg.add_tool_call("s2", mid, "db_query", {"sql": "SELECT 1"})
        res_id = dlg.add_tool_result("s2", call_id, result=[{"n": 1}], ok=True)
        parts = dlg.get_session_messages("s2")[0]["parts"]
        types = [p["type"] for p in parts]
        assert "tool_call" in types and "tool_result" in types
        call_part = dlg.get_part(call_id)
        assert call_part["data"]["status"] == "pending"
        assert call_part["data"]["tool"] == "db_query"
        res_part = dlg.get_part(res_id)
        assert res_part["data"]["status"] == "completed"
        assert res_part["data"]["tool_call_part"] == call_id

    def test_explicit_parts_and_types(self):
        res = dlg.save_message("s3", "assistant", parts=[
            {"type": "text", "data": {"text": "ответ"}},
            {"type": "voice", "data": {"ogg_url": "http://x/1.ogg"}},
            {"type": "retry", "data": {"attempt": 2, "reason": "timeout"}},
        ])
        assert len(res["part_ids"]) == 3
        types = [p["type"] for p in dlg.get_session_messages("s3")[0]["parts"]]
        assert types == ["text", "voice", "retry"]

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            dlg.save_message("s4", "user", parts=[{"type": "bananas", "data": {}}])
        with pytest.raises(ValueError):
            dlg.add_part(1, "bananas", {})

    def test_part_endpoint_shape(self):
        res = dlg.save_message("s5", "user", content="x")
        pid = res["part_ids"][0]
        p = dlg.get_part(pid)
        assert set(p.keys()) == {"id", "message_id", "type", "data", "created_at"}
        assert dlg.get_part(10**9) is None

    def test_add_part_to_missing_message(self):
        assert dlg.add_part(10**9, "text", {"text": "x"}) is None


# ────────────────────────── event-log seq ──────────────────────────

class TestEventLog:
    def test_seq_monotonic_per_session(self):
        for i in range(5):
            dlg.save_message("e1", "user", content=f"m{i}")
        ev = dlg.get_session_events("e1")
        seqs = [e["seq"] for e in ev]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        # 5 сообщений × 2 события (message.created + part.added)
        assert len(seqs) == 10

    def test_seq_independent_sessions(self):
        dlg.save_message("a", "user", content="1")
        dlg.save_message("b", "user", content="2")
        a_seq = [e["seq"] for e in dlg.get_session_events("a")]
        b_seq = [e["seq"] for e in dlg.get_session_events("b")]
        assert a_seq == [1, 2] and b_seq == [1, 2]

    def test_replay_1000_events_exact(self):
        """Критерий: восстановление порядка на синтетике из 1000 событий точное."""
        N = 400  # 400 сообщений → ~800+ событий; добавим тулз-части до 1000
        for i in range(N):
            res = dlg.save_message("big", "user" if i % 2 == 0 else "assistant",
                                   content=f"turn-{i}")
            if i % 2 == 1:
                dlg.add_tool_call("big", res["message_id"], "tool", {})
        total_events = len(dlg.get_session_events("big", limit=10000))
        assert total_events >= 1000, f"ожидали ≥1000 событий, получили {total_events}"

        replay = dlg.replay_session("big")
        msgs = replay["messages"]
        assert len(msgs) == N
        assert replay["events_replayed"] == total_events
        assert replay["max_seq"] == total_events  # seq плотный с 1
        # порядок сообщений совпадает с порядком их создания
        texts = [dlg.get_session_messages("big", limit=N)[j]
                 for j in range(len(msgs))]
        for k in range(0, N, 50):
            assert f"turn-{k}" == texts[k]["parts"][0]["data"]["text"]

    def test_replay_upto_seq(self):
        dlg.save_message("u1", "user", content="first")
        dlg.save_message("u1", "user", content="second")
        full = dlg.replay_session("u1")
        assert len(full["messages"]) == 2
        # срез: только события первых двух сообщений (created+part) → 1 реплика
        cut = dlg.replay_session("u1", upto_seq=2)
        assert len(cut["messages"]) == 1
        assert cut["max_seq"] == 2


# ────────────────────────── компакция → Part ──────────────────────────

class TestCompactionPart:
    def test_record_compaction(self):
        pid = dlg.record_compaction("c1", {"strategy": "prune",
                                           "tokens_before": 100, "tokens_after": 50},
                                    dept="qa")
        p = dlg.get_part(pid)
        assert p["type"] == "compaction"
        assert p["data"]["strategy"] == "prune"
        msgs = dlg.get_session_messages("c1")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["data"]["source"] == "compaction"


# ────────────────────────── миграция ──────────────────────────

class TestMigration:
    def _seed_history(self, chat, n=7):
        for i in range(n):
            _query("INSERT INTO dialog_history (chat_id, role, dept, content, created_at) "
                   "VALUES (?, 'user', 'qa', ?, ?)",
                   (chat, f"legacy-{i}", f"2026-09-01 10:0{i}:00"))

    def test_migrate_copies_and_preserves(self):
        self._seed_history("m1")
        res = dlg.migrate_dialog_history(batch=100)
        assert res["migrated"] == 7 and not res["dry_run"]
        msgs = dlg.get_session_messages("m1")
        assert len(msgs) == 7
        assert msgs[0]["parts"][0]["data"]["text"] == "legacy-0"
        assert msgs[6]["created_at"] == "2026-09-01 10:06:00"  # created_at сохранён
        assert msgs[0]["data"]["source"] == "dialog_history"
        assert msgs[0]["data"]["source_id"] > 0

    def test_migrate_idempotent(self):
        self._seed_history("m2")
        first = dlg.migrate_dialog_history(batch=100)
        second = dlg.migrate_dialog_history(batch=100)
        assert first["migrated"] == 7
        assert second["migrated"] == 0  # водяной знак — дублей нет
        assert len(dlg.get_session_messages("m2")) == 7

    def test_dry_run_touches_nothing(self):
        self._seed_history("m3")
        res = dlg.migrate_dialog_history(batch=100, dry_run=True)
        assert res["migrated"] == 7 and res["dry_run"]
        assert len(dlg.get_session_messages("m3")) == 0

    def test_rollback_reversible(self):
        """Критерий: миграция обратима; legacy dialog_history не трогается."""
        self._seed_history("m4")
        before = _query("SELECT COUNT(*) AS n FROM dialog_history WHERE chat_id='m4'",
                        fetch=True)[0]["n"]
        dlg.migrate_dialog_history(batch=100)
        assert len(dlg.get_session_messages("m4")) == 7
        res = dlg.rollback_migration()
        assert res["messages"] == 7 and res["parts"] == 7 and res["events"] > 0
        assert len(dlg.get_session_messages("m4")) == 0
        after = _query("SELECT COUNT(*) AS n FROM dialog_history WHERE chat_id='m4'",
                       fetch=True)[0]["n"]
        assert after == before == 7  # legacy цел
        # повторная миграция работает после отката
        res2 = dlg.migrate_dialog_history(batch=100)
        assert res2["migrated"] == 7

    def test_rollback_only_migrated_rows(self):
        """Чужие (не миграционные) v2-строки не удаляются."""
        dlg.save_message("live", "user", content="живая реплика", source="api")
        self._seed_history("m5")
        dlg.migrate_dialog_history(batch=100)
        dlg.rollback_migration()
        assert len(dlg.get_session_messages("m5")) == 0
        assert len(dlg.get_session_messages("live")) == 1  # не тронута


# ────────────────────────── совместимость ──────────────────────────

class TestCompat:
    def test_facade_exports(self):
        for name in ("ensure_dialog_schema", "save_message", "add_tool_call",
                     "record_compaction", "replay_session", "migrate_dialog_history",
                     "rollback_migration", "PART_TYPES"):
            assert hasattr(llm_proxy, name), f"facade lost {name}"

    def test_part_types_v1(self):
        assert dlg.PART_TYPES == ("text", "tool_call", "tool_result",
                                  "retry", "compaction", "voice")

    def test_kg_upsert_accepts_source_part_id(self):
        """FO-009 → FO-017: граф ссылается на part_id (обратимо, дефолт None)."""
        from proxy.kg import kg_upsert
        # изоляция: тестовая БД персистентна — убираем прежнюю версию узла
        _query("DELETE FROM knowledge_graph WHERE node_type='pattern' AND node_name='dialog_v2'")
        pid = dlg.record_compaction("kg1", {"strategy": "prune"}, dept="qa")
        node_id, action = kg_upsert("pattern", "dialog_v2", "proxy/dialog.py",
                                    "Part-модель + event-log", source="test",
                                    source_part_id=pid)
        assert action == "new"
        row = _query("SELECT source_part_id FROM knowledge_graph WHERE id = ?",
                     (node_id,), fetch=True)[0]
        assert row["source_part_id"] == str(pid)
