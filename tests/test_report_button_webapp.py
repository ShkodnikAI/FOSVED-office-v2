#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #561: кнопка «Открыть отчёт» — web_app вместо url для /miniapp/.

Факт (наряд): url-кнопка на /miniapp/<id> открывает внешний браузер без
initData → require_telegram отдаёт bootstrap-страницу «только из Telegram».
Гварды формы reply_markup в _tg_send_report_with_button:
- button_url на /miniapp/ (начинается с RENDER_URL) → web_app-кнопка
  с этим URL, ключа url нет (A.2.1);
- без button_url → прежняя url-кнопка https://t.me/FosvedMiniApp,
  web_app нет — дайджесты/обзоры расписания не ломаются (A.2.2);
- URL содержит /miniapp/, но начинается не с RENDER_URL → тоже web_app
  (условие «или содержит /miniapp/»);
- внешний URL без /miniapp/ → прежняя url-кнопка.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Конвенция тестов Flask: env до импорта прокси-модулей (значения — как у
# miniapp-семейства test_miniapp_refine/test_miniapp_action_notify, чтобы
# конфигурация proxy.core, закэшированная первым импортом, была совместима).
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n561-webapp-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
# TELEGRAM_BOT_TOKEN НЕ задаётся: require_telegram пропускает без него

import llm_proxy  # noqa: E402,F401 — импорт до прокси-роутов
from proxy import telegram as tg  # noqa: E402

RENDER_URL = tg.RENDER_URL


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True, "result": {"message_id": 4242}}


def _send_with(monkeypatch, button_url=None, button_text=None):
    """Замокать HTTP-вызов Telegram API внутри _tg_send_report_with_button,
    вернуть payload sendMessage. button_text=None — не перекрывать дефолт."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResp()

    class _HttpStub:
        @staticmethod
        def post(url, json=None, timeout=None):
            return fake_post(url, json=json, timeout=timeout)

    monkeypatch.setattr(tg, "TELEGRAM_BOT_TOKEN", "test-token-561")
    monkeypatch.setattr(tg, "http_requests", _HttpStub)
    kwargs = {"button_url": button_url}
    if button_text is not None:
        kwargs["button_text"] = button_text
    mid = tg._tg_send_report_with_button(42, "ТЕКСТ ОТЧЁТА", **kwargs)
    assert mid == 4242, "сообщение отправлено (ok=true из стаба)"
    assert captured["url"].startswith("https://api.telegram.org/bot")
    return captured["payload"]


def _btn(payload):
    kb = payload["reply_markup"]["inline_keyboard"]
    assert len(kb) == 1 and len(kb[0]) == 1, "одна inline-кнопка"
    return kb[0][0]


def test_miniapp_url_gets_web_app_button(monkeypatch):
    """A.2.1: {RENDER_URL}/miniapp/abc → web_app-кнопка, ключа url нет."""
    payload = _send_with(monkeypatch, button_url=f"{RENDER_URL}/miniapp/abc",
                         button_text="Открыть уточнённую версию")
    btn = _btn(payload)
    assert "web_app" in btn, "кнопка web_app — открытие внутри Telegram Mini App с initData"
    assert btn["web_app"]["url"] == f"{RENDER_URL}/miniapp/abc"
    assert "url" not in btn, "url-кнопки быть не должно"
    assert btn["text"] == "Открыть уточнённую версию"


def test_no_button_url_keeps_tme_url_button(monkeypatch):
    """A.2.2: без button_url → url-кнопка t.me/FosvedMiniApp, web_app нет."""
    payload = _send_with(monkeypatch)
    btn = _btn(payload)
    assert btn == {"text": "Otkryt otchet", "url": "https://t.me/FosvedMiniApp"}
    assert "web_app" not in btn


def test_url_containing_miniapp_also_gets_web_app(monkeypatch):
    """Содержит /miniapp/, но начинается не с RENDER_URL → web_app."""
    payload = _send_with(monkeypatch, button_url="https://mirror.example.com/miniapp/xyz")
    btn = _btn(payload)
    assert btn["web_app"]["url"] == "https://mirror.example.com/miniapp/xyz"
    assert "url" not in btn


def test_external_url_keeps_plain_url_button(monkeypatch):
    """Внешний URL без /miniapp/ → прежняя url-кнопка."""
    payload = _send_with(monkeypatch, button_url="https://example.com/report/1",
                         button_text="Открыть отчёт")
    btn = _btn(payload)
    assert btn == {"text": "Открыть отчёт", "url": "https://example.com/report/1"}
    assert "web_app" not in btn
