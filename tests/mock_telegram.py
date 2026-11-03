#!/usr/bin/env python3
"""Мок Telegram Bot API для mlog test (наряд #634).

send_message в 0.38 fail-closed: на не-2xx бросает — тест ветки блокировки
ReleaseGate падал на реальном api.telegram.org с fake-токеном (404).
Хук METALOGOS_TELEGRAM_API_BASE направляет sendMessage сюда; мок отвечает
200 {"ok": true} на всё. Запуск: python3 tests/mock_telegram.py [port]
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        body = json.dumps({"ok": True, "result": {"message_id": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18801
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
