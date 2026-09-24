"""av.by → Эксперт (наряд #336): реальные объявления о продаже авто.

Решение владельца зафиксировано в наряде: av.by — НЕ источник «Закупок»
(не shop_engine/COLLECTORS/PLATFORMS_MVP), а живой поиск объявлений для
Эксперта при автомобильной теме, рядом со справочной
ExpertAutomotiveKB и двухфазным живым поиском.

Живая разведка 2026-09-24: av.by и cars.av.by закрыты WAF SafeLine —
robots.txt и страницы отвечают HTTP 468 (капча-челлендж) даже с
браузерным UA с датацентровых IP. Форма поиска не снята → парсер
вслепую не пишется (дисциплина #172): транспортная попытка живёт
(прод Render может отвечать иначе), но честные kind'ы:
  recon_unreachable — WAF/сеть недоступна (вердикт кэшируется 1 ч,
                      чтобы не биться в WAF каждым брифингом);
  api_form_mismatch — JSON пришёл, но знакомой формы списка объявлений
                      в нём нет (форма снимется первым живым прогоном);
  ok:True           — реальный список объявлений (только тогда).

Мост для mlog: call_python("avby_collector", "search_avby", [query])
(паттерн lz_sources #221); форматирование раздела — здесь, в питоне,
mlog только redact() и доклейка (урок №268: недоверенные данные не
попадают в промпты без redact).
"""
import json
import logging
import time
import urllib.parse

log = logging.getLogger("avby_collector")

WAF_VERDICT_KEY = "shop_avby_waf_verdict"
WAF_VERDICT_TTL = 3600          # час — брифинг не должен биться в WAF каждый раз
SEARCH_URL = "https://cars.av.by/search?text={q}"   # форма предварительная,
#                                                     уточнится первой живой пробой
_KNOWN_LIST_PATHS = (("result", "items"), ("result", "listings"),
                     ("items",), ("listings",), ("ads",))


def _mcp_fetch(tool, args):
    """Единый транспорт SHOP-2 (mcp_servers/web) — прокси к shop_collectors."""
    from proxy.shop_collectors import FETCH_JSON_FN as _f
    return _f(tool, args)


# точка подмены в тестах (тот же контракт, что в shop_collectors)
FETCH_JSON_FN = _mcp_fetch


def _kv_get(key):
    try:
        from proxy.shop_collectors import _setting_get
        return _setting_get(key)
    except Exception as e:  # noqa: BLE001 — kv недоступен → идём без кэша
        log.warning("kv недоступен: %s", e)
        return None


def _kv_set(key, value):
    try:
        from proxy.shop_collectors import _setting_set
        _setting_set(key, value)
    except Exception as e:  # noqa: BLE001 — кэш не написался, не беда
        log.warning("kv запись не удалась: %s", e)


def _waf_verdict_fresh():
    raw = _kv_get(WAF_VERDICT_KEY)
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except ValueError:
        return False
    return (isinstance(data, dict)
            and (time.time() - (data.get("ts") or 0)) < WAF_VERDICT_TTL
            and bool(data.get("blocked")))


def _waf_verdict_write():
    _kv_set(WAF_VERDICT_KEY, json.dumps({"ts": time.time(), "blocked": True}))


def _fmt_listing(item):
    """Строка объявления из оборонительного набора полей (форма живая)."""
    def pick(*keys, default=""):
        for k in keys:
            v = item.get(k)
            if isinstance(v, dict):
                v = v.get("value") or v.get("amount") or v.get("name")
            if v not in (None, ""):
                return str(v)
        return default
    title = pick("title", "name", "text", default="объявление")
    year = pick("year", "modelYear", default="")
    price = pick("price", "priceUsd", "priceByn", default="цена не указана")
    city = pick("city", "location", "region", default="")
    url = pick("url", "link", "htmlUrl", default="")
    line = f"- {title}"
    if year:
        line += f" ({year})"
    line += f" — {price}"
    if city:
        line += f" · {city}"
    if url.startswith("http"):
        line += f" — {url}"
    return line


def search_avby(query):
    """Поиск реальных объявлений av.by для контекста Эксперта (наряд #336).

    Никогда не бросает; раздел «result.text» уже отформактирован — mlog
    только redact + доклейка. ok:True только на реальном списке объявлений.
    """
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "platform": "avby", "kind": "bad_request",
                "error": "пустой поисковый запрос",
                "result": {"text": ""}}
    # свежий WAF-вердикт → не бьёмся в площадку каждым брифингом
    if _waf_verdict_fresh():
        return {"ok": False, "platform": "avby", "kind": "recon_unreachable",
                "error": "cars.av.by закрыт WAF SafeLine (HTTP 468) с датацентровых "
                         "IP — вердикт разведки 2026-09-24 ещё свежий, площадка "
                         "не дёргается",
                "result": {"text": "реальные объявления av.by сейчас недоступны: "
                                   "площадка закрыта WAF-антиботом для серверных IP "
                                   "(пробы 2026-09-24) — раздел честно пуст, "
                                   "выдуманных объявлений не будет"}}
    url = SEARCH_URL.format(q=urllib.parse.quote(query))
    try:
        r = FETCH_JSON_FN("fetch_json", {"url": url})
    except Exception as e:  # noqa: BLE001 — транспорт, не данные
        log.warning("av.by транспорт упал: %s", e)
        r = {"ok": False, "kind": "network", "error": str(e)}
    if not r.get("ok"):
        kind = r.get("kind", "transport")
        blocked = kind in ("http_468", "http_403", "http_429", "not_json", "network")
        if blocked:
            _waf_verdict_write()   # честный кэш вердикта на час
        return {"ok": False, "platform": "avby", "kind": "recon_unreachable",
                "error": f"cars.av.by недоступен ({r.get('error') or kind}) — "
                         "WAF SafeLine закрывает площадку для серверных IP "
                         "(пробы 2026-09-24)",
                "result": {"text": "реальные объявления av.by сейчас недоступны: "
                                   "площадка закрыта WAF-антиботом для серверных IP "
                                   "(пробы 2026-09-24) — раздел честно пуст, "
                                   "выдуманных объявлений не будет"}}
    # транспорт прошёл — оборонительный разбор известных форм списка
    body = r.get("data") or {}
    items = None
    for path in _KNOWN_LIST_PATHS:
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
        return {"ok": False, "platform": "avby", "kind": "api_form_mismatch",
                "error": "в ответе cars.av.by не найден список объявлений — живая "
                         "форма снимется первым прогоном с белого egress",
                "result": {"text": "av.by ответил, но форма списка объявлений ещё "
                                   "не снята живым прогоном — раздел честно пуст, "
                                   "парсер вслепую не пишется"}}
    lines = [ln for ln in (_fmt_listing(it) for it in items
                           if isinstance(it, dict)) if ln]
    if not lines:
        return {"ok": True, "platform": "avby", "kind": "ok",
                "result": {"text": f"по запросу «{query}» на av.by сейчас нет "
                                   "объявлений (живой ответ площадки)"}}
    return {"ok": True, "platform": "avby", "kind": "ok",
            "result": {"text": "\n".join(lines)}}
