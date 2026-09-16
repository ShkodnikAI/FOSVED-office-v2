"""SHOP-3 (диспатч #172) — сборщики MVP-площадок + история цен.

Канал доступа: весь web — через allowlist-сервер `mcp_servers/web`
(SHOP-2): robots/rate-limit/кэш/SSRF — внутри сервера. Сборщик спавнит
ТОТ ЖЕ бинарник (единственный JSON-RPC вызов на единственный запрос),
каждый вызов — в audit_log (action='shop_fetch').

Живые пробы из песочницы 2026-09-16 (form-истина, не память),
дополнены живым диагнозом первого владельческого прогона (досье #2,
«99 офф. без цены»):
  - search.wb.ru v4 → 200: цены в sizes[].price (копейки): product —
    продажная, basic — до скидки; отзывы = feedbacks; seller =
    supplier/supplierId/supplierRating; наличие = totalQuantity;
    curr=byn игнорируется RU-кластером → цены RUB, BYN через fx_rates()
    (первый живой прогон: без FX все 100 офферов WB ушли в unscored);
  - api.kufar.by → 200: price_byn/price_usd — СТРОКИ В КОПЕЙКАХ
    (сверка 2026-09-16: iPhone 16 Pro price_byn="250000" = 2500 BYN и
    price_usd="82546" = $825.46 — шкалы сходятся; предыдущая версия
    считала поле BYN-числом — завышение в 100 раз). "0" — цены нет.
    Полнословная фраза («… и … размер L-XL …») матчится в ноль →
    лестница биграмм; query_used — какой запрос реально сработал;
  - FX fx_rates(): env SHOP_FX_RATES_JSON → свежий кэш system_settings
    (6 ч) → живой egress НБРБ (полный дневной список, periodicity=0;
    точечные /rates/RUB?paramMode=1 отдают 404 — проверено) → резерв
    open.er-api.com (кросс через USD) → устаревший кэш → аварийные
    константы; отказ egress не роняет сбор (FO-007: лог, не молчание);
  - catalog.api.onliner.by → жив, но слаги категорий не подобраны из
    песочницы: категория — env SHOP_ONLINER_CATEGORY; парсер оборонительный
    (форма по памяти, kind:"api_form_mismatch" при расхождении);
  - 21vek.by — сайт жив, API-форма из песочницы не снята → каркас с
    честным {"ok": false, "kind": "not_implemented_live"}; форма снимется
    первым живым прогоном на Render и парсер добавится точечно.

Все парсеры оборонительные: нет ожидаемых ключей → честный отказ с kind,
ничего не падает. Политика FO-007: except-блоки не молчат — logging.warning.
"""
import json
import logging
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

from proxy.shop_engine import to_byn

log = logging.getLogger("shop_collectors")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_SERVER = _REPO_ROOT / "mcp_servers" / "web"

UTM_JUNK = {
    "gclid", "fbclid", "yclid", "spm", "scm", "pvid", "from", "app_rule",
    "aff_id", "partner", "ref",
}


def canonical_url(url):
    """Прямая ссылка на товар: чистка трекинг-параметров (#172).

    utm_* и рекламные метки выбрасываются, остальной query сохраняется
    (параметры пагинации/фильтров площадок не трогаем).
    """
    parts = urllib.parse.urlsplit(str(url or ""))
    if not parts.scheme or not parts.netloc:
        return str(url or "")
    kept = []
    for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        lk = k.lower()
        if lk in UTM_JUNK or lk.startswith("utm_"):
            continue
        kept.append((k, v))
    query = urllib.parse.urlencode(kept)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query, ""))


# ── FX: курсы к BYN ────────────────────────────────────────────────────
FX_CACHE_KEY = "shop_fx_rates"        # kv system_settings (общий с mlog)
FX_CACHE_TTL = 6 * 3600
# Аварийные константы (фиксация 2026-09-16, официальные НБРБ на дату).
# Только чтобы досье не было пустым при полном отказе egress — источник
# и дата фиксации задокументированы здесь; живой курс всегда точнее.
FX_FALLBACK = {"RUB": 0.0345, "USD": 3.05, "EUR": 3.35, "CNY": 0.43}


def _setting_get(key):
    try:
        from proxy.core import _query
        rows = _query("SELECT value FROM system_settings WHERE key=?",
                      (key,), fetch=True)
        return rows[0]["value"] if rows else None
    except Exception as e:  # noqa: BLE001 — kv недоступен → идём дальше
        log.warning("system_settings недоступен: %s", e)
        return None


def _setting_set(key, value):
    try:
        from proxy.core import _query
        _query("INSERT INTO system_settings (key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, value))
    except Exception as e:  # noqa: BLE001 — кэш не написался, не беда
        log.warning("system_settings недоступен: %s", e)


def _nbrb_rates():
    """НБРБ, полный дневной список (periodicity=0): Cur_OfficialRate за
    Cur_Scale единиц → BYN за 1 единицу. Точечные /rates/RUB?paramMode=1
    отдают 404 (живая проба) — работает только полный список."""
    r = FETCH_JSON_FN("fetch_json",
                      {"url": "https://api.nbrb.by/exrates/rates?periodicity=0"})
    if not r.get("ok"):
        return None
    rows = r.get("data") or []
    rates = {}
    for row in rows if isinstance(rows, list) else []:
        ab = str(row.get("Cur_Abbreviation") or "").upper()
        off = _num(row.get("Cur_OfficialRate"))
        scale = _num(row.get("Cur_Scale")) or 1.0
        if ab and off and scale > 0:
            rates[ab] = round(off / scale, 6)
    return rates or None


def _erapi_cross():
    """Резерв: кросс через open.er-api.com (USD-база) — BYN за 1 единицу.
    Нужен на случай, если НБРБ недоступна из региона рантайма."""
    r = FETCH_JSON_FN("fetch_json",
                      {"url": "https://open.er-api.com/v6/latest/USD"})
    if not r.get("ok"):
        return None
    rates = (r.get("data") or {}).get("rates") or {}
    byn = _num(rates.get("BYN"))
    if not byn or byn <= 0:
        return None
    out = {"USD": round(byn, 6)}
    for ab in ("RUB", "EUR", "CNY", "PLN", "UAH"):
        v = _num(rates.get(ab))
        if v and v > 0:
            out[ab] = round(byn / v, 6)
    return out or None


def _fx_fetch_live():
    """Живой egress: НБРБ → резерв er-api. (rates, source) | (None, None)."""
    for fn, source in ((_nbrb_rates, "nbrb"), (_erapi_cross, "er-api")):
        try:
            rates = fn()
        except Exception as e:  # noqa: BLE001 — транспорт, не данные
            log.warning("FX-источник %s упал: %s", source, e)
            continue
        if rates:
            _audit("fx", f"source={source}", "ok")
            return rates, source
    return None, None


def _fx_cache_read():
    raw = _setting_get(FX_CACHE_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("rates"), dict):
        return data
    return None


def _fx_cache_write(rates, source):
    _setting_set(FX_CACHE_KEY, json.dumps(
        {"rates": rates, "source": source, "fetched_at": time.time()},
        ensure_ascii=False))


def fx_rates():
    """Курсы к BYN. Приоритет: env SHOP_FX_RATES_JSON → свежий кэш (6 ч)
    → живой egress НБРБ/er-api → устаревший кэш → аварийные константы.
    Ошибка egress сбор не роняет (честная деградация, FO-007)."""
    raw = os.environ.get("SHOP_FX_RATES_JSON", "")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                # пустой dict — явный выключатель конвертации (тесты/ops)
                return data
        except ValueError:
            log.warning("SHOP_FX_RATES_JSON не разобран — иду в кэш/egress")
    cached = _fx_cache_read()
    if cached and (time.time() - (cached.get("fetched_at") or 0)) < FX_CACHE_TTL:
        return cached["rates"]
    rates, source = _fx_fetch_live()
    if rates:
        _fx_cache_write(rates, source)
        return rates
    if cached and cached["rates"]:
        log.warning("FX egress недоступен — устаревший кэш (age > %ss)",
                    FX_CACHE_TTL)
        return cached["rates"]
    log.warning("FX недоступен совсем — аварийные константы %s", FX_FALLBACK)
    return dict(FX_FALLBACK)


# совместимость со старыми вызовами/тестами
_fx_rates = fx_rates


def _mcp_web_call(tool, args):
    """Один вызов allowlist-сервера web: spawn → JSON-RPC → ответ.

    Сервер сам соблюдает robots/rate-limit/кэш/SSRF; любые его отказы
    приходят как {"ok": false, ...} — здесь они прозрачно пробрасываются.
    """
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }) + "\n"
    proc = subprocess.run(
        [str(_WEB_SERVER)], input=payload, capture_output=True,
        text=True, timeout=60, cwd=str(_REPO_ROOT))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "error": "web-MCP не ответил", "kind": "mcp_no_response"}
    try:
        resp = json.loads(lines[0])
        return json.loads(resp["result"]["content"][0]["text"])
    except (ValueError, KeyError, IndexError) as e:
        log.warning("web-MCP ответ не разобран: %s", e)
        return {"ok": False, "error": f"web-MCP ответ не разобран: {e}",
                "kind": "mcp_bad_response"}


# Точка подмены в тестах (stub-функция с тем же контрактом).
FETCH_JSON_FN = _mcp_web_call


def _audit(platform, purpose, status):
    try:
        from proxy.core import _query
        _query("INSERT INTO audit_log (action, actor, dept, details, status) "
               "VALUES ('shop_fetch', 'shop', 'shop', ?, ?)",
               (f"platform={platform} purpose={purpose}", status))
    except Exception as e:  # аудит не должен ронять сбор
        log.warning("audit_log недоступен: %s", e)


def _num(x):
    """Число из '129.00' / 129 / None. Нечисловое → None (без исключений)."""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ── WB ──────────────────────────────────────────────────────────────────
def collect_wb(query, page=1, rates=None):
    """Поиск WB (живая форма v4). Цены RUB → BYN по rates (иначе None —
    честно: явный rates=None из вызывающего кода курс не придумывает)."""
    rates = rates if rates is not None else fx_rates()
    base = os.environ.get(
        "SHOP_WB_SEARCH_BASE",
        "https://search.wb.ru/exactmatch/ru/common/v4/search")
    url = (base + "?" + urllib.parse.urlencode({
        "appType": "1", "curr": "rub", "dest": "-1257786",
        "query": query, "resultset": "catalog", "spp": "30",
        "page": str(page), "sort": "popular"}))
    data = FETCH_JSON_FN("fetch_json", {"url": url})
    _audit("wb", f"search:{query}", "ok" if data.get("ok") else "refused")
    if not data.get("ok"):
        return {"ok": False, "platform": "wb", "error": data.get("error"),
                "kind": data.get("kind", "transport"), "url": url}
    body = data.get("data") or {}
    products = body.get("products")
    if not isinstance(products, list):
        return {"ok": False, "platform": "wb", "url": url,
                "error": "нет products[] в ответе", "kind": "api_form_mismatch"}
    offers = []
    for p in products:
        pid = p.get("id")
        if pid is None:
            continue
        sizes = p.get("sizes") or []
        price_raw = None
        old_raw = None
        for s in sizes:
            pr = s.get("price") or {}
            prod_kop = _num(pr.get("product"))
            if prod_kop is not None:
                price_raw = prod_kop / 100.0        # копейки → валюта
                old_raw = _num(pr.get("basic"))
                if old_raw is not None:
                    old_raw = old_raw / 100.0
                break
        price_byn = to_byn(price_raw, "RUB", rates)
        old_byn = to_byn(old_raw, "RUB", rates) if old_raw is not None else None
        qty = _num(p.get("totalQuantity")) or 0
        offers.append({
            "platform": "wb",
            "platform_code": str(pid),
            "url": canonical_url(f"https://www.wildberries.ru/catalog/{pid}/detail.aspx"),
            "title": p.get("name"),
            "price_byn": price_byn,
            "old_price_byn": old_byn,
            "currency_note": "RUB" if price_byn is None else None,
            "in_stock": 1 if qty > 0 else 0,
            "rating": _num(p.get("reviewRating")),
            "reviews_count": int(_num(p.get("feedbacks")) or 0),
            "seller_name": p.get("supplier"),
            "seller_platform_code": str(p.get("supplierId")) if p.get("supplierId") else None,
            "seller_rating": _num(p.get("supplierRating")),
            "seller_deals": None,
            "seller_official": None,
        })
    return {"ok": True, "platform": "wb", "url": url, "offers": offers}


# ── Kufar ───────────────────────────────────────────────────────────────
def _kufar_kop(x):
    """Kufar отдаёт price_byn/price_usd СТРОКАМИ В КОПЕЙКАХ (живая сверка
    2026-09-16: iPhone 16 Pro price_byn="250000" → 2500 BYN, price_usd=
    "82546" → $825.46 — шкалы сходятся; см. докстринг модуля). "0" —
    цены нет (торг/договорная). Нечисловое → None без исключений."""
    v = _num(x)
    if v is None or v <= 0:
        return None
    return round(v / 100.0, 2)


def _kufar_bigrams(query):
    """Первые биграммы запроса (макс 3) для лестницы фолбэка."""
    toks = str(query or "").split()
    return [" ".join(toks[i:i + 2])
            for i in range(min(3, max(0, len(toks) - 1)))]


def _kufar_fetch(query, size):
    """Один транспортный вызов search-api v2. (ok, ads|error, kind, url)."""
    base = os.environ.get(
        "SHOP_KUFAR_BASE",
        "https://api.kufar.by/search-api/v2/search/rendered-paginated")
    url = base + "?" + urllib.parse.urlencode({"query": query, "size": str(size)})
    data = FETCH_JSON_FN("fetch_json", {"url": url})
    _audit("kufar", f"search:{query}", "ok" if data.get("ok") else "refused")
    if not data.get("ok"):
        return {"ok": False, "error": data.get("error"),
                "kind": data.get("kind", "transport"), "url": url}
    ads = (data.get("data") or {}).get("ads")
    if not isinstance(ads, list):
        return {"ok": False, "url": url, "error": "нет ads[] в ответе",
                "kind": "api_form_mismatch"}
    return {"ok": True, "url": url, "ads": ads}


def collect_kufar(query, size=20):
    """Поиск Kufar (search-api v2). Цены — копейки строкой → BYN.

    Лестница запроса (живой диагноз досье #2): полнословная фраза
    матчится в ноль → пробуем первые биграммы, пока не найдём ads;
    query_used — какой запрос реально сработал (для аудита/тестов).
    """
    res = _kufar_fetch(query, size)
    if res.get("ok") and not res.get("ads"):
        for bq in _kufar_bigrams(query):
            res2 = _kufar_fetch(bq, size)
            if res2.get("ok") and res2.get("ads"):
                res = {**res2, "query_used": bq}
                _audit("kufar", f"bigram_fallback:{bq}", "ok")
                break
    if not res.get("ok"):
        return {"ok": False, "platform": "kufar", "error": res.get("error"),
                "kind": res.get("kind", "transport"), "url": res.get("url")}
    ads = res["ads"]
    offers = []
    for a in ads:
        ad_id = a.get("ad_id")
        if ad_id is None:
            continue
        seller_name = None
        for prm in a.get("account_parameters") or []:
            if prm.get("p") == "name":
                seller_name = prm.get("v")
                break
        paid = a.get("paid_services") or {}
        price_byn = _kufar_kop(a.get("price_byn"))
        offers.append({
            "platform": "kufar",
            "platform_code": str(ad_id),
            "url": canonical_url(a.get("ad_link") or f"https://www.kufar.by/item/{ad_id}"),
            "title": a.get("subject"),
            "price_byn": price_byn,
            "old_price_byn": None,
            "in_stock": 1,  # объявление активно
            "installment_ok": 1 if paid.get("halva") else 0,  # рассрочка «Халва»
            "rating": None,
            "reviews_count": None,
            "seller_name": seller_name,
            "seller_platform_code": a.get("account_id"),
            "seller_rating": None,
            "seller_deals": None,
            "seller_official": 1 if a.get("company_ad") else 0,
        })
    out = {"ok": True, "platform": "kufar", "url": res["url"], "offers": offers}
    if res.get("query_used"):
        out["query_used"] = res["query_used"]
    return out


# ── Onliner ─────────────────────────────────────────────────────────────
def collect_onliner(query, page=1):
    """Каталог Onliner. Слаг категории — env SHOP_ONLINER_CATEGORY.

    Форма ответа — по памяти (жирный минус, честно): парсер оборонительный,
    расхождение → kind:"api_form_mismatch" — поправим с живого прогона.
    """
    category = os.environ.get("SHOP_ONLINER_CATEGORY", "")
    if not category:
        return {"ok": False, "platform": "onliner",
                "error": "SHOP_ONLINER_CATEGORY не задан — слаг категории каталога "
                         "определяется с живого прогона (песочница слаги не отдала)",
                "kind": "config_missing"}
    url = ("https://catalog.api.onliner.by/search/" + urllib.parse.quote(category)
           + "?" + urllib.parse.urlencode({"query": query, "products-page": str(page)}))
    data = FETCH_JSON_FN("fetch_json", {"url": url})
    _audit("onliner", f"search:{query}", "ok" if data.get("ok") else "refused")
    if not data.get("ok"):
        return {"ok": False, "platform": "onliner", "error": data.get("error"),
                "kind": data.get("kind", "transport"), "url": url}
    body = data.get("data") or {}
    products = body.get("products")
    if not isinstance(products, list):
        return {"ok": False, "platform": "onliner", "url": url,
                "error": "нет products[] в ответе", "kind": "api_form_mismatch"}
    rates = fx_rates()  # один раз на сбор, не по офферу (эгресс-кэш)
    offers = []
    for p in products:
        key = p.get("key") or p.get("id")
        if key is None:
            continue
        price = (p.get("prices") or {}).get("price") or {}
        amount = _num(price.get("amount"))
        currency = (price.get("currency") or "BYN").upper()
        price_byn = to_byn(amount, currency, rates) if currency != "BYN" else amount
        offers.append({
            "platform": "onliner",
            "platform_code": str(key),
            "url": canonical_url(p.get("html_url") or f"https://catalog.onliner.by/{key}"),
            "title": p.get("full_name") or p.get("name"),
            "price_byn": price_byn,
            "old_price_byn": None,
            "in_stock": 1 if (p.get("prices") or {}).get("offers_count") else 0,
            "rating": _num(p.get("rating")),
            "reviews_count": int(_num(p.get("reviews_count")) or 0),
            "seller_name": None, "seller_platform_code": None,
            "seller_rating": None, "seller_deals": None, "seller_official": None,
        })
    return {"ok": True, "platform": "onliner", "url": url, "offers": offers}


# ── 21vek (каркас) ──────────────────────────────────────────────────────
def collect_21vek(query):
    """Каркас: API-форма не снята из песочницы (честно, #172).

    Первый живой прогон на Render снимет форму (fetch_json на поисковый
    эндпоинт), парсер добавится точечным PR.
    """
    return {"ok": False, "platform": "21vek",
            "error": "API-форма 21vek не снята — каркас ждёт живого прогона на Render",
            "kind": "not_implemented_live"}


COLLECTORS = {
    "wb": collect_wb,
    "kufar": collect_kufar,
    "onliner": collect_onliner,
    "21vek": collect_21vek,
}


def collect(platform, query, **kw):
    fn = COLLECTORS.get(platform)
    if not fn:
        return {"ok": False, "platform": platform,
                "error": f"нет сборщика для '{platform}'", "kind": "no_collector"}
    return fn(query, **kw)


# ── Хранение: upsert офферов + история цен ──────────────────────────────
def _upsert_seller(platform, o):
    from proxy.core import _query
    if o.get("seller_name") is None and o.get("seller_platform_code") is None:
        return None
    row = _query(
        "SELECT id FROM shop_sellers WHERE platform=? AND "
        "COALESCE(name,'')=COALESCE(?,'') LIMIT 1",
        (platform, o.get("seller_name")), fetch=True)
    if row:
        sid = row[0]["id"]
        _query("UPDATE shop_sellers SET rating=COALESCE(?, rating), "
               "official=COALESCE(?, official) WHERE id=?",
               (o.get("seller_rating"), o.get("seller_official"), sid))
        return sid
    _query(
        "INSERT INTO shop_sellers (platform, name, rating, official) "
        "VALUES (?, ?, ?, ?)", (platform, o.get("seller_name"),
                                o.get("seller_rating"), o.get("seller_official")))
    # отдельное соединение на каждый _query → lastrowid недоступен,
    # берём id обратным SELECT по уникальному ключу
    back = _query(
        "SELECT id FROM shop_sellers WHERE platform=? AND "
        "COALESCE(name,'')=COALESCE(?,'') ORDER BY id DESC LIMIT 1",
        (platform, o.get("seller_name")), fetch=True)
    return back[0]["id"] if back else None


def refresh_product(product_id, platform, query, **kw):
    """Собрать площадку и уложить офферы + срез истории. Идемпотентно.

    История: строка на каждый успешный сбор с ценой (2–4 раза/сутки —
    копейки объёма, зато медианы честные с первого дня).
    """
    from proxy.core import _query
    res = collect(platform, query, **kw)
    if not res.get("ok"):
        return res
    count_offers = 0
    count_hist = 0
    for o in res["offers"]:
        sid = _upsert_seller(platform, o)
        existing = _query(
            "SELECT id FROM shop_offers WHERE platform=? AND platform_code=? LIMIT 1",
            (platform, o["platform_code"]), fetch=True)
        if existing:
            oid = existing[0]["id"]
            _query(
                "UPDATE shop_offers SET url=?, price_byn=?, old_price_byn=?, "
                "in_stock=?, installment_ok=?, rating=?, reviews_count=?, "
                "seller_id=?, fetched_at=datetime('now') WHERE id=?",
                (o["url"], o.get("price_byn"), o.get("old_price_byn"),
                 o.get("in_stock"), o.get("installment_ok"), o.get("rating"),
                 o.get("reviews_count"), sid, oid))
        else:
            _query(
                "INSERT INTO shop_offers (product_id, platform, platform_code, url, "
                "price_byn, old_price_byn, in_stock, installment_ok, rating, "
                "reviews_count, seller_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (product_id, platform, o["platform_code"], o["url"],
                 o.get("price_byn"), o.get("old_price_byn"), o.get("in_stock"),
                 o.get("installment_ok"), o.get("rating"), o.get("reviews_count"), sid))
            back = _query(
                "SELECT id FROM shop_offers WHERE platform=? AND platform_code=? "
                "ORDER BY id DESC LIMIT 1",
                (platform, o["platform_code"]), fetch=True)
            oid = back[0]["id"] if back else None
        count_offers += 1
        if o.get("price_byn") is not None:
            _query(
                "INSERT INTO shop_price_history (offer_id, price_byn, old_price_byn, "
                "in_stock) VALUES (?, ?, ?, ?)",
                (oid, o.get("price_byn"), o.get("old_price_byn"), o.get("in_stock")))
            count_hist += 1
    _audit(platform, f"refresh product={product_id}", "ok")
    return {"ok": True, "platform": platform, "product_id": product_id,
            "offers": count_offers, "history_rows": count_hist}


def score_product(product_id, profile="default", target_price_byn=None):
    """Склейка SHOP-1 + SHOP-3: срез БД → вердикт движка (для SHOP-4/5)."""
    from proxy.core import _query
    from proxy.shop_engine import score_offers
    prod_rows = _query("SELECT * FROM shop_products WHERE id=?", (product_id,),
                       fetch=True)
    if not prod_rows:
        return {"ok": False, "error": f"товар {product_id} не найден",
                "kind": "not_found"}
    product = dict(prod_rows[0])
    specs = None
    if product.get("specs_json"):
        try:
            specs = json.loads(product["specs_json"])
        except ValueError:
            log.warning("specs_json товара %s не разобран", product_id)
    offer_rows = _query(
        "SELECT o.*, s.rating AS seller_rating, s.seller_years AS seller_years, "
        "s.deals_count AS seller_deals, s.official AS seller_official "
        "FROM shop_offers o LEFT JOIN shop_sellers s ON o.seller_id = s.id "
        "WHERE o.product_id=?", (product_id,), fetch=True)
    offers, history = [], {}
    for r in offer_rows:
        o = dict(r)
        oid = o["id"]
        hrows = _query(
            "SELECT price_byn FROM shop_price_history WHERE offer_id=? "
            "ORDER BY ts LIMIT 200", (oid,), fetch=True)
        history[oid] = [h["price_byn"] for h in hrows]
        offers.append(o)
    scored = score_offers(offers, history, profile=profile,
                          product={"title": product.get("title"), "specs": specs},
                          target_price_byn=target_price_byn)
    return {"ok": True, "product": {"id": product_id, "title": product.get("title")},
            "scored": scored}
