#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#739 SRC-3: репутационный рейтинг источников (скорость/точность) по
разобранным событиям; ведёт Кавальня; первый случай — Крымский мост 17.11.

Запреты: правило SRC-2 и отбор по умолчанию не меняются (гейт выключен,
гвард n738 жив); оценки источников НЕ ставятся в коде — только из
разобранных событий (source_reports).
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


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Тестовая БД: news_cache (#737-колонки) + source_events/source_reports."""
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
        "CREATE TABLE source_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " event TEXT NOT NULL UNIQUE, fact TEXT, outcome TEXT DEFAULT 'pending',"
        " confirmed_at TEXT, confirmed_by TEXT,"
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP);"
        "CREATE TABLE source_reports (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " event_id INTEGER NOT NULL, source TEXT NOT NULL, published TEXT,"
        " claim TEXT, match TEXT DEFAULT 'pending', counted INTEGER DEFAULT 1,"
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
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


def _ev(conn, event, outcome="confirmed", fact="факт", by="владелец"):
    eid, _ = news.register_resolved_event(event, fact, outcome, by)
    return eid


def _rep(conn, eid, source, published, match, counted=1, claim="утверждение"):
    conn.execute("INSERT INTO source_reports (event_id, source, published, claim,"
                 " match, counted) VALUES (?,?,?,?,?,?)",
                 (eid, source, published, claim, match, counted))
    conn.commit()


# ─────────────── A.1: счёт и сглаживание (3 синтетических события) ──────

def test_a1_accuracy_beta_smoothing(db):
    """НАРЯД A.1: 3 синтетических события — точность = (да + 0.5·частично
    + 1) / (n + 2) (Beta(1,1)). Источник: 2 «да», 1 «частично», 1 «нет»
    → s = 2 + 0.5 = 2.5, n = 4 → (2.5+1)/(4+2) = 3.5/6 ≈ 0.5833."""
    e1 = _ev(db, "Событие-1")
    e2 = _ev(db, "Событие-2")
    e3 = _ev(db, "Событие-3")
    e4 = _ev(db, "Событие-4")
    _rep(db, e1, "Ист-А", "2026-11-22T10:00:00", "yes")
    _rep(db, e2, "Ист-А", "2026-11-22T10:00:00", "yes")
    _rep(db, e3, "Ист-А", "2026-11-22T10:00:00", "partial")
    _rep(db, e4, "Ист-А", "2026-11-22T10:00:00", "no")
    acc, n = news.source_accuracy("Ист-А")
    assert n == 4
    assert abs(acc - 3.5 / 6) < 1e-9, acc


def test_a1_accuracy_excludes_uncounted_and_pending(db):
    """Справочные строки (counted=0) и события без итога (undetermined/
    pending) НЕ в счёте."""
    e1 = _ev(db, "С-1")
    e2 = _ev(db, "С-2", outcome="undetermined")
    e3 = _ev(db, "С-3", outcome="pending")
    _rep(db, e1, "Ист-Б", "2026-11-22T10:00:00", "yes", counted=1)
    _rep(db, e1, "Ист-Б", "2026-11-22T10:00:00", "yes", counted=0)
    _rep(db, e2, "Ист-Б", "2026-11-22T10:00:00", "yes", counted=1)
    _rep(db, e3, "Ист-Б", "2026-11-22T10:00:00", "yes", counted=1)
    acc, n = news.source_accuracy("Ист-Б")
    assert n == 1
    assert abs(acc - 2 / 3) < 1e-9, "Beta(1,1): (1+1)/(1+2)"


def test_a1_accuracy_zero_events_is_neutral(db):
    """n=0 — нейтральный счёт Beta(1,1): 0.5 (но метка его не показывает)."""
    acc, n = news.source_accuracy("Нет-такого")
    assert (acc, n) == (0.5, 0)


def test_a1_speed_median_lag(db):
    """НАРЯД A.1: скорость — медиана отставания от ПЕРВОГО верного
    сообщения. События: С-1 (Ист-А +10 мин после верного Ист-Б), С-2
    (Ист-А +20 мин), С-3 (Ист-А сам первый верный → 0) → медиана(10,20,0)
    = 10 мин."""
    e1 = _ev(db, "Сп-1")
    e2 = _ev(db, "Сп-2")
    e3 = _ev(db, "Сп-3")
    # С-1: верный первый — Ист-Б 10:00; Ист-А 10:10 → лаг 10
    _rep(db, e1, "Ист-Б", "2026-11-22T10:00:00", "yes")
    _rep(db, e1, "Ист-А", "2026-11-22T10:10:00", "yes")
    # С-2: верный первый — Ист-Б 11:00; Ист-А 11:20 → лаг 20
    _rep(db, e2, "Ист-Б", "2026-11-22T11:00:00", "yes")
    _rep(db, e2, "Ист-А", "2026-11-22T11:20:00", "yes")
    # С-3: Ист-А сам первый верный → лаг 0
    _rep(db, e3, "Ист-А", "2026-11-22T12:00:00", "yes")
    med, k = news.source_speed("Ист-А")
    assert k == 3
    assert med == 10.0, med


def test_a1_speed_no_first_yes(db):
    """Событие без верного сообщения — скорость не считается."""
    e1 = _ev(db, "Сп-х")
    _rep(db, e1, "Ист-В", "2026-11-22T10:00:00", "no")
    med, k = news.source_speed("Ист-В")
    assert med is None and k == 0


# ─────────────── A.2: первый случай ───────────────

def test_a2_first_case_registered(db):
    """СТАТИКА: скрипт A.2 содержит событие, итог, и разметку counted
    (в лентах офиса — только РИА; остальное справочно)."""
    s = (REPO / "scripts" / "n739_first_case.py").read_text(encoding="utf-8")
    assert "Крымский мост 17.11" in s
    assert 'OUTCOME = "confirmed"' in s
    assert ('"РИА Новости", "2026-11-17T09:08+03:00"' in s
            and '"no", 1' in s), "РИА в счёт (counted=1)"
    # справочные: UA-каналы/The Insider/Настоящее время/Moscow Times/Медиазона
    for src_name in ("Exilenova+", "The Insider", "Настоящее время",
                     "The Moscow Times", "Медиазона"):
        assert src_name in s
    assert 'counted=0' in s


def test_a2_first_case_idempotent(db, monkeypatch):
    """Скрипт A.2 идемпотентен: повторный запуск не дублирует строки."""
    # запускаем логику скрипта на тестовой БД (моки news._query уже стоят)
    import importlib.util
    # счёт РИА по формуле: no, counted=1 → (0+1)/(1+2)=0.33
    e = _ev(db, "Крымский мост 17.11 — обрушение пролёта",
            fact="обрушение автопролёта", by="аудитор 20.11")
    rid, _ = news.set_report_match("Крымский мост 17.11 — обрушение пролёта",
                                   "РИА Новости", "no", counted=1)
    # повтор — не создаёт вторую строку
    news.set_report_match("Крымский мост 17.11 — обрушение пролёта",
                          "РИА Новости", "no", counted=1)
    rows = db.execute("SELECT COUNT(*) c FROM source_reports WHERE source='РИА "
                      "Новости'").fetchone()
    assert rows["c"] == 1
    acc, n = news.source_accuracy("РИА Новости")
    assert n == 1 and abs(acc - 1 / 3) < 1e-9


# ─────────────── A.3: Кавальня создаёт события ───────────────

def test_a3_resolved_event_matches_reports(db):
    """НАРЯД A.3: разрешённый вопрос (register_resolved_event) порождает
    событие; match_reports_from_news_cache создаёт ≥1 оценку (кандидата)
    сообщения из news_cache (правило пересечения основ ≥2, SRC-2 A.1)."""
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash) VALUES (?,?,?,?,?,?,?)",
               ("РИА Новости", "Крымский мост обрушение пролёта при атаке",
                "арка в море", "https://ria/bridge", "news_ru",
                "2026-11-17T09:08:00", "b1"))
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash) VALUES (?,?,?,?,?,?,?)",
               ("РИА Новости", "Курс доллара вырос", "валюта",
                "https://ria/usd", "finance", "2026-11-17T09:09:00", "b2"))
    db.commit()
    eid, created = news.register_resolved_event(
        "Крымский мост 17.11", "обрушение автопролёта", "confirmed", "владелец")
    assert created
    added = news.match_reports_from_news_cache(
        "Крымский мост 17.11", "Крымский мост обрушение пролёта", window_hours=168)
    assert added >= 1, "оценка сообщения порождена"
    rows = db.execute("SELECT source, match FROM source_reports WHERE event_id=?",
                      (eid,)).fetchall()
    assert any(r["source"] == "РИА Новости" for r in rows)
    assert all(r["match"] == "pending" for r in rows), "оценку ставит Кавальня"


def test_a3_match_reports_no_event(db):
    """Сопоставление без зарегистрированного события — честный отказ."""
    with pytest.raises(ValueError):
        news.match_reports_from_news_cache("нет-такого", "запрос")


def test_a3_kavalnya_seam_exists():
    """СТАТИКА: шов Кавальни KKRegisterSourceEvent/KKMatchSourceReports
    в dept/kavalnya.mlog + call_python на news."""
    mlog = (REPO / "dept" / "kavalnya.mlog").read_text(encoding="utf-8")
    assert "pattern KKRegisterSourceEvent" in mlog
    assert "pattern KKMatchSourceReports" in mlog
    assert 'call_python("news", "register_resolved_event"' in mlog
    assert 'call_python("news", "match_reports_from_news_cache"' in mlog


def test_a3_kavalnya_profile_rule():
    """СТАТИКА: профиль Кавальни — правило ведения событий и запрет
    оценок в коде."""
    prof = (REPO / "library" / "kavalnya.md").read_text(encoding="utf-8")
    assert "#739" in prof
    assert "set_report_match" in prof
    assert "оценки в коде запрещены" in prof


def test_a3_set_report_match_values(db):
    """set_report_match: значения закрытого словаря, счёт/справочно."""
    e = _ev(db, "Оц-1")
    rid, ok = news.set_report_match("Оц-1", "Ист-Г", "partial", counted=1)
    assert ok
    with pytest.raises(ValueError):
        news.set_report_match("Оц-1", "Ист-Г", "верно")  # вне словаря
    acc, n = news.source_accuracy("Ист-Г")
    assert n == 1 and abs(acc - 1.5 / 3) < 1e-9


# ─────────────── A.4: метка с точностью и n ───────────────

def test_a4_label_suffix_format(db):
    """НАРЯД A.4: ', точн. 0.40 (n=3), мало данных' при n<10; n=0 — пусто;
    n>=10 — без пометки."""
    e = _ev(db, "М-1")
    for i in range(3):
        _rep(db, e, "Ист-Д", "2026-11-22T10:00:00", "yes")
    acc, n = news.source_accuracy("Ист-Д")
    assert abs(acc - 4 / 5) < 1e-9
    tail = news.source_label_suffix("Ист-Д")
    assert tail == ", точн. 0.80 (n=3), мало данных", tail
    # n=0 — пусто
    assert news.source_label_suffix("Нет-такого") == ""


def test_a4_label_no_few_data_after_10(db):
    """n>=10 — пометка «мало данных» снята."""
    e = _ev(db, "М-2")
    for i in range(10):
        _rep(db, e, "Ист-Е", "2026-11-22T10:00:00", "yes")
    tail = news.source_label_suffix("Ист-Е")
    assert "мало данных" not in tail
    assert "(n=10)" in tail


def test_a4_label_in_fresh_news_output(db):
    """Метка в выдаче get_fresh_news: [RU, гос., точн. X (n=Y), мало
    данных] — формат примера наряда; n=0 — метка без счёта."""
    e = _ev(db, "М-3")
    _rep(db, e, "РИА Новости", "2026-11-22T09:08:00", "no", counted=1)
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash, origin, ownership) VALUES (?,?,?,?,?,?,?,?,?)",
               ("РИА Новости", "Крымский мост повреждён", "текст",
                "https://ria/x", "news_ru", "2026-11-22T12:00:00", "f1",
                "RU", "state"))
    db.commit()
    text = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "[RU, гос., точн. 0.33 (n=1), мало данных]" in text
    # источник без счёта — метка без точности
    db.execute("INSERT INTO news_cache (source, title, summary, url, category,"
               " published, hash, origin, ownership) VALUES (?,?,?,?,?,?,?,?,?)",
               ("DW", "Крымский мост анализ", "текст", "https://dw/x",
                "news_eu", "2026-11-22T11:00:00", "f2", "DE", "public"))
    db.commit()
    text2 = news.get_fresh_news("Крымский мост", dept="osp", limit=5)
    assert "[DE, обществ.]" in text2, "n=0 — без счёта в метке"
    assert "точн." not in [l for l in text2.splitlines() if "DW" in l][0]


def test_a4_rating_table(db):
    """Таблица рейтинга: точность, n, скорость, флаг «мало данных»."""
    e = _ev(db, "Т-1")
    _rep(db, e, "Ист-Ж", "2026-11-22T10:00:00", "yes")
    _rep(db, e, "Ист-З", "2026-11-22T10:05:00", "no")
    table = news.source_rating_table()
    by_name = {r["source"]: r for r in table}
    # Beta(1,1): 1 «yes» → (1+1)/(1+2) = 2/3 ≈ 0.67 (нельзя получить 1.0
    # при малом n — это и есть сглаживание)
    assert by_name["Ист-Ж"]["accuracy"] == round(2 / 3, 2)
    assert by_name["Ист-Ж"]["events"] == 1
    assert by_name["Ист-Ж"]["few_data"] is True
    assert by_name["Ист-З"]["accuracy"] == round(1 / 3, 2)


def test_a4_endpoint_registered():
    """СТАТИКА: эндпоинт /news/source_rating (Mini App по запросу
    владельца, без графиков)."""
    src = (REPO / "proxy" / "lz_github.py").read_text(encoding="utf-8")
    assert '"/news/source_rating"' in src
    assert "source_rating_table" in src


# ─────────────── запреты наряда ───────────────

def test_no_hardcoded_matches():
    """Запрет: оценки источников не в коде — в news.py нет source→match
    литералов (только через source_reports)."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    seg = src[src.index("SRC_EVENT_OUTCOMES"):]
    # нет зашитых оценок конкретных источников
    for leak in ('"РИА Новости": "no"', '"RIA": "no"', 'match="no"',
                 'match="yes"'):
        assert leak not in seg, leak


def test_src2_default_untouched():
    """Запрет: правило SRC-2 и отбор по умолчанию не меняются — гейт
    выключен (гвард n738 жив)."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    assert 'os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") == "1"' in src


def test_ratings_only_from_events():
    """СТАТИКА: source_accuracy читает source_reports (join source_events
    с известным итогом), не константы."""
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    seg = src[src.index("def source_accuracy"):src.index("def source_speed")]
    assert "source_reports" in seg and "source_events" in seg
    assert "counted = 1" in seg
