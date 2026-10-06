"""Наряд #486: ночная проверка ключей и провайдеров (key_health).

История: credential_manager (fdf7ae1, 2026-08-14) умел проверять ключи и
показывать провайдеров в утреннем отчёте (ff13b43), но был удалён 7ceb6a1
(2026-09-03) как «мёртвый код» — связь с утренним отчётом разорвалась при
переносе брифа на Metalogos. Наряд #486 возвращает функцию.

Манифест — один источник: INTEGRATIONS_REGISTRY (proxy/core.py) + перепись
METALOGOS_ENV_ALLOWLIST_CENSUS (entrypoint.sh). Метаданные (назначение,
обязательность, ссылка на получение, санкционные ограничения) актуализированы
из исходного манифеста fdf7ae1; поля sanctions_ok у ключей, которых не было
в исходном манифесте, выставлены по его же классификации (US-сервисы класса
OpenAI/Anthropic — False; открытые/нейтральные — True) и отмечены в отчёте
наряда как допущение.

Правила наряда:
- дешёвый вызов с авторизацией на каждый ключ, таймаут <= 10 c, без расхода
  платных токенов;
- статусы: ok / invalid (401/403) / missing (не задан) / quota (429, низкий
  баланс) / unreachable (сеть) / unverified (проверка не предусмотрена или
  эндпоинт валидации недоступен);
- НИ ОДНОГО значения ключа в логах/сообщениях/возврате — только статус и
  HTTP-код; детали ошибок сети не содержат URL (в URL Telegram-проверки
  стоит токен).
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests as http_requests

log = logging.getLogger("fosved.key_health")

from proxy.core import INTEGRATIONS_REGISTRY, get_secret  # noqa: E402

TIMEOUT_S = 10.0

# Классификация санкционных ограничений из исходного манифеста fdf7ae1:
# ANTHROPIC/OpenAI — False (заблокированы для владельца), Telegram/DeepSeek/
# Groq/Z.ai/GitHub — True. Ключи, которых в исходном манифесте не было,
# классифицированы по тому же правилу (см. докстринг модуля).
KEY_MANIFEST = [
    {"env_key": "TELEGRAM_BOT_TOKEN", "label": "Telegram (доставка)", "kind": "service",
     "required": True, "sanctions_ok": True,
     "how_link": "https://t.me/BotFather",
     "why": "Доставка отчётов и ответов владельцу; без токена офис нем.",
     "check": {"type": "telegram_getme"}},
    {"env_key": "ZAI_API_KEY", "label": "Z.ai (GLM)", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://open.bigmodel.cn",
     "why": "Основная модель офиса (GLM).",
     "check": {"type": "openai_models", "url": "https://api.z.ai/api/paas/v4/models"}},
    {"env_key": "DEEPSEEK_API_KEY", "label": "DeepSeek", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://platform.deepseek.com/api_keys",
     "why": "LLM-вызовы; баланс проверяется бесплатно (/user/balance).",
     "check": {"type": "deepseek", "url": "https://api.deepseek.com/models",
               "balance_url": "https://api.deepseek.com/user/balance"}},
    {"env_key": "GROQ_API_KEY", "label": "Groq", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://console.groq.com/keys",
     "why": "Быстрый бесплатный LLM-провайдер.",
     "check": {"type": "openai_models", "url": "https://api.groq.com/openai/v1/models"}},
    {"env_key": "GROK_API_KEY", "label": "Grok (xAI)", "kind": "model",
     "required": False, "sanctions_ok": False,
     "how_link": "https://console.x.ai",
     "why": "LLM-провайдер (класс OpenAI/Anthropic по санкционной карте fdf7ae1).",
     "check": {"type": "openai_models", "url": "https://api.x.ai/v1/models"}},
    {"env_key": "ANTHROPIC_API_KEY", "label": "Anthropic (Claude)", "kind": "model",
     "required": False, "sanctions_ok": False,
     "how_link": "https://console.anthropic.com",
     "why": "LLM-провайдер; санкционное ограничение (fdf7ae1).",
     "check": {"type": "anthropic_models", "url": "https://api.anthropic.com/v1/models"}},
    {"env_key": "OPENAI_API_KEY", "label": "OpenAI", "kind": "model",
     "required": False, "sanctions_ok": False,
     "how_link": "https://platform.openai.com/api-keys",
     "why": "LLM-провайдер; санкционное ограничение (fdf7ae1).",
     "check": {"type": "openai_models", "url": "https://api.openai.com/v1/models"}},
    {"env_key": "NVIDIA_API_KEY", "label": "NVIDIA", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://build.nvidia.com",
     "why": "Бесплатный LLM-провайдер (инференс NIM).",
     "check": {"type": "openai_models", "url": "https://integrate.api.nvidia.com/v1/models"}},
    {"env_key": "CEREBRAS_API_KEY", "label": "Cerebras", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://cloud.cerebras.ai",
     "why": "Быстрый бесплатный LLM-провайдер.",
     "check": {"type": "openai_models", "url": "https://api.cerebras.ai/v1/models"}},
    {"env_key": "SAKANA_API_KEY", "label": "Sakana Fugu", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://sakana.ai",
     "why": "LLM-провайдер (mlog llm-блок, app.mlog).",
     "check": {"type": "openai_models", "url": "https://api.sakana.ai/v1/models"}},
    {"env_key": "KIMI_API_KEY", "label": "Kimi (Moonshot)", "kind": "model",
     "required": False, "sanctions_ok": True,
     "how_link": "https://platform.moonshot.ai/console/api-keys",
     "why": "LLM-провайдер.",
     "check": {"type": "openai_models", "url": "https://api.moonshot.ai/v1/models"}},
    {"env_key": "TAVILY_API_KEY", "label": "Tavily (веб-поиск)", "kind": "service",
     "required": True, "sanctions_ok": True,
     "how_link": "https://app.tavily.com",
     "why": "Живой поиск ОСП/ЛЗ по умолчанию (#474); free-квота ~1000/мес.",
     "check": {"type": "tavily_usage", "url": "https://api.tavily.com/usage"}},
    {"env_key": "YANDEX_MARKET_API_KEY", "label": "Яндекс.Маркет (контентный API)", "kind": "service",
     "required": False, "sanctions_ok": True,
     "how_link": "https://yandex.ru/dev/market",
     "why": "Контентный API магазина; дешёвого валидирующего вызова нет — только наличие.",
     "check": None},
    {"env_key": "GITHUB_TOKEN_METALOGOS", "label": "GitHub (трекинг репозиториев)", "kind": "service",
     "required": False, "sanctions_ok": True,
     "how_link": "https://github.com/settings/tokens",
     "why": "Наряды, FORGE, трекинг Metalogos; /rate_limit бесплатен.",
     "check": {"type": "github_rate_limit", "url": "https://api.github.com/rate_limit"}},
    {"env_key": "FRED_API_KEY", "label": "FRED (макроданные)", "kind": "service",
     "required": False, "sanctions_ok": True,
     "how_link": "https://fred.stlouisfed.org/docs/api/api_key.html",
     "why": "Макроряды для ОСП (#467: неделями чинили кодом то, что было ключом).",
     "check": {"type": "fred", "url": "https://api.stlouisfed.org/fred/series",
               "params": {"series_id": "DGS10", "file_type": "json"}}},
    {"env_key": "ALPHAVANTAGE_API_KEY", "label": "Alpha Vantage (рынки)", "kind": "service",
     "required": False, "sanctions_ok": True,
     "how_link": "https://www.alphavantage.co/support/#api-key",
     "why": "Рыночные котировки; бесплатный лимит 25/день — проверка 1 запрос/ночь.",
     "check": {"type": "alphavantage", "url": "https://www.alphavantage.co/query",
               "params": {"function": "GLOBAL_QUOTE", "symbol": "SPY"}}},
]

_HTTP_TIMEOUT_S = TIMEOUT_S


def _key_value(env_key):
    """Значение ключа (db-override или env). Никогда не попадает в вывод."""
    try:
        val = get_secret(env_key)
    except Exception:  # noqa: BLE001 — fail-safe: fallthrough to env
        val = None
    if not val:
        val = os.environ.get(env_key, "")
    return val or ""


def _classify(resp):
    """HTTP-статус -> (status, detail). Значения ключей сюда не попадают."""
    code = resp.status_code
    if code == 200:
        return "ok", ""
    if code in (401, 403):
        return "invalid", f"HTTP {code}"
    if code == 429:
        return "quota", "HTTP 429"
    if code == 404:
        # эндпоинт валидации не существует — честное «не проверено», не «ok»
        return "unverified", "HTTP 404 (эндпоинт валидации недоступен)"
    if 500 <= code < 600:
        return "unreachable", f"HTTP {code}"
    return "unverified", f"HTTP {code}"


def _body_flag(resp, flag):
    """Есть ли ключ flag в JSON-теле ответа (для Alpha Vantage)."""
    try:
        return flag in resp.json()
    except Exception:  # noqa: BLE001 — тело не JSON
        return False


def _run_check(env_key, spec, value):
    """Один проверочный вызов. Возвращает (status, http_code, detail)."""
    t = spec["type"]
    headers = {"Authorization": f"Bearer {value}"} if t in ("openai_models", "tavily_usage", "github_rate_limit", "deepseek") else {}
    if t == "anthropic_models":
        headers = {"x-api-key": value, "anthropic-version": "2023-06-01"}
    try:
        if t == "telegram_getme":
            # токен в пути URL — НИКОГДА не включаем URL в детали/логи
            resp = http_requests.get(f"https://api.telegram.org/bot{value}/getMe", timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            if status == "ok":
                try:
                    if not resp.json().get("ok"):
                        status, detail = "invalid", "getMe ok=false"
                except Exception:  # noqa: BLE001
                    pass
            return status, resp.status_code, detail
        if t == "fred":
            params = dict(spec.get("params", {}))
            params["api_key"] = value
            resp = http_requests.get(spec["url"], params=params, timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            if status == "ok":
                try:
                    if "error" in resp.json():  # FRED отдаёт 400 с JSON-ошибкой при плохом ключе
                        status, detail = "invalid", "FRED error в ответе"
                except Exception:  # noqa: BLE001
                    pass
            return status, resp.status_code, detail
        if t == "alphavantage":
            params = dict(spec.get("params", {}))
            params["apikey"] = value
            resp = http_requests.get(spec["url"], params=params, timeout=_HTTP_TIMEOUT_S)
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except Exception:  # noqa: BLE001
                    return "unverified", 200, "не-JSON ответ"
                if "Global Quote" in body:
                    return "ok", 200, ""
                if "Information" in body:
                    return "quota", 200, "лимит/Information"
                if "Error Message" in body:
                    return "invalid", 200, "Error Message"
                return "unverified", 200, "неожиданное тело"
            status, detail = _classify(resp)
            return status, resp.status_code, detail
        if t == "deepseek":
            resp = http_requests.get(spec["url"], headers=headers, timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            if status != "ok":
                return status, resp.status_code, detail
            # дополнительно бесплатный баланс (/user/balance)
            try:
                b = http_requests.get(spec["balance_url"], headers=headers, timeout=_HTTP_TIMEOUT_S)
                if b.status_code == 200:
                    body = b.json()
                    if body.get("is_available") is False:
                        return "quota", 200, "баланс исчерпан (is_available=false)"
                    return "ok", 200, ""
                return "ok", 200, "модели ок, баланс не проверен"
            except Exception:  # noqa: BLE001
                return "ok", 200, "модели ок, баланс недоступен"
        if t == "openai_models":
            resp = http_requests.get(spec["url"], headers=headers, timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            return status, resp.status_code, detail
        if t == "anthropic_models":
            resp = http_requests.get(spec["url"], headers=headers, timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            return status, resp.status_code, detail
        if t == "tavily_usage":
            resp = http_requests.get(spec["url"], headers=headers, timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            return status, resp.status_code, detail
        if t == "github_rate_limit":
            resp = http_requests.get(spec["url"], headers=headers, timeout=_HTTP_TIMEOUT_S)
            status, detail = _classify(resp)
            if status == "ok":
                try:
                    rem = resp.json().get("resources", {}).get("core", {}).get("remaining")
                    if rem is not None:
                        detail = f"rate_limit remaining={rem}"
                except Exception:  # noqa: BLE001
                    pass
            return status, resp.status_code, detail
        return "unverified", None, "тип проверки не реализован"
    except Exception as e:  # noqa: BLE001 — сеть/таймаут; текст исключения может содержать URL
        return "unreachable", None, f"сеть: {e.__class__.__name__}"


def check_entry(entry):
    """Проверка одного элемента манифеста -> dict результата."""
    env_key = entry["env_key"]
    value = _key_value(env_key)
    base = {"env_key": env_key, "label": entry["label"], "kind": entry["kind"],
            "required": entry["required"], "sanctions_ok": entry["sanctions_ok"]}
    if not value:
        return {**base, "status": "missing", "http_code": None, "detail": "ключ не задан"}
    spec = entry.get("check")
    if not spec:
        return {**base, "status": "unverified", "http_code": None,
                "detail": "задан; дешёвой проверки для этого провайдера нет"}
    status, code, detail = _run_check(env_key, spec, value)
    return {**base, "status": status, "http_code": code, "detail": detail}


def check_all(timeout=TIMEOUT_S):
    """Проверить весь манифест параллельно (таймаут одного вызова <= timeout)."""
    global _HTTP_TIMEOUT_S
    _HTTP_TIMEOUT_S = timeout
    started = time.strftime("%Y-%m-%d %H:%M:%S")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(check_entry, KEY_MANIFEST))
    problems = [r for r in results if r["status"] in ("invalid", "missing", "quota", "unreachable")]
    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {
        "checked_at": started,
        "results": results,
        "problems": problems,
        "ok_count": ok_count,
        "total": len(results),
    }


def save_results(summary):
    """Сохранить последний результат в key_health_status (upsert по env_key)."""
    from proxy.core import _query
    for r in summary["results"]:
        _query(
            "INSERT INTO key_health_status (env_key, status, http_code, detail, checked_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(env_key) DO UPDATE SET status=excluded.status, http_code=excluded.http_code, "
            "detail=excluded.detail, checked_at=excluded.checked_at",
            (r["env_key"], r["status"], r["http_code"], r["detail"], summary["checked_at"]),
        )


def format_report(summary):
    """Текст для Telegram (/admin keys). Без значений ключей."""
    lines = [f"🔑 Проверка ключей ({summary['checked_at']} UTC):"]
    for r in summary["results"]:
        mark = {"ok": "✅", "invalid": "❌", "missing": "⚪", "quota": "⚠️",
                "unreachable": "🔌", "unverified": "❔"}.get(r["status"], "·")
        line = f"{mark} {r['label']}: {r['status']}"
        if r.get("http_code"):
            line += f" (HTTP {r['http_code']}"
            if r.get("detail"):
                line += f"; {r['detail']}"
            line += ")"
        elif r.get("detail"):
            line += f" ({r['detail']})"
        lines.append(line)
    p = len(summary["problems"])
    if p:
        lines.append(f"Итого: проблем {p}, ok {summary['ok_count']}/{summary['total']}")
    else:
        lines.append(f"Итого: все ключи в порядке (ok {summary['ok_count']}/{summary['total']})")
    return "\n".join(lines)


def night_summary(summary):
    """Компактный JSON для фазы ночного цикла (mlog NightSlot)."""
    p = summary["problems"]
    if p:
        problems_line = ", ".join(f"{r['label']} {r['status']}" + (f" ({r['http_code']})" if r.get("http_code") else "") for r in p[:8])
        return {"status": "problems", "problems_line": problems_line,
                "ok_count": summary["ok_count"], "total": summary["total"],
                "checked_at": summary["checked_at"]}
    return {"status": "ok", "problems_line": "",
            "ok_count": summary["ok_count"], "total": summary["total"],
            "checked_at": summary["checked_at"]}


def build_morning_line(max_age_hours=26.0):
    """Детерминированная строка «Ключи» для утреннего отчёта (A.4).

    Только проблемы + одна строка «остальные N — ok»; при всех ok — одна
    строка. Старше max_age_hours — «проверка не выполнялась с <дата>».
    """
    from datetime import datetime, timezone
    from proxy.core import _query
    try:
        rows = _query(
            "SELECT env_key, status, http_code, checked_at FROM key_health_status",
            fetch=True,
        )
    except Exception as e:  # noqa: BLE001 — таблица может ещё не существовать
        log.warning(f"key_health: read failed (non-fatal): {e}")
        return ""
    if not rows:
        return "🔑 Ключи: ещё не проверялись (первый ночной цикл после деплоя)"
    # возраст по самой свежей проверке
    checked = [str(r["checked_at"]) for r in rows if r["checked_at"]]
    age_stale = False
    checked_at = max(checked) if checked else ""
    try:
        dt = datetime.strptime(checked_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        age_stale = age_h > max_age_hours
    except (ValueError, TypeError):
        # дата не распарсилась — считаем «свежей», чтобы не пугать ложной тревогой;
        # сама строка даты остаётся в отчёте (проверяемая честность)
        age_stale = False
    if age_stale:
        return f"🔑 Ключи: проверка НЕ выполнялась с {checked_at[:16]} UTC (>26 ч) ⚠️"
    labels = {e["env_key"]: e["label"] for e in KEY_MANIFEST}
    problems = [r for r in rows if r["status"] in ("invalid", "missing", "quota", "unreachable")]
    total = len(rows)
    ok_count = sum(1 for r in rows if r["status"] == "ok")
    if not problems:
        return f"🔑 Ключи: все {total} — ok (проверка {checked_at[:16]} UTC)"
    parts = [f"{labels.get(r['env_key'], r['env_key'])} {r['status']}" + (f" ({r['http_code']})" if r["http_code"] else "") for r in problems]
    rest = total - len(problems)
    tail = f"; остальные {rest} — ok" if rest > 0 else ""
    return f"🔑 Ключи: ⚠️ " + ", ".join(parts) + tail
