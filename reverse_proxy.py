#!/usr/bin/env python3
"""Reverse proxy for Fosved Office v2.
Routes requests between Metalogos (10001) and LLM Proxy (4000)."""

import os
import requests
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

MLOG_URL = "http://127.0.0.1:10001"
LLM_URL = "http://127.0.0.1:4000"
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Routes that go to LLM Proxy (Mini App + dashboards + archive + scheduler + learning)
LLM_ROUTES_PREFIXES = [
    # "/webhook/",   # Telegram webhook — Python handler
    "/webhook/miniapp-action",  # Mini App action bar → LLM Proxy (must precede generic mlog routing)
    "/cron/collect-news",  # registered in LLM Proxy, not in Metalogos; guarded by CRON_SECRET
    "/news/stats",         # read-only counters, used by the smoke script,
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
    "/scheduler/",
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
    "/extract-document",
]


def is_internal_only(path):
    return any(path.startswith(p) for p in INTERNAL_ONLY_PREFIXES)


# Routes that go to Metalogos
MLOG_ROUTES_PREFIXES = [
    "/webhook/",  # Telegram webhook — mlog handler
    "/cron/",
    "/health",
    "/",
]


def is_llm_route(path):
    """Check if path should go to LLM proxy."""
    for prefix in LLM_ROUTES_PREFIXES:
        if path == prefix or path.startswith(prefix):
            return True
    return False


def is_mlog_route(path):
    """Check if path should go to Metalogos."""
    for prefix in MLOG_ROUTES_PREFIXES:
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

    # Determine target
    if is_llm_route(full_path):
        target_url = LLM_URL + full_path
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
