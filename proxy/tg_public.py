#!/usr/bin/env python3
"""proxy/tg_public.py — #741 MON-5 A.1: Telegram-мониторинг без аккаунта.

Решение владельца 20.11: публичные каналы читаются с открытых страниц
`t.me/s/<username>` — без Telethon-аккаунта (MON-1 остаётся выключенным,
наряд запрещает его включать/удалять). Каналы категории `osint_ua`
(osint-каналы войны, которым владелец доверяет) + любые с source='public'.

Живой замер A.0 (22.11, песочница): t.me/s/<username> отдаёт 200 с HTML
постов (`tgme_widget_message`, `data-post`, `<time datetime>`) для
существующих активных каналов; 302 → редирект на t.me/<username> — канал
есть, но публичная лента недоступна (пустой канал/блок IP). Прод Render
проверяется логом сборщика после деплоя (см. отчёт наряда).

Механика по наряду:
  • поток В llm_proxy (не отдельный процесс, не Telethon);
  • интервал TG_PUBLIC_INTERVAL_S (10 мин), пауза 3 с между каналами,
    таймаут запроса 10 с, ретрай ТОЛЬКО на 502/503/504 (1 повтор);
  • разбор HTML: id поста, время, текст, тип медиа (не скачиваем);
  • запись lz_channel_posts через INSERT OR IGNORE (дедуп
    UNIQUE(channel_id, message_id) — тот же, что MON-1);
  • отказ канала (403/429/пустой HTML 3 раза подряд) — журнал
    (tg_channel_health), канал переводится на запасной путь (блок B:
    fetch_channel через снабженца — постановка из shop_supply).
"""

import re
import threading
import time
from datetime import datetime, timezone

import requests

from proxy.core import _query

try:
    from flask import current_app  # noqa: F401 — наличность flask не критична
except ImportError:  # прагматика тестов без flask
    current_app = None

log = __import__("logging").getLogger("llm_proxy")

# ── Параметры наряда (константы, не env: план Render не меняем) ──────────
TG_PUBLIC_INTERVAL_S = 600      # раз в 10 минут
TG_PUBLIC_TIMEOUT_S = 10        # таймаут запроса
TG_PUBLIC_PAUSE_S = 3           # пауза между каналами
TG_PUBLIC_RETRY_CODES = {502, 503, 504}   # ретрай только на эти
TG_CHANNEL_FAIL_LIMIT = 3       # 3 провала подряд → запасной путь
TG_PUBLIC_MAX_POSTS = 50        # разбираем последние N постов страницы
TG_PUBLIC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Метки #737-класса для каналов osint_ua (наряд: «метки как в #737»)
OSINT_UA_LABELS = {"origin": "UA", "ownership": "independent",
                   "conflict_party": "UA"}

_thread = None
_thread_lock = threading.Lock()

# ── Разбор HTML (t.me/s/<username>) ─────────────────────────────────────

# блок поста: <div class="tgme_widget_message ..." data-post="user/123" ...>
_RE_POST = re.compile(
    r'<div class="tgme_widget_message[^"]*"[^>]*?data-post="([^"/]+)/(\d+)"',
    re.S)
# время: <time datetime="2026-11-22T07:19:44+00:00">
_RE_TIME = re.compile(r'<time datetime="([^"]+)"')
# медиа: классы виджета внутри поста
_MEDIA_CLASSES = (
    ("photo", "tgme_widget_message_photo"),
    ("video", "tgme_widget_message_video"),
    ("other", "tgme_widget_message_document"),
    ("other", "tgme_widget_message_audio"),
    ("other", "tgme_widget_message_voice"),
    ("other", "tgme_widget_message_sticker"),
    ("other", "tgme_widget_message_roundvideo"),
)
# текст: <div class="tgme_widget_message_text ...">…</div> (до закрывающего
# тега того же уровня; в разметке t.me вложенных div внутри текста нет)
_RE_TEXT = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(fragment: str) -> str:
    """Тег-стриппинг + базовые сущности; текст поста — без разметки."""
    text = _TAG_RE.sub("", fragment or "")
    for ent, ch in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"),
                    ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(ent, ch)
    return text.strip()


def parse_tg_s_page(html: str, channel: str):
    """Разбор HTML t.me/s/<username> → [(message_id, posted_at, text,
    media_type, url), …] (порядок страницы — новые в конце; отдаём как есть).

    Фикстурный контракт (tests/fixtures/tg_public_*.html): data-post
    «user/35008» → message_id «35008»; время — ISO из <time datetime>;
    медиа — по классу виджета; url — t.me/<username>/<id>.
    """
    posts = []
    if not html:
        return posts
    for m in _RE_POST.finditer(html):
        username, mid = m.group(1), m.group(2)
        # ищем контекст поста: от начала блока до следующего блока
        seg_end = _RE_POST.search(html, m.end())
        seg = html[m.start():seg_end.start() if seg_end else len(html)]
        t = _RE_TIME.search(seg)
        posted = t.group(1) if t else ""
        txt_m = _RE_TEXT.search(seg)
        text = _strip_html(txt_m.group(1)) if txt_m else ""
        media = "none"
        for mtype, cls in _MEDIA_CLASSES:
            if cls in seg:
                media = mtype
                break
        posts.append({
            "channel": channel or username,
            "message_id": mid,
            "posted_at": posted,
            "text": text,
            "media_type": media,
            "url": f"https://t.me/{channel or username}/{mid}",
        })
    return posts[:TG_PUBLIC_MAX_POSTS]


# ── Здоровье каналов (журнал провалов, перевод на запасной путь) ────────

def ensure_schema():
    """Журнал здоровья каналов + колонки меток (идемпотентно)."""
    _query(
        "CREATE TABLE IF NOT EXISTS tg_channel_health ("
        "channel_id TEXT PRIMARY KEY, fail_count INTEGER DEFAULT 0, "
        "last_status TEXT, last_ok_ts TEXT, switched_to_supply INTEGER DEFAULT 0, "
        "last_error TEXT)")
    for col, ddl in (
        ("source", "ALTER TABLE lz_telegram_channels ADD COLUMN source TEXT"),
        ("origin", "ALTER TABLE lz_telegram_channels ADD COLUMN origin TEXT"),
        ("ownership", "ALTER TABLE lz_telegram_channels ADD COLUMN ownership TEXT"),
        ("conflict_party", "ALTER TABLE lz_telegram_channels ADD COLUMN conflict_party TEXT"),
    ):
        try:
            _query(ddl)
        except Exception as e:  # noqa: BLE001 — duplicate column = уже есть
            if "duplicate column" not in str(e).lower():
                log.warning("tg_public: миграция %s: %s", col, e)


def channel_fail(channel_id: str, status: str, error: str = ""):
    """Провал канала: счётчик +1; после TG_CHANNEL_FAIL_LIMIT подряд —
    переключение на запасной путь (switched_to_supply=1, блок B смотрит
    на этот флаг при постановке fetch_channel)."""
    ensure_schema()
    _query(
        "INSERT INTO tg_channel_health (channel_id, fail_count, last_status, last_error) "
        "VALUES (?, 1, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET "
        "fail_count = fail_count + 1, last_status=excluded.last_status, "
        "last_error=excluded.last_error",
        (channel_id, status, (error or "")[:200]))
    row = _query("SELECT fail_count, switched_to_supply FROM tg_channel_health "
                 "WHERE channel_id=?", (channel_id,), fetch=True)
    if row and row[0]["fail_count"] >= TG_CHANNEL_FAIL_LIMIT \
            and not row[0]["switched_to_supply"]:
        _query("UPDATE tg_channel_health SET switched_to_supply=1 WHERE channel_id=?",
               (channel_id,))
        log.warning("[tg-public] канал %s: %s провалов подряд — переход на "
                    "запасной путь (снабженец)", channel_id,
                    row[0]["fail_count"])
        # #741 B.1: постановка fetch_channel (лимит «1 на канал за
        # интервал» — внутри enqueue_fetch_channel). Сбой постановки не
        # роняет журнал: задание встанет на следующем провале.
        try:
            from proxy.shop_supply import enqueue_fetch_channel
            enqueue_fetch_channel(
                "telegram", f"https://t.me/s/{channel_id}",
                channel_id=channel_id)
        except Exception as e:  # noqa: BLE001
            log.warning("[tg-public] fetch_channel для %s не встал: %s",
                        channel_id, e)


def channel_ok(channel_id: str, status: str = "200"):
    """Успех канала: сброс счётчика провалов (возврат с запасного пути —
    решением владельца/аудита, не автоматически: switched_to_supply
    держим, пока канал не пройдёт сутки без провалов — упрощаем по
    наряду: сброс только fail_count, флаг снимает человек)."""
    ensure_schema()
    _query(
        "INSERT INTO tg_channel_health (channel_id, fail_count, last_status, last_ok_ts) "
        "VALUES (?, 0, ?, datetime('now')) ON CONFLICT(channel_id) DO UPDATE SET "
        "fail_count = 0, last_status=excluded.last_status, "
        "last_ok_ts=datetime('now')",
        (channel_id, status))


# ── Сбор одного канала ───────────────────────────────────────────────────

def fetch_channel_public(channel: str, session=None):
    """GET t.me/s/<channel> → (posts|None, status|error). None + status —
    провал (403/429/пусто/сетевая ошибка), ретрай только 502/503/504."""
    url = f"https://t.me/s/{channel}"
    sess = session or requests.Session()
    last_code = None
    for attempt in (1, 2):
        try:
            r = sess.get(url, timeout=TG_PUBLIC_TIMEOUT_S,
                         headers={"User-Agent": TG_PUBLIC_UA})
        except requests.RequestException as e:
            return None, f"network: {type(e).__name__}"
        last_code = r.status_code
        if r.status_code == 200:
            posts = parse_tg_s_page(r.text, channel)
            if posts:
                return posts, "200"
            return None, "empty"       # 200 без постов — пустая лента
        if r.status_code in TG_PUBLIC_RETRY_CODES and attempt == 1:
            time.sleep(2)
            continue
        return None, str(r.status_code)
    return None, str(last_code)


def store_posts(channel_id: str, posts, source: str = "public"):
    """Посты → lz_channel_posts (INSERT OR IGNORE; дедуп
    UNIQUE(channel_id, message_id) — тот же, что MON-1/B.2). Возврат —
    число НОВЫХ строк (для брифа и лога)."""
    new = 0
    for p in posts:
        cur = _query(
            "INSERT OR IGNORE INTO lz_channel_posts "
            "(channel_id, message_id, channel_name, text, media_type, date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (channel_id, str(p.get("message_id", "")), p.get("channel", ""),
             p.get("text", ""), p.get("media_type", "none"), p.get("posted_at", "")))
        try:
            new += max(0, cur.rowcount if hasattr(cur, "rowcount") else 0)
        except Exception:  # noqa: BLE001 — rowcount не критичен
            pass
    return new


def poll_once():
    """Один проход по каналам (osint_ua + source='public'). Вызывается
    потоком каждые TG_PUBLIC_INTERVAL_S; в тестах — напрямую."""
    ensure_schema()
    rows = _query(
        "SELECT channel_id, channel_name FROM lz_telegram_channels "
        "WHERE category='osint_ua' OR source='public'", fetch=True) or []
    total_new = 0
    ok_channels = 0
    for row in rows:
        ch = (row["channel_id"] or "").lstrip("@")
        if not ch:
            continue
        posts, status = fetch_channel_public(ch)
        if posts is None:
            channel_fail(ch, status)
        else:
            channel_ok(ch, status)
            total_new += store_posts(ch, posts)
            ok_channels += 1
            # запасной путь больше не нужен, если канал сам вернулся:
            # флаг снимается только владельцем (наряд B: постановка по
            # флагу; здесь лишь не ставим новых заданий)
        time.sleep(TG_PUBLIC_PAUSE_S)
    return {"channels": len(rows), "ok": ok_channels, "new_posts": total_new}


# ── Поток в llm_proxy (не отдельный процесс — наряд A.1) ────────────────

def start_tg_public_thread(interval_s=TG_PUBLIC_INTERVAL_S):
    """Демон-поток опроса. Идемпотентен (повторный вызов — no-op)."""
    global _thread
    with _thread_lock:
        if _thread and _thread.is_alive():
            return _thread

        def _loop():
            while True:
                try:
                    res = poll_once()
                    if res["new_posts"] or res["ok"] < res["channels"]:
                        log.info("[tg-public] каналов=%s ok=%s новых постов=%s",
                                 res["channels"], res["ok"], res["new_posts"])
                except Exception as e:  # noqa: BLE001 — поток не умирает
                    log.warning("[tg-public] проход упал: %s", e)
                time.sleep(interval_s)

        _thread = threading.Thread(target=_loop, name="tg-public", daemon=True)
        _thread.start()
        return _thread


# ── Засев каналов (A.2) ──────────────────────────────────────────────────

# Каналы владельца (решение 20.11), проверены вживую A.0 (см. отчёт):
# username → отображаемое имя (со страницы t.me, <title>)
SEED_OSINT_UA_CHANNELS = [
    ("exilenova_plus", "Exilenova+"),
    ("supernova_plus", "Supernova+"),
    ("osint_dnipro", "Dnipro Osint (Гарбуз)"),
    ("CRIMEA_WIND", "Крымский ветер"),
]


def seed_osint_ua_channels():
    """A.2: идемпотентный засев каналов категории osint_ua с метками
    #737 (origin=UA, ownership=independent, conflict_party=UA) и
    source='public' (сборщик A.1 берёт по этому источнику)."""
    ensure_schema()
    added = 0
    for username, name in SEED_OSINT_UA_CHANNELS:
        cur = _query(
            "INSERT INTO lz_telegram_channels "
            "(channel_id, channel_name, category, source, origin, ownership, conflict_party) "
            "SELECT ?, ?, 'osint_ua', 'public', ?, ?, ? "
            "WHERE NOT EXISTS (SELECT 1 FROM lz_telegram_channels WHERE channel_id=?)",
            (username, name, OSINT_UA_LABELS["origin"],
             OSINT_UA_LABELS["ownership"], OSINT_UA_LABELS["conflict_party"],
             username))
        try:
            added += max(0, cur.rowcount if hasattr(cur, "rowcount") else 0)
        except Exception:  # noqa: BLE001
            pass
    return added


# ── A.2/A.3: вызовы из mlog (call_python) ────────────────────────────────

def check_channel_live(username):
    """A.2: живая проверка t.me/s/<username> (команда /lz channel add).
    Возврат — JSON-строка {'ok': True, 'posts': N} | {'ok': False, 'reason'}."""
    import json as _json
    uname = (username or "").strip().lstrip("@")
    if not uname or "/" in uname or " " in uname:
        return _json.dumps({"ok": False, "reason": "некорректный username"},
                           ensure_ascii=False)
    posts, status = fetch_channel_public(uname)
    if posts is None:
        return _json.dumps({"ok": False, "reason": f"HTTP {status}"},
                           ensure_ascii=False)
    return _json.dumps({"ok": True, "posts": len(posts)}, ensure_ascii=False)


def _extract_stems(text, min_len=3):
    """Основы слов (как #475 get_fresh_news: грубый стемминг без морфологии)."""
    import re as _re
    words = _re.findall(r"[а-яёa-z0-9]{%d,}" % min_len, (text or "").lower())
    return [w[: max(4, len(w) - 2)] if len(w) > 5 else w for w in words]


def factpack_block(question, hours=48, limit=10):
    """A.3: блок «Telegram-мониторинг» для LZFactpack/контекста ОСП —
    посты за N часов по основам слов вопроса, до limit, с каналом,
    временем (Минск) и ссылкой t.me/<username>/<id>. Пустая выборка при
    неработающем сборе — честная строка, не пустота."""
    import json as _json
    try:
        stems = _extract_stems(question)
        rows = _query(
            "SELECT channel_id, channel_name, text, date, message_id "
            "FROM lz_channel_posts "
            "WHERE datetime(date) >= datetime('now', ?) "
            "ORDER BY date DESC LIMIT 200",
            (f"-{int(hours)} hours",), fetch=True) or []
        picked = []
        for r in rows:
            hay = (r["text"] or "").lower()
            if any(st in hay for st in stems):
                picked.append(r)
                if len(picked) >= int(limit):
                    break
        if not picked:
            # честно различаем: сбор не работал / посты есть, но не по теме
            any_posts = _query(
                "SELECT COUNT(*) AS n FROM lz_channel_posts "
                "WHERE datetime(date) >= datetime('now', ?)",
                (f"-{int(hours)} hours",), fetch=True)
            n = any_posts[0]["n"] if any_posts else 0
            if n == 0:
                return (f"Telegram-мониторинг не работает с последнего "
                        f"успешного сбора (постов за {int(hours)} ч нет)")
            return (f"по теме за {int(hours)} ч подходящих постов нет "
                    f"(всего постов {n})")
        lines = []
        for r in picked:
            dt = r["date"] or ""
            # Минск = UTC+3 (бриф/офис работают по Минску)
            try:
                d = datetime.fromisoformat(dt)
                msk = (d if d.tzinfo else d.replace(tzinfo=timezone.utc))                     .astimezone(timezone(offset=__import__("datetime")
                                         .timedelta(hours=3)))
                when = msk.strftime("%d.%m %H:%M Минск")
            except ValueError:
                when = dt[:16]
            lines.append(f"- @{r['channel_id']} ({when}): "
                         f"{(r['text'] or '')[:200]} "
                         f"[{r['channel_name'] or r['channel_id']}] "
                         f"https://t.me/{r['channel_id']}/{r.get('message_id', '')}")
        return "Telegram-мониторинг (" + str(len(picked)) + " постов за " \
               + str(int(hours)) + " ч):\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001 — блок не роняет factpack
        log.warning("[tg-public] factpack_block упал: %s", e)
        return "Telegram-мониторинг: сводка недоступна"


# ── Строка брифа (C) ─────────────────────────────────────────────────────

def tg_monitor_line():
    """C: «📡 Telegram-мониторинг: N каналов, M постов за сутки (с прода K,
    через снабженца L)» или «⚠️ НЕ РАБОТАЕТ с <время>» (в раздел внимания).

    «С прода K» — каналы со свежим last_ok_ts (за 30 мин) и не на
    запасном пути; «через снабженца L» — switched_to_supply=1.
    """
    try:
        ensure_schema()
        ch_rows = _query(
            "SELECT COUNT(*) AS n FROM lz_telegram_channels "
            "WHERE category='osint_ua' OR source='public'", fetch=True)
        n_channels = ch_rows[0]["n"] if ch_rows else 0
        posts = _query(
            "SELECT COUNT(*) AS n FROM lz_channel_posts "
            "WHERE datetime(date) >= datetime('now', '-24 hours')", fetch=True)
        n_posts = posts[0]["n"] if posts else 0
        direct = _query(
            "SELECT COUNT(*) AS n FROM tg_channel_health "
            "WHERE last_ok_ts IS NOT NULL AND switched_to_supply=0 "
            "AND datetime(last_ok_ts) >= datetime('now', '-30 minutes')",
            fetch=True)
        n_direct = direct[0]["n"] if direct else 0
        via_supply = _query(
            "SELECT COUNT(*) AS n FROM tg_channel_health WHERE switched_to_supply=1",
            fetch=True)
        n_supply = via_supply[0]["n"] if via_supply else 0
        # «НЕ РАБОТАЕТ»: есть каналы, но ни один не собирался успешно
        # за последние 30 минут (интервал сбора 10 мин — 3 пропуска)
        if n_channels and n_direct == 0 and n_supply == 0:
            row = _query("SELECT MAX(last_ok_ts) AS t FROM tg_channel_health",
                         fetch=True)
            since = (row[0]["t"] if row and row[0]["t"] else "—")
            return (f"⚠️ Telegram-мониторинг НЕ РАБОТАЕТ (нет успешного сбора "
                    f"после {since}; каналов {n_channels})")
        return (f"📡 Telegram-мониторинг: {n_channels} каналов, {n_posts} постов "
                f"за сутки (с прода {n_direct}, через снабженца {n_supply})")
    except Exception as e:  # noqa: BLE001 — строка брифа не роняет сборку
        log.warning("[tg-public] строка брифа упала: %s", e)
        return ""
