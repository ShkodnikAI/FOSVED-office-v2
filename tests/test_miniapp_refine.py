#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #498: строка уточнений на странице отчёта перезапускает отдел.

Гварды:
- «Сохранить заметку» (refine отсутствует) — прежнее поведение: только
  INSERT в miniapp_notes, отдел не запускается (A.3);
- «Уточнить и пересчитать» (refine: true) — исходный вопрос + сжатый текст
  исходного отчёта + уточнение владельца уходят в СУЩЕСТВУЮЩИЙ диспетчер
  /chain/step (mlogserve → ChainDispatchDept, dept/chain.mlog), не новый
  путь (A.1);
- новая версия — новый документ miniapp_responses с parent_doc_id на
  исходный и «Уточнение к <doc_id>» в заголовке; страница исходного
  содержит ссылку на новую версию; владельцу — доставка через
  _tg_send_report_with_button (аналог SendReport) (A.2);
- доступ — токен документа (#497): без токена 401, чужой токен 403 (A.4);
- dispatch-сбой → 503, текст уточнения сохранён заметкой (не теряется);
- пустой текст уточнения → 400.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n498-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
# TELEGRAM_BOT_TOKEN НЕ задаётся: require_telegram пропускает без него

import llm_proxy  # noqa: E402,F401 — конвенция тестов Flask: импорт до прокси-роутов
from proxy.core import app as flask_app  # noqa: E402
from proxy import routes_core  # noqa: E402
from proxy.reports import doc_action_token  # noqa: E402

MASTER = 'test-secret-123'
API_AUTH = {'Authorization': f'Bearer {MASTER}'}

RAW = ("[ФАКТ] Курс стабилен.\n[ИНТЕРПРЕТАЦИЯ] Волатильность снизится.\n"
       "Вердикт: наблюдать.\n\nВероятности: база 0.6 / риск 0.3 / хвост 0.1.")


def _client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture()
def client():
    return _client()


@pytest.fixture(autouse=True)
def _no_bot_token(monkeypatch):
    from proxy import core as _core
    monkeypatch.setattr(_core, "TELEGRAM_BOT_TOKEN", "")
    yield


@pytest.fixture()
def doc_id():
    cid = f"doc-n498-{uuid.uuid4().hex[:8]}"
    routes_core._query(
        "INSERT INTO miniapp_responses (id,dept,title,query,raw_text,html,confidence,created_at) "
        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (cid, 'osp', 'Отчёт #498', 'исходный вопрос теста', RAW, '', 'medium'))
    yield cid
    routes_core._query("DELETE FROM miniapp_responses WHERE parent_doc_id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_responses WHERE id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_responses WHERE id LIKE 'doc-%' AND title LIKE 'Уточнение к %'")
    routes_core._query("DELETE FROM miniapp_notes WHERE doc_id=?", (cid,))
    routes_core._query("DELETE FROM audit_log WHERE action='miniapp_refine'")


@pytest.fixture()
def fake_dispatch(monkeypatch):
    """Стаб mlogserve /chain/step + доставка — захват вызовов."""
    calls = {"chain": [], "tg": []}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"result": "НОВЫЙ ОТЧЁТ ПОСЛЕ УТОЧНЕНИЯ"}

    def fake_post(url, json=None, timeout=None):
        calls["chain"].append({"url": url, "json": json, "timeout": timeout})
        return FakeResp()

    def fake_tg(chat_id, text, button_text="Otkryt otchet", button_url=None):
        calls["tg"].append({"chat_id": chat_id, "text": text,
                            "button_text": button_text, "button_url": button_url})
        return 12345

    monkeypatch.setattr(routes_core.http_requests, "post", fake_post)
    monkeypatch.setattr(routes_core, "_tg_send_report_with_button", fake_tg)
    return calls


# ── A.3: заметка без перезапуска ─────────────────────────────────────────


def test_note_without_refine_is_note_only(client, doc_id, fake_dispatch):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "для себя"},
                    headers=API_AUTH)
    assert r.status_code == 200
    assert fake_dispatch["chain"] == [], "отдел не должен запускаться для обычной заметки"
    rows = routes_core._query("SELECT note_text FROM miniapp_notes WHERE doc_id=?", (doc_id,), fetch=True)
    assert rows and rows[0]["note_text"] == "для себя"


# ── A.1: уточнение → существующий диспетчер /chain/step ──────────────────


def test_refine_calls_existing_chain_step(client, doc_id, fake_dispatch):
    r = client.post('/miniapp/note',
                    json={"doc_id": doc_id, "note_text": "учти, что источникам доверия мало", "refine": True},
                    headers=API_AUTH)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert len(fake_dispatch["chain"]) == 1
    call = fake_dispatch["chain"][0]
    assert call["url"].split("?", 1)[0].endswith("/chain/step"), "диспетчеризация только через существующий /chain/step"
    body = call["json"]
    assert body["dept"] == "osp" and body["chat_id"] == "12345"
    q = body["query"]
    assert "исходный вопрос теста" in q, "исходный вопрос в запросе"
    assert "Курс стабилен" in q, "сжатый текст исходного отчёта в запросе"
    assert "учти, что источникам доверия мало" in q, "уточнение владельца в запросе"
    assert "Уточнение к отчёту" in q


def test_refine_long_report_condensed(client, doc_id, fake_dispatch):
    long_raw = ("[ФАКТ] длинный абзац.\n" * 400)  # > 1500 символов
    routes_core._query("UPDATE miniapp_responses SET raw_text=? WHERE id=?", (long_raw, doc_id))
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "уточни", "refine": True},
                    headers=API_AUTH)
    assert r.status_code == 200
    q = fake_dispatch["chain"][0]["json"]["query"]
    assert len(q) < len(long_raw), "исходный отчёт ушёл сжато, не целиком"
    assert len(q) < 4000


# ── A.2: новая версия, связь, доставка ───────────────────────────────────


def test_refine_creates_linked_new_version_and_delivers(client, doc_id, fake_dispatch):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "пересчитай", "refine": True},
                    headers=API_AUTH)
    assert r.status_code == 200
    new_id = r.get_json()["doc_id"]
    rows = routes_core._query(
        "SELECT id, dept, title, raw_text, parent_doc_id FROM miniapp_responses WHERE id=?",
        (new_id,), fetch=True)
    assert rows, "новая версия — новый документ miniapp_responses"
    nr = rows[0]
    assert nr["dept"] == "osp"
    assert f"Уточнение к {doc_id}" in nr["title"], "заголовок новой версии ссылается на исходный"
    assert nr["parent_doc_id"] == doc_id, "связь версий в БД"
    assert nr["raw_text"] == "НОВЫЙ ОТЧЁТ ПОСЛЕ УТОЧНЕНИЯ"
    # доставка владельцу — обычная (Telegram + кнопка на новую версию)
    assert len(fake_dispatch["tg"]) == 1
    tg = fake_dispatch["tg"][0]
    assert tg["chat_id"] == "12345"
    assert f"/miniapp/{new_id}" in tg["button_url"]


def test_page_links_to_refined_version(client, doc_id, fake_dispatch):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "ещё раз", "refine": True},
                    headers=API_AUTH)
    new_id = r.get_json()["doc_id"]
    page = client.get(f"/miniapp/{doc_id}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Уточнённые версии" in html, "на странице исходного — блок версий"
    assert f'/miniapp/{new_id}' in html, "ссылка на новую версию"


def test_action_bar_has_two_note_actions(client, doc_id):
    page = client.get(f"/miniapp/{doc_id}")
    html = page.get_data(as_text=True)
    assert "addRefine()" in html and "addNote()" in html, "два действия строки уточнений"
    assert 'refine:true' in html, "пересчёт помечен флагом refine"
    assert "refineInput" in html and "noteInput" in html


# ── A.4: доступ по токену документа ──────────────────────────────────────


def test_refine_requires_doc_token(client, doc_id, fake_dispatch):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "х", "refine": True})
    assert r.status_code == 401
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "х", "refine": True},
                    headers={'Authorization': f'Bearer {doc_action_token("doc-другой")}'})
    assert r.status_code == 403
    assert fake_dispatch["chain"] == [], "без авторизации диспетчер не зовётся"


def test_refine_works_with_page_token(client, doc_id, fake_dispatch):
    page = client.get(f"/miniapp/{doc_id}")
    token = [ln for ln in page.get_data(as_text=True).splitlines()
             if "_docToken" in ln and "var" in ln][0].split("'", 1)[1].split("'", 1)[0]
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "ок", "refine": True},
                    headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200


# ── честные сбои ─────────────────────────────────────────────────────────


def test_refine_dispatch_failure_saves_note_503(client, doc_id, monkeypatch):
    def boom(url, json=None, timeout=None):
        raise ConnectionError("mlog down")
    monkeypatch.setattr(routes_core.http_requests, "post", boom)
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "не потеряй меня", "refine": True},
                    headers=API_AUTH)
    assert r.status_code == 503
    rows = routes_core._query("SELECT note_text FROM miniapp_notes WHERE doc_id=?", (doc_id,), fetch=True)
    assert rows and rows[0]["note_text"] == "не потеряй меня"


def test_refine_empty_text_400(client, doc_id, fake_dispatch):
    r = client.post('/miniapp/note', json={"doc_id": doc_id, "note_text": "  ", "refine": True},
                    headers=API_AUTH)
    assert r.status_code == 400
    assert fake_dispatch["chain"] == []


def test_refine_unknown_doc_404(client, fake_dispatch):
    r = client.post('/miniapp/note', json={"doc_id": "doc-нет", "note_text": "х", "refine": True},
                    headers=API_AUTH)
    assert r.status_code == 404
