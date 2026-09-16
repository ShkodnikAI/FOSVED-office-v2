"""SHOP-6 (диспатч #172) — сайты компаний/производителей: generic URL-dossier.

Паттерн PriceGhost (1.1k★, #172): цену извлекают 4 метода «голосуют»:
  1. JSON-LD schema.org/Product → offers (price, priceCurrency,
     availability, seller) — самый надёжный, ищем первым;
  2. сайт-специфичные селекторы — таблица известных РБ-магазинов
     (regex по class/id-атрибутам), расширяемая env SHOP_SITE_SELECTORS_JSON;
  3. generic CSS-эвристика — meta[itemprop=price], og:price:amount,
     элементы с price в class/id: без сторонних HTML-парсеров (RAM/зависимости
     free-плана) — только stdlib re; честно документировано как эвристика;
  4. AI-анализ контекста — call_llm по тексту страницы (вычищенному),
     просим строгий JSON; отказ LLM → пустой список, не падение.
При РАСХОЖДЕНИИ — победитель + все кандидаты с пометками (решение #172:
«при расхождении — кандидаты с пометками в досье»).

Антибот/капча/логин-стена → {"ok": false, "kind": "source_unavailable"} —
источник недоступен, не падение (#172 «Сделано, когда»). Дисквалификация
Ozon/Ali — фаза 2, не здесь.

Транспорт — только allowlist-сервер mcp_servers/web (SHOP-2), для
generic-методов нужен исходный HTML (JSON-LD живёт в script-тегах,
которые text-режим вычищает) → fetch_page(raw_html=true), фикс SHOP-6.
Запись оффера — в shop_offers (platform='web', platform_code=host),
история — как у площадочных сборщиков (SHOP-3); товар канонизируется
canonical_url.

Политика FO-007: в ядре нет except-блоков, кроме краёв I/O с
logging.warning (транспорт/LLM/JSON из env).
"""
import hashlib
import json
import logging
import os
import re
import urllib.parse

log = logging.getLogger("shop_generic")

AVAIL_TRUE = ("instock", "in_stock", "instock", "limitedavailability",
              "preorder", "available")
AVAIL_FALSE = ("outofstock", "out_of_stock", "soldout", "discontinued",
               "unavailable")

# Точки подмены в тестах (контракт: как mcp-вызов и как call_llm)
FETCH_PAGE_FN = None  # лениво: proxy.shop_collectors._mcp_web_call
AI_EXTRACT_FN = None  # лениво: _ai_extract_impl


def _fetch_page(url):
    """Исходный HTML страницы через web-MCP (robots/rate-limit/кэш внутри)."""
    global FETCH_PAGE_FN
    if FETCH_PAGE_FN is None:
        from proxy.shop_collectors import _mcp_web_call
        FETCH_PAGE_FN = _mcp_web_call
    return FETCH_PAGE_FN("fetch_page", {"url": url, "raw_html": True,
                                        "max_chars": 100000})


def is_url(query):
    return str(query or "").strip().lower().startswith(("http://", "https://"))


def looks_like_antibot(html):
    """Стена: капча/антибот/логин — источник недоступен (#172), не падение."""
    h = (html or "").lower()
    markers = ("captcha", "access denied", "ddos-guard", "please enable cookies",
               "checking your browser", "just a moment", "антрабат",
               "подтвердите, что вы не робот")
    return any(m in h for m in markers)


# ── метод 1: JSON-LD ─────────────────────────────────────────────────────
_LD_TYPE_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL)


def _jsonld_offer(node):
    """schema.org/Product|Offer → кандидат цены (price может быть строкой
    «1 299,90» — парсим движком SHOP-1)."""
    from proxy.shop_engine import parse_price
    if not isinstance(node, dict):
        return None
    t = node.get("@type", "")
    types = t if isinstance(t, list) else [t]
    types = [str(x).lower() for x in types]
    offers = node.get("offers")
    if "product" in types and offers is not None:
        offers = offers if isinstance(offers, list) else [offers]
        for off in offers:
            cand = _jsonld_offer(off)
            if cand:
                name = node.get("name")
                if name and not cand.get("name"):
                    cand["name"] = str(name)[:200]
                return cand
        return None
    if "offer" not in types and "aggregateoffer" not in types:
        return None
    price_raw = node.get("price", node.get("lowPrice"))
    price = parse_price(price_raw)
    if price is None:
        return None
    avail = str(node.get("availability", "")).lower()
    in_stock = None
    if any(a in avail for a in AVAIL_TRUE):
        in_stock = True
    elif any(a in avail for a in AVAIL_FALSE):
        in_stock = False
    seller = node.get("seller")
    seller_name = seller.get("name") if isinstance(seller, dict) else None
    return {"price": price,
            "currency": str(node.get("priceCurrency") or "BYN").upper(),
            "in_stock": in_stock, "name": str(node.get("name") or "")[:200],
            "seller": str(seller_name or "")[:120], "source": "jsonld"}


def extract_jsonld(html):
    out = []
    for m in _LD_TYPE_RE.finditer(html or ""):
        blob = m.group(1)
        # JSON-LD может содержать несколько блоков через graph
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict) and node.get("@graph"):
                nodes.extend(node["@graph"] if isinstance(node["@graph"], list)
                             else [node["@graph"]])
            cand = _jsonld_offer(node)
            if cand:
                out.append(cand)
    return out


# ── метод 2: сайт-специфичные селекторы ──────────────────────────────────
# regex по атрибутам (без HTML-парсера): domain → список (name, pattern)
SITE_SELECTORS = {
    "21vek.by": [
        ("21vek_main", r'class="[^"]*(?:product__price|item-price)[^"]*"[^>]*>\s*([^<]{1,40})'),
    ],
    "onliner.by": [
        ("onliner_offers", r'class="[^"]*offer-price[^"]*"[^>]*>\s*([^<]{1,40})'),
    ],
    "5element.by": [
        ("5element_price", r'class="[^"]*product-price[^"]*"[^>]*>\s*([^<]{1,40})'),
    ],
}


def _site_selectors_for(host):
    table = dict(SITE_SELECTORS)
    extra = os.environ.get("SHOP_SITE_SELECTORS_JSON", "")
    if extra:
        try:
            data = json.loads(extra)
            if isinstance(data, dict):
                table.update(data)
        except ValueError:
            log.warning("SHOP_SITE_SELECTORS_JSON не разобран — пропущен")
    for domain, sels in table.items():
        if domain in host:
            return sels
    return []


def extract_site_selectors(html, url):
    from proxy.shop_engine import parse_price
    host = urllib.parse.urlsplit(str(url or "")).netloc.lower()
    out = []
    for name, pattern in _site_selectors_for(host):
        m = re.search(pattern, html or "", re.IGNORECASE)
        if not m:
            continue
        price = parse_price(m.group(1))
        if price is not None:
            out.append({"price": price, "currency": "BYN",
                        "in_stock": None, "name": "", "seller": "",
                        "source": f"selector:{name}"})
    return out


# ── метод 3: generic CSS-эвристика ───────────────────────────────────────
_META_PATTERNS = (
    ("meta_itemprop", re.compile(
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE)),
    ("meta_itemprop2", re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']price["\']',
        re.IGNORECASE)),
    ("og_price", re.compile(
        r'<meta[^>]+property=["\'](?:og|product):price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE)),
    ("og_price2", re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\'](?:og|product):price:amount["\']',
        re.IGNORECASE)),
)
_CLASS_PRICE_RE = re.compile(
    r'<[^>]+(?:class|id)=["\'][^"\']*(?:price|цена)[^"\']*["\'][^>]*>\s*([^<]{1,40})',
    re.IGNORECASE)
_OG_CUR_RE = re.compile(
    r'<meta[^>]+property=["\'](?:og|product):price:currency["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE)


def extract_generic(html):
    from proxy.shop_engine import parse_price
    h = html or ""
    out = []
    for name, pat in _META_PATTERNS:
        m = pat.search(h)
        if m:
            price = parse_price(m.group(1))
            if price is not None:
                cur = _OG_CUR_RE.search(h)
                out.append({"price": price,
                            "currency": str(cur.group(1)).upper() if cur else "BYN",
                            "in_stock": None, "name": "", "seller": "",
                            "source": f"generic:{name}"})
                break  # одна meta-цена: первый источник победил
    if out:
        return out
    for m in _CLASS_PRICE_RE.finditer(h):
        txt = re.sub(r"^\s*(?:от|до|свыше|более)\s+", "", m.group(1),
                     flags=re.IGNORECASE)  # «от 165,50 р.» → «165,50 р.»
        price = parse_price(txt)
        if price is not None:
            out.append({"price": price, "currency": "BYN",
                        "in_stock": None, "name": "", "seller": "",
                        "source": "generic:class_price"})
            break
    return out


# ── метод 4: AI-анализ контекста ─────────────────────────────────────────
_AI_PROMPT = """Ты извлекаешь цену товара со страницы магазина. Верни СТРОГО JSON без пояснений:
{{"price": число или null, "currency": "BYN"|"USD"|"RUB", "in_stock": true|false|null, "name": "название товара"}}
Если цены на странице нет — верни {{"price": null}}. Текст страницы (обрезан):

{TEXT}"""


def _strip_html_text(html):
    txt = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def _ai_extract_impl(url, text):
    from proxy.providers import call_llm
    prompt = _AI_PROMPT.replace("{TEXT}", text[:6000])
    result = call_llm("expert", [{"role": "user", "content": prompt}],
                      command="shop_price_extract")
    reply = (result or {}).get("reply", "")
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    if not m:
        log.warning("AI-извлечение цены: JSON в ответе нет (url=%s)", url)
        return []
    data = json.loads(m.group(0))
    from proxy.shop_engine import parse_price
    price = parse_price(data.get("price"))
    if price is None:
        return []
    return [{"price": price,
             "currency": str(data.get("currency") or "BYN").upper(),
             "in_stock": data.get("in_stock")
             if isinstance(data.get("in_stock"), (bool, type(None))) else None,
             "name": str(data.get("name") or "")[:200], "seller": "",
             "source": "ai"}]


def extract_ai(url, html):
    global AI_EXTRACT_FN
    if AI_EXTRACT_FN is None:
        AI_EXTRACT_FN = _ai_extract_impl
    return AI_EXTRACT_FN(url, _strip_html_text(html or ""))


# ── голосование ──────────────────────────────────────────────────────────
def vote(candidates):
    """Кластеризация кандидатов по цене (допуск 1%).

    Победитель — кластер с наибольшим весом; внутри кластера приоритет
    источника jsonld > selector:* > generic:* > ai (#172). agree=False,
    если кластеров с ценами больше одного — тогда ВСЕ кандидаты идут
    в досье с пометками (решение владельца).
    """
    ranked = {"jsonld": 0, "selector": 1, "generic": 2, "ai": 3}

    def _rank(c):
        src = str(c.get("source") or "")
        return ranked.get(src.split(":")[0], 4)

    clusters = []
    for c in candidates:
        if c.get("price") is None:
            continue
        for cl in clusters:
            if abs(cl["price"] - c["price"]) <= max(0.01, cl["price"] * 0.01):
                cl["members"].append(c)
                break
        else:
            clusters.append({"price": c["price"], "members": [c]})
    if not clusters:
        return {"winner": None, "agree": False, "clusters": []}
    clusters.sort(key=lambda cl: len(cl["members"]), reverse=True)
    best = clusters[0]
    winner = sorted(best["members"], key=_rank)[0]
    agree = len([cl for cl in clusters if cl["members"]]) == 1
    return {"winner": dict(winner), "agree": agree,
            "clusters": [{"price": cl["price"],
                          "sources": [str(m.get("source")) for m in cl["members"]]}
                         for cl in clusters]}


# ── сбор оффера по URL → БД (offer-record SHOP-3-совместимый) ────────────
def collect_url(product_id, url):
    """Полный проход: fetch → 4 метода → голосование → оффер в БД.

    Возвращает {"ok", "offer", "candidates", "vote"} | {"ok": false, kind}.
    platform='web', platform_code=host — UNIQUE(platform, platform_code)
    держит один оффер на сайт (обновление при повторном сборе).
    """
    from proxy.shop_collectors import canonical_url
    url = canonical_url(str(url or "").strip())
    host = urllib.parse.urlsplit(url).netloc.lower()
    if not host:
        return {"ok": False, "kind": "bad_url", "error": "URL не разобран"}
    resp = _fetch_page(url)
    if not resp.get("ok"):
        kind = "source_unavailable" if resp.get("kind") in (
            "fetch_error", "http_error", "timeout") else resp.get("kind")
        log.warning("generic-сбор %s не удался: %s", url, resp.get("error"))
        return {"ok": False, "kind": kind or "source_unavailable",
                "error": str(resp.get("error", ""))[:200]}
    html = resp.get("content") or ""
    if looks_like_antibot(html):
        return {"ok": False, "kind": "source_unavailable",
                "error": "антибот/капча — источник недоступен"}
    candidates = (extract_jsonld(html) + extract_site_selectors(html, url)
                  + extract_generic(html))
    try:
        candidates += extract_ai(url, html)
    except Exception as e:  # noqa: BLE001 — LLM-отказ не роняет сбор
        log.warning("AI-извлечение не удалось (%s): %s", url, e)
    if not candidates:
        return {"ok": False, "kind": "no_candidates",
                "error": "цена на странице не найдена ни одним методом"}
    v = vote(candidates)
    if v["winner"] is None:
        return {"ok": False, "kind": "no_candidates",
                "error": "кандидаты без цены"}
    win = v["winner"]
    from proxy.shop_engine import to_byn
    price_byn = to_byn(win["price"], win.get("currency"),
                       {"USD": float(os.environ.get("SHOP_FX_USD", 0) or 0),
                        "RUB": float(os.environ.get("SHOP_FX_RUB", 0) or 0)}
                       if win.get("currency") != "BYN" else None)
    if price_byn is None and win.get("currency") != "BYN":
        log.warning("нет курса %s — оффер %s без цены (честная деградация)",
                    win.get("currency"), url)
    _save_offer(product_id, url, host, win, price_byn, v)
    return {"ok": True, "url": url, "host": host, "offer": win,
            "candidates": candidates, "vote": v}


def _save_offer(product_id, url, host, win, price_byn, v):
    """Идемпотентный upsert оффера platform='web' + история (стиль SHOP-3)."""
    from proxy.core import _query
    row = _query("SELECT id FROM shop_offers WHERE platform='web' AND "
                 "platform_code=? ORDER BY id DESC LIMIT 1", (host,), fetch=True)
    if row:
        oid = row[0]["id"]
        _query("UPDATE shop_offers SET product_id=?, url=?, price_byn=?, "
               "in_stock=?, fetched_at=datetime('now') WHERE id=?",
               (product_id, url, price_byn,
                1 if win.get("in_stock") else 0, oid))
    else:
        _query("INSERT INTO shop_offers (product_id, platform, platform_code, "
               "url, price_byn, in_stock) VALUES (?, 'web', ?, ?, ?, ?)",
               (product_id, host, url, price_byn,
                1 if win.get("in_stock") else 0))
        row = _query("SELECT id FROM shop_offers WHERE platform='web' AND "
                     "platform_code=? ORDER BY id DESC LIMIT 1", (host,),
                     fetch=True)
        oid = row[0]["id"] if row else None
    if price_byn is not None and oid:
        _query("INSERT INTO shop_price_history (offer_id, price_byn, in_stock) "
               "VALUES (?, ?, ?)", (oid, price_byn,
                                    1 if win.get("in_stock") else 0))
    try:
        _query("INSERT INTO audit_log (action, actor, dept, details, status) "
               "VALUES ('shop_fetch', 'shop', 'shop', ?, 'ok')",
               (f"platform=web purpose=generic url={url[:120]} "
                f"vote_agree={v.get('agree')}",))
    except Exception as e:  # noqa: BLE001 — аудит не роняет сбор
        log.warning("audit_log недоступен: %s", e)
