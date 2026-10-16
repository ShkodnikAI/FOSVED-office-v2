#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #517 (FOIP-003.14): внутренние вызыватели /chain/step передают токен.

Находка: с заданным INTERNAL_API_TOKEN прод `/chain/step` отвечает 401 на
собственных внутренних клиентов (fan-out, нарядная очередь, miniapp refine) —
они шлют POST без ?token=, а RequireInternalAuth (app.mlog:754) ждёт токен в
query_param("token"). Вероятная причина жалоб «нет параллельной работы» и
«уточнение не сработало» (#498).

Гварды:
- chain_parallel._invoke_step / narad_queue._invoke_step / routes_core
  refine → URL содержит ?token=<env INTERNAL_API_TOKEN>;
- env не задан → URL без query (auth-off по замыслу FOIP-003.14);
- токен URL-экранируется (safe=""), ключи не логируются (проверка — в коде
  хелпера _internal_auth_qs, redact-политика запросов не менялась);
- все три вызывателя ходят именно на /chain/step (путь не подменён).
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
    """Стаб http_requests.post: захватывает URL/timeout, возвращает 200 OK."""
    def fake_post(url, json=None, timeout=None):  # noqa: A002 — сигнатура requests
        bucket.append({"url": url, "json": json, "timeout": timeout})
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


# ── _internal_auth_qs: базовая семантика ─────────────────────────────────


def test_auth_qs_empty_env_is_empty(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    assert pcore._internal_auth_qs() == ""


def test_auth_qs_with_token_is_quoted_query(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok with/space&rand")
    qs = pcore._internal_auth_qs()
    assert qs.startswith("?token=")
    assert "/" not in qs and " " not in qs and "&" not in qs, "токен URL-экранирован"


# ── chain_parallel (fan-out/debate) ──────────────────────────────────────


def test_chain_parallel_sends_token(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok-fanout-123")
    out = cp._invoke_step("osp", "вопрос", "0", "grp-1")
    assert out == "OK-СТЕП"
    assert bucket and bucket[0]["url"].startswith(cp.MLOGSERVE_URL + "/chain/step?token=tok-fanout-123")
    body = bucket[0]["json"]
    assert body["dept"] == "osp" and body["query"] == "вопрос"


def test_chain_parallel_auth_off_no_query(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    cp._invoke_step("osp", "вопрос", "0", "grp-1")
    assert "?" not in bucket[0]["url"], "пустой env — запрос без ?token= (auth-off)"


# ── narad_queue (нарядная очередь) ───────────────────────────────────────


def test_narad_queue_sends_token(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok-narad-456")
    out = nq._invoke_step("forge", "наряд", "555")
    assert out == "OK-СТЕП"
    assert bucket and bucket[0]["url"].startswith(nq.MLOGSERVE_URL + "/chain/step?token=tok-narad-456")
    assert bucket[0]["json"]["group_id"].startswith("narad-")


def test_narad_queue_auth_off_no_query(monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    nq._invoke_step("forge", "наряд", "555")
    assert "?" not in bucket[0]["url"]


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


def test_refine_sends_token(client, monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok-refine-789")
    cid = _insert_doc()
    try:
        r = client.post('/miniapp/note',
                        json={"doc_id": cid, "note_text": "учти вариативность", "refine": True},
                        headers=API_AUTH)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert bucket and bucket[0]["url"].startswith(routes_core.MLOGSERVE_URL + "/chain/step?token=tok-refine-789")
        assert bucket[0]["json"]["dept"] == "osp"
    finally:
        _cleanup_doc(cid)


def test_refine_auth_off_no_query(client, monkeypatch):
    bucket = _capture_post(monkeypatch, [])
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    cid = _insert_doc()
    try:
        r = client.post('/miniapp/note',
                        json={"doc_id": cid, "note_text": "учти вариативность", "refine": True},
                        headers=API_AUTH)
        assert r.status_code == 200, r.get_data(as_text=True)
        assert bucket and "?" not in bucket[0]["url"]
    finally:
        _cleanup_doc(cid)


# ── Статический гвард: три вызывателя идут через _internal_auth_qs ───────


def test_all_three_callers_use_auth_qs():
    srcs = {
        "chain_parallel": open(cp.__file__.replace(".pyc", ".py"), encoding="utf-8").read(),
        "narad_queue": open(nq.__file__.replace(".pyc", ".py"), encoding="utf-8").read(),
        "routes_core": open(routes_core.__file__.replace(".pyc", ".py"), encoding="utf-8").read(),
    }
    for name, src in srcs.items():
        assert "_internal_auth_qs()" in src, f"{name}: вызов /chain/step без _internal_auth_qs"
