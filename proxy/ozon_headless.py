"""Ozon headless (наряд #334) — антибот Variti проходится браузером один раз.

Метод подтверждён двумя независимыми реализациями (eduard256/ozon-mcp-server,
dpGorbunov/market-mcp): «публичного API для покупателей нет, сайт закрыт
антиботом Variti — сервер держит headless Chromium, который проходит проверку
один раз (~12 с), дальше забирает JSON из внутреннего composer-api (0.3-1 с)».

Дизайн (по наряду #334):
  - ФЛАГ SHOP_OZON_HEADLESS=1 — контур выключен по умолчанию. A.1 наряда
    гейтит внедрение реальным замером памяти на Render free (512 MB —
    Chromium может не поместиться рядом с офисом); включение — ОДНА env-строка
    после замера на стейджинге (команды — в отчёте наряда).
  - Браузер ПОДНИМАЕТСЯ ПО ТРЕБОВАНИЮ и закрывается ВСЕГДА (finally) —
    не держим ресурс в простое (smoke-пункт 3 наряда: память не растёт).
  - Сессия/cookies с TTL (6 ч) в kv system_settings — антибот проходится
    один раз, повторные запросы быстрые (smoke-пункт 2).
  - robots Ozon честно нечитаем из Датацентра (307-петля Variti); с
    ADR-0011 (#406, решение владельца 2026-09-27) robots-дисциплина
    больше не является блокером — первый живой прогон по-прежнему
    фиксирует вердикт по robots в отчёте (прозрачность, не запрет).
  - Форма composer-api снимется первым живым прогоном: до того сырой ответ
    сохраняется в kv (shop_ozon_last_raw, 24 ч) и отдаётся честный
    kind:"api_form_unknown" — парсер вслепую не пишем (дисциплина #172).

Playwright НЕ в requirements.txt осознанно: флаг выключен, раздувать
Docker-образ (Chromium ~300 MB) для выключенной функции — антипаттерн
dependency-дисциплины. Установка при включении: pip install playwright &&
playwright install chromium --with-deps.
"""
import json
import logging
import os
import time
import urllib.parse

log = logging.getLogger("ozon_headless")

SESSION_KEY = "shop_ozon_session"
SESSION_TTL = 6 * 3600
RAW_CACHE_KEY = "shop_ozon_last_raw"
RAW_TTL = 24 * 3600
CHALLENGE_TIMEOUT_S = 45.0      # референсы: ~12 с проход + запас
SEARCH_URL = "https://www.ozon.by/search/?text={q}&page={p}"
COMPOSER_PATH = "/api/composer-api.bx/page/json/v2?url={path}"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_REVIEW_SELECTOR = "[data-index], div[data-widget='searchResultsV2']"


def flag_enabled():
    return os.environ.get("SHOP_OZON_HEADLESS", "0") == "1"


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


def _session_read():
    raw = _kv_get(SESSION_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if (isinstance(data, dict) and isinstance(data.get("cookies"), list)
            and (time.time() - (data.get("ts") or 0)) < SESSION_TTL):
        return data["cookies"]
    return None


def _session_write(cookies):
    _kv_set(SESSION_KEY, json.dumps({"cookies": cookies, "ts": time.time()}))


def _raw_cache_write(payload):
    _kv_set(RAW_CACHE_KEY, json.dumps({"ts": time.time(), "raw": payload}))


def _composer_fetch(page, query, page_num):
    """fetch() к composer-api ИЗНУТРИ страницы (контекст браузера с его
    cookies/TLS/JS-стеком — надёжнее угадывания нужных cookies)."""
    path = urllib.parse.quote(f"/search/?text={query}&page={page_num}", safe="")
    url = COMPOSER_PATH.format(path=path)
    js = ("async (u) => { const r = await fetch(u, {credentials: 'include'}); "
          "return {status: r.status, text: await r.text()}; }")
    try:
        return page.evaluate(js, url)
    except Exception as e:  # noqa: BLE001 — страница/контекст умерли
        log.warning("composer fetch из контекста не удался: %s", e)
        return None


def collect_ozon_headless(query, page=1, playwright_mod=None):
    """Поиск Ozon через headless Chromium (наряд #334 A.2).

    playwright_mod — точка подмены в тестах (None = реальный импорт).
    Никогда не бросает; честные kind'ы:
      playwright_missing — пакет не установлен;
      challenge_not_passed — челлендж не снят за таймаут (сессия сброшена);
      api_form_unknown — транспорт прошёл, форма composer-api ещё не снята
      (сырой ответ сохранён в kv для точечного PR парсера).
    """
    try:
        if playwright_mod is None:
            from playwright import sync_api as playwright_mod  # noqa: F811
    except ImportError:
        return {"ok": False, "platform": "ozon",
                "error": "playwright не установлен — headless-контур требует "
                         "`pip install playwright && playwright install chromium "
                         "--with-deps` (шаги в отчёте наряда #334)",
                "kind": "playwright_missing"}

    cookies = _session_read()
    try:
        with playwright_mod.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=UA_BROWSER, locale="ru-RU")
                if cookies:
                    ctx.add_cookies(cookies)
                pg = ctx.new_page()
                challenged = cookies is None   # свежая сессия — челлендж обязателен
                res = None
                if cookies:
                    # быстрый путь: сессия живая — composer-api без прохода
                    res = _composer_fetch(pg, query, page)
                    if not res or res.get("status") != 200:
                        cookies = None
                        challenged = True     # протухла — полный проход
                if challenged:
                    pg.goto(SEARCH_URL.format(q=urllib.parse.quote(str(query)),
                                              p=page),
                            timeout=CHALLENGE_TIMEOUT_S * 1000,
                            wait_until="domcontentloaded")
                    try:
                        pg.wait_for_selector(_REVIEW_SELECTOR,
                                             timeout=CHALLENGE_TIMEOUT_S * 1000)
                    except Exception:
                        return {"ok": False, "platform": "ozon",
                                "error": "антибот-челлендж не снят за "
                                         f"{CHALLENGE_TIMEOUT_S:.0f} с — сессия сброшена, "
                                         "следующий запрос начнёт с полного прохода",
                                "kind": "challenge_not_passed"}
                    res = _composer_fetch(pg, query, page)
                    if not res or res.get("status") != 200:
                        status = (res or {}).get("status")
                        return {"ok": False, "platform": "ozon",
                                "error": "composer-api после снятого челленджа ответил "
                                         f"{status or 'без статуса'} — сессия не сохранилась",
                                "kind": "challenge_not_passed"}
                    _session_write(ctx.cookies())
            finally:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001 — закрытие не должно маскировать результат
                    log.warning("browser.close() не удался")
    except Exception as e:  # noqa: BLE001 — браузер/среда, не данные
        log.warning("headless-контур упал: %s", e)
        return {"ok": False, "platform": "ozon",
                "error": f"headless-браузер недоступен/упал: {e}",
                "kind": "browser_error"}

    # транспорт прошёл — форма снимаем первым живым прогоном (дисциплина #172)
    try:
        raw = json.loads(res.get("text") or "null")
    except ValueError:
        raw = None
    if raw is None:
        return {"ok": False, "platform": "ozon",
                "error": "composer-api вернул не-JSON — сырой ответ не сохранён",
                "kind": "api_form_unknown"}
    _raw_cache_write(res["text"][:200000])
    return {"ok": False, "platform": "ozon",
            "error": "транспорт через браузер ПРОШЁЛ (антибот снят), но форма "
                     "composer-api не разобрана вслепую — сырой ответ в kv "
                     "shop_ozon_last_raw (24 ч); парсер добавится точечным PR "
                     "по первому живому срезу",
            "kind": "api_form_unknown"}
