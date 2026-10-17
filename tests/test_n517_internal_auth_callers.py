#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #517 (FOIP-003.14) → #536 A.2/A.4: внутренние вызыватели /chain/step.

История: #517 завёл query-токен (?token=); прод-приёмка #498 (лог Render
02:46:55 UTC) показала, что исключение requests содержит URL целиком, и
_log_error писал значение токена в журнал открытым текстом; кроме того
внутренние вызовы получали 401. #536 A.1/A.2: RequireInternalAuth читает
заголовок X-Internal-Token (request_header + SecretMatches, #546), вызыватели шлют
headers=_internal_auth_headers(); токен в URL запрещён.

Гварды:
- _internal_auth_headers: непустой env → {"X-Internal-Token": token},
  пустой env → {} (auth-off по замыслу FOIP-003.14, expected == "" → "ok");
- все три вызывателя (chain_parallel / narad_queue / routes_core refine)
  через monkeypatch http_requests.post: URL БЕЗ "?token=", заголовок присутствует;
- НИ ОДИН вызов /chain/step не содержит token= в URL (текст #536 A.4);
- статический гвард: источники используют _internal_auth_headers(), следы
  _internal_auth_qs / chain/step?token отсутствуют.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n517-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ.pop('INTERNAL_API_TOKEN', None)  # чистый стенд: без токена
# TELEGRAM_BOT_TOKEN НЕ задаётся: require_telegram пропускает без него

import llm_proxy  # noqa: E402,F401 — конвенция тестов Flask: импорт до прокси-роутов
from proxy import core as pcore  # noqa: E402
from proxy import chain_parallel as cp  # noqa: E402
from proxy import narad_queue as nq  # noqa: E402
from proxy import routes_core  # noqa: E402
from proxy.core import app as flask_app  # noqa: E402

API_AUTH = {'Authorization': 'Bearer test-secret-123'}

RAW = ("[ФАКТ] Курс стабилен.\nВердикт: наблюдать.\n\n"
       "Вероятности: база 0.6 / риск 0.3 / хвост 0.1.")


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"result": "OK-СТЕП"}


def _capture_post(monkeypatch, bucket):
    """Стаб http_requests.post: захватывает URL/headers/timeout, 200 OK."""
    def fake_post(url, json=None, timeout=None, headers=None):  # noqa: A002 — сигнатура requests
        bucket.append({"url": url, "json": json, "timeout": timeout, "headers": headers or {}})
        return _FakeResp()
    monkeypatch.setattr(cp.http_requests, "post", fake_post)
    monkeypatch.setattr(nq.http_requests, "post", fake_post)
    monkeypatch.setattr(routes_core.http_requests, "post", fake_post)
    return bucket


@pytest.fixture(autouse=True)
def _no_bot_token(monkeypatch):
    monkeypatch.setattr(pcore, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")  # по умолчанию auth-off
    yield


@pytest.fixture()
def client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


# ── _internal_auth_headers: базовая семантика (#536 A.2) ─────────────────


def test_auth_headers_empty_env(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    assert pcore._internal_auth_headers() == {}


def test_auth_headers_with_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok with/space&rand")
    h = pcore._internal_auth_headers()
    assert h == {"X-Internal-Token": "tok with/space&rand"}, \
        "заголовок несёт ТОЧНОЕ значение env (без URL-экранирования)"


# ── chain_parallel (fan-out/debate) ──────────────────────────────────────


def test_chain_parallel_sends_header(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok-fanout-123")
    out = cp._invoke_step("osp", "вопрос", "0", "grp-1")
    assert out == "OK-СТЕП"
    call = bucket[0]
    assert call["url"] == cp.MLOGSERVE_URL + "/chain/step", "URL без query"
    assert call["headers"].get("X-Internal-Token") == "tok-fanout-123"
    body = call["json"]
    assert body["dept"] == "osp" and body["query"] == "вопрос"


def test_chain_parallel_auth_off_no_token(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    cp._invoke_step("osp", "вопрос", "0", "grp-1")
    assert "?" not in bucket[0]["url"], "пустой env — запрос без query (auth-off)"
    assert bucket[0]["headers"] == {}, "пустой env — заголовков нет"


# ── narad_queue (нарядная очередь) ───────────────────────────────────────


def test_narad_queue_sends_header(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok-narad-456")
    out = nq._invoke_step("forge", "наряд", "555")
    assert out == "OK-СТЕП"
    call = bucket[0]
    assert call["url"] == nq.MLOGSERVE_URL + "/chain/step"
    assert call["headers"].get("X-Internal-Token") == "tok-narad-456"
    assert call["json"]["group_id"].startswith("narad-")


def test_narad_queue_auth_off_no_token(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    nq._invoke_step("forge", "наряд", "555")
    assert "?" not in bucket[0]["url"]
    assert bucket[0]["headers"] == {}


# ── miniapp refine (#498 маршрут уточнения) ──────────────────────────────


def _insert_doc():
    cid = f"doc-n517-{uuid.uuid4().hex[:8]}"
    routes_core._query(
        "INSERT INTO miniapp_responses (id,dept,title,query,raw_text,html,confidence,created_at) "
        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (cid, 'osp', 'Отчёт #517', 'исходный вопрос', RAW, '', 'medium'))
    return cid


def _cleanup_doc(cid):
    routes_core._query("DELETE FROM miniapp_responses WHERE parent_doc_id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_responses WHERE id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_responses WHERE id LIKE 'doc-%' AND title LIKE 'Уточнение к %'")
    routes_core._query("DELETE FROM miniapp_notes WHERE doc_id=?", (cid,))
    routes_core._query("DELETE FROM audit_log WHERE action='miniapp_refine'")


def test_refine_sends_header(client, monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok-refine-789")
    cid = _insert_doc()
    try:
        r = client.post('/miniapp/note',
                        json={"doc_id": cid, "note_text": "учти вариативность", "refine": True},
                        headers=API_AUTH)
        assert r.status_code == 200, r.get_data(as_text=True)
        call = bucket[0]
        assert call["url"] == routes_core.MLOGSERVE_URL + "/chain/step"
        assert call["headers"].get("X-Internal-Token") == "tok-refine-789"
        assert call["json"]["dept"] == "osp"
    finally:
        _cleanup_doc(cid)


def test_refine_auth_off_no_token(client, monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    cid = _insert_doc()
    try:
        r = client.post('/miniapp/note',
                        json={"doc_id": cid, "note_text": "учти вариативность", "refine": True},
                        headers=API_AUTH)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert bucket[0]["headers"] == {}
        assert "?" not in bucket[0]["url"]
    finally:
        _cleanup_doc(cid)


# ── #536 A.4: ни один вызов /chain/step не несёт token= в URL ────────────
# Три вызывателя через monkeypatch http_requests.post; и с токеном, и без —
# URL обязан быть чистым от token=. В полной батарее через те же модули
# могут ходить и другие вызовы (enrich и пр.) — фильтруем по /chain/step,
# а запрет token= проверяем на ВСЕ захваченные вызовы.


@pytest.mark.parametrize("env_token", ["tok-mutation-check-42", ""])
def test_no_caller_puts_token_in_url(monkeypatch, env_token):
    monkeypatch.setenv("INTERNAL_API_TOKEN", env_token)
    bucket = _capture_post(monkeypatch, [])
    cp._invoke_step("osp", "вопрос", "0", "grp-1")
    nq._invoke_step("forge", "наряд", "555")
    cid = _insert_doc()
    try:
        client = flask_app.test_client()
        flask_app.config['TESTING'] = True
        r = client.post('/miniapp/note',
                        json={"doc_id": cid, "note_text": "учти вариативность", "refine": True},
                        headers=API_AUTH)
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        _cleanup_doc(cid)
    for i, call in enumerate(bucket):
        assert "token=" not in call["url"], \
            f"вызов #{i}: token= в URL запрещён (#536 — утечка через исключения requests): {call['url']}"
    step_calls = [c for c in bucket if c["url"].split("?")[0].endswith("/chain/step")]
    assert len(step_calls) == 3, \
        f"ожидались вызовы всех трёх вызывателей /chain/step, захвачено {len(step_calls)}: " \
        + "; ".join(c["url"] for c in bucket)
    for call in step_calls:
        assert call["url"] == "http://127.0.0.1:10001/chain/step", call["url"]
        if env_token:
            assert call["headers"].get("X-Internal-Token") == env_token, call["headers"]
        else:
            assert call["headers"] == {}, call["headers"]


# ── Статический гвард: заголовок вместо query ────────────────────────────


def test_all_three_callers_use_auth_headers():
    srcs = {
        "chain_parallel": open(cp.__file__.replace(".pyc", ".py"), encoding="utf-8").read(),
        "narad_queue": open(nq.__file__.replace(".pyc", ".py"), encoding="utf-8").read(),
        "routes_core": open(routes_core.__file__.replace(".pyc", ".py"), encoding="utf-8").read(),
    }
    for name, src in srcs.items():
        assert "_internal_auth_headers()" in src, f"{name}: вызов /chain/step без _internal_auth_headers"
        assert "_internal_auth_qs" not in src, f"{name}: остался след старой query-функции"
        assert "chain/step?token" not in src, f"{name}: токен в URL (утечка #536)"
