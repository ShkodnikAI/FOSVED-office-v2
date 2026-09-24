#!/usr/bin/env python3
"""Ozon headless (наряд #334): флаг-гейт, сессия с TTL, честные kind'ы.

Playwright подменяется моком (никакого реального браузера в тестах):
  - sync_playwright() → контекст-менеджер с chromium.launch() →
    new_context/add_cookies/new_page/cookies/close — все вызовы
    фиксируются; page.evaluate эмулирует composer-api;
  - гейт: флаг выключен → старый транспортный путь (antibot_blocked);
  - playwright не установлен → честный playwright_missing;
  - полный проход: goto + wait_for_selector + composer 200 → сессия
    записана, браузер закрыт всегда, raw сохранён, api_form_unknown
    (парсер вслепую не пишем — дисциплина #172);
  - быстрый путь: живая сессия → composer сразу, goto НЕ вызывается
    (антибот проходится один раз — smoke-пункт 2 наряда);
  - протухшая сессия → полный проход заново;
  - челлендж не снят → challenge_not_passed.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-ozon-headless-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query  # noqa: E402
from proxy import shop_collectors as sc  # noqa: E402
from proxy import ozon_headless as oh  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_kv(monkeypatch):
    _query("CREATE TABLE IF NOT EXISTS system_settings "
           "(key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_ozon%'")
    monkeypatch.delenv("SHOP_OZON_HEADLESS", raising=False)
    yield
    _query("DELETE FROM system_settings WHERE key LIKE 'shop_ozon%'")


class _FakePage:
    def __init__(self, composer_status=200, composer_text='{"widgetStates": {}}',
                 challenge_passes=True):
        self.gotos = []
        self.evals = []
        self.composer_status = composer_status
        self.composer_text = composer_text
        self.challenge_passes = challenge_passes

    def goto(self, url, **kw):
        self.gotos.append(url)
        return {"status": 200}

    def wait_for_selector(self, sel, **kw):
        if not self.challenge_passes:
            raise TimeoutError("challenge not cleared")
        return "sel"

    def evaluate(self, js, url):
        self.evals.append(url)
        return {"status": self.composer_status, "text": self.composer_text}


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.cookies_added = []
        self.cookies_out = [{"name": "abt_data", "value": "ok"}]

    def add_cookies(self, cookies):
        self.cookies_added.extend(cookies)

    def new_page(self):
        return self._page

    def cookies(self):
        return self.cookies_out


class _FakeBrowser:
    def __init__(self, context):
        self._context = context
        self.closed = False

    def new_context(self, **kw):
        return self._context

    def close(self):
        self.closed = True


class _FakePlaywright:
    """Подмена playwright.sync_api: записи всех вызовов на себе."""

    def __init__(self, composer_status=200, challenge_passes=True,
                 composer_text='{"widgetStates": {}}'):
        self.page = _FakePage(composer_status=composer_status,
                              challenge_passes=challenge_passes,
                              composer_text=composer_text)
        self.context = _FakeContext(self.page)
        self.browser = _FakeBrowser(self.context)
        self.calls = {"launch": 0}

    def sync_playwright(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def chromium(self):
        outer = self

        class _Ch:
            @staticmethod
            def launch(**kw):
                outer.calls["launch"] += 1
                return outer.browser
        return _Ch()


def test_flag_off_keeps_transport_path(monkeypatch):
    """Флаг выключен (дефолт) → старый честный транспортный отказ."""
    calls = []
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: calls.append(1) or {"ok": False, "kind": "http_403",
                                                         "error": "HTTP 403"})
    r = sc.collect_ozon("смартфон")
    assert r["ok"] is False and calls  # транспорт дёргался, браузер — нет
    assert "антибот Ozon" in r["error"]


def test_playwright_missing_is_honest(monkeypatch):
    monkeypatch.setenv("SHOP_OZON_HEADLESS", "1")
    # None в sys.modules → `from playwright import …` бросает ImportError
    monkeypatch.setitem(sys.modules, "playwright", None)
    r = oh.collect_ozon_headless("смартфон")
    assert r["ok"] is False and r["kind"] == "playwright_missing"
    assert "pip install playwright" in r["error"]


def test_full_challenge_pass_saves_session_and_raw(monkeypatch):
    monkeypatch.setenv("SHOP_OZON_HEADLESS", "1")
    pw = _FakePlaywright(composer_text='{"widgetStates": {"a": 1}}')
    r = oh.collect_ozon_headless("смартфон", playwright_mod=pw)
    # транспорт прошёл, форма не разобрана вслепую — честный api_form_unknown
    assert r["ok"] is False and r["kind"] == "api_form_unknown"
    # сессия записана
    assert oh._session_read() == pw.context.cookies_out
    # raw сохранён в kv
    raw = json.loads(_query("SELECT value FROM system_settings WHERE key=?",
                            (oh.RAW_CACHE_KEY,), fetch=True)[0]["value"])
    assert raw["raw"] == '{"widgetStates": {"a": 1}}'
    # браузер закрыт ВСЕГДА (smoke-пункт 3)
    assert pw.browser.closed and pw.calls["launch"] == 1
    # был полный проход: goto + челлендж-селектор
    assert pw.page.gotos and "ozon.by/search" in pw.page.gotos[0]
    assert len(pw.page.evals) == 1


def test_fresh_session_skips_challenge(monkeypatch):
    """Живая сессия → composer сразу, goto НЕ вызывается (быстрый путь)."""
    monkeypatch.setenv("SHOP_OZON_HEADLESS", "1")
    oh._session_write([{"name": "abt_data", "value": "ok"}])
    pw = _FakePlaywright(composer_text='{"x": 2}')
    r = oh.collect_ozon_headless("смартфон", playwright_mod=pw)
    assert r["kind"] == "api_form_unknown"
    assert pw.page.gotos == []               # челлендж не проходился заново
    assert len(pw.page.evals) == 1           # composer сразу
    assert pw.context.cookies_added          # cookies добавлены в контекст


def test_stale_session_rechallenges(monkeypatch):
    oh._kv_set(oh.SESSION_KEY, json.dumps(
        {"cookies": [{"name": "old"}], "ts": time.time() - oh.SESSION_TTL - 60}))
    monkeypatch.setenv("SHOP_OZON_HEADLESS", "1")
    pw = _FakePlaywright(composer_text='{"y": 3}')
    r = oh.collect_ozon_headless("смартфон", playwright_mod=pw)
    assert r["kind"] == "api_form_unknown"
    assert pw.page.gotos                     # полный проход заново


def test_challenge_not_passed(monkeypatch):
    monkeypatch.setenv("SHOP_OZON_HEADLESS", "1")
    pw = _FakePlaywright(challenge_passes=False)
    r = oh.collect_ozon_headless("смартфон", playwright_mod=pw)
    assert r["ok"] is False and r["kind"] == "challenge_not_passed"
    assert pw.browser.closed                 # закрыли даже при отказе


def test_flag_off_fallback_when_headless_fails(monkeypatch):
    """Флаг включён, но браузерный путь упал → честный транспортный fallback."""
    monkeypatch.setenv("SHOP_OZON_HEADLESS", "1")
    monkeypatch.setitem(sys.modules, "playwright", None)
    calls = []
    monkeypatch.setattr(sc, "FETCH_JSON_FN",
                        lambda t, a: calls.append(1) or {"ok": False, "kind": "http_403",
                                                         "error": "HTTP 403"})
    r = sc.collect_ozon("смартфон")
    assert r["ok"] is False and calls        # упали на транспорт, не замолчали
