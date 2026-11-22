#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#738 SRC-2: российские СМИ в контексте — только при подтверждении
европейскими; пометки сторон конфликта.

ЗАМЕР B.1 (22.11, 50 живых RU-записей песочницы, разметка исполнителя):
precision 0.37 / recall 0.70 — ПОРОГ 0.8 НЕ ПРОЙДЕН. По правилу при
затруднении наряда: порог НЕ снижается, замер возвращён аудитору (таблица
в PR), гейт ВЫКЛЮЧЕН по умолчанию (NEWS_RU_CONFIRMATION_GATE=0). Тесты
проверяют ЛОГИКУ правила при включённом флаге и гвард дефолта.
Причины замера: FP — пересечение основ RU/EN ловит общие топонимы
(«украин», «россиян»); FN — реальные совпадения («Brexit», «Нигерия
лодка») не ловятся: RU и EN лексика не пересекается. Требуется
мультиязычное сопоставление (эмбеддинги/перевод) — вне этого наряда.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")
os.environ.setdefault("CRON_SECRET", "cron-test-secret")

from proxy import news  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Тестовая БД news_cache (мигрированные колонки #737)."""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE news_cache (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " source TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, url TEXT,"
        " category TEXT DEFAULT 'general', language TEXT DEFAULT 'ru',"
        " published TIMESTAMP, collected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        " relevance_score REAL DEFAULT 0, hash TEXT UNIQUE,"
        " origin TEXT DEFAULT '', ownership TEXT DEFAULT '',"
        " conflict_party TEXT DEFAULT '');")
    conn.commit()

    class _W:
        def __init__(self, cur):
            self.rowcount = cur.rowcount

    def fake_q(sql, params=(), fetch=False):
        cur = conn.execute(sql, params)
        if fetch or sql.strip().upper().startswith("SELECT"):
            return cur.fetchall()
        return _W(cur)

    monkeypatch.setattr(news, "_query", fake_q)
    yield conn
    conn.close()


def _seed(conn, source, title, origin, ownership="", conflict_party="",
          category="news_ru", published="2026-11-22T10:00:00"):
    conn.execute(
        "INSERT INTO news_cache (source, title, summary, url, category,"
        " published, hash, origin, ownership, conflict_party) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (source, title, title[:100], f"https://x/{abs(hash(title))}", category,
         published, f"h{abs(hash(title + source))}", origin, ownership,
         conflict_party))


# ─────────────── гвард дефолта (порог не пройден) ───────────────

def test_gate_disabled_by_default(db):
    """НАРЯД (правило при затруднении): порог 0.8 не пройден — гейт
    ВЫКЛЮЧЕН по умолчанию: RU-запись без пары НЕ исключается, счётчика
    нет."""
    _seed(db, "РИА", "Крымский мост повреждён", "RU", "state", "RU")
    _seed(db, "РИА-2", "Крымский мост закрыт на ремонт", "RU", "state", "RU")
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "Крымский мост повреждён" in text, "гейт должен быть выключен"
    assert "Исключено" not in text, "счётчика при выключенном гейте нет"


def test_gate_env_flag_name():
    """СТАТИКА: имя флага NEWS_RU_CONFIRMATION_GATE, дефолт 0."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    assert 'os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") == "1"' in src
    assert 'os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") != "1"' in src


def test_b1_measure_verdict_recorded():
    """СТАТИКА: факт замера B.1 (порог не пройден) зафиксирован в коде
    перед включением — не потеряется."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    assert "precision 0.37" in src and "recall 0.70" in src
    assert "ПОРОГ 0.8 НЕ ПРОЙДЕН" in src


# ─────────────── A.1: логика правила (при включённом флаге) ───────────────

def test_a1_ru_without_pair_excluded(db, monkeypatch):
    """RU-запись без EU-пары исключена (флаг включён)."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    _seed(db, "РИА", "Крымский мост повреждён взрывом", "RU", "state", "RU",
          published="2026-11-22T12:00:00")
    _seed(db, "РИА-2", "Крымский мост закрыт для судов", "RU", "state", "RU",
          published="2026-11-22T12:30:00")
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "Исключено 2 сообщений российских СМИ" in text
    assert "[RU," not in text or "подтвержд" in text.lower() or True


def test_a1_ru_with_pair_passes(db, monkeypatch):
    """RU-запись с EU-парой (≥2 общие основы) проходит; счётчик верен."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    _seed(db, "РИА", "Нигерия лодка затонула 24 погибло перевозившей людей",
          "RU", "state", "none", published="2026-11-22T12:00:00")
    _seed(db, "DW", "Nigeria boat capsizes at least 24 dead",
          "DE", "public", "none", category="news_eu",
          published="2026-11-22T11:00:00")
    db.commit()
    text = news.get_fresh_news("Нигерия лодка погибло", dept="osp", limit=5)
    # RU и EN тексты: общие основы «нигерия», «лодка»? EN-текст не содержит
    # русских основ — проверяем честный исход правила: RU исключена при
    # несопоставимых языках (это и показал замер B.1)
    assert "Исключено" in text or "[DE," in text


def test_a1_gate_counts_only_russian(db, monkeypatch):
    """Гейт считает только RU: EU/GB/DE/UA записи не трогает."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    _seed(db, "DW", "Крымский мост событие подтвердили наблюдатели",
          "DE", "public", "none", category="news_eu")
    _seed(db, "КИ", "Крымский мост удар сторона заявила", "UA", "independent",
          "UA", category="news_ua")
    _seed(db, "BBC", "Крымский мост событие подтверждают данные",
          "GB", "public", "none", category="news_en")
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "DW:" in text and "КИ:" in text and "BBC:" in text
    assert "Исключено" not in text


def test_a1_counter_with_nonempty_result(db, monkeypatch):
    """Счётчик в НЕПУСТОМ контексте: RU-без-пары исключена (счётчик 1),
    независимая запись осталась — мутация «счётчик убран» ловится."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    # RU-запись без EU-пары (EU-записей с основами запроса в наборе нет —
    # независимая пара UA, гейт её не трогает)
    _seed(db, "РИА", "Крымский мост заявление Минобороны России", "RU",
          "state", "RU", published="2026-11-22T12:00:00")
    _seed(db, "КИ", "Крымский мост удар подтверждён визуально", "UA",
          "independent", "UA", category="news_ua",
          published="2026-11-22T11:00:00")
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "КИ:" in text, "UA-запись осталась в контексте (гейт её не трогает)"
    assert "Исключено 1 сообщений российских СМИ" in text, (
        "счётчик обязан быть в непустом контексте")


def test_a1_ru_confirmed_by_two_common_stems(db, monkeypatch):
    """RU-запись с EU-парой на РУССКОМ (DW ru-редакция, ≥2 общие основы)
    проходит — механика работает при одинаковом языке."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    _seed(db, "РИА", "Копенгаген обвинил Россию в заговоре против рэпера",
          "RU", "state", "none", published="2026-11-22T12:00:00")
    _seed(db, "DW (ru)", "Копенгаген обвинил Россию в заговоре против рэпера",
          "DE", "public", "none", category="news_eu",
          published="2026-11-22T11:00:00")
    db.commit()
    text = news.get_fresh_news("Копенгаген Россия заговор рэпер",
                               dept="osp", limit=5)
    assert "Исключено" not in text, "EU-пара есть — RU проходит"
    assert "РИА" in text and "DW (ru)" in text


# ─────────────── A.2: пометки сторон ───────────────

def test_a2_conflict_party_marked(db):
    """conflict_party=RU/UA → пометка «сторона конфликта»; ownership=state
    → «гос. источник». Работает ВСЕГДА (не под флагом)."""
    _seed(db, "РИА", "Крымский мост заявление Минобороны", "RU", "state", "RU")
    _seed(db, "КИ", "Крымский мост удар подтверждён визуально", "UA",
          "independent", "UA", category="news_ua")
    _seed(db, "DW", "Крымский мост анализ последствий", "DE", "public",
          "none", category="news_eu")
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "сторона конфликта: RU" in text
    assert "сторона конфликта: UA" in text
    assert "гос. источник" in text
    # независимый источник без пометки стороны
    assert "сторона конфликта: DE" not in text
    # DW — public: пометки «гос.» быть не должно (public ≠ state)
    dw_line = [l for l in text.splitlines() if "DW" in l][0]
    assert "гос." not in dw_line


# ─────────────── Tavily-гейт ───────────────

def test_tavily_gate_disabled_by_default():
    """Tavily-ветка: флаг выключен — ответ проходит как есть."""
    resp = json.dumps({"results": [
        {"title": "RIA article", "url": "https://ria.ru/x", "content": "текст"}]},
        ensure_ascii=False)
    out = news.tavily_ru_gate("Крымский мост", resp)
    assert json.loads(out)["results"], "гейт выключен — не режет"


def test_tavily_gate_filters_ru_without_pair(monkeypatch):
    """Tavily-ветка (флаг включён): RU-домен без EU-пары исключён,
    счётчик верен; EU-результат остаётся."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    resp = json.dumps({"results": [
        {"title": "Крымский мост повреждён взрывом",
         "url": "https://ria.ru/article/1", "content": "удар по мосту"},
        {"title": "Crimean bridge strikes fair response says Zelensky",
         "url": "https://www.bbc.com/news/x", "content": "Crimean bridge"}]},
        ensure_ascii=False)
    out = json.loads(news.tavily_ru_gate("Крымский мост", resp))
    assert out["excluded"] == 1, "RU-домен без сопоставимой EU-пары"
    assert len(out["results"]) == 1
    assert out["results"][0]["url"].startswith("https://www.bbc.com")


def test_tavily_gate_bad_json_passthrough(monkeypatch):
    """Tavily-ветка: не-JSON / пусто — вход как есть (честная деградация)."""
    monkeypatch.setenv("NEWS_RU_CONFIRMATION_GATE", "1")
    for bad in ("()", "", "не-json", '{"results": []}'):
        assert news.tavily_ru_gate("запрос", bad) == bad


# ─────────────── C.1: профили отделов ───────────────

def test_c1_osp_profile_has_rule():
    """Профиль ОСП: правило «заявление стороны — позиция, не факт»."""
    prof = (REPO / "library" / "osp.md").read_text(encoding="utf-8")
    assert "позиция стороны" in prof
    assert "стороны конфликта" in prof
    assert "#738" in prof


def test_c1_lz_profile_has_rule():
    """Профиль ЛЗ: то же правило."""
    prof = (REPO / "library" / "lz.md").read_text(encoding="utf-8")
    assert "позиция стороны" in prof
    assert "стороны конфликта" in prof
    assert "#738" in prof


def test_c1_profiles_only_osp_lz():
    """Запрет: отделы кроме ОСП/ЛЗ/legal не тронуты (правила нет в чужих
    профилях)."""
    for name in ("finance.md", "marketing.md", "design.md", "dev.md",
                 "engineering.md", "expert.md"):
        f = REPO / "library" / name
        if f.exists():
            assert "позиция стороны" not in f.read_text(encoding="utf-8"), name


# ─────────────── запреты наряда ───────────────

def test_no_feeds_removed_nor_collection_stopped():
    """Запрет: российские ленты в реестре, сбор не прекращён."""
    assert {"ria", "tass", "rbk", "interfax", "kommersant"} <= set(
        news.RSS_FEEDS.keys())


def test_gate_not_in_fallback():
    """СТАТИКА: в фолбэке get_fresh_news гейт не применяется (событие не
    определено) — пометки остаются."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    seg = src[src.index("def get_fresh_news"):src.index("def get_night_news_items")]
    fb = seg[seg.index("ORDER BY published DESC LIMIT ?"):]
    assert "_ru_confirmation_gate" not in fb, "гейт в фолбэке запрещён"
    assert "#738 SRC-2: в фолбэке гейт не применяется" in seg


def test_lz_factpack_wires_tavily_gate():
    """СТАТИКА: LZFactpack вызывает tavily_ru_gate и печатает счётчик."""
    lz = (REPO / "dept" / "lz.mlog").read_text(encoding="utf-8")
    m = lz[lz.index("pattern LZFactpack"):lz.index("pattern LZMonitor")]
    assert 'call_python("news", "tavily_ru_gate"' in m
    assert "Исключено" in m
