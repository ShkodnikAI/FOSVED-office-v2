#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#740 OSP-FRESH, часть 1: A.1 (свежесть перед прогнозом) и A.2 («нет
данных» только после живого поиска).

Инцидент 17.11 (владелец): OSP-2026-11-17-CRIMEAN-BRIDGE-02 построен
05:47 по данным до 16.11 (атака ночи 16→17 не в кэше, слот сбора мёртв
при цикле server_failed #728); Яна 19:25: «нет данных о событии» без
поиска; ЛЗ: «blocked — нет канала данных».

Статические гварды — по исходникам (идиома test_n423), поведенческие —
на tmp-БД (идиома _b3_env test_n728_night4). A.3 — в
tests/test_n740_a3_watch.py.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = Path(__file__).resolve().parent.parent
OSP_MLOG = (REPO / "dept" / "osp.mlog").read_text(encoding="utf-8")
YANA_MLOG = (REPO / "dept" / "yana.mlog").read_text(encoding="utf-8")
LZ_MLOG = (REPO / "dept" / "lz.mlog").read_text(encoding="utf-8")
NEWS_PY = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
LZ_GITHUB = (REPO / "proxy" / "lz_github.py").read_text(encoding="utf-8")


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + 10)
    if nxt == -1:
        nxt = len(source)
    return source[start:nxt]


def _env(tmp_path, monkeypatch):
    os.environ['API_SECRET'] = 'test-secret-123'
    os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
    os.environ['OWNER_TELEGRAM_ID'] = '12345'
    os.environ['DATABASE_PATH'] = str(tmp_path)
    os.environ['ZAI_API_KEY'] = 'fake-key'
    import proxy.core as core
    db = str(tmp_path / "office.db")
    monkeypatch.setattr(core, "DB_FILE", db)
    from proxy.core import init_db, _query
    init_db()
    return _query


# ───────────── A.1: свежесть перед прогнозом ОСП ─────────────

def test_a1_freshness_patterns_exist():
    """Паттерны свежести определены и включены в путь контекста."""
    for p in ("OSPFreshnessData", "OSPFreshnessHeader", "OSPFreshnessVerdict",
              "OSPEventfulTopic"):
        assert f"pattern {p}" in OSP_MLOG, f"нет паттерна {p}"
    ctx = _pattern_body(OSP_MLOG, "BuildOSPContext")
    assert "OSPFreshnessData(" in ctx, "возраст данных не вычисляется в контексте"
    assert "OSPFreshnessHeader(" in ctx, "шапка «Данные на:» не вплетается"


def test_a1_header_line_format():
    """Шапка — строка формата наряда «Данные на: <время> (возраст N ч)»."""
    body = _pattern_body(OSP_MLOG, "OSPFreshnessHeader")
    assert "Данные на: " in body and "возраст" in body, (
        "шапка свежести не в формате наряда A.1")
    assert "НЕТ ЗАПИСЕЙ ПО ТЕМЕ" in body, (
        "нет отдельной ветки пустого кэша (это НЕ «события не было»)")


def test_a1_eventful_topic_triggers_live_search():
    """Событийная тема (военные/событийные ключи) с возрастом > 6 ч —
    дополнительный живой поиск в BuildOSPContext (Tavily поверх factpack)."""
    body = _pattern_body(OSP_MLOG, "BuildOSPContext")
    # #740 A.1: поиск — через обёртку OSPStaleTopicLive (инвариант #474:
    # прямой вызов OSPLiveSearchBlock в автоматическом пути запрещён)
    assert "OSPStaleTopicLive(query)" in body, (
        "дополнительный Tavily-поиск не вызывается при устаревшей теме")
    assert "OSPEventfulTopic(query) and f_age > 6.0" in body, (
        "условие (>6 ч + событийная тема) не ограждает поиск")
    wrap = _pattern_body(OSP_MLOG, "OSPStaleTopicLive")
    assert "OSPLiveSearchBlock(query)" in wrap, (
        "обёртка не ведёт к реальному живому поиску")


def test_a1_defer_blocks_publication():
    """> 12 ч и живой поиск пуст → прогноз НЕ публикуется: карточка в
    gated, событие REFUSED>published, владельцу — строка с возрастом."""
    save = _pattern_body(OSP_MLOG, "OSPSaveCard")
    assert "OSPFreshnessVerdict(" in save, (
        "OSPSaveCard не проверяет свежесть перед публикацией")
    assert "REFUSED>published" in save, "отказ не журналируется событием"
    assert "Прогноз отложен" in save, "владельцу не уходит строка откладывания"
    verdict = _pattern_body(OSP_MLOG, "OSPFreshnessVerdict")
    assert "устарели" in verdict, "причина defer без возраста данных"
    assert 'kv_get("osp_fresh_live_ok")' in save, (
        "факт живого поиска не читается из kv — вердикт слеп к live-данным")


def test_a1_freshness_route_and_helper():
    """Python-шов: /news/freshness (read-only) + osp_freshness —
    возраст по основам (как get_fresh_news) и последний сбор."""
    assert '"/news/freshness"' in LZ_GITHUB, "нет роута /news/freshness"
    assert "def osp_freshness(" in NEWS_PY, "нет хелпера osp_freshness"
    assert "_extract_keywords(query)" in NEWS_PY and "_stem(" in NEWS_PY, (
        "матчинг темы не по основам get_fresh_news")
    assert "MAX(collected)" in NEWS_PY, "последний успешный сбор не вычисляется"


def test_a1_freshness_age_math(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ: запись 14 ч назад → topic_age_hours ≈ 14 → defer при
    пустом поиске (тест-кейс наряда A.1: 14 ч, мок Tavily пуст)."""
    _query = _env(tmp_path, monkeypatch)
    _query("INSERT INTO news_cache (source, title, summary, category, published, collected) "
           "VALUES ('S', 'Удар по мосту X', 'сводка', 'geopolitics', "
           "datetime('now', '-14 hours'), datetime('now', '-14 hours'))", ())
    import proxy.news as news
    fresh = news.osp_freshness("удар по мосту X", dept="osp")
    assert fresh["topic_age_hours"] is not None, fresh
    assert 13.0 < fresh["topic_age_hours"] < 15.0, fresh
    # вердикт (эмуляция OSPFreshnessVerdict: событийная тема, поиск пуст)
    age = fresh["topic_age_hours"]
    assert age > 12.0, "14 ч — возраст обязан пробить порог defer"


def test_a1_freshness_no_topic_rows(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ: записей по теме нет → topic_age_hours None (шифр «нет
    данных», НЕ возраст 0) — ветка «НЕТ ЗАПИСЕЙ ПО ТЕМЕ» в шапке."""
    _query = _env(tmp_path, monkeypatch)
    _query("INSERT INTO news_cache (source, title, summary, category, published, collected) "
           "VALUES ('S', 'Курс евро', 'рынок', 'finance', "
           "datetime('now', '-1 hours'), datetime('now', '-1 hours'))", ())
    import proxy.news as news
    fresh = news.osp_freshness("удар по мосту Y", dept="osp")
    assert fresh["topic_latest"] is None and fresh["topic_age_hours"] is None, fresh


def test_a1_route_end_to_end(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ: /news/freshness отдаёт возраст и последний сбор (кэш
    30 ч — сбор «не работает», строка A.2 появляется у потребителей)."""
    _query = _env(tmp_path, monkeypatch)
    _query("INSERT INTO news_cache (source, title, summary, category, published, collected) "
           "VALUES ('S', 'Удар по мосту Z', 'сводка', 'geopolitics', "
           "datetime('now', '-30 hours'), datetime('now', '-30 hours'))", ())
    import llm_proxy  # noqa: F401
    import proxy.lz_github as lzg
    client = lzg.app.test_client()
    r = client.post("/news/freshness",
                    json={"query": "что с мостом Z после удара", "dept": "osp"})
    assert r.status_code == 200, r.status_code
    d = r.get_json()
    assert d["collect_age_hours"] > 12, d
    assert d["topic_age_hours"] > 12, d


# ───────────── A.2: «нет данных» только после живого поиска ─────────────

def test_a2_yana_block_exists_and_rules():
    """Яна: событийный вопрос → блок свежести с возрастом кэша, фактом
    Tavily-поиска и правилом «нет данных = только если поиск пуст»."""
    assert "pattern YanaNewsFreshnessBlock" in YANA_MLOG
    body = _pattern_body(YANA_MLOG, "YanaNewsFreshnessBlock")
    assert "TavilySearch(" in body, "живой поиск не выполняется"
    assert "возраст" in body, "возраст кэша не называется"
    assert "без факта поиска" in body, (
        "правило «нет данных только после поиска» не задано модели")
    handle = _pattern_body(YANA_MLOG, "HandleYana")
    assert "YanaNewsFreshnessBlock(query)" in handle, "блок не вплетён в контекст Яны"


def test_a2_dead_collector_named():
    """Сбор не работал > 12 ч — прямая строка «сбор новостей не работает
    с <время>» в блоках Яны и ЛЗ (тест-кейс наряда A.2)."""
    for name, src in (("YanaNewsFreshnessBlock", YANA_MLOG),
                      ("LZFreshnessBlock", LZ_MLOG)):
        body = _pattern_body(src, name)
        assert "сбор новостей не работает с" in body, (
            f"{name}: строка о неработающем сборе отсутствует")
        assert "> 12.0" in body, f"{name}: порог 12 ч не задан"


def test_a2_lz_block_in_context():
    """ЛЗ: блок свежести в BuildLZContext; констатация «данных нет» —
    только при пустом живом поиске."""
    assert "pattern LZFreshnessBlock" in LZ_MLOG
    body = _pattern_body(LZ_MLOG, "LZFreshnessBlock")
    assert "только если живой поиск" in body
    ctx = _pattern_body(LZ_MLOG, "BuildLZContext")
    assert "LZFreshnessBlock(query)" in ctx, "блок не вплетён в контекст ЛЗ"
