"""FO-010: детерминированные API-источники для ЛЗ — arXiv, HN Algolia, GitHub Search.

Наряд #70: метаданные статей/репо не требуют LLM. API-вызовы дешёвые и
детерминированные; LLM остаётся только на фильтрацию/синтез отобранного —
объём промптов падает на порядок.

Метрика (FO-004): каждый скан пишет trace-запись trace_type=lz_api_scan с
объёмом отобранного и оценкой сэкономленных токенов (сырой поток ~2 символа/
токен, который раньше прошёл бы через LLM-фильтрацию).
"""
import os
import re
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from proxy.core import log, http_requests, _write_llm_trace

_UA = {"User-Agent": "FOSVED-Office-LZ/1.0 (deterministic source scan)"}

# Тот же токен, что использует github-watch (proxy.lz_github), но без импорта
# оттуда — lz_sources самодостаточен (разрыв цикла импортов).
_GH_TOKEN = (os.environ.get("GITHUB_TOKEN_METALOGOS")
             or os.environ.get("GITHUB_TOKEN") or "")
_GH_HEADERS = {"Accept": "application/vnd.github.v3+json"}
if _GH_TOKEN:
    _GH_HEADERS["Authorization"] = f"token {_GH_TOKEN}"


def arxiv_search(query, max_results=8, since_days=90):
    """arXiv API (Atom). Возврат: [{source,title,url,published,meta}]."""
    q = urllib.parse.quote(query)
    url = f"http://export.arxiv.org/api/query?search_query=all:{q}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    try:
        resp = http_requests.get(url, headers=_UA, timeout=20)
        resp.raise_for_status()
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        items = []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).date()
        for e in root.findall("a:entry", ns):
            published = e.findtext("a:published", "", ns)[:10]
            link = ""
            for l in e.findall("a:link", ns):
                if l.get("type") == "application/pdf" or l.get("rel") == "alternate":
                    link = l.get("href", "")
            summary = re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip()
            items.append({
                "source": "arxiv",
                "title": re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip(),
                "url": link or e.findtext("a:id", "", ns),
                "published": published,
                "meta": f"{len(summary)} chars abstract",
                "summary": summary[:400],
            })
        return items
    except Exception as e:
        log.warning(f"arxiv_search failed: {e}")
        return []


def hn_search(query, max_results=8, since_days=30):
    """HN Algolia (статьи/обсуждения). Возврат: [{source,title,url,points,comments,published}]."""
    since = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
    url = ("https://hn.algolia.com/api/v1/search_by_date?query=" + urllib.parse.quote(query)
           + f"&tags=story&numericFilters=created_at_i>{since}&hitsPerPage={max_results}")
    try:
        resp = http_requests.get(url, headers=_UA, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        return [{
            "source": "hn",
            "title": h.get("title") or h.get("story_title") or "",
            "url": h.get("url") or (f"https://news.ycombinator.com/item?id={h.get('objectID')}" if h.get("objectID") else ""),
            "published": (h.get("created_at") or "")[:10],
            "meta": f"{h.get('points') or 0} points, {h.get('num_comments') or 0} comments",
            "summary": (h.get("story_text") or h.get("comment_text") or "")[:300],
        } for h in hits if (h.get("title") or h.get("story_title"))]
    except Exception as e:
        log.warning(f"hn_search failed: {e}")
        return []


def github_repo_search(query, max_results=8, since_days=180):
    """GitHub Search API: тренд-репо по теме (звёзды/давность). Возврат: [{source,name,url,stars,pushed,desc}]."""
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    q = f"{query} pushed:>{since}"
    url = ("https://api.github.com/search/repositories?q=" + urllib.parse.quote(q)
           + f"&sort=stars&order=desc&per_page={max_results}")
    headers = dict(_GH_HEADERS)
    headers.update(_UA)
    try:
        resp = http_requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return [{
            "source": "github",
            "title": r.get("full_name", ""),
            "url": r.get("html_url", ""),
            "published": (r.get("pushed_at") or "")[:10],
            "meta": f"{r.get('stargazers_count', 0)}★, {r.get('language') or 'n/a'}",
            "summary": (r.get("description") or "")[:300],
        } for r in resp.json().get("items", [])]
    except Exception as e:
        log.warning(f"github_repo_search failed: {e}")
        return []


def _compact(items):
    """Компактное текстовое представление для синтезирующего промпта (без сырого мусора)."""
    lines = []
    for it in items:
        head = f"- [{it['source']}] {it['title']}"
        if it.get("meta"):
            head += f" ({it['meta']})"
        if it.get("published"):
            head += f" [{it['published']}]"
        lines.append(head)
        if it.get("url"):
            lines.append(f"  {it['url']}")
        if it.get("summary"):
            lines.append(f"  {it['summary']}")
    return "\n".join(lines)


def lz_api_scan(topics, max_per_source=6, dept="lz"):
    """Скан по темам через 3 API-источника. Возврат: {items, text, counts, trace_id}.

    Пишет FO-004-трейс: сколько отобрано и сколько токенов сырого потока
    сэкономлено (оценка: 2 символа/токен — параметр оценки из _estimate_tokens).
    """
    t0 = time.monotonic()
    trace_id = None
    seen_urls = set()
    items = []
    counts = {}
    for topic in topics[:10]:  # защита от раздутия
        for fetcher in (arxiv_search, hn_search, github_repo_search):
            for it in fetcher(topic, max_results=max_per_source):
                if it.get("url") and it["url"] in seen_urls:
                    continue
                if it.get("url"):
                    seen_urls.add(it["url"])
                items.append(it)

    for it in items:
        counts[it["source"]] = counts.get(it["source"], 0) + 1

    text = _compact(items)
    latency_ms = int((time.monotonic() - t0) * 1000)
    # честная метрика: компактная выдача уходит в LLM-синтез; сырой поток
    # (полные abstracts/комментарии/README, ~х10 объёма) LLM не видит
    compact_tokens = len(text) // 2
    raw_estimate = sum((len(it.get("summary", "")) + len(it.get("title", "")) * 3 + 150) for it in items) // 2
    est_tokens_saved = max(0, raw_estimate - compact_tokens)

    trace_id = f"lzapi{int(time.monotonic() * 1e6) % 10**10:010d}"
    try:
        _write_llm_trace({
            "trace_id": trace_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "trace_type": "lz_api_scan",
            "gen_ai.system": "api-sources",
            "gen_ai.request.model": "arxiv+hn+github-search",
            "gen_ai.usage.input_tokens": 0,
            "gen_ai.usage.output_tokens": 0,
            "latency_ms": latency_ms,
            "dept": dept,
            "ok": True,
            "items_fetched": len(items),
            "counts": counts,
            "compact_tokens_to_llm": compact_tokens,
            "est_tokens_saved": est_tokens_saved,
        })
    except Exception as e:
        log.warning(f"lz_api_scan trace failed: {e}")

    return {"items": items, "text": text, "counts": counts,
            "latency_ms": latency_ms, "est_tokens_saved": est_tokens_saved,
            "trace_id": trace_id}
