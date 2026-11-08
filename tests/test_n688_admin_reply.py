#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #688 ADMIN-1 (P2): утренний ответ Админа без «Указаний отделам».

Решение владельца 08.11 — вариант А: убрать «Указания отделам» (механизма
исполнения поручений в офисе нет; прод 08.11: «Ответственному за резерв:
выполнить полный бэкап» при 0 проектов — чтение сигналов моделью), приоритеты
— дословно из списка внимания (collect_attention_items, #684/#687), замечания
— только по фактам из сигналов.

A.1 — блок указаний и строки-поручения вырезаются фильтром, срабатывание —
      в audit_log;
A.2 — «📌 Приоритеты на сегодня» собирает программа (до 3 пунктов дословно);
      пустой список — «📌 Приоритетов по сбоям нет»;
A.3 — в промпт замечаний идут те же сигналы, что у брифа; строка-«проблема»
      про резерв при честном «нечего резервировать» вырезается (A.3-гард).
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n688')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')
os.environ.setdefault('CRON_SECRET', 'test-cron-secret')

from llm_proxy import *  # noqa: E402,F401,F403 — регистрация маршрутов Flask
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import key_health, routes_sched  # noqa: E402
from proxy import routes_sched  # noqa: E402

API_AUTH = {'Authorization': 'Bearer test-secret-123'}
BRIEF = ("Утренний отчёт. ⚡ Внимания не требуется\n"
         "Кавальня (24ч): задано 13 — ОСП 3, финансы 3, юристы 4, ЛЗ 3; "
         "ожидают исхода 16 (ближайшие — 2026-11-09); разрешено 3, спорных 3\n")


def _client():
    return flask_app.test_client()


@pytest.fixture()
def green_signals():
    """Все сигналы зелёные: резерв — честное «нечего резервировать (проектов 0)»."""
    _query("DELETE FROM dialog_history WHERE dept='yana' AND content LIKE '%ТЕСТ-БРИФ-688%'")
    _query("DELETE FROM audit_log WHERE action IN ('scheduler_admin_morning_reply', 'admin_reply_directive_filter')")
    _query("DELETE FROM key_health_status", ())
    _query("DELETE FROM system_settings WHERE key='forge_backup_summary'", ())
    _query("INSERT INTO system_settings (key, value) VALUES ('forge_backup_summary', ?)", (
        '{"ok": true, "line": "Резерв FORGE: нечего резервировать (проектов 0)", '
        '"ts": "2026-11-08T04:20:00+00:00"}',))
    _query("INSERT INTO dialog_history (dept, chat_id, role, content) VALUES ('yana', '12345', 'assistant', ?)",
           (BRIEF.replace("Утренний отчёт.", "ТЕСТ-БРИФ-688."),))
    yield
    _query("DELETE FROM dialog_history WHERE dept='yana' AND content LIKE '%ТЕСТ-БРИФ-688%'")
    _query("DELETE FROM audit_log WHERE action IN ('scheduler_admin_morning_reply', 'admin_reply_directive_filter')")
    _query("DELETE FROM key_health_status", ())
    _query("DELETE FROM system_settings WHERE key='forge_backup_summary'", ())


def _patch_model(monkeypatch, reply_text):
    seen = {}

    def fake_call_llm(dept, messages):
        seen["dept"] = dept
        seen["messages"] = messages
        return {"reply": reply_text, "provider": "mock", "tokens_in": 0, "tokens_out": 0}

    monkeypatch.setattr(routes_sched, "call_llm", fake_call_llm)
    monkeypatch.setattr(routes_sched, "_tg_send_formatted", lambda chat_id, text, dept=None: 42)
    monkeypatch.setattr(routes_sched, "_tg_send_message", lambda chat_id, text: 42)
    monkeypatch.setattr(routes_sched, "owner_rate_attach", lambda *a, **kw: None)
    return seen


# ──────────────────────────── A.1: указания вырезаются ────────────────────────────

def test_a1_directives_block_and_lines_cut(monkeypatch, green_signals):
    """Прод-пример 08.11: блок «Указания отделам» и поручения со сроками — нет."""
    model_reply = (
        "💬 Замечания: отчёт Яны полный.\n"
        "🔧 Указания отделам\n"
        "Яне: до 12:00 подготовить сводку\n"
        "ОСП и финансам: закрыть метрики Brier до 2026-11-09\n"
        "Ответственному за резерв: выполнить полный бэкап сегодня\n"
        "🔍 Из находок ЛЗ: посмотреть паттерн дедупликации."
    )
    _patch_model(monkeypatch, model_reply)
    r = _client().post("/scheduler/admin-morning-reply", headers=API_AUTH, json={"owner_id": "12345"})
    d = r.get_json()
    assert d.get("status") == "ok"
    reply = d["reply"]
    assert "Указания отделам" not in reply
    assert "до 12:00" not in reply
    assert "ОСП и финансам:" not in reply
    assert "Ответственному за резерв" not in reply
    assert "до 2026-11-09" not in reply
    assert "из находок лз" in reply.lower(), reply
    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE action='admin_reply_directive_filter'", fetch=True)
    assert rows[0]["c"] >= 1, "срабатывание фильтра не в audit_log"


def test_a1_structural_no_directives_in_task():
    """В задаче модели нет пункта «Указания отделам»; в системном промпте — запрет.
    Мутация «вернуть пункт 3» красит этот тест."""
    src = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
    seg = src[src.index("def scheduler_admin_morning_reply"):]
    seg = seg[:seg.find("\n@app.")]
    code = "\n".join(l for l in seg.splitlines() if not l.strip().startswith("#"))
    assert "Указания отделам" not in code, "пункт «Указания отделам» вернулся в задачу модели"
    assert "Не отдавай поручений отделам и людям, не ставь сроков" in seg
    assert "директива на день" not in code


# ──────────────────────────── A.2: приоритеты — программой ────────────────────────────

def test_a2_priorities_verbatim_from_attention():
    items = ["Проверка ключей не выполнялась (17 сут 5 ч)",
             "Ночная проверка не выполнялась (3 сут)",
             "Третий алерт", "Четвёртый — не входит"]
    section = routes_sched.build_priorities_section(items)
    assert section.startswith("📌 Приоритеты на сегодня:")
    for it in items[:3]:
        assert ("- " + it) in section
    assert "Четвёртый" not in section


def test_a2_priorities_empty():
    assert routes_sched.build_priorities_section([]) == "📌 Приоритетов по сбоям нет"
    assert routes_sched.build_priorities_section(None) == "📌 Приоритетов по сбоям нет"


def test_a2_priorities_from_signals_in_reply(monkeypatch, green_signals):
    """Сигнал (просроченные ключи) → ровно этот пункт в приоритетах ответа."""
    from datetime import datetime, timedelta, timezone
    checked = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    key_health.save_result({"env_key": "ZAI_API_KEY", "status": "ok", "http_code": 200, "detail": ""},
                           checked_at=checked)
    _patch_model(monkeypatch, "💬 Замечаний нет.\n🔍 Из находок ЛЗ: всё спокойно.")
    r = _client().post("/scheduler/admin-morning-reply", headers=API_AUTH, json={"owner_id": "12345"})
    reply = r.get_json()["reply"]
    assert "📌 Приоритеты на сегодня:" in reply
    assert "- Проверка ключей не выполнялась (" in reply
    assert "Приоритетов по сбоям нет" not in reply


def test_a2_priorities_none_when_all_green(monkeypatch, green_signals):
    _patch_model(monkeypatch, "💬 Замечаний нет.\n🔍 Из находок ЛЗ: всё спокойно.")
    r = _client().post("/scheduler/admin-morning-reply", headers=API_AUTH, json={"owner_id": "12345"})
    reply = r.get_json()["reply"]
    assert "📌 Приоритетов по сбоям нет" in reply


# ──────────────────────────── A.3: замечания — только по данным ────────────────────────────

def test_a3_reserve_hole_claim_cut(monkeypatch, green_signals):
    """Сигналы зелёные («нечего резервировать»), модель пишет «критическая дыра» —
    строка вырезана, срабатывание в audit_log; в промпт уходят те же сигналы."""
    seen = _patch_model(monkeypatch, "💬 Критическая дыра в резерве FORGE, нужен немедленный бэкап.\n🔍 Из находок ЛЗ: ничего.")
    r = _client().post("/scheduler/admin-morning-reply", headers=API_AUTH, json={"owner_id": "12345"})
    reply = r.get_json()["reply"]
    assert "дыра в резерве" not in reply
    rows = _query("SELECT COUNT(*) AS c FROM audit_log WHERE action='admin_reply_directive_filter'", fetch=True)
    assert rows[0]["c"] >= 1
    # сигналы в промпте — те же, что у брифа (резерв, ключи, отказы, Кавальня)
    user_prompt = seen["messages"][1]["content"]
    assert "СИГНАЛЫ ДАННЫХ" in user_prompt
    assert "Резерв FORGE: нечего резервировать (проектов 0)" in user_prompt
    assert "не называй проблемой то, чего нет в сигналах" in user_prompt.lower()
