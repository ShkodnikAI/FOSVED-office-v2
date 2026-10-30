"""№850 (Metalogos gh#1674, волна 73 — W-M): restore вместо hard DELETE.

Критерии «сделано, когда» (наряд gh#1674):
- ни одного физического DELETE в ночном цикле — soft-delete purged_at;
- purged исключён из recall/answer/stats по умолчанию;
- FosvedMemory.restore(memory_id) возвращает запись в активную выдачу;
- nightly-отчёт показывает purged-счётчик (честная статистика вместо «Cleaned»);
- пороги retention в константах класса рядом с DECAY_RATES (значения прежние).
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.fosved_memory import FosvedMemory  # noqa: E402


@pytest.fixture()
def mem(tmp_path):
    m = FosvedMemory(str(tmp_path / 'mem850.db'))
    yield m
    m.close()


def _insert(mem, content, mem_type, confidence, created_at):
    cur = mem.db.execute(
        "INSERT INTO typed_memories (content, type, confidence, source, created_at) "
        "VALUES (?,?,?,?,?)", (content, mem_type, confidence, "test:n850", created_at))
    mem.db.commit()
    return cur.lastrowid


class TestSoftDelete:
    """№850.1: nightly переводит строки в purged вместо DELETE."""

    def test_nightly_purges_stale_observation_not_deletes(self, mem):
        old_id = _insert(mem, "устаревшее наблюдение про интеграцию",
                         "observation", 0.4, time.time() - 40 * 86400)
        mem.nightly_maintenance()
        row = mem.db.execute(
            "SELECT purged_at FROM typed_memories WHERE id=?", (old_id,)).fetchone()
        assert row is not None, "строка физически удалена — hard DELETE запрещён (№850)"
        assert row["purged_at"] is not None, "строка не переведена в purged"

    def test_nightly_purges_stale_pattern(self, mem):
        old_id = _insert(mem, "устаревший паттерн про деплой",
                         "pattern", 0.2, time.time() - 70 * 86400)
        mem.nightly_maintenance()
        row = mem.db.execute(
            "SELECT purged_at FROM typed_memories WHERE id=?", (old_id,)).fetchone()
        assert row is not None and row["purged_at"] is not None

    def test_fresh_records_untouched(self, mem):
        fresh_id = _insert(mem, "свежее наблюдение про CI",
                           "observation", 0.4, time.time() - 2 * 86400)
        good_id = _insert(mem, "наблюдение с высокой уверенностью",
                          "observation", 0.8, time.time() - 40 * 86400)
        mem.nightly_maintenance()
        for mid in (fresh_id, good_id):
            row = mem.db.execute(
                "SELECT purged_at FROM typed_memories WHERE id=?", (mid,)).fetchone()
            assert row is not None and row["purged_at"] is None

    def test_purge_idempotent(self, mem):
        _insert(mem, "старое наблюдение для повтора",
                "observation", 0.4, time.time() - 40 * 86400)
        r1 = mem.nightly_maintenance()
        r2 = mem.nightly_maintenance()
        assert "Purged stale observations: 1" in r1
        assert "Purged stale observations: 0" in r2


class TestPurgedExcluded:
    """№850.1: recall/answer/stats исключают purged по умолчанию."""

    def test_purged_not_in_recall(self, mem):
        _insert(mem, "наблюдение которое уйдёт в корзину",
                "observation", 0.9, time.time())
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=1",
                       (time.time(),))
        mem.db.commit()
        assert mem.recall("наблюдение которое уйдёт") == []

    def test_purged_not_in_answer(self, mem):
        _insert(mem, "факт для ответа который спрячут", "fact", 0.9, time.time())
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=1",
                       (time.time(),))
        mem.db.commit()
        assert "нет" in mem.answer("факт для ответа").lower() or \
            mem.answer("факт для ответа") == "No relevant memories found."

    def test_purged_not_in_stats_total(self, mem):
        _insert(mem, "активный факт для статистики", "fact", 0.9, time.time())
        _insert(mem, "удалённый факт для статистики", "fact", 0.9, time.time())
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=2",
                       (time.time(),))
        mem.db.commit()
        s = mem.stats()
        assert s["total_active"] == 1
        assert s["purged"] == 1

    def test_recall_include_purged_shows(self, mem):
        _insert(mem, "спрятанное наблюдение для флага", "observation", 0.9, time.time())
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=1",
                       (time.time(),))
        mem.db.commit()
        assert mem.recall("спрятанное наблюдение") == []
        res = mem.recall("спрятанное наблюдение", include_purged=True)
        assert len(res) == 1

    def test_purged_not_in_conflicts(self, mem):
        _insert(mem, "билд проходит за 120 секунд", "fact", 0.9, time.time())
        _insert(mem, "билд проходит за 180 секунд", "fact", 0.9, time.time())
        assert len(mem.detect_conflicts()) == 1
        mem.db.execute("UPDATE typed_memories SET purged_at=? WHERE id=2",
                       (time.time(),))
        mem.db.commit()
        assert mem.detect_conflicts() == []


class TestRestore:
    """№850.2: restore(memory_id) возвращает запись в активную выдачу."""

    def test_restore_returns_record(self, mem):
        old_id = _insert(mem, "наблюдение которое вернут",
                         "observation", 0.4, time.time() - 40 * 86400)
        mem.nightly_maintenance()
        assert mem.recall("наблюдение которое вернут") == []
        assert mem.restore(old_id) is True
        res = mem.recall("наблюдение которое вернут")
        assert len(res) == 1
        row = mem.db.execute(
            "SELECT purged_at FROM typed_memories WHERE id=?", (old_id,)).fetchone()
        assert row["purged_at"] is None

    def test_restore_unknown_id_false(self, mem):
        assert mem.restore(999999) is False


class TestNightlyReport:
    """№850.4: честная статистика вместо «Cleaned»."""

    def test_report_shows_purged_counter(self, mem):
        _insert(mem, "старое наблюдение для отчёта",
                "observation", 0.4, time.time() - 40 * 86400)
        report = mem.nightly_maintenance()
        assert "Purged stale observations: 1" in report
        assert "Cleaned" not in report
        assert "Purged stale patterns" in report

    def test_report_shows_restorable_total(self, mem):
        _insert(mem, "старое наблюдение для корзины",
                "observation", 0.4, time.time() - 40 * 86400)
        mem.nightly_maintenance()
        report = mem.nightly_maintenance()
        assert "Purged restorable: 1" in report


class TestRetentionConstants:
    """№850.3: пороги retention в константах класса (значения прежние)."""

    def test_constants_exist(self):
        assert FosvedMemory.RETENTION_OBSERVATION_DAYS == 30
        assert FosvedMemory.RETENTION_OBSERVATION_CONF == 0.5
        assert FosvedMemory.RETENTION_PATTERN_DAYS == 60
        assert FosvedMemory.RETENTION_PATTERN_CONF == 0.3
