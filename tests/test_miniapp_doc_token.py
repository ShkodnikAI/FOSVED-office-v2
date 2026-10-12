#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #497: кнопки страницы отчёта — токен документа вместо мастер-ключа.

Гварды (по наряду):
- страница отчёта НЕ содержит литерал {API_SECRET} и значение мастер-ключа,
  содержит токен документа (A.2);
- токен документа действует только на свой doc_id: чужой doc_id с этим
  токеном — 403 (A.1/A.4);
- каждая кнопка action-bar выполняется с токеном страницы — 200 (A.4):
  архив/контроль без LLM, журналист/погружение/контр-прогноз/кризис — со
  стабом call_llm;
- без токена / мусорный токен — 401;
- внутренние вызовы по Bearer мастер-ключа по-прежнему работают;
- /miniapp/note — та же схема токена документа (A.3): без токена 401,
  чужой токен 403, с токеном документа или мастер-ключом — 200;
- токен документа: срок действия (stale) и форма (bad) отфильтровываются.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n497-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
# TELEGRAM_BOT_TOKEN НЕ задаётся: require_telegram пропускает без него

import llm_proxy  # noqa: E402,F401 — конвенция тестов Flask: импорт до прокси-роутов
from proxy.core import app as flask_app  # noqa: E402
from proxy import routes_core  # noqa: E402
from proxy.reports import doc_action_token, doc_token_verify  # noqa: E402

MASTER = 'test-secret-123'
API_AUTH = {'Authorization': f'Bearer {MASTER}'}

RAW = ("[ФАКТ] Курс стабилен.\n[ИНТЕРПРЕТАЦИЯ] Волатильность снизится.\n"
       "Вердикт: наблюдать. Вероятности: база 0.6 / риск 0.3 / хвост 0.1.")


def _client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _no_bot_token(monkeypatch):
    """Полный прогон: ранее тесты задают TELEGRAM_BOT_TOKEN — require_telegram
    отдаёт bootstrap-страницу вместо отчёта. Наряд #497 проверяет слой токена
    документа, не телеграм-слой — глушим проверку initData точечно."""
    from proxy import core as _core
    monkeypatch.setattr(_core, "TELEGRAM_BOT_TOKEN", "")
    yield


@pytest.fixture()
def client():
    return _client()


@pytest.fixture()
def doc_id():
    cid = f"doc-n497-{uuid.uuid4().hex[:8]}"
    routes_core._query(
        "INSERT INTO miniapp_responses (id,dept,title,query,raw_text,html,confidence,created_at) "
        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (cid, 'osp', 'Отчёт #497', 'тест', RAW, '', 'medium'))
    yield cid
    routes_core._query("DELETE FROM miniapp_responses WHERE id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_responses WHERE id LIKE 'doc-%' AND query IN ('journalist','deepen','counter_forecast','crisis_protocol')")
    routes_core._query("DELETE FROM miniapp_notes WHERE doc_id=?", (cid,))
    routes_core._query("DELETE FROM dept_metrics WHERE dept='osp' AND metric_name='control_watch'")


def _page_token(client, cid):
    r = client.get(f"/miniapp/{cid}")
    assert r.status_code == 200, f"страница отчёта: {r.status_code}"
    html = r.get_data(as_text=True)
    m = [ln for ln in html.splitlines() if "_docToken" in ln and "var" in ln]
    assert m, "в странице нет _docToken"
    token = m[0].split("'", 1)[1].split("'", 1)[0]
    return html, token


def _stub_llm(monkeypatch):
    captured = {}

    def fake_call_llm(dept, messages, **kw):
        captured['dept'] = dept
        return {"reply": "СТАБ-ОТВЕТ", "provider": "stub"}

    monkeypatch.setattr(routes_core, "call_llm", fake_call_llm)
    return captured


# ── A.2: страница без мастер-ключа, с токеном документа ─────────────────


def test_page_has_no_master_key_and_no_placeholder(client, doc_id):
    html, token = _page_token(client, doc_id)
    assert "{API_SECRET}" not in html, "литерал {API_SECRET} в странице (класс дефекта #497)"
    assert "{{API_SECRET}}" not in html
    assert MASTER not in html, "МАСТЕР-КЛЮЧ в странице — утечка"
    assert "_apiSecret" not in html, "старая переменная _apiSecret не вычищена"
    assert "_docToken" in html
    assert doc_token_verify(token, doc_id) == "ok"


def test_page_token_is_doc_bound(client, doc_id):
    _, token = _page_token(client, doc_id)
    assert doc_token_verify(token, "doc-чужой") == "mismatch"
    corrupted = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert doc_token_verify(corrupted, doc_id) == "mismatch", (
        "изменённая сигнатура обязана отвергаться"
    )
    assert doc_token_verify("garbage", doc_id) == "bad"
    assert doc_token_verify("", doc_id) == "bad"
    expired = doc_action_token(doc_id, now=0)
    assert doc_token_verify(expired, doc_id) == "stale"


# ── A.4: каждая кнопка — 200 с токеном страницы ──────────────────────────


def test_archive_and_control_with_doc_token(client, doc_id):
    _, token = _page_token(client, doc_id)
    h = {'Authorization': f'Bearer {token}'}
    r = client.post('/webhook/miniapp-action', json={"action": "archive", "doc_id": doc_id}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json().get("status") == "ok"
    r = client.post('/webhook/miniapp-action', json={"action": "control_daily", "doc_id": doc_id}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)


def test_llm_buttons_with_doc_token(client, doc_id, monkeypatch):
    _stub_llm(monkeypatch)
    _, token = _page_token(client, doc_id)
    h = {'Authorization': f'Bearer {token}'}
    for action, prefix in (("journalist", "doc-"), ("deepen_to_3", "doc-"),
                           ("counter_forecast", "doc-"), ("crisis_protocol", "doc-")):
        r = client.post('/webhook/miniapp-action', json={"action": action, "doc_id": doc_id}, headers=h)
        assert r.status_code == 200, f"{action}: {r.get_data(as_text=True)}"
        body = r.get_json()
        assert body.get("status") == "ok" and body.get("doc_id"), action


def test_foreign_doc_id_with_page_token_403(client, doc_id):
    _, token = _page_token(client, doc_id)
    r = client.post('/webhook/miniapp-action',
                    json={"action": "archive", "doc_id": "doc-другой-объект"},
                    headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 403, "чужой doc_id с валидным токеном другого документа"


def test_no_token_and_garbage_401(client, doc_id):
    r = client.post('/webhook/miniapp-action', json={"action": "archive", "doc_id": doc_id})
    assert r.status_code == 401
    r = client.post('/webhook/miniapp-action', json={"action": "archive", "doc_id": doc_id},
                    headers={'Authorization': 'Bearer not-a-token'})
    assert r.status_code == 401


def test_master_key_still_accepted(client, doc_id):
    r = client.post('/webhook/miniapp-action', json={"action": "archive", "doc_id": doc_id},
                    headers=API_AUTH)
    assert r.status_code == 200, "внутренние вызовы по мастер-ключу должны работать"


# ── A.3: /miniapp/note — токен документа ─────────────────────────────────


def test_note_requires_token(client, doc_id):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "без токена"})
    assert r.status_code == 401, "раньше путь был открыт — теперь токен документа"


def test_note_with_page_token_and_foreign_rejected(client, doc_id):
    _, token = _page_token(client, doc_id)
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "заметка"},
                    headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200
    rows = routes_core._query("SELECT note_text FROM miniapp_notes WHERE doc_id=?", (doc_id,), fetch=True)
    assert rows and rows[0]["note_text"] == "заметка"
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "чужой"},
                    headers={'Authorization': f'Bearer {doc_action_token("doc-иной")}'})
    assert r.status_code == 403
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "мусор"},
                    headers={'Authorization': 'Bearer garbage'})
    assert r.status_code == 401


def test_note_master_key_accepted(client, doc_id):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "внутренняя"},
                    headers=API_AUTH)
    assert r.status_code == 200
