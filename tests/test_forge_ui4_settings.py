#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-4 tests (#197): экран «Настройки».

Гварды чек-листа:
- Провайдер: остаток дня из /api/budget/status (не захардкожен); три состояния
  точки (.on зелёный / .limit жёлтый / .off серый) из реальных данных
  (/api/models — ключ, /health — quota_cooldowns и provider_cooldowns);
  ссылка на Интеграции;
- Голос: приглушённые пункты (opacity .45, «нужен наряд»), БЕЗ обработчиков —
  реального HTTP-эндпоинта команд /voice нет (Telegram-контур), фейковый
  интерактив запрещён нарядом;
- Экран: тема — сегмент, синхронный с топбаром (одно состояние setTheme,
  общий localStorage-ключ); ориентация — 3 варианта НА ОТДЕЛЬНОЙ строке под
  подписью (не обрезаются на 390px), screen.orientation.lock() с честным
  catch (не поддерживается — не ошибка), выбор сохраняется;
- Отчёты по расписанию: пустая карточка + кнопка с честным «в разработке»;
- Модели по отделам: приглушены — HTTP-чтения config/override_*.txt и
  HTTP-вызова /model нет (команда живёт в Telegram-контуре).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui4-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


# ── Блок A. Провайдер ────────────────────────────────────────────────────

def test_budget_real_endpoint_no_hardcode():
    assert 'api("/api/budget/status")' in INDEX
    assert '<span id="budgetLeft">—</span>' in INDEX
    assert 'Number(g.limit)-Number(g.spent||0)' in INDEX  # остаток считается
    # захардкоженный остаток-число запрещён (кроме честного «—»)
    assert 'Остаток дня</span><span id="budgetLeft">$' not in INDEX


def test_provider_three_states_from_real_sources():
    assert '.prov-dot.on{background:var(--green)}' in INDEX
    assert '.prov-dot.limit{background:var(--yellow)}' in INDEX
    assert '.prov-dot.off{background:var(--line-strong)}' in INDEX
    # источники состояний — существующие эндпоинты
    assert 'api("/health")' in INDEX and 'api("/api/models")' in INDEX
    assert 'quota_cooldowns' in INDEX and 'provider_cooldowns' in INDEX
    assert 'p.status==="no_key"' in INDEX  # нет ключа → серая
    # причина лимита — реальные данные, «вернётся через N мин» из remaining_s
    assert 'вернётся через "+Math.max(1,Math.ceil(r.remaining_s/60))+" мин' in INDEX
    # лимитный статус подсвечен жёлтым (по наряду)
    assert 'style="color:var(--yellow)"' in INDEX
    # ссылка на интеграции (FORGE-UI-8)
    assert 'data-go="integrations"><span>Все 13 провайдеров и свои ключи</span>' in INDEX


# ── Блок B. Голос — приглушённое, без интерактива ────────────────────────

def test_voice_items_muted_no_handlers():
    assert '.muted-item{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid var(--line);opacity:.45}' in INDEX
    for item in ("Голосовые ответы (вкл/выкл)", "Женский / мужской голос",
                 "Скорость, громкость, тон", "Свой голос / свой провайдер"):
        assert f'<span>{item}</span><span class="need-narad">нужен наряд</span>' in INDEX
    # нет фейковых вызовов голосовых команд
    assert '"/voice' not in INDEX.replace('"/voice-set"', '')  # и voice-set (audit-stub) не притворяется работающим


# ── Блок C. Экран ────────────────────────────────────────────────────────

def test_theme_single_state_two_controls():
    # топбар и Настройки меняют ОДНО состояние через setTheme
    assert 'function setTheme(next){document.documentElement.setAttribute(\'data-theme\',next)' in INDEX
    assert 'function toggleTheme(){setTheme(document.documentElement' in INDEX
    assert 'data-settheme' in INDEX
    assert 'function applyThemeSeg(){var cur=document.documentElement.getAttribute(\'data-theme\')' in INDEX
    # ключ localStorage общий ('theme') — синхронизация через одно состояние
    assert "localStorage.setItem('theme',next)" in INDEX


def test_orientation_three_options_below_label():
    # три варианта на отдельной строке ПОД подписью (обёртка column)
    assert '<div class="set-row" style="flex-direction:column;align-items:flex-start;gap:10px">' in INDEX
    assert '<div class="row-label">Ориентация</div>' in INDEX
    for opt in ("Авто", "Вертикально", "Горизонтально"):
        assert f'data-setorient' in INDEX and f'>{opt}</button>' in INDEX
    assert 'class="seg-3" style="width:100%"' in INDEX
    # реальная блокировка с честным catch: не поддерживается — не ошибка
    assert 'screen.orientation' in INDEX
    assert 'so.lock(mode===\'portrait\'?\'portrait\':\'landscape\')' in INDEX
    assert 'p.catch(function(){' in INDEX
    # выбор сохраняется
    assert 'localStorage.setItem(\'orient\',mode)' in INDEX


# ── Блок D. Отчёты по расписанию ─────────────────────────────────────────

def test_scheduled_reports_honest_empty():
    assert 'Своих расписаний пока нет. Сейчас работают только встроенные — утренний бриф и LZ Daily.' in INDEX
    assert '<div class="add-btn" id="addReportBtn" role="button">+ Добавить отчёт</div>' in INDEX
    assert 'toast("Эта функция в разработке — нужен отдельный наряд")' in INDEX


# ── Блок E. Модели по отделам — приглушённое ─────────────────────────────

def test_models_per_dept_muted():
    assert 'Назначение модели отделу (/model dept provider model)</span><span class="need-narad">нужен наряд</span>' in INDEX
    assert 'Чтение текущих config/override_*.txt</span><span class="need-narad">нужен наряд</span>' in INDEX


# ── Общие инварианты ─────────────────────────────────────────────────────

def test_no_leftover_fake_toggles():
    # прежние декоративные тумблеры (data-toggle) удалены вместе с CSS
    assert 'data-toggle' not in INDEX
    assert '.toggle{width:44px' not in INDEX


def test_api_budget_status_shape():
    """A.1: /api/budget/status жив и отдаёт глобальный срез (остаток считается во фронте)."""
    with _client() as c:
        resp = c.get("/api/budget/status", headers=API_AUTH)
    assert resp.status_code == 200
    body = resp.get_json()
    assert "global" in body and "spent" in body["global"]
