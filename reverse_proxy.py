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

# ── #445 A.3: XFF по контракту Metalogos №263 ───────────────────────────────
# METALOGOS_TRUSTED_PROXIES=127.0.0.1 (entrypoint.sh) делает mlog:10001
# доверяющим XFF только от петлевого пира — а это мы. ОПЕРАТОРСКИЙ КОНТРАКТ
# (REFERENCE §5.6, server.rs №263): прокси ПЕРЕЗАПИСЫВАЕТ X-Forwarded-For
# адресом клиента, который он видит (rightmost значение входящего XFF —
# последний хоп, дописанный доверенным edge Render'а; иначе сам peer) —
# НЕ аппендит. Тогда rate-limit ключ в mlog — реальный клиент, а не 127.0.0.1
# на всех (бут-лог 2026-09-30: один общий лимит 100 req/min на Telegram,
# Mini App и кроны).
# Замечание 2 аудита 2026-10-01 (#451): leftmost XFF — контролируемое
# клиентом значение (первый элемент цепочки присылает сам клиент), подменой
# XFF клиент получал новый лимит-ключ на каждый запрос. Edge Render
# дописывает адрес клиента СПРАВА — rightmost (последний хоп) устойчив
# к клиентской подмене.
def _client_ip():
    """Адрес клиента по контракту №263: rightmost XFF (последний хоп от
    доверенного edge) или сам peer. Перезаписывается в исходящие заголовки
    целиком."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[-1].strip() or "unknown"
    return request.remote_addr or "unknown"


def _upstream_headers():
    """Заголовки для upstream: без host и без клиентских прокси-заголовков,
    X-Forwarded-For/X-Real-IP — перезаписанные адресом клиента (№445 A.3)."""
    headers = {
        k: v
        for k, v in request.headers
        if k.lower() not in ("host", "x-forwarded-for", "x-real-ip")
    }
    client = _client_ip()
    headers["X-Forwarded-For"] = client
    headers["X-Real-IP"] = client
    return headers


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
    "/api/lz/",            # №376: LZ API — Python-слой (proxy/routes_admin.py); перенос из MLOG_ROUTES_PREFIXES — mlog-роутов нет, форвардинг заслонял живые эндпоинты
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
    # FO-053 (office#325): фид счётчиков активности для FO-052 ступени 1 —
    # VM-экспортёр опрашивает его ЧЕРЕЗ публичный порт, auth (ACTIVITY_FEED_TOKEN,
    # fail-closed) несёт сам роут на 4000. Без префикса путь проваливается в
    # default → mlog → тихий 404 (класс FO-042); найдено живой пробой 2026-09-27:
    # прод отвечал 404 на мёржнутый эндпоинт (тесты гоняли 4000 напрямую).
    "/metrics/activity",
    # #407 A.4: диагноз сбора на проде; auth — CRON_SECRET в самом роуте
    # (cron_secret_ok), досье не шлёт. Публично маршрутизируем сознательно.
    "/shop/diagnose",
    # SHOP-SUPPLY-1 (#421): очередь снабженца — GET /supply/next,
    # POST /supply/result; auth Bearer SUPPLY_AGENT_TOKEN (fail-closed)
    # несёт сам роут на 4000. Без префикса путь проваливается в default →
    # mlog → тихий 404 (класс FO-042, прецедент /metrics/activity FO-053).
    "/supply/",
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
    "/cron/onliner-warm",  # #429 A.3/#443: прогрев словаря Onliner — зовут только
                           # entrypoint (фон) и слот schedules.mlog, напрямую на :4000;
                           # auth CRON_SECRET в роуте, наружу не светим (как /forge/export-state)
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
    # №376: /api/expert/* восстановлены (7 роутов в app.mlog, auth CRON_SECRET);
    # до наряда обёртки были удалены (TODO dept/expert.mlog:804) — форвардер
    # отдавал mlog-404 на мёртвый класс.
    "/api/expert/",  # Expert automotive API — routes in app.mlog (mlogserver block), logic in dept/expert.mlog
    # №376: "/api/lz/" ПЕРЕНЕСЁН в LLM_ROUTES_PREFIXES — LZ API живёт на
    # Python-слое (proxy/routes_admin.py: /api/lz/rss, /api/lz/notices, …),
    # mlog-роутов /api/lz/* нет; форвардинг на mlog заслонял Python-эндпоинты
    # (тихий 404 через фронт-дверь — тот же класс, что FO-042 /cron/backup).
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
            headers = _upstream_headers()
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
        headers = _upstream_headers()
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
    # #445 A.1: прод-сервер waitress вместо dev-сервера Werkzeug
    # (бут-лог «This is a development server» больше не появляется).
    # threads=16 под 512 МБ контейнера; channel_timeout=360 покрывает
    # долгие прокси-вызовы (upstream timeout=300 на LLM-запросы).
    # trusted_proxy='*': waitress по умолчанию СРЕЗАЕТ XFF/X-Real-IP
    # (clear_untrusted_proxy_headers=True) — на Render edge не loopback,
    # IP edge заранее не известен, поэтому доверяем входящим прокси-заголовкам.
    # Спуф-риск XFF содержит сам перезапись: _upstream_headers() шлёт mlog
    # ровно ОДНО значение (rightmost — последний хоп от доверенного edge),
    # а mlog принимает XFF только от доверенного пира 127.0.0.1 (№263).
    from waitress import serve

    logging.getLogger(__name__).info(f"Reverse proxy (waitress) on 0.0.0.0:{PORT}")
    serve(
        app,
        host="0.0.0.0",
        port=PORT,
        threads=16,
        channel_timeout=360,
        trusted_proxy="*",
        trusted_proxy_headers={
            "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port",
        },
    )
