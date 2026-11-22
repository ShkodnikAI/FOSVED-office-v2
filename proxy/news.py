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

# #737 SRC-1 A.1: каждая лента несёт метки источника — origin (ISO страны),
# ownership (state | independent | public — общественное вещание),
# conflict_party (RU | UA | none) — и domains (для сопоставления Tavily-
# результатов, A.4). Обоснования меток — таблица в PR наряда. Словарь origin
# открыт (ISO-коды; EU — наднациональная редакция, LV и др. добавляются).
RSS_FEEDS = {
    "ria": {"url": "https://ria.ru/export/rss2/archive/index.xml", "category": "news_ru", "language": "ru", "name": "РИА Новости", "origin": "RU", "ownership": "state", "conflict_party": "RU", "domains": "ria.ru"},
    "tass": {"url": "https://tass.ru/rss/v2.xml", "category": "news_ru", "language": "ru", "name": "ТАСС", "origin": "RU", "ownership": "state", "conflict_party": "RU", "domains": "tass.ru"},
    "rbk": {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "category": "news_ru", "language": "ru", "name": "РБК", "origin": "RU", "ownership": "independent", "conflict_party": "RU", "domains": "rbc.ru"},
    "interfax": {"url": "https://www.interfax.ru/rss.asp", "category": "news_ru", "language": "ru", "name": "Интерфакс", "origin": "RU", "ownership": "independent", "conflict_party": "RU", "domains": "interfax.ru"},
    "kommersant": {"url": "https://www.kommersant.ru/RSS/news.xml", "category": "news_ru", "language": "ru", "name": "Коммерсантъ", "origin": "RU", "ownership": "independent", "conflict_party": "RU", "domains": "kommersant.ru"},
    # NB: Reuters закрыл публичные RSS-ленты (подозрение AGENTS §7 подтверждено
    # живой проверкой нарядом #424, 2026-09-29: feeds.reuters.com не отвечает,
    # ConnectionError) — заменена на The Guardian World. Живая проверка всех
    # лент и замены — в отчёте наряда #424; arXiv-ленты живы (1446/621 записей,
    # ложная тревога чекера с brotli — feedparser видит обе).
    "guardian_world": {"url": "https://www.theguardian.com/world/rss", "category": "news_en", "language": "en", "name": "The Guardian World", "origin": "GB", "ownership": "independent", "conflict_party": "none", "domains": "theguardian.com,guardian.com"},
    "bbc": {"url": "http://feeds.bbci.co.uk/news/world/rss.xml", "category": "news_en", "language": "en", "name": "BBC World", "origin": "GB", "ownership": "public", "conflict_party": "none", "domains": "bbc.com,bbc.co.uk"},
    "aljazeera": {"url": "https://www.aljazeera.com/xml/rss/all.xml", "category": "news_en", "language": "en", "name": "Al Jazeera", "origin": "QA", "ownership": "public", "conflict_party": "none", "domains": "aljazeera.com"},
    "techcrunch": {"url": "https://techcrunch.com/feed/", "category": "tech", "language": "en", "name": "TechCrunch", "origin": "US", "ownership": "independent", "conflict_party": "none", "domains": "techcrunch.com"},
    "theverge": {"url": "https://www.theverge.com/rss/index.xml", "category": "tech", "language": "en", "name": "The Verge", "origin": "US", "ownership": "independent", "conflict_party": "none", "domains": "theverge.com"},
    "hackernews": {"url": "https://hnrss.org/frontpage", "category": "tech", "language": "en", "name": "Hacker News", "origin": "US", "ownership": "independent", "conflict_party": "none", "domains": "news.ycombinator.com,hnrss.org"},
    "arxiv_ai": {"url": "https://rss.arxiv.org/rss/cs.AI", "category": "science", "language": "en", "name": "arXiv AI", "origin": "US", "ownership": "public", "conflict_party": "none", "domains": "arxiv.org"},
    "arxiv_cl": {"url": "https://rss.arxiv.org/rss/cs.CL", "category": "science", "language": "en", "name": "arXiv NLP", "origin": "US", "ownership": "public", "conflict_party": "none", "domains": "arxiv.org"},
    "investing_ru": {"url": "https://ru.investing.com/rss/news.rss", "category": "finance", "language": "ru", "name": "Investing.com RU", "origin": "IL", "ownership": "independent", "conflict_party": "none", "domains": "investing.com"},
    "foreignaffairs": {"url": "https://www.foreignaffairs.com/rss.xml", "category": "geopolitics", "language": "en", "name": "Foreign Affairs", "origin": "US", "ownership": "independent", "conflict_party": "none", "domains": "foreignaffairs.com"},
    # Наряд #424 A.2: белорусские источники (news_by), проверены вживую
    # 2026-09-29 — все отдают 200 и свежие записи (метод и таблица — в отчёте
    # наряда). Баланс: государственные (БелТА, Sputnik, Минск-Новости) и
    # независимые (Zerkalo, Onliner). Отклонённые кандидаты: sb.by (403
    # антибот), charter97.org (403), belsat.eu (connection reset), euroradio
    # (404), naviny.by (timeout), tvr.by (timeout) — в отчёте наряда.
    "belta": {"url": "https://www.belta.by/rss", "category": "news_by", "language": "ru", "name": "БелТА", "origin": "BY", "ownership": "state", "conflict_party": "none", "domains": "belta.by"},
    "sputnik_by": {"url": "https://sputnik.by/export/rss2/archive/index.xml", "category": "news_by", "language": "ru", "name": "Sputnik Беларусь", "origin": "BY", "ownership": "state", "conflict_party": "RU", "domains": "sputnik.by,riab.ru"},
    "minsknews": {"url": "https://minsknews.by/feed/", "category": "news_by", "language": "ru", "name": "Минск-Новости", "origin": "BY", "ownership": "state", "conflict_party": "none", "domains": "minsknews.by"},
    "zerkalo": {"url": "https://news.zerkalo.io/rss/all.rss", "category": "news_by", "language": "ru", "name": "Зеркало", "origin": "BY", "ownership": "independent", "conflict_party": "none", "domains": "zerkalo.io"},
    "onliner": {"url": "https://people.onliner.by/feed", "category": "news_by", "language": "ru", "name": "Onlíner", "origin": "BY", "ownership": "independent", "conflict_party": "none", "domains": "onliner.by,people.onliner.by"},
    # #737 SRC-1 A.2: украинские и европейские ленты. Живая проверка из CI
    # 2026-11-22 (метод как в #424): ПРОШЛИ — Kyiv Independent (news-archive/
    # rss, 200, свежие), DW en/ru (RDF, 140/75 записей), Politico EU (200,
    # 10), Le Monde in English (200, 14). ОТКЛОНЕНЫ по правилу при
    # затруднении (таблица с кодами — в отчёте наряда): Українська правда
    # (403 антибот), Укрінформ (404 все URL), Суспільне (403), Европейская
    # правда (403), Euronews (406), France 24 (403), RFI (403).
    "kyivindependent": {"url": "https://kyivindependent.com/news-archive/rss/", "category": "news_ua", "language": "en", "name": "The Kyiv Independent", "origin": "UA", "ownership": "independent", "conflict_party": "UA", "domains": "kyivindependent.com"},
    "dw_en": {"url": "https://rss.dw.com/rdf/rss-en-all", "category": "news_eu", "language": "en", "name": "Deutsche Welle (en)", "origin": "DE", "ownership": "public", "conflict_party": "none", "domains": "dw.com"},
    "dw_ru": {"url": "https://rss.dw.com/rdf/rss-ru-all", "category": "news_eu", "language": "ru", "name": "Deutsche Welle (ru)", "origin": "DE", "ownership": "public", "conflict_party": "none", "domains": "dw.com"},
    "politico_eu": {"url": "https://www.politico.eu/feed/", "category": "news_eu", "language": "en", "name": "Politico Europe", "origin": "EU", "ownership": "independent", "conflict_party": "none", "domains": "politico.eu"},
    "lemonde_en": {"url": "https://www.lemonde.fr/en/rss/une.xml", "category": "news_eu", "language": "en", "name": "Le Monde in English", "origin": "FR", "ownership": "independent", "conflict_party": "none", "domains": "lemonde.fr"},
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
    # #737 A.2: ОСП и legal получают news_ua/news_eu (решение владельца:
    # украинские и европейские ленты в событийном ядре)
    "osp": ("news_ru", "geopolitics", "news_en", "news_by", "news_ua", "news_eu"),
    "lz": ("tech", "science"),
    "finance": ("finance",),
    "legal": ("geopolitics", "news_ru", "news_ua", "news_eu"),
    "marketing": ("tech", "news_en"),
}


# ── Tavily collection (merged into cron_collect_news, no extra cron slot needed) ──
def _tavily_source_labels(url):
    """#737 A.4: домен результата Tavily → метки реестра. Совпадение с
    domains ленты — её метки; нет совпадения — пусто («не в реестре»)."""
    try:
        host = re.sub(r"^https?://", "", (url or "")).split("/")[0].lower()
        host = host.removeprefix("www.")
    except Exception:
        return "", ""
    for fc in RSS_FEEDS.values():
        for d in (fc.get("domains") or "").split(","):
            d = d.strip().lower().removeprefix("www.")
            if d and (host == d or host.endswith("." + d)):
                return fc.get("origin", ""), fc.get("ownership", "")
    return "", ""


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
                    # #737 A.4: домен результата → метки реестра (нет — пусто)
                    _t_origin, _t_ownership = _tavily_source_labels(url)
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash,origin,ownership,conflict_party)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (f"Tavily", title, summary, url, cat, "en", None, content_hash,
                         _t_origin, _t_ownership, ""))
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
    состояния. Выключенные (enabled=0) и удалённые (deleted=1) пропускаются.
    #550 A.4: ленты из БД (rss_sources) не имеют колонки language — отдаём
    language: "" явно, чтобы collect_rss не падал KeyError'ом и не терял
    все записи такой ленты (факт 5 наряда: 'news insert failed: language').
    """
    from proxy.core import _query
    _rss_state_table()
    out = {}
    rows = _query("SELECT feed, url, name, tag FROM rss_sources "
                  "WHERE enabled=1 AND deleted=0 ORDER BY feed", fetch=True) or []
    for r in rows:
        fc = {"url": r["url"], "name": r["name"], "category": r["tag"], "language": ""}
        # #737 A.1: метки источника (origin/ownership/conflict_party/domains)
        # — из код-реестра, если лента в нём; БД-таблица хранит только
        # url/name/tag — метки не теряются при слиянии
        reg = RSS_FEEDS.get(r["feed"])
        if reg:
            for k in ("origin", "ownership", "conflict_party", "domains", "language"):
                if reg.get(k):
                    fc[k] = reg[k]
        out[r["feed"]] = fc
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
                    # #550 A.4: .get вместо [..] — ленты без language/category/name
                    # (в т.ч. все ленты из БД) не должны ронять вставку записей:
                    # KeyError 'language' терял ВСЕ записи ленты (data_loss).
                    # #737 A.1: метки источника — из реестра ленты
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash,origin,ownership,conflict_party)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (fc.get("name", feed_id), title, summary, url, fc.get("category", ""), fc.get("language", ""), pub_date, content_hash,
                         fc.get("origin", ""), fc.get("ownership", ""), fc.get("conflict_party", "")))
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


# #475 A.2: нормализованные основы слов. SQLite LIKE регистрозависим для
# кириллицы и lower() там ASCII-only ('Иркутске' LIKE '%иркутске%' = 0),
# словоформы не матчатся ('чумы' ≠ 'чума') — вопрос про чуму в Иркутске
# не находил в кэше записи о чуме (инцидент OSP-2026-10-05-PLAGUE-01).
# Поэтому ключи запроса сравниваются с текстом документов в Python,
# по основам, а не LIKE-ом по точной словоформе.
_RU_STRIP = "аеёиоуыэюяьйъ"


def _stem(word):
    """Лёгкий стем для поиска по кэшу: нижний регистр + срез хвостовых
    гласных/ь/й при длине > 3 (чума/чумы/чумой → чум; иркутске → иркутск;
    эпидемии → эпидем; вероятность/вероятности → вероятност). Для
    английского дополнительно срезается хвостовая 's' (news → new).
    Сознательно грубый: цель — вспомогательный поиск по кэшу, не лингвистика."""
    w = (word or "").lower().strip()
    while len(w) > 3 and w[-1] in _RU_STRIP:
        w = w[:-1]
    if len(w) > 3 and w.endswith("s"):
        w = w[:-1]
    return w


def _doc_stems(text):
    """Множество основ всех слов документа (title + summary)."""
    return {_stem(m) for m in re.findall(r"[а-яёa-z]{3,}", (text or "").lower())}


# #738 SRC-2 A.1: европейские origin, чьё подтверждение пропускает
# российскую запись в контекст (наряд: «news_eu и GB»)
EU_CONFIRMING_ORIGINS = {"DE", "FR", "EU", "GB"}


def _ru_confirmation_gate(rows, stems, pool=None):
    """#738 SRC-2 A.1: запись origin=RU проходит в контекст, только если
    среди собранных за окно (pool — полный релевантный набор, не только
    срез picked) есть запись с европейским origin, содержащая те же ≥2
    основы ключевых слов (#475) — то же событие подтверждено.
    Не прошедшие исключаются (счётчик — в строку контекста).
    Возврат (прошедшие, исключено_N).
    ЗАМЕР B.1 (22.11, 50 живых RU-записей): precision 0.37 / recall 0.70 —
    ПОРОГ 0.8 НЕ ПРОЙДЕН; гейт выключен по умолчанию (см. PR наряда)."""
    if not stems:
        return rows, 0
    pool = pool if pool is not None else rows

    def _origin_of(r):
        try:
            return ((r["origin"] if len(r) > 6 else "") or "")
        except Exception:  # noqa: BLE001 — записи-моки без колонок
            return ""

    eu_docs = [_doc_stems(f"{r[1] or ''} {r[2] or ''}")
               for r in pool if _origin_of(r) in EU_CONFIRMING_ORIGINS]
    kept, excluded = [], 0
    for r in rows:
        if _origin_of(r) == "RU":
            ru_doc = _doc_stems(f"{r[1] or ''} {r[2] or ''}")
            confirmed = any(
                len({st for st in stems if st in ru_doc and st in eu_doc}) >= 2
                for eu_doc in eu_docs)
            if not confirmed:
                excluded += 1
                continue
        kept.append(r)
    return kept, excluded


def _conflict_marks(r):
    """#738 SRC-2 A.2: пометки записи — сторона конфликта (RU/UA) и
    гос. источник. Возвращает строку-суффикс или ""."""
    parts = []
    try:
        cp = (r[8] or "").strip() if len(r) > 8 else ""
        ow = (r[7] or "").strip() if len(r) > 7 else ""
        if cp in ("RU", "UA"):
            parts.append(f"⚠️ сторона конфликта: {cp}")
        if ow == "state":
            parts.append("гос. источник")
    except Exception:  # noqa: BLE001 — пометка не роняет выдачу
        return ""
    return ("  (" + "; ".join(parts) + ")") if parts else ""


def tavily_ru_gate(query, response_json):
    """#738 SRC-2 A.1 для TavilySearch-ветки LZFactpack (mlog-шов через
    call_python): результаты с RU-доменами (метки по _tavily_source_labels)
    проходят, только если среди прочих результатов есть европейский с ≥2
    общими основами запроса. Возврат — JSON {"results": [...],
    "excluded": N}; не-JSON/пусто — вход как есть (деградация честная)."""
    # #738 SRC-2: замер B.1 — порог 0.8 не пройден (см. PR), гейт выключен
    # по умолчанию; включение — решение владельца после исправления
    # сопоставления (NEWS_RU_CONFIRMATION_GATE=1)
    if os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") != "1":
        return response_json
    try:
        d = json.loads(response_json or "")
        results = d.get("results") if isinstance(d, dict) else None
        if not isinstance(results, list) or not results:
            return response_json
        stems = {_stem(k) for k in _extract_keywords(query) if len(k) >= 3}
        if not stems:
            return response_json
        def _doc(r):
            return _doc_stems(f"{r.get('title', '')} {r.get('content', '')}")
        def _origin(r):
            o, _ = _tavily_source_labels(r.get("url", ""))
            return o
        eu_docs = [_doc(r) for r in results if _origin(r) in EU_CONFIRMING_ORIGINS]
        kept, excluded = [], 0
        for r in results:
            if _origin(r) == "RU":
                ru_doc = _doc(r)
                confirmed = any(
                    len({st for st in stems if st in ru_doc and st in ed}) >= 2
                    for ed in eu_docs)
                if not confirmed:
                    excluded += 1
                    continue
            kept.append(r)
        return json.dumps({"results": kept, "excluded": excluded},
                          ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 — гейт не роняет фактпак
        log.warning("[news] tavily_ru_gate: %s", e)
        return response_json


# #737 SRC-1 A.3: ни один источник не занимает больше NEWS_MAX_PER_SOURCE
# мест в отборе для отделов (частые ленты вытесняли редкие: окно 500
# забивалось РИА/ТАСС)
NEWS_MAX_PER_SOURCE = 2
# #737 A.3: окно выборки — до 60 свежих записей на каждую ленту (не 500
# общих), чтобы ленты с высокой частотой публикаций не вытесняли редкие
NEWS_WINDOW_PER_FEED = 60


def get_fresh_news(query, dept=None, limit=5, max_chars=1500):
    """Get recent news relevant to query. Used by BuildContext in mlog.

    #475 A.2: релевантность — по нормализованным основам слов (Python,
    регистронезависимо для кириллицы, устойчиво к словоформам), не по
    точному LIKE. Документ релевантен, если в нём есть хотя бы одна основа
    запроса; сортировка — по числу совпавших основ, затем по дате.
    Фолбэк прежний: если по основам ничего — общие свежие записи по
    категориям департамента (за 24 ч).
    #737 A.3: окно — до 60 свежих на ленту (ROW_NUMBER по source), после
    оценки — не больше NEWS_MAX_PER_SOURCE записей от одного source.
    #737 A.4: каждая строка выдачи — префикс [<origin>, <ownership>]
    (записи без меток — [?, ?])."""
    keywords = _extract_keywords(query)
    stems = {_stem(k) for k in keywords if len(k) >= 3}

    cats = DEPT_CATEGORIES.get(dept, ("news_ru", "tech", "geopolitics"))
    cat_filter = " OR ".join(["category = ?" for _ in cats])

    # #737 A.3: до NEWS_WINDOW_PER_FEED свежих записей НА КАЖДУЮ ленту;
    # #738 SRC-2: conflict_party в выборке (пометки сторон)
    rows = _query(f"""SELECT source, title, summary, url, published, relevance_score,
                             origin, ownership, conflict_party
                      FROM (
                          SELECT news_cache.*,
                                 ROW_NUMBER() OVER (PARTITION BY source
                                                    ORDER BY published DESC) AS rn
                          FROM news_cache WHERE ({cat_filter})
                          AND collected > datetime('now', '-48 hours')
                      )
                      WHERE rn <= ?
                      ORDER BY published DESC""", list(cats) + [NEWS_WINDOW_PER_FEED], fetch=True) or []

    scored = []
    for r in rows:
        doc = _doc_stems(f"{r[1] or ''} {r[2] or ''}")
        score = 0
        for st in stems:
            if st in doc or (len(st) >= 5 and any(d.startswith(st) for d in doc)):
                score += 1
        if score > 0:
            scored.append((score, r))
    ru_excluded = 0
    if scored:
        scored.sort(key=lambda t: (t[0], t[1][4] or ""), reverse=True)
        picked = []
        per_source = {}
        for score, r in scored:
            # #737 A.3: не больше NEWS_MAX_PER_SOURCE записей от источника
            if per_source.get(r[0], 0) >= NEWS_MAX_PER_SOURCE:
                continue
            per_source[r[0]] = per_source.get(r[0], 0) + 1
            picked.append(r)
            if len(picked) >= limit:
                break
        # #738 SRC-2 A.1: RU-запись — только при EU-подтверждении события.
        # ЗАМЕР B.1 (22.11, 50 живых RU-записей, разметка исполнителя):
        # precision 0.37 / recall 0.70 — ПОРОГ 0.8 НЕ ПРОЙДЕН (пересечение
        # основ RU/EN текстов ловит общие топонимы=FP и не ловит реальные
        # совпадения=FN). По правилу при затруднении: порог НЕ снижаем,
        # гейт ВЫКЛЮЧЕН по умолчанию до исправления сопоставления
        # (мультиязычные эмбеддинги/перевод) — замер в PR наряду.
        if os.environ.get("NEWS_RU_CONFIRMATION_GATE", "0") == "1":
            picked, ru_excluded = _ru_confirmation_gate(
                picked, stems, pool=[r for _, r in scored])
        rows = picked
    else:
        sql2 = f"""SELECT source, title, summary, url, published, relevance_score,
                          origin, ownership, conflict_party
                  FROM (
                      SELECT news_cache.*,
                             ROW_NUMBER() OVER (PARTITION BY source
                                                ORDER BY published DESC) AS rn
                      FROM news_cache WHERE ({cat_filter})
                      AND collected > datetime('now', '-24 hours')
                  )
                  WHERE rn <= ?
                  ORDER BY published DESC LIMIT ?"""
        rows = _query(sql2, list(cats) + [NEWS_WINDOW_PER_FEED, limit], fetch=True)
        # #738 SRC-2: в фолбэке гейт не применяется (основы запроса не
        # совпали — «то же событие» не определено), пометки сторон — да

    if not rows:
        # #738 SRC-2: все записи исключены гейтом — счётчик обязан быть
        # виден (наряд: «это видно в ответе»), а не тихая пустота
        if ru_excluded:
            return ("=== СВЕЖИЕ СОБЫТИЯ (последние 48ч) ===\n\n"
                    f"Исключено {ru_excluded} сообщений российских СМИ "
                    "без подтверждения европейскими источниками\n"
                    "=== КОНЕЦ СОБЫТИЙ ===\n")
        return ""

    news_text = "=== СВЕЖИЕ СОБЫТИЯ (последние 48ч) ===\n\n"
    current_len = 0
    for r in rows:
        # #737 A.4: метка источника в каждой строке — [origin, ownership];
        # имя источника сохранено (SRC-2 будет сопоставлять по нему).
        # len-гвард: мок-тесты #475 дают 6-колоночные кортежи.
        _origin = (r[6] or "").strip() if len(r) > 6 else ""
        _ownership = (r[7] or "").strip() if len(r) > 7 else ""
        tag = f"{_origin or '?'}, {_ownership or '?'}"
        entry = f"[{tag}] {r[0]}: {r[1]}\n"
        # #738 SRC-2 A.2: пометка стороны конфликта / гос. источника
        _mk = _conflict_marks(r)
        if _mk:
            entry += _mk + "\n"
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

    # #738 SRC-2 A.1: счётчик исключённых без EU-подтверждения — в конце
    # блока контекста (наряд: «это видно в ответе»)
    if ru_excluded:
        news_text += (f"Исключено {ru_excluded} сообщений российских СМИ "
                      f"без подтверждения европейскими источниками\n")
    news_text += "=== КОНЕЦ СОБЫТИЙ ===\n"
    return news_text


def get_night_news_items():
    """№597 A.2: Топ события за ночь — только НЕ сообщённые владельцу.

    Возвращает (text, items): text — дайджест новых новостей (или строка
    «За ночь новых событий нет», если сбор есть, но всё уже сообщено; или
    "" — сбор не вернул ничего); items — [{key, title}] для пометки в
    реестре reported_items(channel='brief_events') ПОСЛЕ успешной отправки.
    Сбор (news_cache, окна, лимиты) не меняется — фильтруется только выдача.
    """
    rows = _query("""SELECT source, title, category, url, hash FROM news_cache
                     WHERE collected > datetime('now', '-12 hours')
                     ORDER BY relevance_score DESC, published DESC LIMIT 20""", fetch=True)
    if not rows:
        return "", []
    try:
        from proxy import reported as rpt
        fresh = []
        for r in rows:
            try:
                key = rpt.norm_news_key(r["hash"], r["url"])
                if rpt.is_reported("brief_events", key):
                    continue
            except Exception:  # noqa: BLE001 — сбой реестра не роняет бриф
                pass
            fresh.append((r, key))
    except Exception:  # noqa: BLE001 — реестр недоступен → прежнее поведение
        fresh = [(r, None) for r in rows]
    if not fresh:
        return "\n📰 За ночь новых событий нет.\n", []
    emoji = {"tech": "🔬", "finance": "💰", "geopolitics": "🌍", "science": "🧪", "news_ru": "📌", "news_en": "📌"}
    # прежний формат выдачи (топ-5), но из неотмеченных
    digest = "\n📰 Топ события за ночь:\n"
    items = []
    for r, key in fresh[:5]:
        digest += f"  {emoji.get(r[2], '📄')} [{r[0]}] {r[1][:80]}\n"
        # #689 B.1: source — для раздела мировых событий брифа (программа
        # печатает «📌 <title> (<source>)»); key может быть None при сбое
        # реестра — пометка в брифе фильтрует, показ новости не теряется
        items.append({"key": key, "title": r[1], "source": r[0]})
    return digest, items


def get_night_news_digest():
    """Top-5 events over last 12 hours for morning brief (#597: только новые)."""
    text, _items = get_night_news_items()
    return text


# ── #740 OSP-FRESH: свежесть данных перед прогнозом/ответом ──────────────

def osp_freshness(query, dept=None):
    """#740 A.1/A.2: возраст данных по теме + время последнего сбора.

    Возврат — dict для /news/freshness (mlog-потребители: BuildOSPContext,
    HandleYana, HandleLz):
      topic_latest      — published (fallback collected) самой свежей записи
                          по теме; матчачится по основам, как get_fresh_news
                          (те же основы слов — наряд), все категории
                          департамента, БЕЗ окна 48 ч: возраст меряем честно,
                          «старое» ≠ «нет данных»;
      topic_age_hours   — возраст записи в часах (None — записей по теме нет);
      last_collect      — MAX(collected) по всей news_cache (последний
                          успешный сбор любого коллектора);
      collect_age_hours — возраст сбора в часах (None — кэш пуст).

    Инцидент-кейс (владелец, 17.11): прогноз OSP-2026-11-17-CRIMEAN-BRIDGE-02
    построен 05:47 по данным до 16.11 — модель не видела ночную атаку 01:35;
    слот сбора (раз в 6 ч) при цикле server_failed не работал.
    """
    keywords = _extract_keywords(query)
    stems = {_stem(k) for k in keywords if len(k) >= 3}
    cats = DEPT_CATEGORIES.get(dept, ("news_ru", "tech", "geopolitics"))
    cat_filter = " OR ".join(["category = ?"] * len(cats))

    latest = None
    if stems:
        rows = _query(f"""SELECT title, summary, published, collected FROM news_cache
                          WHERE ({cat_filter})
                          ORDER BY COALESCE(published, collected) DESC LIMIT 500""",
                      list(cats), fetch=True) or []
        for r in rows:
            doc = _doc_stems(f"{r[0] or ''} {r[1] or ''}")
            if any(st in doc or (len(st) >= 5 and any(d.startswith(st) for d in doc))
                   for st in stems):
                latest = r[2] or r[3]
                break
    col = _query("SELECT MAX(collected) AS m, COUNT(*) AS n FROM news_cache",
                 (), fetch=True)
    last_collect = col[0][0] if col else None
    # #741 MON-5 A.3: самый свежий пост Telegram-мониторинга учитывается
    # в «Данные на:» — osint_ua-каналы сообщают первыми (решение владельца
    # 20.11); если пост свежее новости — шапка честно показывает его
    try:
        tg = _query("SELECT MAX(date) AS m FROM lz_channel_posts",
                    (), fetch=True)
        tg_latest = tg[0][0] if tg else None
    except Exception:  # noqa: BLE001 — таблицы нет (до бута) — не мешаем
        tg_latest = None
    if tg_latest and (latest is None or str(tg_latest) > str(latest)):
        latest = tg_latest
    return {
        "topic_latest": latest,
        "topic_age_hours": _age_hours(latest),
        "last_collect": last_collect,
        "collect_age_hours": _age_hours(last_collect),
        "tg_latest": tg_latest,
        "searched": False,
    }


def _age_hours(ts):
    """Возраст SQLite-таймстемпа UTC 'YYYY-MM-DD HH:MM:SS' в часах; None —
    пусто/нераспознано (тихо: вызывающий трактует как «нет данных»)."""
    if not ts:
        return None
    from datetime import datetime, timezone
    try:
        t = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t).total_seconds() / 3600.0, 1)
    except ValueError:
        return None


def topic_matches_news(query, row_title_summary):
    """#740 A.3: запись news_cache релевантна теме (те же основы)."""
    keywords = _extract_keywords(query)
    stems = {_stem(k) for k in keywords if len(k) >= 3}
    if not stems:
        return False
    doc = _doc_stems(row_title_summary or "")
    return any(st in doc or (len(st) >= 5 and any(d.startswith(st) for d in doc))
               for st in stems)
