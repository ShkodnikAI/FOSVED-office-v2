#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-8 tests (#201): экран «Интеграции и ключи».

Гварды:
- группы «Модели (N)» / «Сервисы (N)» со СЧЁТЧИКАМИ из фактического реестра
  (считаются в JS из intData, не захардкожены);
- живой поиск по названию (input + фильтр в реальном времени);
- точка on (зелёная, ключ задан) / off (серая, не задан); статус-текст
  «подключён»/«не задан» — маска значения НЕ показывается даже частично;
- лист ввода: подключённый → маска-плейсхолдер «••••••••» + кнопка «Убрать значение»;
  неподключённый → пустое поле «Вставь ключ», кнопка «Убрать» НЕ рендерится (hidden);
- сохранение/удаление — существующие POST/DELETE /api/integrations/<key>;
- после операций — перечитывание списка без перезагрузки страницы.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui8-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, INTEGRATIONS_REGISTRY  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


# ── Блок A. Список ───────────────────────────────────────────────────────

def test_group_counts_real_not_hardcoded():
    assert 'Модели (\'+nM+")' in INDEX
    assert 'Сервисы (\'+nS+")' in INDEX
    assert 'nM=intData.filter' in INDEX  # счётчики считаются из реестра
    assert 'Модели (13)' not in INDEX and 'Сервисы (7)' not in INDEX


def test_search_filters_realtime():
    assert '<input type="text" id="intSearch" placeholder="Найти интеграцию…"' in INDEX
    assert "intQuery=this.value.trim();renderIntegrations()" in INDEX
    assert 'String(x.label).toLowerCase().indexOf(q)>=0' in INDEX


def test_dot_on_off_and_status_not_masked():
    assert '.int-dot.on{background:var(--green)}' in INDEX
    assert '(x.connected?"on":"")' in INDEX
    assert '(x.connected?"подключён":"не задан")' in INDEX
    # значение ключа не показывается даже частично: masked в рендере отсутствует
    assert 'x.masked' not in INDEX
    assert 'r.masked' not in INDEX
    # строка кликабельна целиком и несёт данные для листа
    assert 'data-int-key' in INDEX and 'data-int-source' in INDEX


# ── Блок B. Лист ввода ключа ─────────────────────────────────────────────

def test_sheet_connected_vs_not():
    # подключённый: маска-плейсхолдер + «Убрать значение» активен
    assert 'inp.placeholder=connected?"••••••••":"Вставь ключ"' in INDEX
    assert 'document.getElementById("intSheetDelete").hidden=!connected' in INDEX
    # кнопка «Убрать» есть в разметке ровно одна (тогглится hidden'ом)
    assert INDEX.count('id="intSheetDelete"') == 1


def test_save_delete_hit_existing_endpoints():
    assert 'api("/api/integrations/"+encodeURIComponent(key),{method:"POST",body:{value:val}})' in INDEX
    assert 'api("/api/integrations/"+encodeURIComponent(key),{method:"DELETE"})' in INDEX


def test_list_refresh_without_page_reload():
    # после операций — перечитывание списка (fetch), НЕ location.reload
    assert 'await refreshIntegrations()' in INDEX
    assert "location.reload" not in INDEX
    assert 'async function refreshIntegrations(){' in INDEX
    assert 'renderIntegrations()' in INDEX


def test_lead_never_even_partial():
    assert 'Значение ключа никогда не показывается — даже частично.' in INDEX


# ── Поведенческие: существующий API (не трогался, но контракту должен жить) ──

def test_api_integrations_list_shape():
    with _client() as c:
        resp = c.get("/api/integrations", headers=API_AUTH)
    body = resp.get_json()
    assert body["status"] == "ok"
    ids = {x["id"] for x in body["integrations"]}
    assert {i["env_key"] for i in INTEGRATIONS_REGISTRY} <= ids
    for x in body["integrations"]:
        assert isinstance(x["connected"], bool)
        assert x["source"] in ("db", "env", "none")


def test_api_integrations_unknown_key_404():
    with _client() as c:
        r = c.post("/api/integrations/NOT_A_KEY", headers=API_AUTH, json={"value": "x"})
        d = c.delete("/api/integrations/NOT_A_KEY", headers=API_AUTH)
    assert r.status_code == 404 and d.status_code == 404
