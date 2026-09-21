#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MINIAPP-1 tests (#288): переключатель «Голосовые ответы» из Mini App.

Гварды:
- один источник правды: роут /api/voice/settings читает/пишет ту же таблицу
  kv_store и ровно те же литералы "true"/"false", что mlog-команда /voice on|off
  (app.mlog: kv_set("voice_enabled", ...)); таблица kv_store — встроенное KV
  mlog-бинаря, схема подтверждена по бинарю в #268 (не system_settings);
- после POST из Mini App состояние видно TG-команде /voice (это тот же ключ kv);
- guard: /api/* требует Bearer API_SECRET (без него 401);
- audit: voice_settings_saved фиксируется;
- UI: у пункта «Голосовые ответы» снят .need-narad, стоит рабочий контрол;
- отсутствие таблицы kv_store (неинициализированный бинарь) — честный
  voice_enabled=false, не 500.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-miniapp1-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

with open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8") as _f:
    APP_MLOG = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def voice_db():
    """kv_store — схема по бинарю (key, value); в проде таблицу создаёт бинарь."""
    _query("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM kv_store WHERE key = 'voice_enabled'")
    _query("DELETE FROM audit_log WHERE action = 'voice_settings_saved'")
    yield
    _query("DELETE FROM kv_store WHERE key = 'voice_enabled'")
    _query("DELETE FROM audit_log WHERE action = 'voice_settings_saved'")


def _kv_voice():
    row = _query("SELECT value FROM kv_store WHERE key = 'voice_enabled' LIMIT 1", fetch=True)
    return str(row[0]["value"]) if row else None


def test_get_default_off():
    """Пустая kv_store → голос выключен (mlog-гейт: только 'true' включает)."""
    r = _client().get("/api/voice/settings", headers=API_AUTH)
    assert r.status_code == 200
    assert r.get_json()["voice_enabled"] is False


def test_get_reads_kv_store_true():
    """kv voice_enabled='true' (как пишет mlog /voice on) → API видит вкл."""
    _query("INSERT OR REPLACE INTO kv_store (key, value) VALUES ('voice_enabled', 'true')")
    r = _client().get("/api/voice/settings", headers=API_AUTH)
    assert r.status_code == 200
    assert r.get_json()["voice_enabled"] is True


def test_post_on_writes_exact_mlog_literal():
    """POST enabled=true пишет в kv_store ровно 'true' — тот же литерал,
    что kv_set("voice_enabled", "true") в app.mlog (/voice on)."""
    r = _client().post("/api/voice/settings", headers=API_AUTH, json={"enabled": True})
    assert r.status_code == 200
    assert r.get_json() == {"status": "ok", "voice_enabled": True}
    assert _kv_voice() == "true"
    # и symmetрично mlog-литералу в коде:
    assert 'kv_set("voice_enabled", "true")' in APP_MLOG


def test_post_off_writes_exact_mlog_literal():
    r = _client().post("/api/voice/settings", headers=API_AUTH, json={"enabled": False})
    assert r.status_code == 200
    assert r.get_json()["voice_enabled"] is False
    assert _kv_voice() == "false"
    assert 'kv_set("voice_enabled", "false")' in APP_MLOG


def test_post_roundtrip_visible_to_tg_voice():
    """Раундтрип: POST из Mini App → состояние в kv_store — тот же ключ,
    который читает TG-контур (kv_get("voice_enabled") в app.mlog)."""
    assert 'kv_get("voice_enabled")' in APP_MLOG
    _client().post("/api/voice/settings", headers=API_AUTH, json={"enabled": True})
    r = _client().get("/api/voice/settings", headers=API_AUTH)
    assert r.get_json()["voice_enabled"] is True
    _client().post("/api/voice/settings", headers=API_AUTH, json={"enabled": False})
    r = _client().get("/api/voice/settings", headers=API_AUTH)
    assert r.get_json()["voice_enabled"] is False


def test_post_requires_enabled_field():
    r = _client().post("/api/voice/settings", headers=API_AUTH, json={})
    assert r.status_code == 400
    assert _kv_voice() is None  # ничего не записано


def test_post_audit_logged():
    _client().post("/api/voice/settings", headers=API_AUTH, json={"enabled": True})
    row = _query("SELECT details FROM audit_log WHERE action = 'voice_settings_saved' LIMIT 1", fetch=True)
    assert row, "нет audit-записи voice_settings_saved"
    assert "miniapp" in str(row[0]["details"])


def test_api_guard_401_without_bearer():
    """Guard: /api/* без Bearer — 401 (как у остальных miniapp-настроек)."""
    c = _client()
    assert c.get("/api/voice/settings").status_code == 401
    assert c.post("/api/voice/settings", json={"enabled": True}).status_code == 401


def test_missing_kv_table_degrades_honest():
    """Нет таблицы kv_store (бинарь ещё не создавал) → честный false, не 500."""
    _query("DROP TABLE IF EXISTS kv_store")
    r = _client().get("/api/voice/settings", headers=API_AUTH)
    assert r.status_code == 200
    assert r.get_json()["voice_enabled"] is False


def test_ui_need_narad_removed_and_control_present():
    """UI: пункт «Голосовые ответы» — живой сегмент-контрол, без .need-narad."""
    assert 'id="voiceSeg"' in INDEX
    assert 'data-voice="1"' in INDEX and 'data-voice="0"' in INDEX
    # строка голосового пункта не содержит need-narad
    assert 'Голосовые ответы</span><span class="need-narad"' not in INDEX
    # глушитель в JS-комментарии больше не заявляет, что голоса нет
    assert "приглушены (HTTP-эндпоинтов команд /voice" not in INDEX
