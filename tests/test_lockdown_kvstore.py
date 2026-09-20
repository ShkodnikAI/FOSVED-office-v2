#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#268: system_lockdown — один источник правды (kv_store), индикатор больше не лжёт.

Аудит #244: mlog пишет блокировку kv_set("system_lockdown", ...) во
встроенное KV бинаря (таблица kv_store, подтверждено по бинарю:
INSERT OR REPLACE INTO kv_store (key, value)), а Python читал из
system_settings — индикатор безопасности в /api/attention всегда
показывал false при реально включённой блокировке.

Гварды:
- /api/attention показывает lockdown=true при kv_store.system_lockdown='true'
  (то, что пишет mlog /lockdown);
- разблокировка ('false' и удаление ключа) → lockdown=false;
- в python-коде не осталось чтения system_lockdown из system_settings.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n268-lockdown-test")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402
from proxy.core import _query  # noqa: E402

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _seed_kv_store():
    """kv_store — схема по бинарю (key, value); в проде таблицу создаёт бинарь."""
    _query("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")


def _set_lockdown(value: str) -> None:
    """Эквивалент mlog kv_set("system_lockdown", ...) — примитив бинаря."""
    _query("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
           ('system_lockdown', value))


def _get_lockdown_flag() -> bool:
    with flask_app.test_client() as c:
        resp = c.get("/api/attention", headers=API_AUTH)
    assert resp.status_code == 200, f"/api/attention: {resp.status_code}"
    return resp.get_json()["lockdown"]


def test_lockdown_on_visible_via_api():
    _seed_kv_store()
    _set_lockdown('true')
    assert _get_lockdown_flag() is True, "индикатор обязан показывать включённую блокировку"


def test_lockdown_off_visible_via_api():
    _seed_kv_store()
    _set_lockdown('false')
    assert _get_lockdown_flag() is False, "после разблокировки индикатор обязан погаснуть"


def test_lockdown_absent_key_means_unlocked():
    _seed_kv_store()
    _query("DELETE FROM kv_store WHERE key = 'system_lockdown'")
    assert _get_lockdown_flag() is False, "нет ключа → не заблокировано"


def test_no_system_settings_read_for_lockdown():
    ra = (ROOT / "proxy" / "routes_admin.py").read_text(encoding="utf-8")
    assert "FROM system_settings WHERE key = 'system_lockdown'" not in ra, (
        "routes_admin.py всё ещё читает system_lockdown из system_settings (наряд #268)")
    for ln in ra.splitlines():
        if "system_lockdown" in ln and "SELECT" in ln:
            assert "kv_store" in ln, f"чтение system_lockdown не из kv_store: {ln.strip()[:120]}"
