#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#741 MON-5: Telegram-мониторинг без аккаунта (публичные t.me/s).

A.0 (живой замер, песочница 22.11): exilenova_plus/supernova_plus/
osint_dnipro/CRIMEA_WIND — HTTP 200, посты в HTML (фикстуры сохранены);
302 = канал есть, публичная лента недоступна (блок IP/пустой канал).
Прод Render — по логу сборщика после деплоя (в отчёте PR).
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

FIXT = REPO / "tests" / "fixtures"
os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")
os.environ.setdefault("CRON_SECRET", "cron-test-secret")

from proxy import tg_public  # noqa: E402


def _db(tmp_path):
    """Тестовая БД: таблицы наряда (lz_channel_posts/channels/health)."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE lz_channel_posts (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " channel_id TEXT NOT NULL, message_id TEXT NOT NULL, channel_name TEXT,"
        " text TEXT, media_type TEXT, date TEXT,"
        " scanned_at TEXT DEFAULT (datetime('now')), UNIQUE(channel_id, message_id));"
        "CREATE TABLE lz_telegram_channels (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " channel_id TEXT, channel_name TEXT, category TEXT,"
        " source TEXT, origin TEXT, ownership TEXT, conflict_party TEXT,"
        " added_at TEXT DEFAULT (datetime('now')));"
        "CREATE TABLE tg_channel_health (channel_id TEXT PRIMARY KEY,"
        " fail_count INTEGER DEFAULT 0, last_status TEXT, last_ok_ts TEXT,"
        " switched_to_supply INTEGER DEFAULT 0, last_error TEXT);")
    conn.commit()
    return db, conn


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    db, conn = _db(tmp_path)
    # редирект _query на тестовую БД
    import proxy.core as core
    monkeypatch.setattr(core, "DB_FILE", str(db))

    def fake_query(sql, params=(), fetch=False):
        # ВСЕ запросы исполняются (включая DDL ensure_schema);
        # возврат строк — для SELECT (fetch=True или SELECT-префикс)
        cur = conn.execute(sql, params)
        if fetch or sql.strip().upper().startswith("SELECT"):
            rows = [dict(r) for r in cur.fetchall()]

            class _R:
                def __init__(self, rows, cur):
                    self.rows = rows
                    self._cur = cur
                def __iter__(self):
                    return iter(self.rows)
                def __getitem__(self, i):
                    return self.rows[i]
                @property
                def rowcount(self):
                    return self._cur.rowcount
            return _R(rows, cur)

        class _W:
            def __init__(self, cur):
                self.rowcount = cur.rowcount
        return _W(cur)
    monkeypatch.setattr(tg_public, "_query", fake_query)
    # ensure_schema исполняется честно через fake_query (DDL + ALTER
    # с duplicate column — глушим только их ошибки, как в проде)
    yield conn
    conn.close()


# ─────────────── A.1: разбор фикстур ───────────────

def test_a1_parse_exilenova_fixture():
    """Фикстура exilenova (живой HTML 22.11): посты с id/временем/текстом."""
    html = (FIXT / "tg_public_exilenova.html").read_text(encoding="utf-8")
    posts = tg_public.parse_tg_s_page(html, "exilenova_plus")
    assert len(posts) == 10, len(posts)
    p0 = posts[0]
    assert p0["message_id"].isdigit()
    assert p0["channel"] == "exilenova_plus"
    assert p0["posted_at"].startswith("2026-11-")
    assert p0["text"], "текст пуст"
    assert p0["url"] == f"https://t.me/exilenova_plus/{p0['message_id']}"
    assert p0["media_type"] in ("none", "photo", "video", "other")


def test_a1_parse_all_fixtures():
    """Все 4 канала: посты распознаны, время ISO, url-формат единый."""
    for f, ch in [("tg_public_exilenova", "exilenova_plus"),
                  ("tg_public_supernova", "supernova_plus"),
                  ("tg_public_crimea", "CRIMEA_WIND"),
                  ("tg_public_dnipro", "osint_dnipro")]:
        html = (FIXT / f"{f}.html").read_text(encoding="utf-8")
        posts = tg_public.parse_tg_s_page(html, ch)
        assert posts, f"{ch}: пусто"
        assert all("T" in p["posted_at"] for p in posts), ch


def test_a1_store_posts_dedup(db_env):
    """Дедуп: повторная запись тех же постов — 0 новых (UNIQUE)."""
    posts = [{"channel": "x", "message_id": "1", "posted_at": "2026-11-22T00:00:00+00:00",
              "text": "a", "media_type": "none", "url": "https://t.me/x/1"},
             {"channel": "x", "message_id": "2", "posted_at": "2026-11-22T01:00:00+00:00",
              "text": "b", "media_type": "photo", "url": "https://t.me/x/2"}]
    n1 = tg_public.store_posts("x", posts)
    n2 = tg_public.store_posts("x", posts)
    assert (n1, n2) == (2, 0)
    rows = db_env.execute("SELECT COUNT(*) AS c FROM lz_channel_posts").fetchone()
    assert rows["c"] == 2


def test_a1_channel_fail_switch_to_supply(db_env):
    """3 провала подряд → switched_to_supply=1 (+ постановка fetch_channel
    при живой очереди — здесь проверяем флаг; постановка — в B-тестах)."""
    for i in range(3):
        tg_public.channel_fail("blocked_ch", "403")
    row = db_env.execute(
        "SELECT fail_count, switched_to_supply FROM tg_channel_health "
        "WHERE channel_id='blocked_ch'").fetchone()
    assert row["fail_count"] == 3
    assert row["switched_to_supply"] == 1


def test_a1_channel_ok_resets_fail_count(db_env):
    """Успех сбрасывает счётчик провалов."""
    tg_public.channel_fail("ch", "429")
    tg_public.channel_fail("ch", "429")
    tg_public.channel_ok("ch")
    row = db_env.execute(
        "SELECT fail_count FROM tg_channel_health WHERE channel_id='ch'").fetchone()
    assert row["fail_count"] == 0


def test_a1_fetch_retry_only_on_50x():
    """СТАТИКА: ретрай только 502/503/504 (не на 403/429)."""
    assert tg_public.TG_PUBLIC_RETRY_CODES == {502, 503, 504}
    src = (REPO / "proxy" / "tg_public.py").read_text(encoding="utf-8")
    assert "attempt == 1" in src  # ровно один повтор


def test_a1_thread_in_llm_proxy_not_process():
    """СТАТИКА: поток в llm_proxy (не процесс), старт при буте + засев."""
    src = (REPO / "llm_proxy.py").read_text(encoding="utf-8")
    assert "start_tg_public_thread()" in src
    assert "seed_osint_ua_channels()" in src
    tp = (REPO / "proxy" / "tg_public.py").read_text(encoding="utf-8")
    assert "threading.Thread" in tp and "multiprocessing" not in tp


def test_a1_mutation_parse_breaks_tests():
    """МУТАЦИЯ-ДЕТЕКТОР: регэксп _RE_POST обязан ловить data-post="user/123"
    и группу id — иначе фикстурные тесты выше красные (возврат к сломанному
    разбору заметен здесь, без прогена мутационного скрипта)."""
    # регэксп РЕАЛЬНО ловит живую разметку (фикстуры выше — полный тест);
    # здесь — прямая проверка формата data-post="user/123" и группы id
    m = tg_public._RE_POST.search(
        '<div class="tgme_widget_message_wrap" data-post="user/123"')
    assert m, "регэксп не ловит живой формат data-post"
    assert m.group(1) == "user" and m.group(2) == "123", (
        "группы username/id не ловятся — ссылки t.me/<u>/<id> сломаются")


# ─────────────── A.2: засев + команда ───────────────

def test_a2_seed_idempotent(db_env):
    """Засев 4 каналов osint_ua с метками #737; повтор — 0 новых."""
    n1 = tg_public.seed_osint_ua_channels()
    n2 = tg_public.seed_osint_ua_channels()
    assert n1 == 4
    assert n2 == 0
    rows = db_env.execute(
        "SELECT channel_id, category, source, origin, ownership, conflict_party "
        "FROM lz_telegram_channels").fetchall()
    byid = {r["channel_id"]: r for r in rows}
    assert set(byid) == {"exilenova_plus", "supernova_plus",
                         "osint_dnipro", "CRIMEA_WIND"}
    assert all(r["category"] == "osint_ua" for r in rows)
    assert all(r["source"] == "public" for r in rows)
    assert all(r["origin"] == "UA" and r["ownership"] == "independent"
               and r["conflict_party"] == "UA" for r in rows)


def test_a2_channel_add_command_wired():
    """СТАТИКА: команда /lz channel add в app.mlog → LZPublicChannelAdd
    (живая проверка A.0 на лету + osint_ua + метки)."""
    src = (REPO / "app.mlog").read_text(encoding="utf-8")
    assert 'starts_with(text, "/lz channel add ")' in src
    lz = (REPO / "dept" / "lz.mlog").read_text(encoding="utf-8")
    assert "pattern LZPublicChannelAdd" in lz
    assert 'check_channel_live' in lz
    assert "'osint_ua', 'public'" in lz


# ─────────────── A.3: factpack + «Данные на:» ───────────────

def test_a3_factpack_block_by_stems(db_env):
    """3 поста по теме + 2 нет → блок несёт 3 с метками/ссылками; время МСК."""
    db_env.executemany(
        "INSERT INTO lz_channel_posts (channel_id, message_id, text, date) "
        "VALUES (?,?,?,?)",
        [("exilenova_plus", "1", "Удар по НПЗ в Краснодарском крае", "2026-11-22T05:00:00+00:00"),
         ("supernova_plus", "2", "Обстановка: удары по НПЗ продолжаются", "2026-11-22T06:00:00+00:00"),
         ("exilenova_plus", "3", "НПЗ снова в огне", "2026-11-22T07:00:00+00:00"),
         ("supernova_plus", "9", "Рынок акций вырос", "2026-11-22T08:00:00+00:00"),
         ("other_ch", "8", "Погода в Лиссабоне", "2026-11-22T08:30:00+00:00")])
    db_env.commit()
    block = tg_public.factpack_block("что с НПЗ сегодня", 48, 10)
    assert "Telegram-мониторинг (3 постов" in block
    assert "НПЗ" in block
    assert "Лиссабон" not in block and "акций" not in block
    assert "https://t.me/exilenova_plus/1" in block
    assert "Минск" in block


def test_a3_factpack_block_empty_vs_broken(db_env):
    """Различие: сбор не работал («не работает с») vs посты есть, но не по
    теме («подходящих постов нет») — наряд: пустая выборка при неработающем
    сборе — строка «не работает с <время>»."""
    broken = tg_public.factpack_block("тема", 48, 10)
    assert "не работает" in broken
    db_env.execute(
        "INSERT INTO lz_channel_posts (channel_id, message_id, text, date) "
        "VALUES ('c','1','совсем другое','2026-11-22T08:00:00+00:00')")
    db_env.commit()
    off_topic = tg_public.factpack_block("тема", 48, 10)
    assert "подходящих постов нет" in off_topic


def test_a3_freshness_includes_tg_post():
    """«Данные на:» (#740): самый свежий TG-пост участвует — свежее новости
    → берётся пост. Поведенчески: сравнение дат в коде берёт MAX(date)
    TG-постов и обновляет topic_latest, если он свежее."""
    import re
    src = (REPO / "proxy" / "news.py").read_text(encoding="utf-8")
    assert "lz_channel_posts" in src, "osp_freshness не смотрит TG-посты"
    # формула сравнения: пост свежее новости → latest = пост
    m = re.search(r"if tg_latest and \(latest is None or str\(tg_latest\) > str\(latest\)\):\s*\n\s*latest = tg_latest", src)
    assert m, "сравнение tg_latest/latest исчезло — TG-пост не попадает в «Данные на:»"


def test_a3_lz_factpack_wires_tg_block():
    """СТАТИКА: LZFactpack включает factpack_block (блок [TG]); ОСП
    получает factpack через TeamConsult (уже в контексте)."""
    lz = (REPO / "dept" / "lz.mlog").read_text(encoding="utf-8")
    m = lz[lz.index("pattern LZFactpack"):lz.index("pattern LZMonitor")]
    assert "factpack_block" in m
    osp = (REPO / "dept" / "osp.mlog").read_text(encoding="utf-8")
    assert "TeamConsult(\"osp\", \"lz\", \"factpack\"" in osp


# ─────────────── B: fetch_channel в очереди ───────────────

def test_b_enqueue_and_dequeue(db_env, monkeypatch):
    """Задание fetch_channel выдаётся /supply/next с type и url; лимит
    «1 на канал за интервал» — второй enqueue → None."""
    import proxy.shop_supply as ss
    conn = db_env
    import proxy.core as core

    class _W:
        def __init__(self, cur):
            self.rowcount = cur.rowcount
    def fake_q(sql, params=(), fetch=False):
        cur = conn.execute(sql, params)
        if fetch or sql.strip().upper().startswith("SELECT"):
            return [dict(r) for r in cur.fetchall()]
        return _W(cur)
    # shop_supply импортирует _query ЛОКАЛЬНО (from proxy.core import) —
    # патчим сам proxy.core._query на время теста
    monkeypatch.setattr(core, "_query", fake_q)
    conn.execute("CREATE TABLE IF NOT EXISTS shop_supply_queue("
                 "task_id TEXT PRIMARY KEY, product_id INTEGER, platform TEXT,"
                 " type TEXT, query TEXT, url TEXT, status TEXT, created_at TEXT,"
                 " dispatched_at TEXT, timeout_s INTEGER, result_json TEXT,"
                 " error TEXT, kind TEXT, wave_id TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS shop_supply_waves("
                 "wave_id TEXT PRIMARY KEY, product_id INTEGER,"
                 " notified INTEGER DEFAULT 0, created_at TEXT)")
    conn.commit()
    monkeypatch.setattr(ss, "ensure_schema", lambda: None)
    monkeypatch.setattr(ss, "expire_stale_tasks", lambda: None)

    tid = ss.enqueue_fetch_channel("telegram", "https://t.me/s/blocked_ch",
                                   channel_id="blocked_ch")
    assert tid
    dup = ss.enqueue_fetch_channel("telegram", "https://t.me/s/blocked_ch",
                                   channel_id="blocked_ch")
    assert dup is None, "второе задание за интервал не должно вставать"
    row = conn.execute("SELECT type, platform, url, status FROM shop_supply_queue "
                       "WHERE task_id=?", (tid,)).fetchone()
    assert (row["type"], row["platform"], row["status"]) == \
        ("fetch_channel", "telegram", "pending")

    task = ss.dequeue_next_task()
    assert task["type"] == "fetch_channel"
    assert task["url"] == "https://t.me/s/blocked_ch"
    assert task["platform"] == "telegram"


def test_b_apply_result_posts(db_env, monkeypatch):
    """/supply/result с posts[]: 2 поста → 2 строки; повтор — не дубль;
    пост без message_id → result_format (наряд B.2)."""
    import proxy.shop_supply as ss
    import proxy.core as core
    conn = db_env
    class _W:
        def __init__(self, cur):
            self.rowcount = cur.rowcount
    monkeypatch.setattr(core, "_query", lambda sql, params=(), fetch=False: (
        [dict(r) for r in conn.execute(sql, params).fetchall()]
        if fetch or sql.strip().upper().startswith("SELECT") else _W(conn.execute(sql, params))))
    monkeypatch.setattr(ss, "ensure_schema", lambda: None)
    monkeypatch.setattr(ss, "expire_stale_tasks", lambda: None)
    conn.execute("CREATE TABLE IF NOT EXISTS shop_supply_queue("
                 "task_id TEXT PRIMARY KEY, product_id INTEGER, platform TEXT,"
                 " type TEXT, query TEXT, url TEXT, status TEXT, created_at TEXT,"
                 " dispatched_at TEXT, timeout_s INTEGER, result_json TEXT,"
                 " error TEXT, kind TEXT, wave_id TEXT)")
    conn.commit()
    conn.execute("INSERT INTO shop_supply_queue (task_id, product_id, platform,"
                 " type, query, url, status, created_at, timeout_s)"
                 " VALUES ('t1', NULL, 'telegram', 'fetch_channel', '',"
                 " 'https://t.me/s/x', 'dispatched', datetime('now'), 900)")
    conn.commit()

    payload = {"task_id": "t1", "ok": True, "platform": "telegram",
               "url": "https://t.me/s/x",
               "posts": [
                   {"channel": "x", "message_id": "10",
                    "posted_at": "2026-11-22T05:00:00+00:00", "text": "a",
                    "media_type": "photo", "url": "https://t.me/x/10"},
                   {"channel": "x", "message_id": "11",
                    "posted_at": "2026-11-22T06:00:00+00:00", "text": "b",
                    "media_type": "none", "url": "https://t.me/x/11"}]}
    res = ss.apply_supply_result("t1", payload)
    assert res["applied"] and res["ok"] and res["posts_saved"] == 2
    n = conn.execute("SELECT COUNT(*) AS c FROM lz_channel_posts "
                     "WHERE channel_id='x'").fetchone()["c"]
    assert n == 2
    # повтор — задание закрыто
    res2 = ss.apply_supply_result("t1", payload)
    assert not res2["applied"]

    # пост без message_id → result_format
    conn.execute("INSERT INTO shop_supply_queue (task_id, product_id, platform,"
                 " type, query, url, status, created_at, timeout_s)"
                 " VALUES ('t2', NULL, 'telegram', 'fetch_channel', '',"
                 " 'u', 'dispatched', datetime('now'), 900)")
    bad = {"task_id": "t2", "ok": True, "platform": "telegram", "url": "u",
           "posts": [{"channel": "x", "posted_at": "t", "text": "y",
                      "media_type": "none", "url": "u2"}]}
    res3 = ss.apply_supply_result("t2", bad)
    assert res3["applied"] and not res3["ok"] and res3["kind"] == "result_format"


def test_b_ok_true_empty_posts_is_fine(db_env, monkeypatch):
    """ok:true с posts: [] — «смотрели, новых нет» (не ошибка формата)."""
    import proxy.shop_supply as ss
    import proxy.core as core
    conn = db_env
    class _W:
        def __init__(self, cur):
            self.rowcount = cur.rowcount
    monkeypatch.setattr(core, "_query", lambda sql, params=(), fetch=False: (
        [dict(r) for r in conn.execute(sql, params).fetchall()]
        if fetch or sql.strip().upper().startswith("SELECT") else _W(conn.execute(sql, params))))
    monkeypatch.setattr(ss, "ensure_schema", lambda: None)
    monkeypatch.setattr(ss, "expire_stale_tasks", lambda: None)
    conn.execute("CREATE TABLE IF NOT EXISTS shop_supply_queue("
                 "task_id TEXT PRIMARY KEY, product_id INTEGER, platform TEXT,"
                 " type TEXT, query TEXT, url TEXT, status TEXT, created_at TEXT,"
                 " dispatched_at TEXT, timeout_s INTEGER, result_json TEXT,"
                 " error TEXT, kind TEXT, wave_id TEXT)")
    conn.execute("INSERT INTO shop_supply_queue (task_id, product_id, platform,"
                 " type, query, url, status, created_at, timeout_s)"
                 " VALUES ('t3', NULL, 'telegram', 'fetch_channel', '',"
                 " 'u3', 'dispatched', datetime('now'), 900)")
    conn.commit()
    res = ss.apply_supply_result("t3", {"task_id": "t3", "ok": True,
                                        "platform": "telegram", "url": "u3",
                                        "posts": []})
    assert res["applied"] and res["ok"] and res["posts_saved"] == 0


# ─────────────── C: строка брифа ───────────────

def test_c_monitor_line_ok(db_env):
    """Нормальная: «📡 … N каналов, M постов за сутки (с прода K, через
    снабженца L)»."""
    db_env.execute("INSERT INTO lz_telegram_channels (channel_id, category, source)"
                   " VALUES ('exilenova_plus', 'osint_ua', 'public')")
    db_env.execute("INSERT INTO lz_channel_posts (channel_id, message_id, text, date)"
                   " VALUES ('exilenova_plus','1','a','2026-11-22T08:00:00+00:00')")
    db_env.execute("INSERT INTO tg_channel_health (channel_id, fail_count,"
                   " last_status, last_ok_ts, switched_to_supply)"
                   " VALUES ('exilenova_plus', 0, '200', datetime('now'), 0)")
    db_env.commit()
    line = tg_public.tg_monitor_line()
    assert line.startswith("📡 Telegram-мониторинг: 1 канал")
    assert "постов за сутки" in line and "с прода 1" in line


def test_c_monitor_line_not_working(db_env):
    """Каналы есть, успешных сборов нет → «⚠️ … НЕ РАБОТАЕТ …» (в раздел
    внимания)."""
    db_env.execute("INSERT INTO lz_telegram_channels (channel_id, category, source)"
                   " VALUES ('exilenova_plus', 'osint_ua', 'public')")
    db_env.commit()
    line = tg_public.tg_monitor_line()
    assert "НЕ РАБОТАЕТ" in line and line.startswith("⚠️")


def test_c_brief_wires_line():
    """СТАТИКА: оба вызова collect_attention_items + тело брифа несут
    строку 📡; ⚠️-ветка — в раздел внимания."""
    src = (REPO / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
    assert src.count("tg_line=tg_monitor_line_safe(),") == 2
    assert "_tl.startswith" in src, "⚠️-ветка Telegram-мониторинга не в разделе внимания"
    assert "_tgl = tg_monitor_line_safe()" in src
