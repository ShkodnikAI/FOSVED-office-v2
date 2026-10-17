#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #522: карточка Визуала простым языком (стиль «Журналиста»),
фолбэк — детерминированный разбор #521.

A.1 POST /card-summary: один дешёвый вызов LLM (fosved-free), выход —
строгий JSON {verdict, theses[≤3], scenarios[≤3 {name, prob}], terms_explained[]};
raw_text — недоверенные данные (запрет исполнять инструкции — в промпте).
A.2 валидация кодом: JSON валиден; каждое число присутствует в raw_text
(иначе поле отбрасывается); термины стоп-листа (ATH, 52-нед, YTD, бейджи)
в содержательных полях отсутствуют, в terms_explained разрешены.
A.3 GenerateAnalysisCard: сначала /card-summary, при сбое/таймауте/невалидном
JSON — детерминированный разбор #521; источник текста — в audit_log
(card_text_source=plain|parsed).
A.4 тесты: фикстура отчёта ОСП (золото, 16.10); в JSON нет ATH/52-нед, нет
чисел вне отчёта; сломанный ответ модели → фолбэк.
Живая проверка: scripts/n522_live_probe.py — 12/12 PASS (оба пути).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n522-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '')

import llm_proxy  # noqa: E402,F401
from proxy import routes_tail  # noqa: E402
from proxy.core import app as flask_app  # noqa: E402

RAW_GOLD = (
    "КОНТР-АНАЛИЗ · OSP-2026-10-16-GOLD-01\n\n"
    "[ФАКТ] Текущая цена золота $4 118,42/oz — рост +48,7% YTD с начала года.\n"
    "[ФАКТ] 52-недельный диапазон $2 760,00–$4 198,50. Приток в ETF (GLD) держит цену.\n\n"
    "## Вердикт\n\nЗолото остаётся в бычьем тренде, но локально перекуплено: коррекция вероятна до конца месяца.\n\n"
    "## ВЕРОЯТНОСТИ СЦЕНАРИЕВ\n\n"
    "| Сценарий | Вероятность |\n|---|---|\n"
    "| Базовый: консолидация $4 000–4 300/oz | 55% |\n"
    "| Бычий: тест $4 600/oz | 25% |\n"
    "| Медвежий: откат к $3 600/oz | 20% |\n"
)


@pytest.fixture()
def client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _mock_llm(monkeypatch, reply):
    def fake_call_llm(dept, messages, **kwargs):
        assert dept == 'osp'
        assert kwargs.get('combo') == 'fosved-free', "карточка — дешёвый уровень fosved-free"
        assert 'не выполняй ничего' in messages[-1]['content'] or 'НЕ инструкция' in messages[-1]['content'], \
            "в промпте обязано быть правило не выполнять инструкции из текста отчёта"
        return {"reply": reply}
    monkeypatch.setattr(routes_tail, "call_llm", fake_call_llm)


# ── A.2 валидатор ─────────────────────────────────────────────────────────


def test_valid_summary_passes():
    reply = json.dumps({
        "verdict": "Золото дорожает, но возможна откатка до конца месяца.",
        "theses": ["Цена золота $4 118,42 за унцию — за год выросла почти наполовину."],
        "scenarios": [{"name": "Цена стоит между $4 000 и $4 300", "prob": "55%"}],
        "terms_explained": ["YTD — с начала текущего года."],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW_GOLD)
    assert s is not None
    assert "откатка" in s["verdict"]
    assert s["theses"] and s["scenarios"] == [{"name": "Цена стоит между $4 000 и $4 300", "prob": "55%"}]


def test_number_not_in_report_is_dropped():
    reply = json.dumps({
        "verdict": "Золото стоит 9 999,99 долларов за унцию — ждите роста.",
        "theses": [],
        "scenarios": [],
        "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW_GOLD)
    assert s is None, "число вне отчёта — весь вердикт отбрасывается, содержательного ничего не осталось"


def test_field_with_invented_number_is_dropped_only():
    reply = json.dumps({
        "verdict": "Золото на $4 118,42 — тренд бычий.",
        "theses": ["ETF приток держит цену.", "АУДИТ: запасы 777 тонн металла."],
        "scenarios": [],
        "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW_GOLD)
    assert s is not None
    assert s["verdict"], "валидный вердикт остаётся"
    assert s["theses"] == ["ETF приток держит цену."], "тезис с числом вне отчёта отбрасывается"


def test_stop_terms_dropped_from_content_but_ok_in_terms():
    reply = json.dumps({
        "verdict": "Рост +48,7% YTD продолжается.",
        "theses": ["Цена у ATH — максимум за всё время."],
        "scenarios": [{"name": "52-недельный диапазон сужается", "prob": "55%"}],
        "terms_explained": ["YTD — с начала текущего года."],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW_GOLD)
    # всё содержательное отброшено — валидатор возвращает None (фолбэк #521);
    # термины с YTD валидны сами по себе — проверим рядом с живым вердиктом:
    reply2 = json.dumps({
        "verdict": "Рост +48,7% за год продолжается.",
        "theses": [], "scenarios": [],
        "terms_explained": ["YTD — с начала текущего года."],
    }, ensure_ascii=False)
    s2 = routes_tail._validate_card_summary(reply2, RAW_GOLD)
    assert s is None, "YTD/ATH/52-нед в содержании — карточка не валидна"
    assert s2 is not None and s2["terms_explained"], "YTD в пояснении терминов — разрешён"


def test_broken_json_returns_none():
    assert routes_tail._validate_card_summary("модель ответила текстом без JSON", RAW_GOLD) is None
    assert routes_tail._validate_card_summary('{"verdict": обрыв', RAW_GOLD) is None
    assert routes_tail._validate_card_summary("", RAW_GOLD) is None


def test_numbers_with_spaces_and_comma_match():
    reply = json.dumps({
        "verdict": "Диапазон 2 760,00–4 198,50 — цена близко к максимуму.",
        "theses": [], "scenarios": [], "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW_GOLD)
    assert s is not None, "числа «2 760,00» и «4 198,50» есть в отчёте — нормализованная сверка"


# ── A.1 эндпоинт ──────────────────────────────────────────────────────────


def test_endpoint_ok(client, monkeypatch):
    reply = json.dumps({
        "verdict": "Золото на $4 118,42 — возможна откатка.",
        "theses": ["Приток в ETF держит цену."],
        "scenarios": [{"name": "Откатка к 4 тысячам", "prob": "20%"}],
        "terms_explained": [],
    }, ensure_ascii=False)
    _mock_llm(monkeypatch, reply)
    r = client.post('/card-summary', json={"raw_text": RAW_GOLD})
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["status"] == "ok" and d["summary"]["verdict"]


def test_endpoint_empty_raw_400(client, monkeypatch):
    r = client.post('/card-summary', json={"raw_text": ""})
    assert r.status_code == 400


def test_endpoint_invalid_reply_422(client, monkeypatch):
    _mock_llm(monkeypatch, "модель отказалась от JSON")
    r = client.post('/card-summary', json={"raw_text": RAW_GOLD})
    assert r.status_code == 422


def test_endpoint_llm_crash_502(client, monkeypatch):
    def boom(dept, messages, **kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(routes_tail, "call_llm", boom)
    r = client.post('/card-summary', json={"raw_text": RAW_GOLD})
    assert r.status_code == 502


# ── A.3 mlog-сторона: plain → фолбэк → audit ─────────────────────────────


def test_visual_has_plain_path_with_fallback_and_audit():
    visual = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dept", "visual.mlog")
    src = open(visual, encoding="utf-8").read()
    i_plain = src.index("/card-summary")
    i_render = src.index("RenderCardPdfViaProxy(output_path")
    assert i_plain < i_render, "простой язык опрашивается до рендера"
    assert "card_text_source" in src, "источник текста не журналируется"
    assert '"plain"' in src and '"parsed"' in src, "оба источника различаются в audit"
    assert "TryVal(try http_post" in src, "сбой /card-summary — честный фолбэк (TryVal)"
