#!/usr/bin/env python3
"""Reverse proxy for Fosved Office v2.
Routes requests between Metalogos (10001) and LLM Proxy (4000)."""

import logging
import os
import re

import requests
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

MLOG_URL = "http://127.0.0.1:10001"
LLM_URL = "http://127.0.0.1:4000"
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# ── №423: маскирование секретов в access-логах прокси ──────────────────────
# Контекст: CRON_SECRET ходит в query string у внешних кронов (cron-job.org),
# а dev-сервер werkzeug пишет в лог строку запроса ЦЕЛИКОМ — инцидент
# 2026-09-22: «GET /cron/morning?secret=...» в логе Render. Решение владельца —
# секрет не ротировать, поэтому единственная компенсация: больше не печатать
# чувствительные query-параметры. Затрагивает только ЛОГИ, не обработку запросов.
SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:secret|token|password|api_key|apikey)=)[^&\s]*",
    re.IGNORECASE,
)


class QuerySecretMasker(logging.Filter):
    """Redacts secret=/token=/password= query values in access-log records.

    Works on the werkzeug logger (который пишет строки вида
    `"GET /cron/morning?secret=X HTTP/1.1" 403`). Record переписывается
    до хендлеров, так что в Render stdout уходит уже замаскированная строка.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True  # битая запись не должна ронять логирование
        if "=" not in message:
            return True
        masked = SENSITIVE_QUERY_RE.sub(r"\1<redacted>", message)
        if masked != message:
            record.msg = masked
            record.args = ()
        return True


logging.getLogger("werkzeug").addFilter(QuerySecretMasker())

# Routes that go to LLM Proxy (Mini App + dashboards + archive + scheduler + learning)
LLM_ROUTES_PREFIXES = [
    # "/webhook/",   # Telegram webhook — Python handler
    "/webhook/miniapp-action",  # Mini App action bar → LLM Proxy (must precede generic mlog routing)
    "/cron/collect-news",  # registered in LLM Proxy, not in Metalogos; guarded by CRON_SECRET
    "/cron/backup",        # FO-001 db-backup: роут был только здесь — раньше уходил в mlog и молча 404 (нашли FO-042)
    "/cron/backup-forge",  # FO-042: git bundle bare-репозиториев FORGE
    "/cron/narad-tick",    # FO-047: такт нарядной очереди (исполнение через /chain/step)
    "/cron/shop-tick",             # SHOP-4 (#172): такт вотчлиста — без этого Render-cron ловил молчаливый 404 от mlog (ловим живым деплоем)
    "/cron/cleanup-tool-output",   # FO-016: чистка tool-output — тот же класс пропуска
    "/cron/consolidate-memory",    # консолидация памяти — тот же класс пропуска
    "/scheduler/golden-evals",     # golden-эвалы по крону — тот же класс пропуска
    "/shop/dossier/",              # SHOP-5 (#172): GET HTML-досье по HMAC-токену ?t= (клик из inline-кнопки). ВАЖНО: префикс со слэшем — POST /shop/dossier (внутренний, без auth) остаётся публично недостижим; POST /shop/product|watch|watch-list дёргает только mlog на 127.0.0.1:4000
    "/news/stats",         # read-only counters, used by the smoke script,
    "/scheduler/morning-brief",   # cron-accessible
    "/scheduler/lz-daily",        # cron-accessible
    "/scheduler/watch-sweep",     # cron-accessible (OSP watch sweep)
    "/scheduler/indicator-pre-reminders",  # cron-accessible (OSP pre-reminders)
    "/lz/diagnose",  # безопасная read-only диагностика источников ЛЗ
    "/miniapp/",
    "/miniapp",
    "/miniapp-spa/",
    "/miniapp-spa",
    "/api/",
    "/dept-dashboard/",
    "/dept-dashboard",
    "/office-dashboard",
    "/archive/browse",
    "/audit/",
]

# Called by Metalogos directly on 127.0.0.1:4000 — must never be reachable
# through the public port. Listed explicitly so the intent survives refactors.
INTERNAL_ONLY_PREFIXES = [
    "/ask",
    "/detect-dept",
    # /scheduler/ endpoints: crons need public access, but internal sub-routes stay blocked
    "/scheduler/admin-morning-reply",
    "/scheduler/admin-daily",
    "/scheduler/evening-summary",
    "/scheduler/weekly-digest",
    "/scheduler/monthly-review",
    "/scheduler/control-check",
    "/scheduler/self-learn",
    "/scheduler/reminder-check",
    "/learning/",
    "/memory/",
    "/lz/",
    "/search",
    "/tts",
    "/stt",
    "/voice-set",
    "/enrich",
    "/tg-send",
    "/now-time",
    "/now-weather",
    "/generate-image",
    "/news/fresh",
    "/yana/",
    "/admin-ua/",
    "/archive/publish",
    "/archive/digest",
    "/archive/daily-digest",
    "/archive/save",
    "/extract-document",
    "/expert/chart",  # Expert chart gen — called by mlog internally
]


def is_internal_only(path):
    # /lz/diagnose — безопасный, только чтение (GET), без побочных эффектов
    # и без платных вызовов. Исключение из общего блока /lz/, чтобы можно
    # было проверять состояние источников ЛЗ снаружи, не только изнутри.
    if path == "/lz/diagnose":
        return False
    return any(path.startswith(p) for p in INTERNAL_ONLY_PREFIXES)


# Routes that go to Metalogos
# NOTE: mlog routes checked BEFORE LLM routes (specific > catch-all)
# "/" is exact-only — see is_mlog_route (must not swallow /miniapp, /api, …)
MLOG_ROUTES_PREFIXES = [
    "/api/expert/",  # Expert automotive API — served by mlog (dept/expert.mlog)
    "/api/lz/",      # LZ multi-domain API — served by mlog (dept/lz.mlog)
    "/webhook/",    # Telegram webhook — mlog handler
    "/cron/",
    "/health",
    "/version",
    "/",
]


def is_llm_route(path):
    """Check if path should go to LLM proxy."""
    for prefix in LLM_ROUTES_PREFIXES:
        if path == prefix or path.startswith(prefix):
            return True
    return False


def is_mlog_route(path):
    """Check if path should go to Metalogos.

    Prefix "/" matches only the exact root path. Without this guard,
    path.startswith("/") is true for every URL and Mini App / LLM routes
    never reach port 4000 (net::ERR_HTTP_RESPONSE_CODE_FAILURE / 404).
    """
    for prefix in MLOG_ROUTES_PREFIXES:
        if prefix == "/":
            if path == "/":
                return True
            continue
        if path == prefix or path.startswith(prefix):
            return True
    return False


@app.route("/", methods=["GET"])
def root():
    return "Fosved Office v2 alive"


@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path):
    full_path = "/" + path

    # SEC-1: Block internal-only paths from public access
    if is_internal_only(full_path):
        return jsonify({"error": "not found"}), 404

    # SEC-3: Verify Telegram webhook secret token
    if WEBHOOK_SECRET and full_path in ("/webhook/", "/webhook/telegram"):
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != WEBHOOK_SECRET:
            app.logger.warning("SEC-3: webhook rejected — bad or missing secret token")
            return jsonify({"error": "not found"}), 404

    # Rewrite /webhook/ → /webhook/telegram for mlog (Telegram sends /webhook/, mlog route is /webhook/telegram)
    if full_path == "/webhook/":
        full_path = "/webhook/telegram"

    # FO-039 B.1: живое превью — /preview-live/<slug>/* → 127.0.0.1:<порт>
    # из forge_previews (таблица читается при запросе — кэша нет, свежесть
    # максимальная; требование «кэш не дольше 30 с» удовлетворено консервативно)
    if full_path.startswith("/preview-live/"):
        slug = full_path.split("/")[2] if len(full_path.split("/")) > 2 else ""
        if not slug:
            return Response("preview-live: slug обязателен", status=400)
        import sqlite3
        db_path = os.path.join(os.environ.get("DATABASE_PATH", "./data"), "office.db")
        port = None
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            row = conn.execute(
                "SELECT port, pid FROM forge_previews WHERE slug = ? AND status = 'running'",
                (slug,)).fetchone()
            conn.close()
            if row:
                port = row[0]
                # B.2: last_access_at при каждом обращении через прокси
                try:
                    conn = sqlite3.connect(db_path, timeout=5)
                    conn.execute(
                        "UPDATE forge_previews SET last_access_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE slug = ?",
                        (slug,))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
        except Exception:
            port = None
        if port is None:
            return Response("Превью неактивно, поднять снова (кнопка на странице задачи).", status=410)
        target_url = f"http://127.0.0.1:{port}" + full_path[len(f"/preview-live/{slug}"):] or "/"
        try:
            headers = {k: v for k, v in request.headers if k.lower() != "host"}
            resp = requests.request(
                method=request.method, url=target_url, headers=headers,
                data=request.get_data(), params=request.args,
                timeout=60, allow_redirects=False)
            excluded = {"content-encoding", "transfer-encoding", "connection"}
            response_headers = [
                (k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded
            ]
            return Response(resp.content, status=resp.status_code, headers=response_headers)
        except requests.exceptions.RequestException:
            return Response("Превью неактивно, поднять снова (кнопка на странице задачи).", status=410)

    # Determine target:
    # 1) LLM-specific prefixes first (miniapp, dashboards, …)
    # 2) then mlog-specific prefixes
    # 3) default → mlog
    if is_llm_route(full_path):
        target_url = LLM_URL + full_path
    elif is_mlog_route(full_path):
        target_url = MLOG_URL + full_path
    else:
        target_url = MLOG_URL + full_path

    # Forward request
    try:
        headers = {k: v for k, v in request.headers if k.lower() != "host"}
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            params=request.args,
            timeout=300,
            allow_redirects=False,
        )

        # Build response
        excluded = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = [
            (k, v) for k, v in resp.raw.headers.items() if k.lower() not in excluded
        ]

        return Response(
            resp.content,
            status=resp.status_code,
            headers=response_headers,
        )
    except requests.exceptions.RequestException as e:
        return Response(f"Proxy error: {e}", status=502)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
