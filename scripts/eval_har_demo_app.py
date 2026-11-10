#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_har_demo_app.py — минимальное REST-образное приложение для контраст-демо.

Наряд #697 (REA-4): приложение офиса имеет RPC-образную HTTP-поверхность
(глагол в пути: /schedules/create; конверт с двумя массивами: {jobs, registry}) —
на ней агентная среда получается replay-only (см. docs/eval-har-env.md).
Этот демо-стенд — СВОЁ приложение с намеренно REST-образной поверхностью:

  GET  /items      -> 200, ГОЛЫЙ JSON-массив [{id, title, done}, ...]
  POST /items      -> 201, JSON созданной сущности {id, title, done}
  GET  /items/<id> -> 200, JSON сущности | 404

…чтобы пилот доказал и вторую ветку рецепта: state-ответы read-инструментов
и SERVED write (create подтверждён позже прочитанным списком). Сессия для
записи: GET /items → POST /items → GET /items (seed: 2 элемента до записи).

Границы: своё приложение, порт 18766, только localhost; никаких данных
владельца; стенд наружу не публикуется. Запуск:
  python3 scripts/eval_har_demo_app.py [--port 18766]
"""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
# seed: непустая коллекция до записи — пустой/одноэлементный baseline не даёт
# state-машине ни идентичности, ни membership (уроки пилота, см. док).
_ITEMS = [
    {"id": 1, "title": "seed-alpha", "done": False},
    {"id": 2, "title": "seed-beta", "done": True},
]
_NEXT_ID = [3]


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/items":
            with _LOCK:
                snapshot = list(_ITEMS)
            return self._json(200, snapshot)
        if self.path.startswith("/items/"):
            try:
                wanted = int(self.path.rsplit("/", 1)[1])
            except ValueError:
                return self._json(400, {"error": "bad id"})
            with _LOCK:
                found = next((x for x in _ITEMS if x["id"] == wanted), None)
            if found is None:
                return self._json(404, {"error": "not found"})
            return self._json(200, found)
        return self._json(404, {"error": "no route"})

    def do_POST(self):
        if self.path != "/items":
            return self._json(404, {"error": "no route"})
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        title = str(data.get("title", "")).strip()
        if not title:
            return self._json(400, {"error": "title required"})
        with _LOCK:
            item = {"id": _NEXT_ID[0], "title": title, "done": False}
            _NEXT_ID[0] += 1
            _ITEMS.append(item)
        return self._json(201, item)

    def log_message(self, fmt, *args):
        pass  # тихий стенд: журнал не нужен, пилот пишет свой HAR


def main(argv=None):
    ap = argparse.ArgumentParser(description="REST-демо для HAR-пилота (наряд #697)")
    ap.add_argument("--port", type=int, default=18766)
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[demo] REST demo app on http://127.0.0.1:{args.port} "
          f"(GET /items, POST /items, GET /items/<id>)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
