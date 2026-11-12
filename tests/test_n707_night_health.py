#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #707 NIGHT-3: шапка ночного отчёта «здоровье ?/10» — разрешение
из живых фаз этой ночи.

Факт: прод 11.11 — AdminNightCycle упал на фазе 3 → kv admin_last_health
не записан → шапка «?», хотя UA Health 1/10 был жив в теле того же отчёта.

Гварды (структурные; живые сценарии A/B — в tests/test_n687_night_slot.py):
- A.1: health_score из результата UA-фазы — в переменную слота (ua_health);
- A.2: разрешение приоритетом источников — свежий (ts ≥ старта слота,
  разбор to_float_or №514) mlog-Reviewer health ≠ «?» → UA → «?»;
  UA-источник помечается « (UA)» в шапке; разрешённое значение — в
  review_json и INSERT (консистентность БД и отчёта);
- A.2 (запись): admin_last_health_ts кладётся рядом с обеими записями
  admin_last_health (после фазы 2 #705 A.3 и дубль в Phase 7);
- мутация «убрать ts-проверку» — гвард краснеет (точная строка условия).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n707')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")


def _segment(text: str, marker: str) -> str:
    start = text.index(marker)
    nxt = text.find("\npattern ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


class TestA1UaHealthScore:
    def test_extracted_next_to_summary(self):
        slot = _segment(APP, "pattern NightSlot()")
        assert 'let mut ua_health = "?"' in slot
        assert 'json_get(ua_parsed, "health_score", "?")' in slot

    def test_slot_start_captured(self):
        slot = _segment(APP, "pattern NightSlot()")
        assert "let slot_started = now()" in slot


class TestA2Resolution:
    def test_freshness_by_ts(self):
        slot = _segment(APP, "pattern NightSlot()")
        # разбор — to_float_or (№514), сравнение — со стартом слота
        assert 'to_float_or(kv_get("admin_last_health_ts"), 0.0)' in slot
        # мутация «убрать ts-проверку» — красит этот гвард (точная строка)
        assert 'if kv_health != "" and kv_health != "?" and kv_ts >= slot_started then {' in slot

    def test_priority_and_ua_mark(self):
        slot = _segment(APP, "pattern NightSlot()")
        # приоритет источников: свежий mlog-Reviewer ≠ «?» → UA → «?»
        assert 'let mut health_src = ""' in slot
        assert 'health_src = " (UA)"' in slot
        # пометка — только в шапке (outbox), формат шапки не менялся иначе
        assert '"/10" + health_src' in slot

    def test_resolved_value_in_db_and_report(self):
        slot = _segment(APP, "pattern NightSlot()")
        # review_json и INSERT используют разрешённое значение (консистентность)
        assert "health: health_last" in slot
        assert "health_num" in slot and "to_int(health_last)" in slot

    def test_admin_mlog_writes_ts(self):
        seg = _segment(ADMIN, "pattern AdminNightCycle")
        # обе записи admin_last_health (после фазы 2 — #705 A.3, дубль Phase 7)
        # сопровождаются меткой времени той же записью
        assert seg.count('kv_set("admin_last_health", health)') == 2
        assert seg.count('kv_set("admin_last_health_ts", to_string(now()))') == 2
        # метка стоит рядом (после) каждой записи здоровья
        i1 = seg.index('kv_set("admin_last_health", health)')
        i2 = seg.index('kv_set("admin_last_health_ts", to_string(now()))')
        i3 = seg.index('kv_set("admin_last_health", health)', i1 + 1)
        i4 = seg.index('kv_set("admin_last_health_ts", to_string(now()))', i2 + 1)
        assert i1 < i2 < i3 < i4
