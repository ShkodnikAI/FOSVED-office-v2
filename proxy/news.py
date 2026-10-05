"""FO-008: транспорт ч.2 — коллекторы новостей (RSS, GDELT, Tavily, fulltext).

Вырезано из llm_proxy.py вербатим (стренглер, шаг 4b; наряд #68, стоп-гейт SG-F2).
"""
import os
import re
import json
import time
import hashlib
import doc_extract
from datetime import datetime, timedelta, timezone

import feedparser

from flask import request, jsonify

from proxy.core import (
    app, log, http_requests,
    _query, _log_audit, _log_error,
    DEPT_NAMES,
)

# ══════════════════════════════════════════════════════════════════════
#  NEWS MONITORING: RSS + GDELT + Telegram channels
# ══════════════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "ria": {"url": "https://ria.ru/export/rss2/archive/index.xml", "category": "news_ru", "language": "ru", "name": "РИА Новости"},
    "tass": {"url": "https://tass.ru/rss/v2.xml", "category": "news_ru", "language": "ru", "name": "ТАСС"},
    "rbk": {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "category": "news_ru", "language": "ru", "name": "РБК"},
    "interfax": {"url": "https://www.interfax.ru/rss.asp", "category": "news_ru", "language": "ru", "name": "Интерфакс"},
    "kommersant": {"url": "https://www.kommersant.ru/RSS/news.xml", "category": "news_ru", "language": "ru", "name": "Коммерсантъ"},
    # NB: Reuters закрыл публичные RSS-ленты (подозрение AGENTS §7 подтверждено
    # живой проверкой нарядом #424, 2026-09-29: feeds.reuters.com не отвечает,
    # ConnectionError) — заменена на The Guardian World. Живая проверка всех
    # лент и замены — в отчёте наряда #424; arXiv-ленты живы (1446/621 записей,
    # ложная тревога чекера с brotli — feedparser видит обе).
    "guardian_world": {"url": "https://www.theguardian.com/world/rss", "category": "news_en", "language": "en", "name": "The Guardian World"},
    "bbc": {"url": "http://feeds.bbci.co.uk/news/world/rss.xml", "category": "news_en", "language": "en", "name": "BBC World"},
    "aljazeera": {"url": "https://www.aljazeera.com/xml/rss/all.xml", "category": "news_en", "language": "en", "name": "Al Jazeera"},
    "techcrunch": {"url": "https://techcrunch.com/feed/", "category": "tech", "language": "en", "name": "TechCrunch"},
    "theverge": {"url": "https://www.theverge.com/rss/index.xml", "category": "tech", "language": "en", "name": "The Verge"},
    "hackernews": {"url": "https://hnrss.org/frontpage", "category": "tech", "language": "en", "name": "Hacker News"},
    "arxiv_ai": {"url": "https://rss.arxiv.org/rss/cs.AI", "category": "science", "language": "en", "name": "arXiv AI"},
    "arxiv_cl": {"url": "https://rss.arxiv.org/rss/cs.CL", "category": "science", "language": "en", "name": "arXiv NLP"},
    "investing_ru": {"url": "https://ru.investing.com/rss/news.rss", "category": "finance", "language": "ru", "name": "Investing.com RU"},
    "foreignaffairs": {"url": "https://www.foreignaffairs.com/rss.xml", "category": "geopolitics", "language": "en", "name": "Foreign Affairs"},
    # Наряд #424 A.2: белорусские источники (news_by), проверены вживую
    # 2026-09-29 — все отдают 200 и свежие записи (метод и таблица — в отчёте
    # наряда). Баланс: государственные (БелТА, Sputnik, Минск-Новости) и
    # независимые (Zerkalo, Onliner). Отклонённые кандидаты: sb.by (403
    # антибот), charter97.org (403), belsat.eu (connection reset), euroradio
    # (404), naviny.by (timeout), tvr.by (timeout) — в отчёте наряда.
    "belta": {"url": "https://www.belta.by/rss", "category": "news_by", "language": "ru", "name": "БелТА"},
    "sputnik_by": {"url": "https://sputnik.by/export/rss2/archive/index.xml", "category": "news_by", "language": "ru", "name": "Sputnik Беларусь"},
    "minsknews": {"url": "https://minsknews.by/feed/", "category": "news_by", "language": "ru", "name": "Минск-Новости"},
    "zerkalo": {"url": "https://news.zerkalo.io/rss/all.rss", "category": "news_by", "language": "ru", "name": "Зеркало"},
    "onliner": {"url": "https://people.onliner.by/feed", "category": "news_by", "language": "ru", "name": "Onlíner"},
}

GDELT_BASE = "https://api.gdeltproject.org/api/v2"

DEPT_QUERIES = {
    "osp": "geopolitics OR sanctions OR regulation OR war OR election",
    "lz": "artificial intelligence OR quantum computing OR disruption OR breakthrough",
    "finance": "economy OR inflation OR GDP OR stock market OR cryptocurrency",
    "legal": "legislation OR court OR GDPR OR compliance OR lawsuit",
    "marketing": "consumer trends OR advertising OR social media OR brand",
    "engineering": "infrastructure OR energy OR construction OR nuclear OR solar",
}

DEPT_CATEGORIES = {
    # news_by добавлена нарядом #424: белорусская повестка — событийное ядро
    # ОСП (smoke-кейс 2: /news/fresh по Беларуси должен возвращать news_by).
    "osp": ("news_ru", "geopolitics", "news_en", "news_by"),
    "lz": ("tech", "science"),
    "finance": ("finance",),
    "legal": ("geopolitics", "news_ru"),
    "marketing": ("tech", "news_en"),
}


# ── Tavily collection (merged into cron_collect_news, no extra cron slot needed) ──
def collect_tavily():
    """Collect real-time web results via Tavily API. Uses same DEPT_QUERIES as GDELT."""
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        return 0
    # #474: физическая уборка протухшего ответного кэша живого поиска
    # (таблицу создаёт mlog-шов TavilySearch в dept/utils.mlog; DELETE из
    # mlog — irreversible-sink с одноразовым грантом, поэтому уборка здесь,
    # в trusted-слое сборщика). Таблицы может ещё не быть — молча пропускаем.
    try:
        _query("DELETE FROM tavily_cache WHERE created_at < datetime('now', '-1 day')")
    except Exception as e:
        log.debug(f"[tavily] cache cleanup skipped: {e}")
    collected = 0
    for dept, query in DEPT_QUERIES.items():
        try:
            resp = http_requests.post("https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query,
                      "search_depth": "basic", "max_results": 5,
                      "days": 1}, timeout=15)
            if resp.status_code != 200:
                continue
            for r in resp.json().get("results", []):
                title = r.get("title", "").strip()
                url = r.get("url", "").strip()
                summary = re.sub(r"<[^>]+>", "", r.get("content", ""))[:500]
                if not title:
                    continue
                content_hash = hashlib.md5((title + url).encode()).hexdigest()
                cat = DEPT_CATEGORIES.get(dept, ("tech",))[0]
                try:
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (f"Tavily", title, summary, url, cat, "en", None, content_hash))
                    collected += 1
                except Exception as e:
                    _log_error(f"tavily news insert failed: {e}", source="collector", dept="news", kind="data_loss")
        except Exception as e:
            _log_audit("tavily_error", {"dept": dept, "error": str(e)[:100]}, "collector")
    if collected:
        _log_audit("tavily_collected", {"collected": collected}, "collector")
    return collected


def enrich_news_with_fulltext(limit=5):
    """Extract full text from top news URLs missing body content.
    Merges into existing collect cycle — no extra cron needed."""
    rows = _query("""SELECT id, url FROM news_cache
                      WHERE (summary IS NULL OR length(summary) < 100)
                      AND url IS NOT NULL AND url != ''
                      AND collected > datetime('now', '-6 hours')
                      ORDER BY published DESC LIMIT ?""", (limit,), fetch=True)
    enriched = 0
    for row_id, url in (rows or []):
        try:
            resp = http_requests.get(url, timeout=10, headers={"User-Agent": "FosvedBot/1.0"})
            if resp.status_code == 200 and len(resp.text) > 200:
                tmp = f"/tmp/news_enrich_{row_id}.html"
                with open(tmp, "w", encoding="utf-8", errors="replace") as f:
                    f.write(resp.text)
                text = doc_extract.extract_text(tmp, url)
                try: os.remove(tmp)
                except Exception as e: log.warning(f"[cleanup] news tmp remove failed: {e}")
                if text and len(text) > 50:
                    summary = text[:800]
                    _query("UPDATE news_cache SET summary = ? WHERE id = ?", (summary, row_id))
                    enriched += 1
        except Exception as e:
            _log_error(f"news enrich failed: {e}", source="collector", dept="news", kind="external")
    if enriched:
        _log_audit("news_enriched", {"enriched": enriched}, "collector")
    return enriched


def _rss_state_table():
    """FORGE-UI-10 (#203): состояние RSS-источников (ленивая схема).
    rss_sources — общий список: сееденные из RSS_FEEDS (custom=0) и
    добавленные владельцем (custom=1). deleted=1 скрывает сеединую ленту
    (иначе она вернётся при следующем сеединге из кода)."""
    from proxy.core import _query
    _query("""CREATE TABLE IF NOT EXISTS rss_sources (
            feed TEXT PRIMARY KEY, url TEXT, name TEXT, tag TEXT,
            enabled INTEGER DEFAULT 1, custom INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0)""")
    for feed_id, fc in RSS_FEEDS.items():
        _query("INSERT OR IGNORE INTO rss_sources (feed, url, name, tag, enabled, custom, deleted) "
               "VALUES (?, ?, ?, ?, 1, 0, 0)",
               (feed_id, fc["url"], fc["name"], fc["category"]))


def rss_enabled_feeds():
    """FORGE-UI-10 (#203): активные ленты для collect_rss — код + таблица
    состояния. Выключенные (enabled=0) и удалённые (deleted=1) пропускаются."""
    from proxy.core import _query
    _rss_state_table()
    out = {}
    rows = _query("SELECT feed, url, name, tag FROM rss_sources "
                  "WHERE enabled=1 AND deleted=0 ORDER BY feed", fetch=True) or []
    for r in rows:
        out[r["feed"]] = {"url": r["url"], "name": r["name"], "category": r["tag"]}
    return out


def rss_validate_url(url):
    """FORGE-UI-10 (#203): проверка, что URL — реально рабочая RSS/Atom-лента
    (попытка распарсить до сохранения). Возвращает (ok, title)."""
    import feedparser as _fp
    try:
        d = _fp.parse(str(url))
        if d.bozo and not d.entries:
            return False, ""
        title = (d.feed.get("title") or "").strip()
        if not d.entries and not title:
            return False, ""
        return True, title or "RSS-лента"
    except Exception:
        return False, ""


def collect_rss():
    """Collect from all RSS feeds. Dedup by hash(title+url). TTL 7 days."""
    import feedparser as _fp
    collected, errors = 0, 0
    for feed_id, fc in rss_enabled_feeds().items():
        try:
            feed = _fp.parse(fc["url"])
            for entry in feed.entries[:20]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", ""))).strip()
                url = entry.get("link", "").strip()
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if not title:
                    continue
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                content_hash = hashlib.md5((title + url).encode()).hexdigest()
                pub_date = None
                if published:
                    try:
                        pub_date = datetime(*published[:6]).isoformat()
                    except Exception as e:
                        log.warning(f"[collector] bad published date {published}: {e}")
                try:
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (fc["name"], title, summary, url, fc["category"], fc["language"], pub_date, content_hash))
                    collected += 1
                except Exception as e2:
                    _log_error(f"feedparser news insert failed: {e2}", source="collector", dept="news", kind="data_loss")
        except Exception as e:
            errors += 1
            _log_audit("rss_error", {"feed": feed_id, "error": str(e)[:100]}, "collector")
    _query("DELETE FROM news_cache WHERE collected < datetime('now', '-7 days')")
    _log_audit("rss_collected", {"collected": collected, "errors": errors}, "collector")
    return collected


def collect_gdelt(query=None, language="russian", max_items=25):
    """GDELT DOC API — free, no key."""
    params = {
        "query": query or "Russia OR technology OR AI",
        "mode": "artlist",
        "maxrecords": str(max_items),
        "format": "json",
        "sort": "DateDesc",
        "sourcelang": language,
    }
    try:
        resp = http_requests.get(f"{GDELT_BASE}/doc/doc", params=params, timeout=15)
        if resp.status_code != 200:
            return 0
        data = resp.json()
        articles = data.get("articles", [])
        collected = 0
        for a in articles:
            title = a.get("title", "").strip()
            url = a.get("url", "").strip()
            source = a.get("domain", a.get("sourcecountry", "GDELT"))
            seendate = a.get("seendate", "")
            tone = a.get("tone", 0)
            if not title:
                continue
            content_hash = hashlib.md5((title + url).encode()).hexdigest()
            cat = "geopolitics"
            tl = title.lower()
            if any(w in tl for w in ["technology", "ai", "artificial", "технолог", "искусствен"]):
                cat = "tech"
            elif any(w in tl for w in ["economy", "экономик", "market", "рынок", "billion", "млрд"]):
                cat = "finance"
            elif any(w in tl for w in ["science", "наук", "research", "исследован"]):
                cat = "science"
            try:
                _query("""INSERT OR IGNORE INTO news_cache
                    (source,title,summary,url,category,language,published,relevance_score,hash)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (f"GDELT/{source}", title, f"Tone: {float(tone):.1f}", url, cat,
                     language[:2], seendate, abs(float(tone)), content_hash))
                collected += 1
            except Exception as e:
                _log_error(f"gdelt news insert failed: {e}", source="collector", dept="news", kind="data_loss")
        _log_audit("gdelt_collected", {"collected": collected}, "collector")
        return collected
    except Exception as e:
        _log_audit("gdelt_error", {"error": str(e)[:200]}, "collector")
        return 0


def collect_gdelt_themes():
    total = 0
    for dept, query in DEPT_QUERIES.items():
        total += collect_gdelt(query=query, language="russian", max_items=10)
        total += collect_gdelt(query=query, language="english", max_items=10)
    return total


def _extract_keywords(text):
    stop = {"и", "в", "на", "с", "по", "для", "от", "что", "как", "не", "это", "the", "a", "an", "in", "on", "for", "of", "and", "to", "is", "it"}
    words = re.findall(r"[а-яёa-z]{3,}", text.lower())
    return [w for w in words if w not in stop][:10]


def get_fresh_news(query, dept=None, limit=5, max_chars=1500):
    """Get recent news relevant to query. Used by BuildContext in mlog."""
    keywords = _extract_keywords(query)
    conditions, params = [], []
    for kw in keywords[:5]:
        conditions.append("(title LIKE ? OR summary LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    where = " OR ".join(conditions) if conditions else "1=1"

    cats = DEPT_CATEGORIES.get(dept, ("news_ru", "tech", "geopolitics"))
    cat_filter = " OR ".join(["category = ?" for _ in cats])
    params.extend(cats)

    sql = f"""SELECT source, title, summary, url, published, relevance_score
             FROM news_cache WHERE ({where}) AND ({cat_filter})
             AND collected > datetime('now', '-48 hours')
             ORDER BY published DESC LIMIT ?"""
    params.append(limit)
    rows = _query(sql, params, fetch=True)

    if not rows:
        sql2 = f"""SELECT source, title, summary, url, published, relevance_score
                  FROM news_cache WHERE ({cat_filter})
                  AND collected > datetime('now', '-24 hours')
                  ORDER BY published DESC LIMIT ?"""
        rows = _query(sql2, list(cats) + [limit], fetch=True)

    if not rows:
        return ""

    news_text = "=== СВЕЖИЕ СОБЫТИЯ (последние 48ч) ===\n\n"
    current_len = 0
    for r in rows:
        entry = f"[{r[0]}] {r[1]}\n"
        if r[3]:
            entry += f"  Ссылка: {r[3]}\n"
        if r[2] and r[2] != r[1]:
            entry += f"  {r[2][:150]}\n"
        if r[4]:
            entry += f"  Дата: {r[4]}\n"
        entry += "\n"
        if current_len + len(entry) > max_chars:
            break
        news_text += entry
        current_len += len(entry)

    news_text += "=== КОНЕЦ СОБЫТИЙ ===\n"
    return news_text


def get_night_news_digest():
    """Top-5 events over last 12 hours for morning brief."""
    rows = _query("""SELECT source, title, category FROM news_cache
                     WHERE collected > datetime('now', '-12 hours')
                     ORDER BY relevance_score DESC, published DESC LIMIT 5""", fetch=True)
    if not rows:
        return ""
    emoji = {"tech": "🔬", "finance": "💰", "geopolitics": "🌍", "science": "🧪", "news_ru": "📌", "news_en": "📌"}
    digest = "\n📰 Топ события за ночь:\n"
    for r in rows:
        digest += f"  {emoji.get(r[2], '📄')} [{r[0]}] {r[1][:80]}\n"
    return digest
