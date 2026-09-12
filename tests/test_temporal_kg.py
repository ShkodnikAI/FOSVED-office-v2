"""FO-009: темпоральный knowledge_graph — миграция, версии, чтение, конфликты."""
import os
import sys
import sqlite3
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-kg-test")

import proxy.kg as kg  # noqa: E402


@pytest.fixture
def fresh_kg(monkeypatch):
    """Чистая таблица knowledge_graph на время теста (init_db уже создал схему)."""
    import llm_proxy
    llm_proxy._query("DELETE FROM knowledge_graph")
    llm_proxy._query("DELETE FROM admin_findings WHERE category = 'kg_entity_conflict'")
    yield llm_proxy
    llm_proxy._query("DELETE FROM knowledge_graph")
    llm_proxy._query("DELETE FROM admin_findings WHERE category = 'kg_entity_conflict'")


def _rows(llm_proxy, **kw):
    return llm_proxy._query("SELECT * FROM knowledge_graph", fetch=True) or []


class TestMigration:
    """Миграция legacy-схемы: узлы сохраняются, valid_from заливается."""

    def test_old_db_migrates_without_loss(self, tmp_path):
        db = tmp_path / "old.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT, "
                  "file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')))")
        c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) "
                  "VALUES ('file', 'app.mlog', 'app.mlog', 'legacy node', '2026-01-01 00:00:00')")
        c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description) "
                  "VALUES ('pattern', 'Main', 'app.mlog', 'entry')")
        c.commit()
        cols = {r[1] for r in c.execute("PRAGMA table_info(knowledge_graph)")}
        assert "valid_from" not in cols
        c.close()

        # миграция = ALTERs + backfill (логика init_db; повторяем шаги вручную на копии)
        c = sqlite3.connect(str(db))
        for col_sql in ("ALTER TABLE knowledge_graph ADD COLUMN valid_from TEXT",
                        "ALTER TABLE knowledge_graph ADD COLUMN valid_to TEXT",
                        "ALTER TABLE knowledge_graph ADD COLUMN superseded_by INTEGER"):
            try:
                c.execute(col_sql)
            except sqlite3.OperationalError:
                pass
        c.execute("UPDATE knowledge_graph SET valid_from = updated_at WHERE valid_from IS NULL")
        c.commit()

        rows = c.execute("SELECT node_name, valid_from FROM knowledge_graph ORDER BY id").fetchall()
        assert len(rows) == 2  # узлы не потеряны
        assert all(r[1] is not None for r in rows)  # valid_from заполнен
        assert rows[0][1] == "2026-01-01 00:00:00"
        c.close()


class TestUpsert:
    def test_new_then_noop(self, fresh_kg):
        nid, action = kg.kg_upsert("file", "app.mlog", "app.mlog", "dispatcher")
        assert action == "new"
        nid2, action2 = kg.kg_upsert("file", "app.mlog", "app.mlog", "dispatcher")
        assert action2 == "noop"
        assert nid2 == nid  # тот же узел, дубля нет
        assert len(_rows(fresh_kg)) == 1

    def test_update_closes_old_and_links(self, fresh_kg):
        nid1, a1 = kg.kg_upsert("pattern", "Main", "app.mlog", "entry v1")
        assert a1 == "new"
        nid2, a2 = kg.kg_upsert("pattern", "Main", "app.mlog", "entry v2")
        assert a2 == "updated"
        old = fresh_kg._query("SELECT * FROM knowledge_graph WHERE id = ?", (nid1,), fetch=True)[0]
        new = fresh_kg._query("SELECT * FROM knowledge_graph WHERE id = ?", (nid2,), fetch=True)[0]
        assert old["valid_to"] is not None          # старая версия закрыта
        assert old["superseded_by"] == nid2          # и связана с новой
        assert new["valid_to"] is None               # новая актуальна
        assert new["valid_from"] is not None
        assert len(_rows(fresh_kg)) == 2             # история не потеряна

    def test_entity_conflict_reported_to_admin(self, fresh_kg):
        # один и тот же ключ, два активных узла с разными file_path — конфликт
        fresh_kg._query("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, valid_from) "
                        "VALUES ('pattern', 'X', 'a.mlog', '', datetime('now'))", ())
        fresh_kg._query("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, valid_from) "
                        "VALUES ('pattern', 'X', 'b.mlog', '', datetime('now'))", ())
        nid, action = kg.kg_upsert("pattern", "X", "c.mlog", "")
        assert action == "updated"
        findings = fresh_kg._query("SELECT * FROM admin_findings WHERE category = 'kg_entity_conflict'", fetch=True)
        assert len(findings) == 1
        assert "a.mlog" in findings[0]["issue"] and "b.mlog" in findings[0]["issue"]
        # конфлик versions closed, каноничная одна
        active = kg.kg_active("pattern")
        assert [r["node_name"] for r in active] == ["X"]
        assert active[0]["file_path"] == "c.mlog"


class TestRebuild:
    def test_scan_rebuild_preserves_history(self, fresh_kg):
        kg.kg_upsert("file", "a.mlog", "a.mlog", "v1")
        kg.kg_upsert("file", "b.mlog", "b.mlog", "exists")
        kg.kg_upsert("file", "c.mlog", "c.mlog", "will disappear")
        before = len(_rows(fresh_kg))

        res = kg.kg_scan_rebuild([
            {"node_type": "file", "node_name": "a.mlog", "file_path": "a.mlog", "description": "v2"},  # updated
            {"node_type": "file", "node_name": "b.mlog", "file_path": "b.mlog", "description": "exists"},  # noop
            {"node_type": "file", "node_name": "d.mlog", "file_path": "d.mlog", "description": "brand new"},  # new
        ], source="test")
        assert res["updated"] == 1
        assert res["noop"] == 1
        assert res["inserted"] == 1
        assert res["closed_missing"] == 1  # c.mlog закрыт, не стёрт

        after = len(_rows(fresh_kg))
        assert after > before  # история росла
        names = {r["node_name"] for r in kg.kg_active()}
        assert "c.mlog" not in names  # исчезнувший не актуален
        assert "c.mlog" in {r["node_name"] for r in _rows(fresh_kg)}  # но в истории остался


class TestRead:
    def test_active_only(self, fresh_kg):
        kg.kg_upsert("route", "/x", "app.mlog", "GET")
        kg.kg_upsert("route", "/x", "app.mlog", "POST")  # версия 2
        active = kg.kg_active("route")
        assert len(active) == 1
        assert active[0]["description"] == "POST"

    def test_history_chain(self, fresh_kg):
        kg.kg_upsert("pattern", "Main", "app.mlog", "v1")
        kg.kg_upsert("pattern", "Main", "app.mlog", "v2")
        kg.kg_upsert("pattern", "Main", "app.mlog", "v3")
        hist = kg.kg_history("pattern", "Main")
        assert len(hist) == 3
        descs = [r["description"] for r in hist]
        assert descs == ["v3", "v2", "v1"]  # новые сверху
        # цепочка superseded_by
        ids = [r["id"] for r in hist]
        assert hist[1]["superseded_by"] == ids[0]
        assert hist[2]["superseded_by"] == ids[1]

    def test_as_of_query(self, fresh_kg):
        nid1, _ = kg.kg_upsert("route", "/old", "app.mlog", "GET")
        # эмулируем прошлое: версия действовала час и была закрыта два часа назад
        fresh_kg._query("UPDATE knowledge_graph SET valid_from = datetime('now', '-3 hours'), "
                        "valid_to = datetime('now', '-2 hours') WHERE id = ?", (nid1,))
        nid2, _ = kg.kg_upsert("route", "/old", "app.mlog", "PUT")
        fresh_kg._query("UPDATE knowledge_graph SET valid_from = datetime('now', '-1 hour') WHERE id = ?", (nid2,))

        at_old = kg.kg_active(as_of=datetime_utc(2, 30))
        assert [r["description"] for r in at_old if r["node_name"] == "/old"] == ["GET"]
        at_now = kg.kg_active()
        assert [r["description"] for r in at_now if r["node_name"] == "/old"] == ["PUT"]


def datetime_utc(hours_ago, minutes_ago=0):
    """Момент N часов/минут назад (строка для сравнения с SQLite-датами)."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago, minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
