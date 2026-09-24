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
  - Kufar ВЫВЕДЕН из реестра по решению владельца (2026-09-16). Старые
    kufar-строки в БД не трогаем: досье/скоринг рендерят их как есть
    (платформа для движка — строка), такт их больше не освежает;
  - Ozon (ozon.by) — ЗАКРЫТ АНТИБОТОМ (живые пробы из песочницы,
    см. докстринг collect_ozon): любой путь → 307-петля (?__rr=1,2 →
    403 abt_data) для честного клиента; с TLS-имперсонацией robots.txt
    → 200, но поисковые API → 403 + JS-челлендж. Каркас: транспортный
    вызов остаётся живым (заработает при egress-решении), отказ честный
    kind:"antibot_blocked";
  - FX fx_rates(): env SHOP_FX_RATES_JSON → свежий кэш system_settings
    (6 ч) → живой egress НБРБ (полный дневной список, periodicity=0;
    точечные /rates/RUB?paramMode=1 отдают 404 — проверено) → резерв
    open.er-api.com (кросс через USD) → устаревший кэш → аварийные
    константы; отказ egress не роняет сбор (FO-007: лог, не молчание);
  - WB фото (#329): image_url строится по формуле basket-{N} с живым
    HEAD-перебором шардов (подробности — у wb_basket_for_vol);
  - catalog.api.onliner.by (#327) — ЖИВ, форма снята живьём 2026-09-24
    (пробы из песочницы исполнителя — хост отвечает без всякого
    домен-allowlist, robots разрешает): цены в prices.price_min/price_max
    (amount строкой, BYN), наличие = prices.offers.count, рейтинг =
    reviews.rating (0..50 → /10) + reviews.count; html_url/full_name —
    как было. ВАЖНО: прежний парсер читал prices.price — такого ключа
    в живой форме НЕТ (все офферы уходили в unscored). Слаг категории
    env SHOP_ONLINER_CATEGORY (legacy, приоритетен) → карта синонимов
    (значения сверены с живым словарём) → живой словарь /schemas
    (страницы по 20, 886 схем на 2026-09-24; дозагрузка по курсору,
    ≤8 страниц за вызов — бюджет таймаутов; кэш kv 7 дней) →
    не нашлось — честный kind:"no_category", слаг наугад не берём;
  - 21vek.by (#328) — ЖИВОЙ robots.txt 2026-09-24: User-agent: *
    Disallow: /search, /api/* и ВСЕ URL с query ("*?*") — поисковая
    поверхность закрыта для честных клиентов, включая Googlebot.
    Дисциплина SHOP-2 (robots уважается) сбор запрещает; каркас отвечает
    честный kind:"robots_disallow_surface". Реализация возможна только
    явным решением владельца отступить от robots-красной линии (#172) —
    вопрос вынесен в отчёт наряда;
  - tm.by (#331) — недоступен из песочницы исполнителя: TLS
    «unexpected eof» на все 4 варианта (https/http × с/без www) —
    площадка обрывает соединения с датацентровых IP. Форма не снята —
    реализация вслепую запрещена нарядом; каркас честно отвечает
    kind:"recon_unreachable", форма снимется первым живым прогоном
    (Render egress или браузер владельца).

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


# ── WB: фото товара (#329) — basket-хост по vol-диапазону ────────────────
# Формула (подтверждена живыми HEAD-пробами 2026-09-24, наряд #329):
#   https://basket-{N}.wbbasket.ru/vol{vol}/part{part}/{id}/images/big/1.webp
# где vol=id//100000, part=id//1000, а basket-{N} НЕ выводится из id —
# номер шарда WB расширяет по мере роста (живая проба: id 546061442 →
# basket-28; id 1274546138 → нет ответа ни на basket-01..40 — шард ещё
# шире либо фото нет). Поэтому перебор (вариант A.2 наряда, рекомендация
# аудита — «надёжнее в долгосрочной перспективе»): HEAD по basket-01..40,
# первый 200 — кэшируем vol→basket (hit 30 дней, miss 12 часов, чтобы
# новые шарды подхватывались). Транспорт — probe_url MCP-web (#329:
# статус без чтения тела, та же дисциплина SSRF/robots/rate-limit).
WB_BASKET_CACHE_KEY = "shop_wb_basket_map"
WB_BASKET_HIT_TTL = 30 * 24 * 3600
WB_BASKET_MISS_TTL = 12 * 3600


def _wb_basket_probe(basket, vol, part, pid):
    """HEAD-проба одной ссылки; True только на HTTP 200."""
    host = f"basket-{basket:02d}" if basket < 10 else f"basket-{basket}"
    url = (f"https://{host}.wbbasket.ru/vol{vol}/part{part}/{pid}"
           "/images/big/1.webp")
    r = FETCH_JSON_FN("probe_url", {"url": url})
    if not r.get("ok"):
        return False
    try:
        return int(r.get("status") or 0) == 200
    except (TypeError, ValueError):
        return False


def _wb_basket_map_read():
    raw = _setting_get(WB_BASKET_CACHE_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _wb_basket_map_write(mapping):
    _setting_set(WB_BASKET_CACHE_KEY, json.dumps(mapping, ensure_ascii=False))


def wb_basket_for_vol(vol, pid=None):
    """Номер basket-хоста для vol-диапазона (None — не найден в диапазоне).

    Кэш в system_settings: {"vol:{vol}": {"basket": N|None, "ts": epoch}}.
    Проба конкретного pid нужна, потому что 200 зависит и от наличия фото
    у товара — но false-negative кэшируется всего на 12ч (miss), так что
    появление фото/нового шарда подхватится при следующем сборе.
    """
    mapping = _wb_basket_map_read() or {}
    entry = mapping.get(f"vol:{vol}")
    now = time.time()
    if entry:
        ttl = WB_BASKET_HIT_TTL if entry.get("basket") is not None else WB_BASKET_MISS_TTL
        if now - (entry.get("ts") or 0) < ttl:
            return entry.get("basket")
    found = None
    if pid is not None:
        part = int(pid) // 1000
        for basket in range(1, 41):
            if _wb_basket_probe(basket, vol, part, int(pid)):
                found = basket
                break
    mapping[f"vol:{vol}"] = {"basket": found, "ts": now}
    _wb_basket_map_write(mapping)
    return found


def wb_image_url(pid):
    """Ссылка на фото WB для id товара (None — шарди не подобран)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    vol, part = pid // 100000, pid // 1000
    basket = wb_basket_for_vol(vol, pid)
    if basket is None:
        return None
    host = f"basket-{basket:02d}" if basket < 10 else f"basket-{basket}"
    return (f"https://{host}.wbbasket.ru/vol{vol}/part{part}/{pid}"
            "/images/big/1.webp")


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
            "image_url": wb_image_url(pid),
        })
    return {"ok": True, "platform": "wb", "url": url, "offers": offers}


# ── Ozon ────────────────────────────────────────────────────────────────
def collect_ozon(query, page=1):
    """Ozon (ozon.by) — поисковый API за антиботом; каркас.

    Живые пробы из песочницы 2026-09-16 (form-истина, не память):
      - честный клиент (urllib/curl, UA браузера): ЛЮБОЙ путь
        www.ozon.by|ozon.ru → 307-петля (?__rr=1 → ?__rr=2 → 403 +
        cookie abt_data) — TLS-фингерпринт-слой антибота;
      - с TLS-имперсонацией (curl_cffi chrome): robots.txt → 200, но
        composer-api / entrypoint-api / mobile / search / sitemap →
        403 + JS-челлендж (cdn2.ozone.ru/s3/abt-challenge) — нужен
        реальный браузерный JS, из датацентра не проходит;
      - api-seller.ozon.ru жив, но требует Client-Id/Api-Key продавца
        и поиск по всему маркетплейсу не умеет (только свои товары).
    Вывод: прямой egress закрыт на уровне JS-челленджа. Транспортный
    вызов ниже оставлен живым: когда появится egress-решение (резидент-
    проки/браузерный контур), сбор начнёт отвечать без правок здесь;
    форма ответа снимется первым же прогоном (сейчас честный
    kind:"api_form_unknown" — парсер вслепую не пишем).
    """
    url = ("https://www.ozon.by/api/composer-api.bx/page/json/v2?url="
           + urllib.parse.quote(f"/search/?text={query}&page={page}", safe=""))
    data = FETCH_JSON_FN("fetch_json", {"url": url})
    _audit("ozon", f"search:{query}", "ok" if data.get("ok") else "refused")
    if not data.get("ok"):
        note = ("антибот Ozon: TLS-фингерпринт (307-петля) + JS-челлендж на "
                "поисковых API; egress-решение — см. приёмку #172")
        base = (data.get("error") or "").strip()
        return {"ok": False, "platform": "ozon", "url": url,
                "error": f"{base} | {note}" if base else note,
                "kind": data.get("kind", "antibot_blocked")}
    return {"ok": False, "platform": "ozon", "url": url,
            "error": "транспорт прошёл, но форма ответа composer-api не снята — "
                     "нужен первый живой прогон с решённым egress",
            "kind": "api_form_unknown"}


# ── Onliner (#327): динамическая категория + живая форма ──────────────
ONLINER_SCHEMAS_KEY = "shop_onliner_schemas"
ONLINER_SCHEMAS_TTL = 7 * 24 * 3600
ONLINER_SCHEMAS_PAGES_PER_CALL = 8   # бюджет таймаутов: 8×3с ≈ 24с/вызов
ONLINER_SCHEMAS_PAGE_CAP = 80
ONLINER_SCHEMAS_URL = "https://catalog.api.onliner.by/schemas?page={n}"

# Карта синонимов (вариант 1 наряда). ЗНАЧЕНИЯ сверены с живым словарём
# /schemas 2026-09-24 (ключ существует, имя подтверждено); при ренейме
# ключа площадкой запись честно деградирует (проверка наличия в словаре).
# Расширение — новой записью с проверкой по живому словарю, не по памяти.
ONLINER_KEYWORD_MAP = {
    "телефон": "mobile", "смартфон": "mobile", "iphone": "mobile",
    "android": "mobile", "ноутбук": "notebook", "наушники": "headphones",
    "кофеварка": "coffee", "кофемашина": "coffee",
    "стиральная": "washingmachine", "пылесос": "vacuumcleaner",
    "холодильник": "refrigerator", "телевизор": "tv",
    "газонокосилка": "mowers",
}


def _norm_words(s):
    s = (s or "").lower().replace("ё", "е")
    import re as _re
    return _re.findall(r"[a-zа-я0-9]+", s)


def _schema_match_score(query_words, schema):
    """Скор совпадения запроса со схемой (0 — не совпадает).

    Живая форма имён: «Мобильные телефоны», «Газонокосилки» — совпадение
    по общему префиксу слов (стеммер не нужен при пороге min(len)-2);
    бонус слову в начале имени; штраф совпадению в хвосте «…для X»
    (аксессуары: «Аккумуляторы для телефонов» не должны выигрывать у
    «Мобильные телефоны»).
    """
    name_words = _norm_words(schema.get("name") or "")
    best = 0
    for_query = "для" in name_words
    for w in query_words:
        if len(w) < 4:
            continue
        for pos, v in enumerate(name_words):
            c = len(__import__("os").path.commonprefix([w, v]))
            if c >= max(4, min(len(w), len(v)) - 2):
                score = c + max(0, 3 - pos)
                if for_query and pos > name_words.index("для"):
                    score -= 4
                best = max(best, score)
    return best


def _onliner_schemas_cache_read():
    raw = _setting_get(ONLINER_SCHEMAS_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("schemas"), list):
        return data
    return None


def _onliner_schemas_cache_write(data):
    _setting_set(ONLINER_SCHEMAS_KEY, json.dumps(data, ensure_ascii=False))


def onliner_resolve_category(query, max_pages=None):
    """Слаг категории Onliner для произвольного запроса (None — не нашли).

    Порядок: env SHOP_ONLINER_CATEGORY (legacy, приоритетен) → карта
    синонимов с проверкой по словарю → живой словарь /schemas
    (дозагрузка по курсору ≤N страниц за вызов, персист между вызовами,
    кэш 7 дней после полной выгрузки) → ничего не нашли — None.
    Никогда не возвращает слаг, которого нет в живом словаре.
    """
    env_cat = os.environ.get("SHOP_ONLINER_CATEGORY", "").strip()
    if env_cat:
        return env_cat

    cache = _onliner_schemas_cache_read() or {"schemas": [], "next_page": 1, "complete": False, "ts": 0}
    schemas = [s for s in cache.get("schemas") or []
               if isinstance(s, dict) and s.get("key")]
    fresh = cache.get("complete") and (time.time() - (cache.get("ts") or 0)) < ONLINER_SCHEMAS_TTL

    qwords = _norm_words(query)
    # 1) карта синонимов — только если слаг живой в словаре
    known_keys = {s["key"] for s in schemas} if fresh else None
    if fresh and known_keys:
        for w in qwords:
            for kw, slug in ONLINER_KEYWORD_MAP.items():
                if w.startswith(kw) and slug in known_keys:
                    return slug

    # 2) совпадение по словарю: свежий полный — сразу; неполный —
    #    ищем в накопленном, затем дозагружаем ≤N страниц за вызов
    if not fresh:
        budget = max_pages or ONLINER_SCHEMAS_PAGES_PER_CALL
        fetched_any = False
        page = cache.get("next_page") or 1
        while page <= ONLINER_SCHEMAS_PAGE_CAP and budget > 0:
            r = FETCH_JSON_FN("fetch_json", {"url": ONLINER_SCHEMAS_URL.format(n=page)})
            if not r.get("ok"):
                log.warning("onliner /schemas стр.%s не получена: %s", page, r.get("error"))
                break
            chunk = ((r.get("data") or {}).get("schemas")) or []
            schemas.extend(s for s in chunk if isinstance(s, dict) and s.get("key"))
            fetched_any = True
            page += 1
            budget -= 1
            if not chunk:
                cache["complete"] = True
                break
        cache["schemas"] = schemas
        cache["next_page"] = page
        if fetched_any or cache.get("complete"):
            cache["ts"] = time.time()
            _onliner_schemas_cache_write(cache)

    known_keys = {s["key"] for s in schemas}
    # карта по накопленному словарю (даже если он ещё неполный)
    for w in qwords:
        for kw, slug in ONLINER_KEYWORD_MAP.items():
            if w.startswith(kw) and slug in known_keys:
                return slug
    # 3) нечёткое совпадение по именам словаря (порог 7)
    best, best_score = None, 0
    for s in schemas:
        sc = _schema_match_score(qwords, s)
        if sc > best_score:
            best, best_score = s["key"], sc
    if best and best_score >= 7:
        return best
    if best:
        log.info("onliner категория для %r не уверена (score=%s) — честный отказ", query, best_score)
    return None


def collect_onliner(query, page=1):
    """Каталог Onliner — ЖИВАЯ форма (пробы 2026-09-24, наряд #327).

    products[].prices: price_min/price_max {amount, currency}, offers.count;
    reviews: rating 0..50 + count. Слаг категории — динамически
    (onliner_resolve_category); не нашли — честный no_category, не слаг
    наугад. Парсер оборонительный: расхождение формы → api_form_mismatch.
    """
    category = onliner_resolve_category(query)
    if not category:
        return {"ok": False, "platform": "onliner",
                "error": f"категория Onliner для «{query}» не определена по живому "
                         "словарю /schemas — слаг наугад не подставляем",
                "kind": "no_category"}
    url = ("https://catalog.api.onliner.by/search/" + urllib.parse.quote(category)
           + "?" + urllib.parse.urlencode({"query": query, "products-page": str(page)}))
    data = FETCH_JSON_FN("fetch_json", {"url": url})
    _audit("onliner", f"search:{query} cat:{category}", "ok" if data.get("ok") else "refused")
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
        prices = p.get("prices") or {}
        price = prices.get("price_min") or {}
        amount = _num(price.get("amount"))
        currency = (price.get("currency") or "BYN").upper()
        price_byn = to_byn(amount, currency, rates) if currency != "BYN" else amount
        offers_count = _num((prices.get("offers") or {}).get("count")) or 0
        reviews = p.get("reviews") or {}
        rating = _num(reviews.get("rating"))
        rating = rating / 10.0 if rating is not None else None  # 0..50 → 0..5
        offers.append({
            "platform": "onliner",
            "platform_code": str(key),
            "url": canonical_url(p.get("html_url") or f"https://catalog.onliner.by/{key}"),
            "title": p.get("full_name") or p.get("name"),
            "price_byn": price_byn,
            "old_price_byn": None,
            "in_stock": 1 if offers_count else 0,
            "rating": rating,
            "reviews_count": int(_num(reviews.get("count")) or 0),
            "seller_name": None, "seller_platform_code": None,
            "seller_rating": None, "seller_deals": None, "seller_official": None,
        })
    return {"ok": True, "platform": "onliner", "url": url, "category": category,
            "offers": offers}


# ── 21vek (#328): robots запрещает поисковую поверхность ─────────────
def collect_21vek(query):
    """Живой robots.txt 2026-09-24 (наряд #328): User-agent: * запрещает
    /search, /api/* и ВСЕ URL с query (*?*) — поисковая поверхность
    21vek закрыта для честных клиентов. Красная линия SHOP-2 (#172):
    robots уважается — сбор запрещён без явного решения владельца.
    Вопрос вынесен в отчёт наряда: отступление от robots меняет
    дисциплину сбора всего офиса, единолично не принимается.
    """
    return {"ok": False, "platform": "21vek",
            "error": "robots.txt 21vek запрещает /search, /api/* и все URL "
                     "с query (*?*) — сбор поисковой поверхности нарушает "
                     "дисциплину SHOP-2; нужно явное решение владельца",
            "kind": "robots_disallow_surface"}


# ── tm.by (#331): площадка недоступна для разведки ───────────────────
def collect_tmby(query):
    """Живые пробы 2026-09-24 (наряд #331): TLS «unexpected eof» на все
    4 варианта (https/http × tm.by/www.tm.by) — площадка обрывает
    соединения с датацентровых IP (фильтрация на её стороне); DNS жив.
    Форма поиска не снята — реализация вслепую запрещена нарядом
    («сначала разведка, потом код», тот же принцип, что 21vek).
    Форма снимется первым живым прогоном (Render egress может отличаться)
    или из браузера владельца — тогда парсер добавится точечным PR.
    """
    return {"ok": False, "platform": "tmby",
            "error": "tm.by недоступен из песочницы (TLS unexpected eof на все "
                     "варианты), форма поиска не снята — каркас ждёт живого "
                     "прогона/разведки владельца",
            "kind": "recon_unreachable"}


COLLECTORS = {
    "wb": collect_wb,
    "ozon": collect_ozon,
    "onliner": collect_onliner,
    "21vek": collect_21vek,
    "tmby": collect_tmby,
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
                "seller_id=?, image_url=COALESCE(?, image_url), "
                "fetched_at=datetime('now') WHERE id=?",
                (o["url"], o.get("price_byn"), o.get("old_price_byn"),
                 o.get("in_stock"), o.get("installment_ok"), o.get("rating"),
                 o.get("reviews_count"), sid, o.get("image_url"), oid))
        else:
            _query(
                "INSERT INTO shop_offers (product_id, platform, platform_code, url, "
                "price_byn, old_price_byn, in_stock, installment_ok, rating, "
                "reviews_count, seller_id, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (product_id, platform, o["platform_code"], o["url"],
                 o.get("price_byn"), o.get("old_price_byn"), o.get("in_stock"),
                 o.get("installment_ok"), o.get("rating"), o.get("reviews_count"), sid,
                 o.get("image_url")))
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
