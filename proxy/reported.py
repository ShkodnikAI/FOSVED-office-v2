#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #597 A.1: реестр сообщённого владельцу (reported_items).

Каждая находка/событие попадает к владельцу ОДИН раз: повторно — только
«существенное изменение» (звёзды +30% и ≥+500) с пометкой «обновление».
Запись в реестр — только после УСПЕШНОЙ отправки владельцу; сбой отправки
= «не сообщено». DDL идемпотентный, таблица — рядом с существующими
(news_cache, lz_github_updates не трогаются).

Каналы: 'lz_daily' (полный отчёт ЛЗ 09:10), 'brief_events' (события брифа).
Ключи:
- репозиторий: repo:<owner/name> — нижний регистр;
- релиз: release:<owner/name>@<tag>;
- новость: news:<news_cache.hash>, без хэша — news:u:<нормализованный URL
  без query и fragment>.
"""
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from proxy.core import _query

DDL = """CREATE TABLE IF NOT EXISTS reported_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  item_key TEXT NOT NULL,
  first_reported_at TEXT DEFAULT (datetime('now')),
  last_reported_at TEXT DEFAULT (datetime('now')),
  times INTEGER NOT NULL DEFAULT 1,
  last_value TEXT,
  UNIQUE(channel, item_key)
)"""


def init_reported_items():
    """Идемпотентное создание таблицы (вызывается из init_db)."""
    _query(DDL)
    _query("CREATE INDEX IF NOT EXISTS idx_reported_channel ON reported_items (channel, last_reported_at)")


# ── Нормализация ключей ─────────────────────────────────────────────────────

def norm_repo_key(full_name: str) -> str:
    """repo:<owner/name> — нижний регистр, без пробелов по краям."""
    return "repo:" + (full_name or "").strip().lower()


def norm_release_key(full_name: str, tag: str) -> str:
    """release:<owner/name>@<tag> — нижний регистр репозитория, тег как есть."""
    return f"release:{(full_name or '').strip().lower()}@{tag or ''}"


def norm_news_key(hash_: str = "", url: str = "") -> str:
    """news:<hash> или news:u:<URL без query/fragment>.

    Нормализация URL: схема+host+path, нижний регистр scheme/host, path без
    хвостового слэша-дубля; query и fragment отбрасываются (utm-мусор не
    создаёт ложной «новизны»)."""
    if hash_:
        return f"news:{hash_}"
    parts = urlsplit(url or "")
    if not parts.netloc:
        return "news:u:" + (url or "").strip().lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    host = parts.netloc.lower()
    scheme = (parts.scheme or "https").lower()
    return f"news:u:{urlunsplit((scheme, host, path, '', ''))}"


# ── Чтение/запись реестра ───────────────────────────────────────────────────

def is_reported(channel: str, key: str, within_days: int = None) -> bool:
    """Сообщён ли элемент. within_days — окно от last_reported_at."""
    if within_days is None:
        row = _query("SELECT 1 FROM reported_items WHERE channel = ? AND item_key = ? LIMIT 1",
                     (channel, key), fetch=True)
        return bool(row)
    cutoff = (datetime.utcnow() - timedelta(days=within_days)).strftime("%Y-%m-%d %H:%M:%S")
    row = _query(
        "SELECT 1 FROM reported_items WHERE channel = ? AND item_key = ? AND last_reported_at > ? LIMIT 1",
        (channel, key, cutoff), fetch=True)
    return bool(row)


def get_last_value(channel: str, key: str):
    """last_value (JSON) последнего сообщения или None."""
    row = _query("SELECT last_value FROM reported_items WHERE channel = ? AND item_key = ? LIMIT 1",
                 (channel, key), fetch=True)
    if not row:
        return None
    try:
        return json.loads(row[0]["last_value"] or "null")
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def mark_reported(channel: str, key: str, last_value=None):
    """Записать «сообщено». Существующий ключ: times+1, обновить last_*.
    ВЫЗЫВАТЬ ТОЛЬКО после успешной отправки владельцу (#597 A.1)."""
    lv = json.dumps(last_value, ensure_ascii=False) if last_value is not None else None
    _query(
        """INSERT INTO reported_items (channel, item_key, times, last_value)
           VALUES (?, ?, 1, ?)
           ON CONFLICT(channel, item_key) DO UPDATE SET
             times = times + 1,
             last_reported_at = datetime('now'),
             last_value = COALESCE(?, last_value)""",
        (channel, key, lv, lv))


def mark_many(channel: str, keys, last_values=None):
    """Пометить пачку ключей (одна отправка = одна пачка)."""
    for k in keys:
        lv = None
        if last_values and k in last_values:
            lv = last_values[k]
        try:
            mark_reported(channel, k, lv)
        except Exception as e:  # noqa: BLE001 — сбой реестра не роняет отчёт
            from proxy.core import _log_error
            _log_error(f"reported_items mark failed {channel}/{k}: {e}",
                       source="reported_items", kind="registry")


# ── Отбор нового (#597 A.2) ────────────────────────────────────────────────

STARS_GROWTH_MIN = 0.30   # ≥30%
STARS_ABS_MIN = 500       # и не меньше чем +500


def stars_update_label(old_stars, new_stars) -> str:
    """Пометка «существенного изменения» для промпта."""
    return f"[ОБНОВЛЕНИЕ: было {old_stars}★, стало {new_stars}★]"


def is_significant_stars_growth(old_stars, new_stars) -> bool:
    """≥30% И не меньше чем +500 с прошлого сообщения (#597 A.2)."""
    try:
        old_stars = float(old_stars or 0)
        new_stars = float(new_stars or 0)
    except (TypeError, ValueError):
        return False
    if new_stars <= old_stars:
        return False
    grew = new_stars - old_stars
    return grew >= STARS_ABS_MIN and (grew / old_stars) >= STARS_GROWTH_MIN if old_stars > 0 else grew >= STARS_ABS_MIN


def filter_lz_items(channel: str, items):
    """Отбор элементов до модели. items: [{key, stars?, ...}].

    Возвращает (new_items, updates):
    - new_items — нет в реестре;
    - updates — есть в реестре, но звёзды выросли значимо; к item
      добавляется update_label.
    Прочее (уже сообщено без существенного роста) — отбрасывается."""
    new_items, updates = [], []
    for it in items:
        key = it.get("key")
        if not key:
            continue
        prev = get_last_value(channel, key)
        if prev is None and not is_reported(channel, key):
            new_items.append(it)
            continue
        old_stars = (prev or {}).get("stars")
        new_stars = it.get("stars")
        if new_stars is not None and is_significant_stars_growth(old_stars, new_stars):
            u = dict(it)
            u["update_label"] = stars_update_label(old_stars, new_stars)
            updates.append(u)
    return new_items, updates


# ── Страховка после модели (#597 A.3) ──────────────────────────────────────

_URL_RE = re.compile(r"https?://[^\s)\"'>\]]+", re.IGNORECASE)
_GH_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)
_GH_RELEASE_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases/tag/([^/\s)\"'>\]]+)", re.IGNORECASE)


def key_for_url(url: str) -> str:
    """Разрешить URL в ключ реестра (repo/release/news)."""
    m = _GH_RELEASE_RE.search(url or "")
    if m:
        return norm_release_key(f"{m.group(1)}/{m.group(2)}", m.group(3))
    m = _GH_REPO_RE.search(url or "")
    if m:
        return norm_repo_key(f"{m.group(1)}/{m.group(2)}")
    return norm_news_key(url=url)


def filter_stale_blocks(analysis: str, channel: str, within_days: int = 14):
    """Страховка после модели: абзац, где ЕДИНСТВЕННАЯ (вся) ссылка ведёт
    на элемент, уже сообщённый за 14 дней (и абзац не помечен как
    обновление), удаляется. Возвращает (текст, число удалённых)."""
    if not analysis:
        return analysis, 0
    blocks = analysis.split("\n\n")
    kept, dropped = [], 0
    for block in blocks:
        if "[ОБНОВЛЕНИЕ" in block:
            kept.append(block)
            continue
        urls = _URL_RE.findall(block)
        if urls and all(is_reported(channel, key_for_url(u), within_days=within_days) for u in urls):
            dropped += 1
            continue
        kept.append(block)
    return "\n\n".join(kept), dropped
