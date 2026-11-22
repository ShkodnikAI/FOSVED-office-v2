#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#737 SRC-1: реестр источников с метками страна/тип/сторона,
украинские и европейские ленты, не больше 2 записей от источника.

Живая проверка A.2 (22.11, CI-подобное окружение): прошли Kyiv Independent
(200, свежие), DW en/ru (RDF 140/75), Politico EU (200/10), Le Monde in
English (200/14); отклонены по правилу наряда — pravda/ukrinform/suspilne/
eurointegration (403/404), euronews (406), france24/rfi (403) — таблица
в отчёте. Запреты: правило сопоставления RU/EU — SRC-2, не здесь.
"""
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

ORIGINS = {"RU", "BY", "UA", "GB", "DE", "FR", "QA", "US", "EU", "IL", "LV"}
OWNERSHIP = {"state", "independent", "public"}
CONFLICT_PARTY = {"RU", "UA", "none"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Тестовая БД news_cache (мигрированные колонки) + audit/error +
    rss_sources (слияние #203). Патч news._query — модуль связывает имя
    на верхнем уровне; sqlite3.Row — как прод-фабрика (r[0] и r["x"])."""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE news_cache (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " source TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, url TEXT,"
        " category TEXT DEFAULT 'general', language TEXT DEFAULT 'ru',"
        " published TIMESTAMP, collected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        " relevance_score REAL DEFAULT 0, hash TEXT UNIQUE,"
        " origin TEXT DEFAULT '', ownership TEXT DEFAULT '',"
        " conflict_party TEXT DEFAULT '');"
        "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " action TEXT, details TEXT, actor TEXT, created_at TEXT DEFAULT (datetime('now')));"
        "CREATE TABLE error_log (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " message TEXT, source TEXT, dept TEXT, kind TEXT,"
        " created_at TEXT DEFAULT (datetime('now')));"
        "CREATE TABLE rss_sources (feed TEXT PRIMARY KEY, url TEXT, name TEXT,"
        " tag TEXT, enabled INTEGER DEFAULT 1, custom INTEGER DEFAULT 0,"
        " deleted INTEGER DEFAULT 0);")
    conn.commit()

    class _W:
        def __init__(self, cur):
            self.rowcount = cur.rowcount

    def fake_q(sql, params=(), fetch=False):
        cur = conn.execute(sql, params)
        if fetch or sql.strip().upper().startswith("SELECT"):
            return cur.fetchall()  # sqlite3.Row — как прод-фабрика
        return _W(cur)

    monkeypatch.setattr(news, "_query", fake_q)
    yield conn
    conn.close()


# ─────────────── A.1: метки в реестре ───────────────

def test_a1_every_feed_has_labels():
    """Каждая лента RSS_FEEDS несёт три метки из закрытых словарей."""
    for fid, fc in news.RSS_FEEDS.items():
        assert fc.get("origin") in ORIGINS, f"{fid}: origin"
        assert fc.get("ownership") in OWNERSHIP, f"{fid}: ownership"
        assert fc.get("conflict_party") in CONFLICT_PARTY, f"{fid}: conflict_party"


def test_a1_labels_persist_on_collect(db, monkeypatch):
    """Новая запись news_cache получает метки ленты при сборе; метки при
    слиянии код-реестра с БД (#203) — из RSS_FEEDS (rss_enabled_feeds
    исполняется ЧЕСТНО, мутация «рег = None» ловится)."""
    import feedparser as _fp
    db.execute("INSERT INTO rss_sources (feed, url, name, tag) VALUES "
               "('interfax', ?, 'Интерфакс', 'news_ru')",
               (news.RSS_FEEDS["interfax"]["url"],))
    db.commit()

    # _rss_state_table сеединит ВСЕ ленты код-реестра — записи делаем
    # уникальными по url ленты (hash UNIQUE иначе переживает одна)
    class FakeFeed:
        def __init__(self, url):
            self.entries = [{"title": f"Заголовок {url}",
                             "summary": "текст",
                             "link": f"https://example.com/{abs(hash(url))}",
                             "published_parsed": (2026, 11, 22, 12, 0, 0, 0, 0, 0)}]
    monkeypatch.setattr(_fp, "parse", FakeFeed)
    n = news.collect_rss()
    assert n >= len(news.RSS_FEEDS), f"ожидались записи всех лент: {n}"
    row = db.execute("SELECT origin, ownership, conflict_party FROM news_cache "
                     "WHERE source='Интерфакс'").fetchone()
    assert row and row["origin"] == "RU" and row["ownership"] == "independent"
    assert row["conflict_party"] == "RU"
    # метки ВСЕХ записей совпадают с реестром (сверка по имени источника)
    for r in db.execute("SELECT source, origin, ownership, conflict_party "
                        "FROM news_cache").fetchall():
        fc = next(f for f in news.RSS_FEEDS.values() if f["name"] == r["source"])
        assert (r["origin"], r["ownership"], r["conflict_party"]) == \
            (fc["origin"], fc["ownership"], fc["conflict_party"]), r["source"]


def test_a1_migration_columns_in_core():
    """СТАТИКА: миграция +3 колонок news_cache в core.py (идиома блока)."""
    src = (REPO / "proxy" / "core.py").read_text(encoding="utf-8")
    for col in ("origin", "ownership", "conflict_party"):
        assert f'("ALTER TABLE news_cache ADD COLUMN {col} TEXT' in src


# ─────────────── A.2: новые ленты ───────────────

def test_a2_new_feeds_registered():
    """news_ua и news_eu в реестре (прошедшие живую проверку 22.11)."""
    ua = [f for f, fc in news.RSS_FEEDS.items() if fc["category"] == "news_ua"]
    eu = [f for f, fc in news.RSS_FEEDS.items() if fc["category"] == "news_eu"]
    assert "kyivindependent" in ua
    assert set(["dw_en", "dw_ru", "politico_eu", "lemonde_en"]) <= set(eu)
    for fid in ua + eu:
        fc = news.RSS_FEEDS[fid]
        assert fc["origin"] in ORIGINS and fc["ownership"] in OWNERSHIP
        assert fc["conflict_party"] in CONFLICT_PARTY


def test_a2_osp_legal_categories_include_ua_eu():
    """ОСП и legal получают news_ua, news_eu (наряд A.2)."""
    assert "news_ua" in news.DEPT_CATEGORIES["osp"]
    assert "news_eu" in news.DEPT_CATEGORIES["osp"]
    assert "news_ua" in news.DEPT_CATEGORIES["legal"]
    assert "news_eu" in news.DEPT_CATEGORIES["legal"]


def test_a2_fresh_query_multi_origin(db):
    """/news/fresh для dept: osp по «Крымский мост» — записи минимум из
    3 разных origin (наряд A.2, как проверяемость)."""
    rows = [
        ("РИА Новости", "Крымский мост закрыт на ремонт", "news_ru", "RU", "independent"),
        ("Deutsche Welle (en)", "Crimean bridge (Крымский мост) reopens after inspection", "news_eu", "DE", "public"),
        ("The Kyiv Independent", "Traffic restricted on Crimean bridge (Крымский мост)", "news_ua", "UA", "independent"),
        ("Зеркало", "Движение по Крымскому мосту приостановлено", "news_by", "BY", "independent"),
        ("BBC World", "Crimea bridge status (Крымский мост) update", "news_en", "GB", "public"),
    ]
    for i, (src, title, cat, origin, own) in enumerate(rows):
        db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
                   " language, published, hash, origin, ownership) "
                   "VALUES (?,?,?,?,?,?,datetime('now'),?,?,?)",
                   (src, title, title, f"https://x/{i}", cat, "ru", f"h{i}", origin, own))
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert text
    origins = {r[0] for r in db.execute(
        "SELECT DISTINCT origin FROM news_cache").fetchall()}
    assert len(origins) >= 3, origins
    assert "[RU," in text and "[UA," in text


# ─────────────── A.3: лимит на источник ───────────────

def test_a3_max_per_source(db):
    """НАРЯД A.3: 300 релевантных записей одной ленты (САМАЯ СВЕЖАЯ —
    без лимита топ-5 состоял бы только из неё) + по 3 от трёх других
    → в топ-5 не больше 2 от первой, редкие не вытеснены."""
    # flood-лента свежее редких (12:xx-16:59 vs 10:xx)
    for i in range(300):
        db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
                   " published, hash, origin) VALUES (?,?,?,?,?,?,?,?)",
                   ("RIA-flood", f"Крымский мост новость {i}",
                    "про Крымский мост", f"https://ria/{i}", "news_ru",
                    f"2026-11-22T{12 + i // 60}:{i % 60:02d}:00", f"f{i}", ""))
    for j, src_name in enumerate(("Зеркало", "DW", "KID")):
        for k in range(3):
            db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
                       " published, hash, origin) VALUES (?,?,?,?,?,?,?,?)",
                       (src_name, f"Крымский мост {src_name} {k}", "про мост",
                        f"https://{j}/{k}", "news_ru",
                        f"2026-11-22T10:{j * 2 + k:02d}:00", f"s{j}_{k}", ""))
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert text.count("RIA-flood") <= news.NEWS_MAX_PER_SOURCE, text
    assert news.NEWS_MAX_PER_SOURCE == 2
    assert ("Зеркало" in text or "DW" in text or "KID" in text), (
        "редкие ленты вытеснены flood-лентой")


def test_a3_window_per_feed_limits_dominance(db):
    """НАРЯД A.3 (окно): 600 релевантных записей одной ленты (переполняют
    прежнее окно 500) + 3 записи редкой ленты СТАРШЕ — без окна редкая
    лента вообще не попадает в 500 кандидатов; с окном (до 60 на ленту)
    — попадает в выдачу."""
    for i in range(600):
        db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
                   " published, hash) VALUES (?,?,?,?,?,?,?)",
                   ("Frequent", f"Крымский мост поток {i}", "про мост",
                    f"https://f/{i}", "news_ru",
                    f"2026-11-22T{12 + i // 60}:{i % 60:02d}:00", f"q{i}"))
    for k in range(3):
        db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
                   " published, hash) VALUES (?,?,?,?,?,?,?)",
                   ("Rare", f"Крымский мост редкий {k}", "про мост", f"https://r/{k}",
                    "news_ru", f"2026-11-22T09:0{k}:00", f"r{k}"))
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "Rare" in text, ("окно по лентам: редкая лента вытеснена 600 "
                            "записями частой — кандидаты должны включать "
                            "до 60 на ленту")
    assert "NEWS_WINDOW_PER_FEED" in (REPO / "proxy" / "news.py").read_text(encoding="utf-8")


# ─────────────── A.4: префиксы в выдаче и Tavily ───────────────

def test_a4_prefix_labels_in_output(db):
    """Выдача get_fresh_news — каждая строка [origin, ownership] + имя
    источника (SRC-2 будет сопоставлять по нему)."""
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash, origin, ownership) VALUES (?,?,?,?,?,?,?,?,?)",
               ("Deutsche Welle (en)", "Crimean bridge traffic resumed",
                "про мост", "https://dw/1", "news_ua", "2026-11-22T12:00:00",
                "d1", "DE", "public"))
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash, origin, ownership) VALUES (?,?,?,?,?,?,?,?,?)",
               ("RIA", "Крымский мост", "про мост", "https://ria/1", "news_ru",
                "2026-11-22T12:10:00", "r1", "RU", "state"))
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash) VALUES (?,?,?,?,?,?,?)",
               ("NoLabel", "Крымский мост снова", "про мост", "https://n/1",
                "news_ua", "2026-11-22T12:20:00", "n1"))
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    # #739 SRC-3 A.4: ownership в метке по-русски (формат примера наряда
    # «[RU, гос., точн. 0.40 (n=3)]»)
    assert "[DE, обществ.]" in text
    assert "[RU, гос.]" in text
    assert "[?, ?]" in text, "запись без меток обязана быть [?, ?]"
    assert "Deutsche Welle (en):" in text, "имя источника сохранено в строке"


def test_a4_tavily_domain_labels():
    """Разметка домена Tavily: известный домен → метки реестра, неизвестный
    → пусто; поддомен матчится."""
    o, w = news._tavily_source_labels("https://www.dw.com/news/some-article-x")
    assert (o, w) == ("DE", "public")
    o2, w2 = news._tavily_source_labels("https://unknown-site.example/a")
    assert (o2, w2) == ("", "")
    o3, w3 = news._tavily_source_labels("https://blog.theguardian.com/x")
    assert (o3, w3) == ("GB", "independent"), "поддомен тоже матчится"


def test_a4_tavily_insert_has_labels():
    """СТАТИКА: INSERT collect_tavily размечает запись вызовом
    _tavily_source_labels(url) (мутация «не размечаются» ловится)."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    seg = src[src.index("def collect_tavily"):src.index("def collect_gdelt")]
    assert "origin,ownership,conflict_party" in seg
    assert "_t_origin, _t_ownership" in seg
    assert "_tavily_source_labels(url)" in seg, (
        "вызов разметки домена исчез из collect_tavily")


# ─────────────── запреты наряда ───────────────

def test_no_feeds_removed():
    """Запрет: ни одна существующая лента не удалена (20 исходных живы)."""
    baseline = {"ria", "tass", "rbk", "interfax", "kommersant",
                "guardian_world", "bbc", "aljazeera", "techcrunch",
                "theverge", "hackernews", "arxiv_ai", "arxiv_cl",
                "investing_ru", "foreignaffairs", "belta", "sputnik_by",
                "minsknews", "zerkalo", "onliner"}
    assert baseline <= set(news.RSS_FEEDS.keys())


def test_no_matching_rule_src2():
    """Запрет: правило сопоставления RU/EU — SRC-2, не здесь: в SQL
    get_fresh_news нет ФИЛЬТРА по conflict_party (SELECT-колонка для
    пометок SRC-2 разрешена; WHERE-условие по стороне — нет)."""
    body = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    m = body[body.index("def get_fresh_news"):body.index("def get_night_news_items")]
    import re as _re
    for sql in _re.findall(r'"""(.*?)"""', m, _re.S):
        where = sql[sql.upper().find("WHERE"):]
        assert "conflict_party" not in where, (
            "фильтрация по стороне в WHERE — это SRC-2, запрет")
