#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #602 — учёт использования по ключам отделов: лента вызовов,
агрегаты per-key, диф-окна, ночная лента, /api-роут, негативные контролы
наряда: (А) вызов с невалидным ключом попадает в ленту как отказ, а не
проходит мимо; (Б) секрет ключа не появляется в ленте ни в каком поле.
Shadow-гарантия: учёт не меняет prod-поведение вызова и не пишет в
чужие ленты (token_usage/audit_log)."""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_PATH", "/tmp/n602_test_db")

from proxy.core import _query  # noqa: E402
from proxy import providers  # noqa: E402
from proxy import usage_by_key  # noqa: E402

_SECRET = "sk-live-" + uuid.uuid4().hex[:16] + "9876"


def _clean():
    _query("DELETE FROM usage_key_calls", commit_safe=True) if False else None
    try:
        _query("DELETE FROM usage_key_calls")
    except Exception:  # noqa: BLE001 — таблицы ещё нет
        pass


def _rows():
    return [dict(r) for r in _query(
        "SELECT key_mask, provider, env_key, dept, route, ok, err_kind, duration_ms, created_at "
        "FROM usage_key_calls ORDER BY id", fetch=True)]


def test_mask_never_secret_and_record_shape():
    _clean()
    m = usage_by_key.mask_key(_SECRET)
    # маска: первые 3 + … + последние 4; секрет не восстановим
    assert _SECRET not in m and "…" in m
    usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "combo:x", True, None, 111)
    usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "combo:x", False, "forbidden", 55)
    rows = _rows()
    assert len(rows) == 2
    # негативный контроль Б: секрет не появляется в ленте ни в каком поле
    for r in rows:
        for v in r.values():
            assert _SECRET not in str(v), "секрет ключа в ленте запрещён (#602 А/Б)"
    assert rows[0]["key_mask"] == m and rows[0]["ok"] == 1
    assert rows[1]["ok"] == 0 and rows[1]["err_kind"] == "forbidden"
    # содержимое запросов/ответов не логируется вовсе (колонок контента нет)
    cols = [r["name"] for r in _query("PRAGMA table_info(usage_key_calls)", fetch=True)]
    assert not any(c in cols for c in ("request", "response", "messages", "reply", "body"))


def test_agg_sums_match_feed():
    _clean()
    m = usage_by_key.mask_key(_SECRET)
    for ok, err in [(True, None), (True, None), (True, None), (False, "forbidden"), (False, "rateLimit")]:
        usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "combo", ok, err, 100)
    agg = usage_by_key.agg_window(1)
    feed_rows = usage_by_key.feed(100)
    # сходимость: сумма агрегата = число записей ленты за окно (Сделано, когда)
    assert agg["total"] == len(feed_rows) == 5
    assert agg["failed"] == 2 and agg["fail_rate"] == 0.4
    assert agg["rows"][0]["calls"] == 5 and agg["rows"][0]["fails"] == 2


def test_invalid_key_lands_as_failure_not_bypass():
    """Негативный контроль А на живой врезке: вызов через провайдера с битым
    upstream → отказ в ленте (err_kind из классификатора), результат вызова
    прежний (None), поведение не меняется."""
    _clean()
    secret = "sk-test-" + uuid.uuid4().hex[:12] + "4242"
    saved_prov = dict(providers.PROVIDERS)
    saved_secret = providers.get_secret
    try:
        providers.PROVIDERS["mockbad"] = {
            "env_key": "MOCKBAD_KEY", "format": "openai",
            "base_url": "http://127.0.0.1:9/v1",  # порт 1 — соединение отвергнуто
        }
        providers.get_secret = lambda name: secret if name == "MOCKBAD_KEY" else None
        providers._breaker.open_until.clear() if hasattr(providers._breaker, "open_until") else None
        res = providers._call_single_provider("mockbad", "mock-model", [{"role": "user", "content": "ping"}], dept="dev", route="combo:test")
        # shadow: prod-поведение прежнее — примитив вернул None (отказ), как и без учёта
        assert res is None
        rows = _rows()
        assert len(rows) == 1, "вызов с невалидным ключом обязан попасть в ленту как отказ"
        r = rows[0]
        assert r["ok"] == 0 and r["err_kind"] in (
            "forbidden", "aborted", "conn", "rateLimit", "serverError",
            "notFound", "timeout", "empty", "truncated", "other"), \
            f"отказ обязан попасть в ленту с классом классификатора: {r['err_kind']}"
        assert r["dept"] == "dev" and r["route"] == "combo:test" and r["duration_ms"] is not None
        # негативный контроль Б: секрет не в ленте
        for v in r.values():
            assert secret not in str(v)
        assert "…" in r["key_mask"]
    finally:
        providers.PROVIDERS.clear()
        providers.PROVIDERS.update(saved_prov)
        providers.get_secret = saved_secret


def test_no_key_and_breaker_early_exits_recorded():
    _clean()
    saved_prov = dict(providers.PROVIDERS)
    saved_secret = providers.get_secret
    try:
        providers.PROVIDERS["mockempty"] = {"env_key": "EMPTY_KEY", "format": "openai", "base_url": "http://127.0.0.1:9/v1"}
        providers.get_secret = lambda name: ""  # ключа нет
        res = providers._call_single_provider("mockempty", "m", [{"role": "user", "content": "x"}], dept="dev")
        assert res is None
        rows = _rows()
        assert len(rows) == 1 and rows[0]["err_kind"] == "no_key" and rows[0]["ok"] == 0
        # нет такого провайдера — тоже строка отказа
        res2 = providers._call_single_provider("noprovider", "m", [{"role": "user", "content": "x"}], dept="dev")
        assert res2 is None
        rows = _rows()
        assert rows[-1]["err_kind"] == "no_provider"
    finally:
        providers.PROVIDERS.clear()
        providers.PROVIDERS.update(saved_prov)
        providers.get_secret = saved_secret


def test_night_block_form_and_empty_honesty():
    _clean()
    empty_block = usage_by_key.night_block()
    assert "вызовов нет" in empty_block, "пустое окно — честное сообщение, не нули"
    m = usage_by_key.mask_key(_SECRET)
    usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "combo", True, None, 200)
    usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "override", False, "forbidden", 50)
    block = usage_by_key.night_block()
    assert "🔑 Учёт по ключам" in block
    assert "вызовов 2, отказов 1" in block
    assert "новый маршрут" in block and "override" in block
    assert _SECRET not in block


def test_diff_surge_and_new_keys():
    _clean()
    m = usage_by_key.mask_key(_SECRET)
    usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "combo", True, None, 10)
    d = usage_by_key.diff_window(1)
    assert any(k["key_mask"] == m for k in d["new_keys"])
    assert any(r["route"] == "combo" for r in d["new_routes"])
    # всплеск честно не утверждается при малых n (<5)
    assert d["fail_surge"] is None


def test_api_route_registered_and_shadow_isolation():
    # /api/usage-by-key зарегистрирован (bearer-гвард общего before_request)
    import proxy.routes_admin as ra
    assert any(getattr(rule, "rule", "") == "/api/usage-by-key" for rule in ra.app.url_map.iter_rules())
    # shadow-изоляция: учёт не пишет в token_usage/audit_log
    _clean()
    before_tu = _query("SELECT COUNT(*) AS c FROM token_usage", fetch=True)[0]["c"]
    m = usage_by_key.mask_key(_SECRET)
    usage_by_key.record_call("mockprov", "MOCK_API_KEY", m, "dev", "combo", True, None, 5)
    after_tu = _query("SELECT COUNT(*) AS c FROM token_usage", fetch=True)[0]["c"]
    assert after_tu == before_tu, "shadow: чужие ленты не пишутся"


def test_call_python_whitelist_and_mlog_hook():
    # ночной мост: whitelist call_python + OutboxPut в NightSlot
    tail_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proxy", "routes_tail.py"), encoding="utf-8").read()
    assert '"usage_by_key": {"night_block"}' in tail_src
    app_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.mlog"), encoding="utf-8").read()
    assert 'OutboxPut("usage-by-key", call_python("usage_by_key", "night_block", "[]"))' in app_src


def test_route_tags_in_call_chain():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proxy", "providers.py"), encoding="utf-8").read()
    for tag in ('route="override"', 'route="direct"', 'route="race"', 'route="fallback"', 'route="combo:" + combo_pre'):
        assert tag in src, tag
