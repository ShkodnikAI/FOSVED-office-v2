#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #567: токен бота не попадает в логи; длинные отчёты — частями.

Гварды:
- logging.Filter на root-хендлерах маскирует bot<токен> → bot<redacted>,
  обычные записи не тронуты (A.1);
- ошибка Telegram API логируется как status/desc/len — без {e} и без
  URL с токеном (A.2);
- текст > 4000 символов идёт частями ≤ 4000: части 1..n-1 без кнопки
  (_tg_send_message), последняя — с кнопкой; возврат — message_id
  последней части (A.3);
- текст 1000 символов — один вызов с кнопкой (поведение #561 не изменено);
- _tg_split_report: абзац → строка → жёстко, все части ≤ limit.
Реальный токен нигде не используется — только фиктивный
`123456:TEST_TOKEN_…` (запрет наряда).
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Конвенция тестов Flask: env до импорта прокси-модулей (значения miniapp-семейства)
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n567-token-log-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
# TELEGRAM_BOT_TOKEN НЕ задаётся: require_telegram пропускает без него

import llm_proxy  # noqa: E402,F401 — импорт до прокси-роутов
import requests  # noqa: E402
from proxy import telegram as tg  # noqa: E402
from proxy.core import _TgTokenRedactFilter, RENDER_URL  # noqa: E402

FAKE_TG_TOKEN = "123456:TEST_TOKEN_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
FAKE_URL = f"https://api.telegram.org/bot{FAKE_TG_TOKEN}/sendMessage"


class _Resp:
    """Заглушка ответа Telegram API; при >=400 raise_for_status несёт URL (как requests)."""

    def __init__(self, status=200, payload=None, message_id=1):
        self.status_code = status
        self._payload = payload or {"ok": True, "result": {"message_id": message_id}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: Bad Request for url: {FAKE_URL}")

    def json(self):
        return self._payload


def _capture_post(monkeypatch, responses):
    """Стаб http_requests в telegram.py: захват payload'ов, ответы по порядку."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": json})
        return responses[min(len(calls) - 1, len(responses) - 1)]

    class _HttpStub:
        @staticmethod
        def post(url, json=None, timeout=None):
            return fake_post(url, json=json, timeout=timeout)

    monkeypatch.setattr(tg, "TELEGRAM_BOT_TOKEN", FAKE_TG_TOKEN)
    monkeypatch.setattr(tg, "http_requests", _HttpStub)
    return calls


# ── A.1: маскирование токена в логах ─────────────────────────────────────


def test_filter_attached_and_masks_token():
    """A.4.1: фильтр на root-хендлерах; токен маскируется, обычный текст не тронут."""
    root_handlers = logging.getLogger().handlers
    assert any(any(isinstance(f, _TgTokenRedactFilter) for f in h.filters)
               for h in root_handlers), \
        "маскирующий фильтр должен быть на хендлерах root-логгера при импорте proxy.core"

    f = _TgTokenRedactFilter()
    # токен через args (как в реальном f-string/%-логе с {e})
    rec = logging.LogRecord("llm_proxy", logging.ERROR, __file__, 1,
                            "Telegram sendReport failed: 400 Client Error for url: %s",
                            (FAKE_URL,), None)
    assert f.filter(rec) is True, "фильтр не блокирует запись"
    out = rec.getMessage()
    assert "TEST_TOKEN" not in out, "токен не должен попасть в лог"
    assert "bot<redacted>" in out

    # токен уже в msg (args=None)
    rec_inline = logging.LogRecord("llm_proxy", logging.ERROR, __file__, 1,
                                   f"failed for url: {FAKE_URL}", (), None)
    f.filter(rec_inline)
    assert "TEST_TOKEN" not in rec_inline.getMessage()

    # обычная запись не искажается
    plain = "обычная запись: bot в тексте, но без токена"
    rec2 = logging.LogRecord("llm_proxy", logging.INFO, __file__, 1, plain, (), None)
    assert f.filter(rec2) is True
    assert rec2.getMessage() == plain


# ── A.2: причина ошибки Telegram в лог, без URL ──────────────────────────


def test_tg_error_logs_desc_without_url(monkeypatch, caplog):
    """A.4.2: 400 + description → в логе desc=…/status=…/len=…, НЕТ url и токена."""
    bad = _Resp(400, payload={"ok": False, "error_code": 400,
                              "description": "Bad Request: message is too long"})
    calls = _capture_post(monkeypatch, [bad])
    sample = "короткий отчёт"
    with caplog.at_level(logging.ERROR, logger="llm_proxy"):
        mid = tg._tg_send_report_with_button(42, sample, button_text="Открыть",
                                             button_url=f"{RENDER_URL}/miniapp/abc")
    assert mid is None, "при 400 message_id не возвращается"
    assert len(calls) == 1
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "desc=Bad Request: message is too long" in text, "причина 400 видна в логе"
    assert "status=400" in text
    assert f"len={len(sample)}" in text
    assert "api.telegram.org/bot" not in text, "URL с токеном не попадает в лог"
    assert "TEST_TOKEN" not in text, "токен не попадает в лог"


# ── A.3: длинный текст частями ───────────────────────────────────────────


def test_long_report_split_into_parts(monkeypatch):
    """A.4.3: 9000+ символов с абзацами → 3 вызова, каждый ≤ 4000, кнопка на последнем."""
    para = "А" * 1500
    text = "\n\n".join([para] * 6)  # 6*1500 + 5*2 = 9010
    assert len(text) > 9000
    calls = _capture_post(monkeypatch, [
        _Resp(message_id=1), _Resp(message_id=2), _Resp(message_id=3)])
    mid = tg._tg_send_report_with_button(42, text, button_text="Открыть",
                                         button_url=f"{RENDER_URL}/miniapp/abc")
    assert len(calls) == 3, f"ожидались 3 вызова, получено {len(calls)}"
    lens = [len(c["payload"]["text"]) for c in calls]
    assert all(ln <= 4000 for ln in lens), f"каждая часть ≤ 4000: {lens}"
    assert sum(lens) >= 9000, "содержимое отчёта не потеряно"
    for c in calls[:-1]:
        assert "reply_markup" not in c["payload"], "промежуточные части без кнопки"
    assert "reply_markup" in calls[-1]["payload"], "кнопка только на последней части"
    btn = calls[-1]["payload"]["reply_markup"]["inline_keyboard"][0][0]
    assert btn["web_app"]["url"] == f"{RENDER_URL}/miniapp/abc", "кнопка #561 сохранена"
    assert mid == 3, "возврат — message_id последней части"


def test_short_report_single_call(monkeypatch):
    """A.4.3b: 1000 символов → 1 вызов с кнопкой (поведение #561 не изменено)."""
    text = "Б" * 1000
    calls = _capture_post(monkeypatch, [_Resp(message_id=7)])
    mid = tg._tg_send_report_with_button(42, text, button_text="Открыть",
                                         button_url=f"{RENDER_URL}/miniapp/abc")
    assert len(calls) == 1, "короткий текст не режется"
    assert mid == 7
    btn = calls[0]["payload"]["reply_markup"]["inline_keyboard"][0][0]
    assert btn["web_app"]["url"] == f"{RENDER_URL}/miniapp/abc"


def test_split_report_priorities():
    """A.3 юнит: абзац → строка → жёстко; все части ≤ limit; содержимое сохраняется."""
    assert tg._tg_split_report("короткий", limit=4000) == ["короткий"]
    # жёсткий разрез: без разделителей
    hard = "Ж" * 9000
    parts = tg._tg_split_report(hard, limit=4000)
    assert [len(p) for p in parts] == [4000, 4000, 1000]
    assert "".join(parts) == hard
    # приоритет строки, когда абзацной границы в окне нет
    line = ("Л" * 300) + "\n" + ("М" * 9000)
    parts = tg._tg_split_report(line, limit=4000)
    assert all(len(p) <= 4000 for p in parts)
    assert "".join(parts).startswith("Л" * 300)
    # граница абзаца: части собираются из целых абзацев
    para = "П" * 1500
    parts = tg._tg_split_report("\n\n".join([para] * 6), limit=4000)
    assert len(parts) == 3
    assert all(len(p) == 3002 for p in parts)
