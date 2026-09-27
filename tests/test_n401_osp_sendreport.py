#!/usr/bin/env python3
"""Наряд #401: /osp/analyze шлёт отчёт через SendReport (архив Mini App).

Запуск: python3 -m pytest tests/test_n401_osp_sendreport.py -v

Контракт (#401):
  A.1 — роут /osp/analyze доставляет отчёт ОСП через SendReport (тот же путь,
        что у прямых запросов ОСП): архив miniapp_responses + превью с кнопкой.
  A.2 — остальные прямые SendTelegramReply(chat_id, reply) разобраны; остаются
        только служебные ответы Админа (по дизайну мимо miniapp) и собственный
        short-путь SendReport.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n401-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
MINIAPP = (REPO_ROOT / "dept" / "miniapp.mlog").read_text(encoding="utf-8")


def test_osp_analyze_uses_sendreport():
    """A.1: мост ЛЗ→ОСП доставляет отчёт как прямые запросы ОСП."""
    i0 = APP.index('route "/osp/analyze" method=POST')
    i1 = APP.index("return respond(\"200 analysis complete\")", i0)
    route = APP[i0:i1]
    assert 'SendReport(reply, "osp", query, "3.0", chat_id)' in route, (
        "/osp/analyze должен отправлять отчёт через SendReport")
    assert "SendTelegramReply(chat_id, reply)" not in route, (
        "прямая отправка из /osp/analyze потеряет отчёт >4096 символов")


def test_long_report_reaches_miniapp_archive():
    """SendReport для dept != yana/admin при >800 символов пишет miniapp_responses."""
    assert "INSERT INTO miniapp_responses" in MINIAPP
    assert "web_app: { url: miniapp_url }" in MINIAPP


def test_remaining_direct_sends_are_admin_service_only():
    """A.2: прямые SendTelegramReply(chat_id, reply) — только служебные ответы
    Админа (Admin по дизайну не идёт через miniapp) и short-путь SendReport."""
    app_lines = APP.splitlines()
    direct = [i for i, l in enumerate(app_lines)
              if "SendTelegramReply(chat_id, reply)" in l]
    assert len(direct) == 3, (
        f"прямых отправок в app.mlog должно быть 3 (админ-блоки), сейчас {len(direct)}")
    for i in direct:
        window = "\n".join(app_lines[max(0, i - 8):i + 2]).lower()
        assert "admin" in window, (
            f"прямая отправка вне админ-контекста (строка {i + 1}) — разобрать по A.2")
    mini_lines = MINIAPP.splitlines()
    m_direct = [i for i, l in enumerate(mini_lines)
                if "SendTelegramReply(chat_id, reply)" in l]
    assert len(m_direct) == 1, "в miniapp.mlog прямая отправка — только short-путь SendReport"
    seg = "\n".join(mini_lines[max(0, m_direct[0] - 10):m_direct[0] + 1])
    assert "pattern SendReport" in MINIAPP and "Short reply" in seg, (
        "единственная прямая отправка в miniapp.mlog — short-путь SendReport")
