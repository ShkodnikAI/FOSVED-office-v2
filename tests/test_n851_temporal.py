"""№851 (Metalogos gh#1675, волна 73 — W-M): темпоральные срезы памяти.

Критерии «сделано, когда» (наряд gh#1675):
- supersede фиксирует момент (superseded_at); бэкфорис честный — старым строкам NULL;
- recall_as_of(query, as_of_ts): создано ≤ ts И (не superseded ИЛИ superseded_at > ts);
- recall_changed_since(query, since_ts): созданные или superseded после метки;
- выдача помечает качество среза: as_of_quality exact|approx — аппроксимация
  (legacy-supersede без момента) видна потребителю;
- конфликт двух фактов: срезы ДО и ПОСЛЕ расходятся; changed_since между
  двумя supersede показывает изменение.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.fosved_memory import FosvedMemory  # noqa: E402


@pytest.fixture()
def mem(tmp_path):
    m = FosvedMemory(str(tmp_path / 'mem851.db'))
    yield m
    m.close()


def _insert(mem, content, mem_type, confidence, created_at):
    cur = mem.db.execute(
        "INSERT INTO typed_memories (content, type, confidence, source, created_at) "
        "VALUES (?,?,?,?,?)", (content, mem_type, confidence, "dept:qa", created_at))
    mem.db.commit()
    return cur.lastrowid


def _now() -> float:
    # момент исполнения теста (не импорта) — батарея едет минуты, срезы честны
    return time.time()


class TestSupersedeMoment:
    """№851.1: supersede фиксирует момент; бэкфорис честный (NULL у старых)."""

    def test_resolve_conflict_records_superseded_at(self, mem):
        a = _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 86400)
        b = _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, _now() - 3600)
        mem.resolve_conflict(keep_id=b, supersede_id=a)
        row = mem.db.execute(
            "SELECT superseded_by, superseded_at FROM typed_memories WHERE id=?",
            (a,)).fetchone()
        assert row["superseded_by"] == b
        assert row["superseded_at"] is not None, "момент supersede не зафиксирован"
        assert abs(row["superseded_at"] - _now()) < 60

    def test_remember_conflict_supersede_records_moment(self, mem):
        # auto-supersede в remember(): новый контент — подстрока старого
        # (recall-LIKE) с другим набором чисел (_contradicts)
        a = _insert(mem, "версия 2 версия 3 версия 4", "fact", 0.9, _now() - 86400)
        mem.remember("версия 2", "fact", 0.9, source="dept:qa")
        row = mem.db.execute(
            "SELECT superseded_by, superseded_at FROM typed_memories WHERE id=?",
            (a,)).fetchone()
        assert row["superseded_by"] == -1
        assert row["superseded_at"] is not None

    def test_legacy_backfill_rows_have_null(self, mem):
        # строки, supersede которых случился ДО миграции — moment NULL, не переписывается
        a = _insert(mem, "старый факт до миграции", "fact", 0.9, _now() - 86400)
        mem.db.execute("UPDATE typed_memories SET superseded_by=-1 WHERE id=?", (a,))
        mem.db.commit()
        row = mem.db.execute(
            "SELECT superseded_at FROM typed_memories WHERE id=?", (a,)).fetchone()
        assert row["superseded_at"] is None


class TestRecallAsOf:
    """№851.2: срез «что память знала на дату X»."""

    def _two_versions(self, mem):
        old = _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 5 * 86400)
        new = _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, _now() - 86400)
        mem.resolve_conflict(keep_id=new, supersede_id=old)
        return old, new

    def test_as_of_between_versions_shows_old_only(self, mem):
        old, new = self._two_versions(mem)
        res = mem.recall_as_of("билд", as_of_ts=_now() - 3 * 86400)
        ids = [r["id"] for r in res]
        assert old in ids, "старая версия должна быть видна ДО supersede"
        assert new not in ids, "новая версия создана позже среза"

    def test_as_of_after_versions_shows_new_only(self, mem):
        old, new = self._two_versions(mem)
        res = mem.recall_as_of("билд", as_of_ts=_now() + 60)
        ids = [r["id"] for r in res]
        assert new in ids
        assert old not in ids, "superseded-версия ушла с среза после supersede"

    def test_as_of_before_both_empty(self, mem):
        self._two_versions(mem)
        assert mem.recall_as_of("билд", as_of_ts=_now() - 10 * 86400) == []

    def test_as_of_quality_exact_for_known_moments(self, mem):
        self._two_versions(mem)
        res = mem.recall_as_of("билд", as_of_ts=_now() - 3 * 86400)
        assert all(r["as_of_quality"] == "exact" for r in res)

    def test_as_of_legacy_supersede_is_approx(self, mem):
        """Бэкфорис: supersede без момента → строка на срезе помечена approx."""
        old = _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 5 * 86400)
        new = _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, _now() - 86400)
        mem.resolve_conflict(keep_id=new, supersede_id=old)
        # честная имитация legacy-строки: момент supersede не зафиксирован
        mem.db.execute("UPDATE typed_memories SET superseded_at=NULL WHERE id=?", (old,))
        mem.db.commit()
        res = mem.recall_as_of("билд", as_of_ts=_now() - 3600)
        row = [r for r in res if r["id"] == old][0]
        assert row["as_of_quality"] == "approx"

    def test_as_of_includes_row_purged_after_slice(self, mem):
        """Запись, purged ПОСЛЕ среза, была активна на срезе."""
        mid = _insert(mem, "наблюдение перед корзиной", "observation", 0.9, _now() - 86400)
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=?", (_now(), mid))
        mem.db.commit()
        res = mem.recall_as_of("наблюдение перед корзиной", as_of_ts=_now() - 3600)
        assert [r["id"] for r in res] == [mid]
        assert mem.recall("наблюдение перед корзиной") == []  # текущая выдача пуста

    def test_as_of_excludes_row_purged_before_slice(self, mem):
        mid = _insert(mem, "наблюдение удалённое рано", "observation", 0.9, _now() - 5 * 86400)
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=?",
                       (_now() - 3 * 86400, mid))
        mem.db.commit()
        assert mem.recall_as_of("наблюдение удалённое рано", as_of_ts=_now()) == []


class TestRecallChangedSince:
    """№851.2: срез «что изменилось с даты Y»."""

    def test_changed_since_shows_creation_and_supersede(self, mem):
        old = _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 5 * 86400)
        new = _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, _now() - 86400)
        mem.resolve_conflict(keep_id=new, supersede_id=old)
        res = mem.recall_changed_since("билд", since_ts=_now() - 2 * 86400)
        kinds = {r["id"]: r["change_kind"] for r in res}
        assert kinds.get(new) == "created"
        assert kinds.get(old) == "superseded", "supersede после метки — изменение"

    def test_changed_since_empty_before_all(self, mem):
        old = _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 5 * 86400)
        new = _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, _now() - 86400)
        mem.resolve_conflict(keep_id=new, supersede_id=old)
        # всё создано/superseded ПОСЛЕ метки → обе записи изменились
        res = mem.recall_changed_since("билд", since_ts=_now() - 10 * 86400)
        assert len(res) == 2

    def test_changed_since_after_all_empty(self, mem):
        _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 5 * 86400)
        assert mem.recall_changed_since("билд", since_ts=_now() + 60) == []

    def test_changed_since_between_two_supersedes(self, mem):
        """Между двумя supersede: виден только второй supersede-момент."""
        v1 = _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, _now() - 5 * 86400)
        v2 = _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, _now() - 3 * 86400)
        mem.resolve_conflict(keep_id=v2, supersede_id=v1)
        # фиксируем время первого supersede, разводим моменты, затем второй конфликт
        first_supersede_ts = mem.db.execute(
            "SELECT superseded_at FROM typed_memories WHERE id=?", (v1,)).fetchone()[0]
        time.sleep(1.1)
        v3 = _insert(mem, "билд проходит за 240 секунд", "fact", 0.9, time.time())
        mem.resolve_conflict(keep_id=v3, supersede_id=v2)
        res = mem.recall_changed_since("билд", since_ts=first_supersede_ts + 0.5)
        ids = [r["id"] for r in res]
        assert v1 not in ids, "первый supersede до метки — не изменение"
        assert v2 in ids and v3 in ids
