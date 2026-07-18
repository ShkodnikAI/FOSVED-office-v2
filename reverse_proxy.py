#!/usr/bin/env python3
"""Reverse proxy for Fosved Office v2.
Routes requests between Metalogos (10001) and LLM Proxy (4000)."""

import os
import requests
from flask import Flask, request, Response

app = Flask(__name__)

MLOG_URL = "http://127.0.0.1:10001"
LLM_URL = "http://127.0.0.1:4000"
PORT = int(os.environ.get("PORT", 10000))

# Routes that go to LLM Proxy (Mini App + dashboards + archive + scheduler + learning)
LLM_ROUTES_PREFIXES = [
    # "/webhook/",   # Telegram webhook — Block C: mlog
    "/miniapp/",
    "/miniapp",
    "/miniapp-spa/",
    "/miniapp-spa",
    "/api/",
    "/dept-dashboard/",
    "/dept-dashboard",
    "/office-dashboard",
    "/report",
    "/archive/",
    "/scheduler/",
    "/learning/",
    "/search",
    "/tts",
    "/stt",
    "/audit/",
    "/voice-set",
    "/memory/",
    "/lz/",
]

# Routes that go to Metalogos
MLOG_ROUTES_PREFIXES = [
    "/webhook/",  # Block C: mlog
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
