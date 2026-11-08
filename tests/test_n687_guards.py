#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #687 NIGHT-1 (P0): гварды python-стороны.

A.4 — фактический возраст просрочки вместо константы «(>26 ч)»
      (key_health.build_morning_line, night_report_line);
A.6.1 — просроченная ночная проверка видна разделу внимания брифа
      (collect_attention_items, условие 8) с фактическим возрастом;
A.6.2 — резерв FORGE при нуле проектов — не алерт, строка
      «Резерв FORGE: нечего резервировать (проектов 0)» (backup_forge_repos);
A.2 — структурная гвардия: разборы ответов фаз в NightSlot/NightLzPhase/
      NightUsageKeyLine — только под try (мутация «вернуть голый parse_json»
      ловится структурно, поведенческая — в test_n687_night_slot.py);
A.3 — маршруты проверки ключей сохраняют результат в key_health_status
      (ночная фаза 5 и ручной /admin keys — оба пути).
"""
import importlib.util
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n687-guards')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')
os.environ.setdefault('CRON_SECRET', 'test-cron-secret')

from llm_proxy import *  # noqa: E402,F401,F403 — регистрация маршрутов Flask (конвенция test_n588)
from proxy.core import _query  # noqa: E402
from proxy import key_health, routes_sched  # noqa: E402

APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def _mlog_segment(pattern_decl: str) -> str:
    """Тело одного паттерна app.mlog: от 'pattern NAME' до следующего 'pattern '."""
    start = APP.index(pattern_decl)
    rest = APP[start + len(pattern_decl):]
    nxt = rest.find("\npattern ")
    return rest[:nxt] if nxt != -1 else rest


def _code_lines(src: str) -> list:
    return [l for l in src.splitlines() if not l.strip().startswith("//")]


# ──────────────────────────── A.4: фактический возраст ────────────────────────────

def test_a4_format_age_hours():
    f = key_health.format_age_hours
    assert f(17 * 24 + 5) == "17 сут 5 ч"
    assert f(31.0) == "31 ч"
    assert f(47.9) == "48 ч"
    assert f(72.0) == "3 сут"
    assert f(24.0) == "24 ч"
    assert f(48.0) == "2 сут"
    assert f(49.0) == "2 сут 1 ч"
    assert f(23.4) == "23 ч"


def test_a4_keys_morning_line_actual_age():
    """Отметка 17 сут 5 ч назад → «17 сут 5 ч», не «>26 ч»."""
    _query("DELETE FROM key_health_status", ())
    checked = (datetime.now(timezone.utc) - timedelta(hours=17 * 24 + 5)).strftime("%Y-%m-%d %H:%M:%S")
    for e in key_health.KEY_MANIFEST[:2]:
        key_health.save_result({"env_key": e["env_key"], "status": "ok", "http_code": 200, "detail": ""},
                               checked_at=checked)
    line = key_health.build_morning_line()
    assert "НЕ выполнялась" in line
    assert "17 сут 5 ч" in line, line
    assert ">26 ч" not in line, line


def test_a4_night_line_actual_age():
    """Ночной отчёт 3 суток назад → «3 сут», не «>26 ч»."""
    _query("DELETE FROM admin_night_reports WHERE scan_data='night-slot'", ())
    created = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    _query(
        "INSERT INTO admin_night_reports (scan_data, review_data, health_score, findings_count, created_at) "
        "VALUES ('night-slot', ?, 8.0, 0, ?)",
        ('{"status":"partial (недоступно фаз: 1)","summary":"тест","health":"8"}', created),
    )
    line, age_h = routes_sched.night_report_line()
    assert "НЕ выполнялась" in line and "3 сут" in line, line
    assert ">26 ч" not in line, line
    assert age_h is not None and age_h > 70.0


# ──────────────────────────── A.6: раздел внимания ────────────────────────────

def _collect(**kw):
    base = dict(forge_backup_ok=True, forge_backup_line="создано 2, упало 0, всего 1 МБ (репозиториев 2); smoke-восстановление: ok",
                forge_backup_stale=False, keys_line="🔑 Ключи: все 17 — ok (проверка 2026-11-08 02:05 UTC)",
                dept_fail_line="Отказы отделов за сутки: 0", kk_line="Кавальня (24ч): задано 3",
                forge_attention="", errors_digest="", night_line="")
    base.update(kw)
    return routes_sched.collect_attention_items(**base)


def test_a6_night_stale_is_attention_item():
    line = "🌙 Ночная проверка: НЕ выполнялась с 2026-11-04 02:00 UTC (4 сут 3 ч) ⚠️"
    items = _collect(night_line=line)
    assert any("Ночная проверка не выполнялась (4 сут 3 ч)" == it for it in items), items


def test_a6_night_fresh_no_item():
    line = "🌙 Ночная проверка (2026-11-08 02:05 UTC): ok; здоровье: 9/10; открытых находок: 0"
    assert not any("Ночная проверка" in it for it in _collect(night_line=line))
    line_none = "🌙 Ночная проверка: ещё не выполнялась (первый ночной цикл после деплоя)"
    assert not any("Ночная проверка" in it for it in _collect(night_line=line_none))


def test_a6_forge_zero_repos_not_alert():
    """Резерв при 0 проектов — не алерт (даже если контур вернул ok=False)."""
    items = _collect(forge_backup_ok=False,
                     forge_backup_line="Резерв FORGE: нечего резервировать (проектов 0)")
    assert not any("Резерв FORGE" in it for it in items), items
    items2 = _collect(forge_backup_ok=False, forge_backup_line="бэкап FORGE: сбой контура (rc=1)")
    assert any("Резерв FORGE" in it for it in items2), items2


def test_a6_backup_script_zero_repos_line():
    """do_backup без проектов → честная строка, ok=True, smoke пропущен."""
    spec = importlib.util.spec_from_file_location("backup_forge_repos_n687", REPO_ROOT / "scripts" / "backup_forge_repos.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        repos = Path(td) / "repos"
        backups = Path(td) / "backups"
        repos.mkdir()
        old_repos, old_backups, old_marker = mod.REPOS_DIR, mod.BACKUPS_DIR, mod.SMOKE_MARKER
        mod.REPOS_DIR, mod.BACKUPS_DIR, mod.SMOKE_MARKER = str(repos), str(backups), str(Path(td) / "smoke.marker")
        try:
            res = mod.do_backup()
        finally:
            mod.REPOS_DIR, mod.BACKUPS_DIR, mod.SMOKE_MARKER = old_repos, old_backups, old_marker
    assert res["line"] == "Резерв FORGE: нечего резервировать (проектов 0)", res["line"]
    assert res["summary"]["ok"] is True
    assert res["summary"]["repos"] == 0


# ──────────────────────────── A.2: структурные гвардии ────────────────────────────

def test_a2_no_bare_parse_in_night_slot():
    """Каждый parse_json в ночном слоте — под try. Мутация «вернуть голый
    parse_json» ловится здесь (поведенчески — в test_n687_night_slot)."""
    for decl in ("pattern NightSlot() -> String {",
                 "pattern NightLzPhase() -> String {",
                 "pattern NightUsageKeyLine() -> String {"):
        seg = "\n".join(_code_lines(_mlog_segment(decl)))
        naked = [l.strip() for l in seg.splitlines() if "parse_json(" in l and "try parse_json" not in l]
        assert not naked, f"{decl}: голый parse_json: {naked}"


def test_a2_night_slot_try_wraps_phase_calls():
    seg = "\n".join(_code_lines(_mlog_segment("pattern NightSlot() -> String {")))
    for frag in ("try http_post(\"http://127.0.0.1:4000/admin-ua/night-cycle",
                 "try http_post(\"http://127.0.0.1:4000/memory/maintenance\"",
                 "try http_post(\"http://127.0.0.1:4000/admin/keys/night-check\"",
                 "try NightLzPhase()"):
        assert frag in seg, f"нет защиты фазы: {frag}"


def test_a5_usage_block_extracts_result():
    """В ленту уходит NightUsageKeyLine (поле result), не конверт целиком."""
    seg = "\n".join(_code_lines(_mlog_segment("pattern NightSlot() -> String {")))
    assert 'OutboxPut("usage-by-key", NightUsageKeyLine())' in seg, "лента получает не NightUsageKeyLine"
    seg2 = "\n".join(_code_lines(_mlog_segment("pattern NightUsageKeyLine() -> String {")))
    assert 'json_get(usage_json, "result"' in seg2, "поле result не извлекается"


# ──────────────────────────── A.3: маршруты проверки ключей ────────────────────────────

@pytest.fixture()
def fake_keys_env(monkeypatch):
    monkeypatch.setattr(key_health, "_key_value", lambda env_key: "fake-key-value")
    monkeypatch.setattr(key_health, "_run_check", lambda env_key, spec, value, models_out=None: ("ok", 200, ""))
    _query("DELETE FROM key_health_status", ())
    yield
    _query("DELETE FROM key_health_status", ())


def test_a3_night_check_route_saves(monkeypatch, fake_keys_env):
    from proxy.core import app as flask_app
    r = flask_app.test_client().post("/admin/keys/night-check", json={})
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok" and d["total"] == len(key_health.KEY_MANIFEST)
    rows = _query("SELECT COUNT(*) AS c FROM key_health_status", fetch=True)
    assert rows[0]["c"] == len(key_health.KEY_MANIFEST), "ночная фаза не сохранила результат"


def test_a3_manual_keys_route_saves(monkeypatch, fake_keys_env):
    from proxy.core import app as flask_app
    r = flask_app.test_client().get("/admin/keys/run")
    assert r.status_code == 200
    assert "Проверка ключей" in r.get_data(as_text=True)
    rows = _query("SELECT COUNT(*) AS c FROM key_health_status", fetch=True)
    assert rows[0]["c"] == len(key_health.KEY_MANIFEST), "ручной путь не сохранил результат"
