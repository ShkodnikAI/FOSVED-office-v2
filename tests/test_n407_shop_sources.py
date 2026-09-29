#!/usr/bin/env python3
"""Наряд #407: статус источников сбора виден владельцу (текст + HTML + ответ +
/audit/recent + /shop/diagnose на проде).

Запуск: python3 -m pytest tests/test_n407_shop_sources.py -v

Контекст: досье #7 (2026-09-27) — ноль офферов с 10 площадок и «предложения
не собраны» без причин. Причины по каждой площадке теперь сохраняются в
снимок и показываются; диагноз сбора на проде — /shop/diagnose (CRON_SECRET).
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n407-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy import shop_dossier as sd  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app
from proxy.core import app  # noqa: E402

TAIL_SRC = (REPO_ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")
SCHED_SRC = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
PROXY_SRC = (REPO_ROOT / "reverse_proxy.py").read_text(encoding="utf-8")


def test_humanize_reasons_human_words():
    """A.1: причины человеческими словами — включая HTTP 403."""
    assert "не собиралось" in sd.humanize_source_status(None)
    assert "предложений" in sd.humanize_source_status({"ok": True, "offers": 7})
    assert sd.humanize_source_status({"ok": True}) == "ok"
    # формулировку source_disabled обновил #429 A.2: «выключено в настройках»
    assert "выключено в настройках" in sd.humanize_source_status({"ok": False, "kind": "source_disabled"})
    assert "антибот" in sd.humanize_source_status({"ok": False, "kind": "antibot_blocked"})
    assert "HTTP 403" in sd.humanize_source_status(
        {"ok": False, "kind": "transport", "error": "HTTP 403 Forbidden"})
    # неизвестный kind — не падаем, показываем как есть с error
    out = sd.humanize_source_status({"ok": False, "kind": "new_kind", "error": "boom"})
    assert "new_kind" in out and "boom" in out


def test_snapshot_keeps_sources():
    """A.1: details сохраняются в снимок (и в snapshot_json)."""
    details = {"wb": {"ok": False, "kind": "transport", "error": "HTTP 403"},
               "onliner": {"ok": True, "offers": 3}}
    snap = {"ok": True, "product": {"id": 1, "title": "t"}, "profile": "default",
            "verdict": {"score": 50, "text": "ok"}, "badges": {}, "unscored": [],
            "unscored_total": 0, "unscored_offers": [], "offers": [],
            "history_best": [], "median_best": None, "generated_at": "x"}
    # имитируем то, что делает build_snapshot (без БД): поля по контракту
    snap["sources"] = details
    snap["sources_display"] = sd.sources_display_rows(details)
    assert snap["sources_display"][0]["platform"] == "wb"
    assert "HTTP 403" in snap["sources_display"][0]["status"]
    assert snap["sources_display"][1]["status"] == "3 предложений"
    assert "collect_details" in sd.build_snapshot.__doc__ + (sd.build_snapshot.__code__.co_varnames + ("",))[0] or \
        "collect_details" in sd.build_snapshot.__code__.co_varnames, (
        "build_snapshot принимает collect_details")


def test_verdict_points_to_sources_block():
    """Пустой сбор — вердикт отсылает к блоку «Источники», не молчит."""
    snap = {"verdict": None, "unscored_total": None, "unscored": [],
            "offers": [], "unscored_offers": [],
            "sources_display": [{"platform": "wb", "status": "доступ с сервера закрыт (HTTP 403)"}]}
    score, text = sd.verdict_display(snap)
    assert "Источники" in text


def test_render_text_and_html_show_sources():
    snap = {"ok": True, "product": {"title": "Чайник"}, "profile": "default",
            "generated_at": "x", "verdict": {"score": None, "text": "t"},
            "badges": {}, "unscored": [], "unscored_total": 0,
            "unscored_offers": [], "offers": [], "history_best": [],
            "median_best": None, "stop_flags": [],
            "sources_display": [{"platform": "wb", "status": "HTTP 403"},
                                {"platform": "onliner", "status": "2 предложений"}]}
    score, text = sd.verdict_display(snap)
    txt = sd.render_text(snap)
    assert "Источники:" in txt and "wb: HTTP 403" in txt and "onliner: 2 предложений" in txt
    html = sd.render_html(snap)
    assert "Источники" in html and "HTTP 403" in html and "onliner" in html


def test_shop_product_returns_kind_error():
    """A.2: ответ /shop/product — kind/error по площадкам, не только bool."""
    assert "_collect_summary" in TAIL_SRC
    assert '"collect": {k: _collect_summary(v)' in TAIL_SRC
    assert "collect_details=details" in TAIL_SRC


def test_diagnose_endpoint_fail_closed():
    """A.4: /shop/diagnose существует и fail-closed без секрета."""
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/shop/diagnose" in rules, "диагностический эндпоинт должен быть зарегистрирован"
    client = app.test_client()
    r = client.get("/shop/diagnose?query=чайник")
    assert r.status_code == 403, "без секрета — отказ (fail-closed)"
    assert "/shop/diagnose" in PROXY_SRC, "маршрут должен быть публично доступен"


def test_audit_recent_exposes_status():
    """A.3: /audit/recent отдаёт status (ok/refused) в журнал Mini App."""
    assert '"SELECT id, action, details, timestamp, status FROM audit_log' in SCHED_SRC
    assert '"status": r["status"]' in SCHED_SRC
