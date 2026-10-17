#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #542 A.3: результаты кнопок отчёта уходят владельцу в Telegram.

Действия, создающие новый документ (Журналист, Погружение deepen_to_*,
Контр-прогноз, Кризис-протокол), отправляют РОВНО ОДНО сообщение через
существующую доставку _tg_send_report_with_button: «<Действие> готов —
<заголовок>» + кнопка «Открыть» на /miniapp/{new_id}. Перенаправление на
странице сохраняется (ответ эндпоинта прежний).

Гварды:
- каждое из 4 действий → ровно 1 вызов доставки, doc_id в URL совпадает
  с doc_id нового документа из ответа;
- archive и control_* документ НЕ создают → доставки нет;
- без OWNER_TELEGRAM_ID (dev-стенд) — доставки нет, эндпоинт работает.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n542-notify-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401 — конвенция тестов Flask: импорт до прокси-роутов
from proxy.core import app as flask_app  # noqa: E402
from proxy import routes_core  # noqa: E402

MASTER = 'test-secret-123'
API_AUTH = {'Authorization': f'Bearer {MASTER}'}

RAW = ("[ФАКТ] Курс стабилен.\n[ИНТЕРПРЕТАЦИЯ] Волатильность снизится.\n"
       "Вердикт: наблюдать.")
LLM_REPLY = "ОТВЕТ МОДЕЛИ ПОСЛЕ ДЕЙСТВИЯ"

# action → (ожидаемая метка «<Действие> готов», префикс заголовка нового документа)
DOC_ACTIONS = {
    "journalist": ("Журналист", "Журналистская версия:"),
    "deepen_to_2": ("Погружение (ур. 2)", "Углублено (ур. 2):"),
    "counter_forecast": ("Контр-прогноз", "Контр-прогноз:"),
    "crisis_protocol": ("Кризис-протокол", "Кризис-протокол:"),
}


def _client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture()
def doc_id():
    cid = f"doc-n542-{uuid.uuid4().hex[:8]}"
    routes_core._query(
        "INSERT INTO miniapp_responses (id,dept,title,query,raw_text,html,confidence,created_at) "
        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (cid, 'osp', 'Отчёт #542', 'исходный вопрос теста', RAW, '', 'medium'))
    yield cid
    routes_core._query("DELETE FROM miniapp_responses WHERE parent_doc_id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_responses WHERE id=?", (cid,))
    routes_core._query("DELETE FROM audit_log WHERE action LIKE 'miniapp%'")


@pytest.fixture()
def stubs(monkeypatch):
    """Стабы LLM и доставки: захват вызовов _tg_send_report_with_button."""
    calls = {"tg": []}

    def fake_llm(dept, messages):
        return {"reply": LLM_REPLY}

    def fake_tg(chat_id, text, button_text="Открыть", button_url=None):
        calls["tg"].append({"chat_id": chat_id, "text": text,
                            "button_text": button_text, "button_url": button_url})
        return 12345

    monkeypatch.setattr(routes_core, "call_llm", fake_llm)
    monkeypatch.setattr(routes_core, "_tg_send_report_with_button", fake_tg)
    return calls


# ── Каждое создающее-документ действие: ровно один вызов доставки ────────

@pytest.mark.parametrize("action,expected", sorted(DOC_ACTIONS.items()))
def test_action_sends_telegram_exactly_once(client_stub, doc_id, action, expected):
    label, title_prefix = expected
    client, calls = client_stub
    resp = client.post("/webhook/miniapp-action", json={"action": action, "doc_id": doc_id},
                       headers=API_AUTH)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["status"] == "ok" and data["doc_id"], data
    new_id = data["doc_id"]
    # ровно один вызов доставки на действие
    tg = calls["tg"]
    assert len(tg) == 1, tg
    call = tg[0]
    assert call["chat_id"] == "12345"
    assert call["text"].startswith(f"{label} готов — "), call["text"]
    assert title_prefix in call["text"]          # заголовок нового документа
    # кнопка «Открыть» ведёт на новый документ
    assert call["button_text"] == "Открыть"
    assert call["button_url"].endswith(f"/miniapp/{new_id}")
    # doc_id нового документа — тот же, что в ответе эндпоинта
    assert new_id != doc_id


@pytest.fixture()
def client_stub(stubs):
    flask_app.config['TESTING'] = True
    return flask_app.test_client(), stubs


# ── Не создающие документ действия: доставки нет ─────────────────────────

def test_archive_sends_nothing(client_stub, doc_id):
    client, calls = client_stub
    resp = client.post("/webhook/miniapp-action", json={"action": "archive", "doc_id": doc_id},
                       headers=API_AUTH)
    assert resp.status_code == 200
    assert calls["tg"] == []


def test_control_sends_nothing(client_stub, doc_id):
    client, calls = client_stub
    resp = client.post("/webhook/miniapp-action", json={"action": "control_daily", "doc_id": doc_id},
                       headers=API_AUTH)
    assert resp.status_code == 200
    assert calls["tg"] == []


# ── Dev-стенд без OWNER_TELEGRAM_ID: эндпоинт работает, доставки нет ─────

def test_no_owner_env_still_ok(client_stub, doc_id, monkeypatch):
    client, calls = client_stub
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "")
    resp = client.post("/webhook/miniapp-action",
                       json={"action": "counter_forecast", "doc_id": doc_id},
                       headers=API_AUTH)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
    assert calls["tg"] == []
