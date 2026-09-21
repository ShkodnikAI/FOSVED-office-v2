#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE #221: детерминированные источники ЛЗ (arXiv/HN/GitHub) в общем пути /lz.

Гварды:
- call_python-мост: lz_sources.lz_api_scan в whitelist; POST /call-python
  реально исполняет lz_api_scan (мок-HTTP) и возвращает result.text;
- dept/lz.mlog: BuildLZContext добавляет LZApiScanContext; вызов
  call_python("lz_sources","lz_api_scan",...); честная деградация — строка
  «не нашёл релевантных результатов» при пустой выдаче (A.3);
- A.2 явное решение: домены tech/economics в условии LZApiScanContext,
  решение зафиксировано ADR-0003 (файл существует, статус принят,
  politics/geopolitics/events с обоснованием отказа);
- явные подкоманды не задеты: блоки starts_with("/lz …") стоят в HandleLZ
  раньше вызова BuildLZContext (порядок строк в файле);
- lz_api_scan живой контракт не тронут (сигнатура, 3 источника).
"""
import os
import sys
import json
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-lz221-bridge-test")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402
from proxy.routes_tail import CALL_PYTHON_ALLOWED  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LZ_MLOG = open(os.path.join(REPO_ROOT, "dept", "lz.mlog"), encoding="utf-8").read()
LZ_MLOG_LINES = LZ_MLOG.splitlines()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}

SCAN_RESULT = {"items": [{"source": "github", "title": "org/repo", "url": "https://github.com/org/repo"}],
               "text": "- [github] org/repo | https://github.com/org/repo",
               "counts": {"github": 1}, "trace_id": "lzapi0001"}


def _client():
    return flask_app.test_client()


# ── мост call_python → lz_sources ────────────────────────────────────────────

def test_whitelist_contains_lz_api_scan():
    assert "lz_sources" in CALL_PYTHON_ALLOWED
    assert CALL_PYTHON_ALLOWED["lz_sources"] == {"lz_api_scan"}


def test_call_python_endpoint_executes_scan():
    from proxy import routes_tail as rt
    with mock.patch.object(rt.http_requests, "get") as mget:
        mget.side_effect = RuntimeError("offline — источники честно вернут пусто")
        r = _client().post("/call-python", headers=API_AUTH,
                           json={"module": "lz_sources", "function": "lz_api_scan",
                                 "args": [["solid state batteries"], 3, "lz"], "dept": "lz"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["type"] == "dict"
    assert "text" in body["result"] and "counts" in body["result"]


def test_call_python_rejects_other_functions():
    r = _client().post("/call-python", headers=API_AUTH,
                       json={"module": "lz_sources", "function": "arxiv_search",
                             "args": [["x"]], "dept": "lz"})
    assert r.status_code == 403  # только lz_api_scan в whitelist
    r = _client().post("/call-python", headers=API_AUTH,
                       json={"module": "lz_sources", "function": "__init__", "args": [], "dept": "lz"})
    assert r.status_code == 403


# ── dept/lz.mlog: подключение и честная деградация ───────────────────────────

def test_buildlzcontext_wires_apiscan():
    ctx = next(i for i, l in enumerate(LZ_MLOG_LINES) if "pattern BuildLZContext(" in l)
    body = "\n".join(LZ_MLOG_LINES[ctx:ctx + 8])
    assert "LZApiScanContext(query, domain, chat_id)" in body
    assert "APIscan" in "\n".join(LZ_MLOG_LINES[ctx:ctx + 60])


def test_apiscan_calls_lz_sources_via_bridge():
    assert 'call_python("lz_sources", "lz_api_scan", json_encode([[topic], 6.0, "lz"]))' in LZ_MLOG


def test_honest_degradation_on_empty_result():
    assert "не нашёл релевантных результатов" in LZ_MLOG


def test_domain_scope_is_explicit_tech_economics():
    # A.2: условие домена явное; ADR-0003 фиксирует решение
    assert 'if domain != "tech" and domain != "economics" then { return "" }' in LZ_MLOG
    adr = open(os.path.join(REPO_ROOT, "docs", "adr",
                            "0003-lz-deterministic-scan-domains.md"), encoding="utf-8").read()
    assert "**Статус:** принято" in adr
    for dom in ("politics", "geopolitics", "events"):
        assert dom in adr  # отказ по трём доменам обоснован явно
    assert "q-fin" in adr and "Tavily" in adr


def test_explicit_subcommands_untouched():
    # явные подкоманды резолвятся РАНЬШЕ общего пути (порядок строк в HandleLZ)
    handle = next(i for i, l in enumerate(LZ_MLOG_LINES) if "pattern HandleLZ(" in l)
    build = next(i for i, l in enumerate(LZ_MLOG_LINES) if "BuildLZContext(query, domain, chat_id)" in l)
    for sub in ('starts_with(t, "/lz tavily")', 'starts_with(t, "/lz politics")',
                'starts_with(t, "/lz dark")'):
        idx = next((i for i in range(handle, build) if sub in LZ_MLOG_LINES[i]), None)
        assert idx is not None and idx < build, f"{sub} должен резолвиться раньше общего пути"


def test_lz_api_scan_signature_untouched():
    import inspect
    from proxy import lz_sources as lzs
    sig = inspect.signature(lzs.lz_api_scan)
    assert list(sig.parameters) == ["topics", "max_per_source", "dept"]


def test_lz_compare_command_removed():
    # #284 (вариант 2, решение владельца): подкоманда compare удалена из /lz —
    # вызывала несуществующий паттерн (гарантированное падение при первом
    # использовании), исходный замысел умер вместе с Apodex (#282).
    app_mlog = open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8").read()
    assert "/lz compare" not in app_mlog
    assert "LZCompare" not in app_mlog  # несуществующий паттерн не должен вернуться
    assert 'starts_with(query, " compare ")' not in app_mlog  # ветка не возвращается
    assert "/lz compare" not in LZ_MLOG
    assert "LZCompetingAlternatives" not in LZ_MLOG
    # способность ЛЗ «конкурирующие альтернативы» остаётся: Gate 7 + скилл-контекст
    assert "LZGateCompetingCheck" in LZ_MLOG
    assert "competing-alternatives" in LZ_MLOG
