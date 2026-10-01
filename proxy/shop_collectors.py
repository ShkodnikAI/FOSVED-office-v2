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
  - 21vek.by (#328/#406) — красная линия robots СНЯТА (ADR-0011,
    решение владельца 2026-09-27). Живой сборщик: пробует страницу поиска
    каждый раз; товары в SSR не серверены (SPA, gate session-bound) —
    честный kind:"recon_unreachable" с диагнозом до первого живого
    прогона с браузерным контекстом;
  - tm.by (#331) — недоступен из песочницы исполнителя: TLS
    «unexpected eof» на все 4 варианта (https/http × с/без www) —
    площадка обрывает соединения с датацентровых IP. Форма не снята —
    реализация вслепую запрещена нарядом; каркас честно отвечает
    kind:"recon_unreachable", форма снимется первым живым прогоном
    (Render egress или браузер владельца);
  - батч-2 источников (2026-09-24, наряды #335/#337/#338/#339 — живая
    разведка из песочницы, robots проверен ПЕРВЫМ — красная линия SHOP-2):
    7745.by (#335) — robots запрещает /search, но /catalog?search=
    разрешён; однако тело сайта 403 с датацентровых IP (/, /catalog,
    /catalog?search= — 403 при роботс/sitemap 200: динамика закрыта
    GeoIP-фильтром, статика отдаётся). Форма не снята → честный
    kind:"recon_unreachable";
    shop.by (#337) — 403 на robots.txt И на сайт (HTTP/2 + браузерный
    UA тоже 403) — robots unverifiable → консервативный отказ,
    kind:"recon_unreachable";
    tomas.by (#338/#406) — robots-правило снято (ADR-0011); живой
    сборщик: пробует /search/<запрос>, антибот-стена «Проверка
    безопасности» (recaptcha) → честный kind:"antibot_blocked";
    unishop.by (#339/#406) — капча-стена reagate (антибот на весь
    сайт с датацентровых IP) → kind:"antibot_blocked"; браузерный
    контур — решение владельца (robots-правило снято ADR-0011);
  - Яндекс.Маркет (#340) — ЕДИНСТВЕННЫЙ из батча с официальным API:
    контентный API для покупателей (базовый тариф 100 запросов/сутки).
    Регистрация ключа — шаг владельца (A.1 наряда); сам хост
    api.content.market.yandex.ru из песочницы рвёт соединения
    (RemoteDisconnected — как tm.by), форма снимется первым живым
    прогоном с реальным ключом. Реализовано ПОЛНОСТЬЮ, но честно:
    без ключа — kind:"config_missing"; дневной счётчик 100/сутки в
    kv + кэш повторов 5 мин (лимит не жжётся); парсер оборонительный
    (несколько известных форм списка офферов; расхождение →
    kind:"api_form_mismatch"). Транспорт — новая тулза
    fetch_api_json в mcp_servers/web (Bearer-токен; robots к
    авторизованным API не применяется по дизайну — см. докстринг
    сервера).

Все парсеры оборонительные: нет ожидаемых ключей → честный отказ с kind,
ничего не падает. Политика FO-007: except-блоки не молчат — logging.warning.
"""
import hashlib
import json
import logging
import os
import re
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
    """HEAD-проба одной ссылки; True только на HTTP 200.

    #408 A.2: проба — прямой HEAD в ЭТОМ процессе (timeout 5 с), не новый
    web-MCP subprocess на каждую пробу (было: до 40 процессов на vol,
    до ~4000 на сбор). SSRF-гейт по построению: host — константа
    *.wbbasket.ru, vol/part/pid — только целые числа, пользовательских
    строк в URL нет."""
    host = f"basket-{basket:02d}" if basket < 10 else f"basket-{basket}"
    url = (f"https://{host}.wbbasket.ru/vol{vol}/part{part}/{pid}"
           "/images/big/1.webp")
    return _wb_direct_probe(url)


def _wb_direct_probe(url):
    """Прямой HEAD без запуска процесса (#408 A.2). Точка подмены в тестах."""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "fosved-shop/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
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


def wb_basket_for_vol(vol, pid=None, deadline=None):
    """Номер basket-хоста для vol-диапазона (None — не найден в диапазоне).

    Кэш в system_settings: {"vol:{vol}": {"basket": N|None, "ts": epoch}}.
    Проба конкретного pid нужна, потому что 200 зависит и от наличия фото
    у товара — но false-negative кэшируется всего на 12ч (miss), так что
    появление фото/нового шарда подхватится при следующем сборе.

    #408 A.2: перебор начинается с корзины БЛИЖАЙШЕГО кэшированного vol
    (у близких vol одна корзина), не с basket-01. При исчерпании бюджета
    (deadline) промах НЕ кэшируется — подбор продолжится при следующем
    сборе, ложный miss на 12ч не записывается.
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
        # соседи из кэша: ближайшие vol с известной корзиной — до 3 кандидатов
        neighbors = sorted(
            (abs(int(key[4:]) - vol), val["basket"])
            for key, val in mapping.items()
            if key.startswith("vol:") and isinstance(key[4:], str)
            and key[4:].isdigit() and val.get("basket") is not None
        )[:3]
        tried = []
        order = [b for _, b in neighbors] + [b for b in range(1, 41)]
        for basket in order:
            if basket in tried:
                continue
            tried.append(basket)
            if deadline is not None and time.monotonic() > deadline:
                return None  # бюджет исчерпан — без кэширования промаха
            if _wb_basket_probe(basket, vol, part, int(pid)):
                found = basket
                break
    mapping[f"vol:{vol}"] = {"basket": found, "ts": now}
    _wb_basket_map_write(mapping)
    return found


def wb_image_url(pid, deadline=None):
    """Ссылка на фото WB для id товара (None — шарди не подобран).

    deadline (time.monotonic) — общий бюджет подбора фото (#408 A.1);
    исчерпан — None без кэширования промаха."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    vol, part = pid // 100000, pid // 1000
    basket = wb_basket_for_vol(vol, pid, deadline=deadline)
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
            # #408 A.1: фото НЕ в критическом пути сбора — подбираются после
            # сохранения офферов, топ-N с бюджетом (см. _wb_fill_images).
            # Раньше wb_image_url(pid) в цикле по ~100 товарам давал до ~4000
            # HEAD-проб (процесс на пробу) ДО возврата офферов — сбор срывал
            # 90-секундное ожидание Яны, офферы не сохранялись вовсе.
            "image_url": None,
        })
    return {"ok": True, "platform": "wb", "url": url, "offers": offers}


# ── Ozon ────────────────────────────────────────────────────────────────
def collect_ozon(query, page=1):
    """Ozon (ozon.by) — поисковый API за антиботом; каркас.

    Наряд #334 (2026-09-24): метод подтверждён двумя независимыми
    реализациями — headless Chromium проходит челлендж один раз (~12 с),
    дальше JSON из внутреннего composer-api. Контур реализован в
    proxy/ozon_headless.py (Playwright по требованию, сессия/cookies с
    TTL 6 ч в kv, браузер закрывается всегда), включается флагом
    SHOP_OZON_HEADLESS=1 — выключен по умолчанию, т.к. A.1 наряда
    требует реального замера памяти на Render free (512 MB) ДО включения.

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
    Флаг выключен → транспортный вызов ниже жив как прежде: честный
    kind:"antibot_blocked"/"api_form_unknown".
    """
    from proxy.ozon_headless import flag_enabled
    if flag_enabled():
        from proxy.ozon_headless import collect_ozon_headless
        res = collect_ozon_headless(query, page)
        if res.get("ok"):
            return res
        if res.get("kind") == "api_form_unknown":
            return res
        # браузерный контур недоступен — падаем на честный транспортный отказ
        log.warning("ozon headless недоступен (%s) — честный fallback на транспорт",
                    res.get("kind"))
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
# Наряд #437 A.2: бытовая техника первой необходимости — слаги сверены
# с живым словарём /schemas 2026-09-30 (887 схем, 45 страниц снято
# целиком; имена подтверждены: iron=«Утюги», steamcleaner=«Пароочистители
# и отпариватели», kettles=«Чайники», microvawe=«Микроволновые печи» —
# слаг самой площадки, не наша опечатка). Ключ — основа слова: матчится
# startswith (утюг/утюги/утюгом).
ONLINER_KEYWORD_MAP = {
    "телефон": "mobile", "смартфон": "mobile", "iphone": "mobile",
    "android": "mobile", "ноутбук": "notebook", "наушник": "headphones",
    "кофеварка": "coffee", "кофемашина": "coffee",
    "стиральная": "washingmachine", "пылесос": "vacuumcleaner",
    "холодильник": "refrigerator", "телевизор": "tv",
    "газонокосилка": "mowers",
    # #437 A.2 — бытовая техника/электроника первой необходимости
    "утюг": "iron", "отпаривател": "steamcleaner",
    "пароочистител": "steamcleaner",
    "чайник": "kettles", "электрочайник": "kettle",
    "микроволнов": "microvawe", "блендер": "blender",
    "тостер": "toaster", "миксер": "mixer",
    "мультиварк": "multicooker", "мясорубк": "meatgrinder",
    "посудомоечн": "dishwasher", "плита": "cooker",
    "обогревател": "heater", "увлажнител": "humidifier",
    "водонагревател": "waterheater", "робот": "robotcleaner",
    "планшет": "tabletpc", "монитор": "display",
}

# Слова-маски для главного предмета запроса (#437 A.1): глаголы покупки,
# оценочные прилагательные, вопросительные слова. ТОЛЬКО точные слова —
# основы опасны (основа «куп» съела бы «купальник», «сам» — «самовар»).
_SUBJECT_STOPWORDS = {
    "купить", "куплю", "купим", "подбери", "подобрать", "подбирал",
    "ищу", "искал", "искала", "нужен", "нужна", "нужно", "нужны",
    "хочу", "хотел", "хотела", "выбери", "выбрать",
    "лучший", "лучшая", "лучшие", "лучшее",
    "самый", "самая", "самые", "самое",
    "какой", "какая", "какие", "где", "порекомендуй", "рекомендуешь",
    "хороший", "хорошая", "хорошее", "качественный", "качественная",
    # местоимения/предлоги между маской и предметом: «подбери мне утюг»
    "мне", "меня", "для", "пожалуйста",
}


def _main_subject_word(query_words):
    """Главный предмет запроса (#437 A.1) — первое значимое слово.

    Ведущие слова-маски (купить/подбери/лучший…) пропускаются: в
    «лучший утюг с паром» предмет — «утюг». Ничего не нашли — None
    (запрос из одних масок — приоритет главного предмета не применяется).
    """
    for w in query_words:
        if w not in _SUBJECT_STOPWORDS:
            return w
    return None


# Бонус главному предмету в нечётком скоринге (#437 A.1). Фактура 2026-09-30:
# «утюг» (4 буквы) и «паром» против «Пароочистители» давали равные 7 очков,
# побеждала категория, встреченная раньше. Совпадение имени схемы с главным
# предметом весит больше описательных слов запроса.
MAIN_SUBJECT_BONUS = 10


def _words_prefix_hit(a, b):
    """Словоформы: общий префикс по порогу _schema_match_score."""
    if not a or not b:
        return False
    c = len(os.path.commonprefix([a, b]))
    return c >= max(4, min(len(a), len(b)) - 2)


def relevance_mismatch(query, offers, min_rate=None):
    """Проверка соответствия выдачи запросу (#437 A.3).

    Считает долю предложений, в названии которых есть главный предмет
    запроса (с учётом словоформ). Ниже порога — dict с предметом и долей
    (досье покажет «найдено не то» и не даст вердикта «Купить»); при
    нормальной доле или без главного предмета — None.
    Порог: env SHOP_RELEVANCE_MIN, дефолт 0.3 — примеси аксессуаров
    («подошвы для утюгов» рядом с утюгами) допустимы, полная нерелевантность
    («утюг» → 30 отпаривателей, hit 0.0) — нет.
    """
    subject = _main_subject_word(_norm_words(query))
    if not subject or not offers:
        return None
    if min_rate is None:
        try:
            min_rate = float(os.environ.get("SHOP_RELEVANCE_MIN", "0.3"))
        except ValueError:
            min_rate = 0.3
    hits = 0
    for o in offers:
        title_words = _norm_words((o.get("title") or ""))
        if any(_words_prefix_hit(tw, subject) for tw in title_words):
            hits += 1
    rate = hits / len(offers)
    if rate >= min_rate:
        return None
    return {"subject": subject, "hit_rate": round(rate, 2),
            "min_rate": round(min_rate, 2)}


def onliner_category_name(slug):
    """Человекочитаемое имя категории по слагу из накопленного словаря
    схем (без сети; #437 A.3 — сообщение «найдено не то: <категория>»).
    Нет в кеше — сам слаг, не выдумываем имя."""
    if not slug:
        return slug
    cache = _onliner_schemas_cache_read() or {}
    for s in cache.get("schemas") or []:
        if isinstance(s, dict) and s.get("key") == slug:
            return s.get("name") or slug
    return slug


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


def onliner_warm_catalog(max_pages=None):
    """#429 A.3: фоновый прогрев каталога схем Onliner.

    Догружает словарь /schemas до complete — до ONLINER_SCHEMAS_PAGE_CAP
    страниц за вызов. Запрос владельца больше не расходует бюджет дозагрузки
    (onliner_resolve_category при неполном каталоге читает только накопленное
    + карту синонимов). Кэш персистный (system_settings — постоянный диск),
    TTL 7 дней после полной выгрузки: свежий полный каталог — мгновенный
    no-op (0 сетевых вызовов). Вызывается из entrypoint.sh (фон при старте)
    и слота onliner-warm (dept/schedules.mlog).
    """
    cache = _onliner_schemas_cache_read() or {"schemas": [], "next_page": 1, "complete": False, "ts": 0}
    schemas = [s for s in cache.get("schemas") or []
               if isinstance(s, dict) and s.get("key")]
    if cache.get("complete") and (time.time() - (cache.get("ts") or 0)) < ONLINER_SCHEMAS_TTL:
        return {"ok": True, "complete": True, "fresh": True,
                "total_schemas": len(schemas), "pages_fetched": 0, "added": 0}
    budget = max_pages or ONLINER_SCHEMAS_PAGE_CAP
    page = cache.get("next_page") or 1
    known = {s["key"] for s in schemas}
    added = 0
    fetched = 0
    while page <= ONLINER_SCHEMAS_PAGE_CAP and budget > 0:
        r = FETCH_JSON_FN("fetch_json", {"url": ONLINER_SCHEMAS_URL.format(n=page)})
        if not r.get("ok"):
            log.warning("onliner warm: /schemas стр.%s не получена: %s", page, r.get("error"))
            break
        chunk = ((r.get("data") or {}).get("schemas")) or []
        for s in chunk:
            if isinstance(s, dict) and s.get("key") and s["key"] not in known:
                known.add(s["key"])
                schemas.append(s)
                added += 1
        fetched += 1
        page += 1
        budget -= 1
        if not chunk:
            cache["complete"] = True
            break
    cache["schemas"] = schemas
    cache["next_page"] = page
    if fetched or cache.get("complete"):
        cache["ts"] = time.time()
        _onliner_schemas_cache_write(cache)
    return {"ok": True, "complete": bool(cache.get("complete")), "fresh": False,
            "total_schemas": len(schemas), "pages_fetched": fetched,
            "added": added, "next_page": page}


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
    # #437 A.1: главный предмет проверяется по карте ПЕРВЫМ — описательные
    # слова запроса не могут увести категорию от предмета
    subject = _main_subject_word(qwords)
    ordered_words = ([subject] if subject else []) + \
                    [w for w in qwords if w != subject]
    # 1) карта синонимов — только если слаг живой в словаре
    known_keys = {s["key"] for s in schemas} if fresh else None
    if fresh and known_keys:
        for w in ordered_words:
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
    # карта по накопленному словарю (даже если он ещё неполный),
    # главный предмет — первым (#437 A.1)
    for w in ordered_words:
        for kw, slug in ONLINER_KEYWORD_MAP.items():
            if w.startswith(kw) and slug in known_keys:
                return slug
    # 3) нечёткое совпадение по именам словаря (порог 7); #437 A.1:
    # совпадение имени схемы с ГЛАВНЫМ предметом весит больше описательных
    # слов — при равенстве очков побеждает категория предмета, а не первая
    # встреченная с тем же баллом за слово-признак
    best, best_score = None, 0
    for s in schemas:
        sc = _schema_match_score(qwords, s)
        if subject and len(subject) >= 4:
            name_words = _norm_words(s.get("name") or "")
            # len(nw) >= len(subject) - 1: имя — грамматическая форма
            # предмета («Утюги» для «утюг»), а не вложенный корень
            # составного слова («Семена трав, газон» для «газонокосилка»)
            if any(_words_prefix_hit(nw, subject) and len(nw) >= len(subject) - 1
                   for nw in name_words):
                sc += MAIN_SUBJECT_BONUS
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
    reviews: rating 0..50 + count; photo: products[].images.header (#438 A.2,
    снято с живого ответа 2026-09-30). Слаг категории — динамически
    (onliner_resolve_category); не нашли — честный no_category, не слаг
    наугад. Парсер оборонительный: расхождение формы → api_form_mismatch.

    Правило для будущих сборщиков (21vek, Tomas.by, снабженец — #438 A.4):
    image_url — обязательное поле оффера, ЕСЛИ площадка отдаёт фото;
    нет фото — None, URL не выдумываем.
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
            # #438 A.2: фото товара — products[].images.header, снято с живого
            # ответа /search/iron 2026-09-30 (URL imgproxy.onliner.by); поле
            # необязательное — нет photo, нет фото, не угадываем
            "image_url": ((p.get("images") or {}).get("header")
                          if isinstance(p.get("images"), dict)
                          and str((p.get("images") or {}).get("header") or "")
                          .startswith(("http://", "https://")) else None),
            "seller_name": None, "seller_platform_code": None,
            "seller_rating": None, "seller_deals": None, "seller_official": None,
        })
    return {"ok": True, "platform": "onliner", "url": url, "category": category,
            "offers": offers}


# ── батч-2 источников (#335/#337/#338/#339, 2026-09-24) ──────────────
def collect_7745(query, page=1):
    """7745.by — живая разведка 2026-09-24 (наряд #335).

    robots.txt (200): Disallow /search — но /catalog?search= НЕ запрещён
    (проверено по всем Disallow-паттернам) — путь был честный. Однако
    тело сайта отдаёт 403 с датацентровых IP: /, /catalog,
    /catalog?search=смартфон (URL-encoded) — 403, при том что
    robots.txt и sitemap.xml (статика) — 200. Динамика закрыта
    GeoIP-фильтром. Форма не снята — реализация вслепую запрещена
    нарядом; каркас ждёт живого прогона с белого egress (Render может
    отличаться) или браузера владельца.
    """
    return {"ok": False, "platform": "7745",
            "error": "7745.by отдаёт 403 на / и /catalog?search= с датацентровых "
                     "IP (robots/sitemap при этом 200 — GeoIP-фильтр динамики); "
                     "форма поиска не снята — каркас ждёт живого прогона",
            "kind": "recon_unreachable"}


def collect_shopby(query, page=1):
    """Shop.by — живая разведка 2026-09-24 (наряд #337).

    robots.txt → 403 (и честным UA, и браузерным, и curl --http2),
    сайт тоже 403 на всё. Robots unverifiable — консервативный отказ
    (не можем подтвердить разрешение — не собираем; красная линия
    SHOP-2). Форма снимется первым живым прогоном с белого egress.
    """
    return {"ok": False, "platform": "shopby",
            "error": "shop.by отдаёт 403 на robots.txt и на сайт с датацентровых "
                     "IP (HTTP/2 + браузерный UA тоже 403) — robots unverifiable, "
                     "консервативный отказ по красной линии SHOP-2",
            "kind": "recon_unreachable"}


def collect_tomas(query, page=1, region="minsk"):
    """Tomas.by — живая попытка сбора (#406, ADR-0011: красная линия robots
    снята решением владельца 2026-09-27; раньше #338: robots запрещал *?*,
    */poisk/, */search/ — теперь правило не является основанием отказа).

    Форма: https://tomas.by/search/<запрос> (региональные поддомены —
    параметр region, дефолт minsk → tomas.by). Продавец-участник агрегатора —
    в seller_name (для всех офферов «Tomas.by» ставить нельзя).
    Живая разведка 2026-09-27 из песочницы: и /, и /search/ отдают страницу
    «Проверка безопасности» с recaptcha (антибот-стена для датацентровых IP) —
    сборщик пробует реальную страницу каждый раз: если egress прода отличается
    (или антибот смягчается) — витрина подхватится без правки кода; иначе
    честный отказ с диагнозом. Транспорт — SHOP-2 (web-MCP: SSRF/rate-limit/
    кэш), A.5 наряда соблюдён.
    """
    host = "tomas.by" if region in ("", "minsk") else f"{region}.tomas.by"
    url = f"https://{host}/search/" + urllib.parse.quote(query)
    page_res = FETCH_JSON_FN("fetch_page", {"url": url, "max_chars": 120000})
    _audit("tomas", f"search:{query} reg:{region}",
           "ok" if page_res.get("ok") else "refused")
    if not page_res.get("ok"):
        return {"ok": False, "platform": "tomas", "error": page_res.get("error"),
                "kind": page_res.get("kind", "transport"), "url": url}
    html = str(page_res.get("content") or "")
    low = html.lower()
    if "проверка безопасности" in low or "recaptcha" in low or "reagate" in low:
        return {"ok": False, "platform": "tomas", "url": url,
                "error": "Tomas.by отдаёт антибот-стену («Проверка безопасности», "
                         "recaptcha) — живая проба 2026-09-27 с датацентрового "
                         "egress; прод может отличаться — прогон через /shop/diagnose",
                "kind": "antibot_blocked"}
    offers = _parse_tomas_html(html, url)
    if offers:
        return {"ok": True, "platform": "tomas", "url": url, "offers": offers}
    return {"ok": False, "platform": "tomas", "url": url,
            "error": "страница получена, но товарных карточек в HTML нет "
                     "(форма вернулась антиботу или изменилась) — разбор "
                     "оборонительный, слаги наугад не подставляем",
            "kind": "api_form_mismatch"}


def _parse_tomas_html(html, base_url):
    """Оборонительный разбор товарных карточек Tomas.by (schema.org Product).

    Работает только с реальными данными страницы: JSON-LD Product /
    ItemList. Нет карточек — пустой список (вызывающий код отдаст честный
    отказ, не выдумку)."""
    def _name_of(x):
        # schema.org: brand/seller могут быть строкой ИЛИ {"name": "..."}
        if isinstance(x, dict):
            return x.get("name")
        return x

    offers = []
    for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                        html, re.S | re.I):
        try:
            data = json.loads(m.strip())
        except ValueError:
            continue
        items = data.get("itemListElement") if isinstance(data, dict) else None
        candidates = items or ([data] if isinstance(data, dict) else [])
        for it in candidates:
            if not isinstance(it, dict):
                continue
            node = it.get("item") if isinstance(it.get("item"), dict) else it
            if (node.get("@type") or "").lower() not in ("product", ""):
                continue
            name = node.get("name")
            offer = node.get("offers") or {}
            price = _num(offer.get("price") if isinstance(offer, dict) else None)
            if not name or price is None:
                continue
            page_url = offer.get("url") or node.get("url") or it.get("url") or base_url
            offers.append({
                "platform": "tomas",
                "platform_code": str(node.get("sku") or node.get("gtin13") or name)[:64],
                "url": canonical_url(str(page_url)),
                "title": str(name)[:200],
                "price_byn": price,
                "old_price_byn": None,
                "in_stock": 0 if "outofstock" in str(offer.get("availability", "")).lower() else 1,
                "rating": None, "reviews_count": 0,
                "seller_name": _name_of(node.get("brand")) or _name_of(offer.get("seller")) or None,
                "seller_platform_code": None,
                "seller_rating": None, "seller_deals": None, "seller_official": None,
            })
    return offers


def collect_unishop(query, page=1):
    """UniShop.by — живой robots.txt + живая проба 2026-09-24 (наряд #339).

    robots.txt (200): Disallow /search (с ADR-0011 правило снято — не
    основание отказа). Реальная причина отказа — живая проба /: капча-стена
    reagate (обязательное поле reagate_captcha_value) — антибот на весь сайт
    с датацентровых IP; браузерный контур ждёт решения владельца (#406).
    """
    return {"ok": False, "platform": "unishop",
            "error": "UniShop.by закрыт капчей reagate (антибот на весь сайт с "
                     "датацентровых IP) — нужен браузерный контур, решение "
                     "владельца (см. ADR-0011)",
            "kind": "antibot_blocked"}


# ── Яндекс.Маркет (#340): официальный контентный API ─────────────────
YM_API_BASE = "https://api.content.market.yandex.ru"
YM_API_VERSION = "v3.1.0"     # версия по официальной документации; живой
#                              прогон с реальным ключом подтвердит/поправит
YM_DAILY_LIMIT = 100          # базовый тариф контентного API (наряд #340)
YM_COUNTER_KEY = "shop_ym_counter"
YM_CACHE_TTL = 300            # 5 мин — повторные одинаковые запросы не жгут лимит


def _ym_counter_read():
    """Дневной счётчик (kv system_settings): авто-сброс в 00:00 UTC."""
    raw = _setting_get(YM_COUNTER_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if not isinstance(data, dict) or data.get("date") != today:
        data = {"date": today, "count": 0}
    return data


def _ym_counter_bump(n=1):
    data = _ym_counter_read()
    data["count"] = int(data.get("count") or 0) + n
    _setting_set(YM_COUNTER_KEY, json.dumps(data))
    return data["count"]


def _ym_offers_from(body, rates):
    """Оборонительный парсер: список офферов из нескольких известных форм.

    Живой формат снимется первым прогоном с реальным ключом (хост из
    песочницы недоступен — RemoteDisconnected, как tm.by). Известные
    по документации формы: result.offers / result.items / offers /
    items. Оффер: цена в price.value|price.amount|price (валюта
    price.currency|price.currencyCode, дефолт RUB — Маркет RU/BY),
    название name|fullName, ссылка url|link, продавец
    seller.name|shopInfo.name, рейтинг rating 0..5, отзывы
    reviewsCount|feedbacksCount. Отсутствие списка → None (вверху
    решат как api_form_mismatch).
    """
    items = None
    for path in (("result", "offers"), ("result", "items"), ("offers",), ("items",)):
        node = body
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                node = None
                break
        if isinstance(node, list):
            items = node
            break
    if items is None:
        return None
    offers = []
    for it in items:
        if not isinstance(it, dict):
            continue
        pr = it.get("price")
        amount = None
        currency = "RUB"
        if isinstance(pr, dict):
            amount = _num(pr.get("value"))
            if amount is None:
                amount = _num(pr.get("amount"))
            currency = str(pr.get("currency") or pr.get("currencyCode") or "RUB").upper()
        elif pr is not None:
            amount = _num(pr)
        price_byn = to_byn(amount, currency, rates) if currency != "BYN" else amount
        seller = it.get("seller") if isinstance(it.get("seller"), dict) else {}
        shop = it.get("shopInfo") if isinstance(it.get("shopInfo"), dict) else {}
        stock = it.get("stockState")
        in_stock = 1  # форма неизвестна — дефолт «доступно» (не фейк-нуль)
        if isinstance(stock, dict) and stock.get("inStock") is not None:
            in_stock = 1 if _num(stock.get("inStock")) else 0
        pid = it.get("id") or it.get("offerId")
        if pid is None:
            continue
        rating = _num(it.get("rating"))
        if rating is not None and rating > 5:
            rating = rating / 10.0 if rating <= 50 else None
        offers.append({
            "platform": "ym",
            "platform_code": str(pid),
            "url": canonical_url(it.get("url") or it.get("link")
                                 or f"https://market.yandex.ru/product--/{pid}"),
            "title": it.get("fullName") or it.get("name") or it.get("text"),
            "price_byn": price_byn,
            "old_price_byn": None,
            "in_stock": in_stock,
            "rating": rating,
            "reviews_count": int(_num(it.get("reviewsCount")) or _num(it.get("feedbacksCount")) or 0),
            "seller_name": seller.get("name") or shop.get("name"),
            "seller_platform_code": str(seller.get("id")) if seller.get("id") else None,
            "seller_rating": _num(seller.get("rating")) or _num(shop.get("rating")),
            "seller_deals": None, "seller_official": None,
        })
    return offers


def collect_yandexmarket(query, page=1):
    """Яндекс.Маркет — официальный контентный API (наряд #340).

    Гейт честности: без YANDEX_MARKET_API_KEY — kind:"config_missing"
    (регистрация ключа — шаг владельца A.1, из Беларуси доступность
    подтверждает владелец). Дневной счётчик 100/сутки (базовый тариф)
    в kv с авто-сбросом в 00:00 UTC; кэш повторов 5 мин — повторный
    тот же запрос лимит НЕ жжёт. Транспорт — fetch_api_json
    (Bearer-токен; токен в репо/логи/кэш-ключ не попадает). Парсер
    оборонительный: расхождение живой формы → api_form_mismatch
    (форма снимется первым прогоном).
    """
    key = os.environ.get("YANDEX_MARKET_API_KEY", "").strip()
    if not key:
        return {"ok": False, "platform": "ym",
                "error": "YANDEX_MARKET_API_KEY не задан — контентный API требует "
                         "регистрации ключа владельцем (наряд #340 A.1, шаг владельца)",
                "kind": "config_missing"}
    cache_key = "shop_ym_cache:" + hashlib.sha1(
        f"{query}|{page}".encode("utf-8")).hexdigest()[:20]
    raw = _setting_get(cache_key)
    if raw:
        try:
            hit = json.loads(raw)
            if (isinstance(hit, dict) and isinstance(hit.get("res"), dict)
                    and (time.time() - (hit.get("ts") or 0)) < YM_CACHE_TTL):
                return dict(hit["res"], cached=True)
        except ValueError:
            log.warning("ym кэш %s повреждён — игнорирую, иду в API", cache_key)
    counter = _ym_counter_read()
    if int(counter.get("count") or 0) >= YM_DAILY_LIMIT:
        return {"ok": False, "platform": "ym",
                "error": f"дневной лимит контентного API исчерпан ({YM_DAILY_LIMIT}/сутки, "
                         "базовый тариф) — счётчик обнулится в 00:00 UTC",
                "kind": "daily_limit"}
    url = (f"{YM_API_BASE}/{YM_API_VERSION}/search?"
           + urllib.parse.urlencode({"text": query, "page": str(page),
                                     "sortBy": "PRICE"}))
    r = FETCH_JSON_FN("fetch_api_json", {"url": url, "token": key})
    if not r.get("ok"):
        # счётчик НЕ бьётся: запрос до API не дошёл или отклонён до ответа
        _audit("ym", f"search:{query}", "refused")
        kind = r.get("kind", "transport")
        note = {"http_401": "ключ невалиден/не принят (проверить регистрацию)",
                "http_403": "прав недостаточно (проверить подключение контентного API)",
                "http_429": "лимит API на их стороне"}.get(kind)
        base = (r.get("error") or "").strip()
        return {"ok": False, "platform": "ym", "url": url,
                "error": f"{base} | {note}" if note and base else (base or note or "контентный API недоступен"),
                "kind": kind}
    _ym_counter_bump()          # 200-ответ — лимит израсходован
    _audit("ym", f"search:{query}", "ok")
    offers = _ym_offers_from(r.get("data") or {}, fx_rates())
    if offers is None:
        return {"ok": False, "platform": "ym", "url": url,
                "error": "в ответе Content API не найден список офферов — живая форма "
                         "снимется первым прогоном с реальным ключом",
                "kind": "api_form_mismatch"}
    res = {"ok": True, "platform": "ym", "url": url, "offers": offers}
    _setting_set(cache_key, json.dumps({"ts": time.time(), "res": res},
                                       ensure_ascii=False))
    return res


# ── 21vek (#328): robots запрещает поисковую поверхность ─────────────
def collect_21vek(query, page=1):
    """21vek.by — живая попытка сбора (#406, ADR-0011: красная линия robots
    снята решением владельца 2026-09-27; раньше #328: robots запрещал /search,
    /api/* и все URL с query — теперь правило не является основанием отказа).

    Форма: https://www.21vek.by/search/?query=… (SSR-HTML). Живая разведка
    2026-09-27 из песочницы: страница отдаётся (200, ~180KB), но товары в
    HTML НЕ серверены — Next.js SPA, витрина через session-bound
    gate.21vek.by (проб gate-путей: 404/415 без браузерного контекста).
    Сборщик пробует реальную страницу каждый раз: если платформа начнёт
    серверить товары или egress прода получит иной ответ — витрина
    подхватится без правки кода; иначе честный отказ с диагнозом.
    Транспорт — SHOP-2 (web-MCP: SSRF/rate-limit/кэш), A.5 наряда.
    """
    url = ("https://www.21vek.by/search/?"
           + urllib.parse.urlencode({"query": query, "page": str(page)}))
    page_res = FETCH_JSON_FN("fetch_page", {"url": url, "max_chars": 150000})
    _audit("21vek", f"search:{query}", "ok" if page_res.get("ok") else "refused")
    if not page_res.get("ok"):
        return {"ok": False, "platform": "21vek", "error": page_res.get("error"),
                "kind": page_res.get("kind", "transport"), "url": url}
    html = str(page_res.get("content") or "")
    offers = _parse_21vek_html(html, url)
    if offers:
        return {"ok": True, "platform": "21vek", "url": url, "offers": offers}
    return {"ok": False, "platform": "21vek", "url": url,
            "error": "страница поиска получена, но товары в HTML не серверены "
                     "(Next.js SPA: витрина через session-bound gate.21vek.by — "
                     "живая разведка 2026-09-27, gate 404/415 без браузерного "
                     "контекста); живой прогон на проде — /shop/diagnose",
            "kind": "recon_unreachable"}


def _parse_21vek_html(html, base_url):
    """Оборонительный разбор товарных карточек 21vek.by из SSR-HTML.

    Ищет JSON-LD Product/ItemList (schema.org). Нет карточек — пустой
    список (вызывающий код отдаст честный отказ, не выдумку)."""
    offers = []
    for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                        html, re.S | re.I):
        try:
            data = json.loads(m.strip())
        except ValueError:
            continue
        items = data.get("itemListElement") if isinstance(data, dict) else None
        candidates = items or ([data] if isinstance(data, dict) else [])
        for it in candidates:
            if not isinstance(it, dict):
                continue
            node = it.get("item") if isinstance(it.get("item"), dict) else it
            if (node.get("@type") or "").lower() not in ("product", ""):
                continue
            name = node.get("name")
            offer = node.get("offers") or {}
            price = _num(offer.get("price") if isinstance(offer, dict) else None)
            if not name or price is None:
                continue
            page_url = offer.get("url") or node.get("url") or it.get("url") or base_url
            offers.append({
                "platform": "21vek",
                "platform_code": str(node.get("sku") or node.get("gtin13") or name)[:64],
                "url": canonical_url(str(page_url)),
                "title": str(name)[:200],
                "price_byn": price,
                "old_price_byn": None,
                "in_stock": 0 if "outofstock" in str(offer.get("availability", "")).lower() else 1,
                "rating": None, "reviews_count": 0,
                "seller_name": "21vek.by",
                "seller_platform_code": None,
                "seller_rating": None, "seller_deals": None,
                "seller_official": 1,
            })
    return offers


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
    "7745": collect_7745,
    "shopby": collect_shopby,
    "tomas": collect_tomas,
    "unishop": collect_unishop,
    "ym": collect_yandexmarket,
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


def _persist_offers(product_id, platform, offers):
    """Сохранение офферов collect()-результата (вербатим из refresh_product,
    SHOP-SUPPLY-1 #421): офферы снабженца из /supply/result проходят ТЕМ ЖЕ
    путём (shop_offers/_upsert_seller/история цен) — SQL не дублируется.
    Возвращает (count_offers, count_hist)."""
    from proxy.core import _query
    count_offers = 0
    count_hist = 0
    for o in offers:
        sid = _upsert_seller(platform, o)
        existing = _query(
            "SELECT id FROM shop_offers WHERE platform=? AND platform_code=? LIMIT 1",
            (platform, o["platform_code"]), fetch=True)
        if existing:
            oid = existing[0]["id"]
            _query(
                "UPDATE shop_offers SET url=?, title=?, price_byn=?, old_price_byn=?, "
                "in_stock=?, installment_ok=?, rating=?, reviews_count=?, "
                "seller_id=?, image_url=COALESCE(?, image_url), "
                "fetched_at=datetime('now') WHERE id=?",
                (o["url"], o.get("title"), o.get("price_byn"), o.get("old_price_byn"),
                 o.get("in_stock"), o.get("installment_ok"), o.get("rating"),
                 o.get("reviews_count"), sid, o.get("image_url"), oid))
        else:
            _query(
                "INSERT INTO shop_offers (product_id, platform, platform_code, url, "
                "title, price_byn, old_price_byn, in_stock, installment_ok, rating, "
                "reviews_count, seller_id, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (product_id, platform, o["platform_code"], o["url"],
                 o.get("title"), o.get("price_byn"), o.get("old_price_byn"), o.get("in_stock"),
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
    return count_offers, count_hist


def refresh_product(product_id, platform, query, **kw):
    """Собрать площадку и уложить офферы + срез истории. Идемпотентно.

    История: строка на каждый успешный сбор с ценой (2–4 раза/сутки —
    копейки объёма, зато медианы честные с первого дня).
    """
    # SHOP-SUPPLY-1 (#421): площадки снабженца не собираются с сервера
    # (антибот/GeoIP с датацентровых IP — recog. наряда) — задание ставится
    # в очередь /supply/*, офферы приложит снабженец с домашнего IP.
    # wb/onliner/ym не в SUPPLY_AGENT_PLATFORMS — путь ниже не меняется.
    from proxy.shop_supply import SUPPLY_AGENT_PLATFORMS, enqueue_supply_task
    if platform in SUPPLY_AGENT_PLATFORMS:
        task_id = enqueue_supply_task(product_id, platform, query)
        return {"ok": False, "platform": platform,
                "kind": "supply_pending", "task_id": task_id}
    from proxy.core import _query
    res = collect(platform, query, **kw)
    if not res.get("ok"):
        return res
    count_offers, count_hist = _persist_offers(product_id, platform, res["offers"])
    # #408 A.1: фото после сохранения офферов — топ-N с общим бюджетом;
    # не успели — честный плейсхолдер «нет фото», подбор продолжится при
    # следующем срезе (офферы и цены уже сохранены).
    images_filled = 0
    if platform == "wb" and count_offers:
        t0 = time.monotonic()
        images_filled = _wb_fill_images(product_id, budget_secs=15.0, top_n=10)
        _audit("wb", f"images:filled={images_filled} "
                     f"took={time.monotonic() - t0:.1f}s", "ok")
    return {"ok": True, "platform": platform, "product_id": product_id,
            "offers": count_offers, "history_rows": count_hist,
            "images_filled": images_filled}


def _wb_fill_images(product_id, budget_secs=15.0, top_n=10):
    """#408 A.1: подобрать image_url для топ-N офферов WB в бюджете времени.

    Порядок — офферы с ценой (дешевле первым): это и есть топ досье.
    Фото поднимаются в БД сразу по мере подбора; бюджет исчерпан —
    остальные ждут следующего сбора, ничего не блокируют."""
    from proxy.core import _query
    deadline = time.monotonic() + budget_secs
    rows = _query(
        "SELECT platform_code FROM shop_offers "
        "WHERE product_id=? AND platform='wb' AND image_url IS NULL "
        "ORDER BY (price_byn IS NULL), price_byn, id LIMIT ?",
        (product_id, top_n), fetch=True) or []
    filled = 0
    for r in rows:
        if time.monotonic() > deadline:
            break
        url = wb_image_url(r["platform_code"], deadline=deadline)
        if url:
            _query("UPDATE shop_offers SET image_url=? "
                   "WHERE platform='wb' AND platform_code=?",
                   (url, r["platform_code"]))
            filled += 1
    return filled


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
