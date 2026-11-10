#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_har_recorder.py — генерический рекордер HAR-сессии СВОЕГО веб-приложения.

Наряд #697 (REA-4): рецепт «HAR-запись сессии своего приложения → агентная
среда для evals/QA». Рекордер — сценарный: читает JSON-сценарий, выполняет
каждую операцию как РЕАЛЬНЫЙ HTTP-запрос к живому приложению и сериализует
пару «запрос-ответ» в формат HAR 1.2 (HTTP Archive, softwareishard.com/blog/har-12-spec),
который принимает `rea environment-build` (декодер HAR — собственный, от
Chrome/DevTools не зависит: creator честно называет этот рекордер).

Границы (наряд #697 «Что НЕ делаем»):
  • только свои приложения (base-URL задаётся сценарием; чужие сервисы —
    вне границ наряда);
  • HAR содержит всё записанное, включая параметры авторизации — писать
    сессии только с тестовыми секретами (как CRON_SECRET стенда serve_stack.sh),
    прод-секреты в HAR не попадают никогда;
  • стенды/HAR наружу не публикуются.

Сценарий (JSON): {
  "name": "office-schedules-session",
  "base": "http://127.0.0.1:10001",
  "ops": [
    {"id": "list-before", "method": "GET",
     "path": "/schedules/list?secret=n349-test-secret"},
    {"id": "create", "method": "POST",
     "path": "/schedules/create?secret=n349-test-secret",
     "body": {"cron": "37 3 * * *", "target": "ControlSlot", ...}},
    ...
  ]}
Операция может объявить "expect_json": true/false — гейт «ответ обязан
парситься как JSON» применяется по-операционно (create-роуты офиса
отвечают текстом "created <id>", а list-роуты — JSON).
Для демонстрации агентной среды сценарий должен содержать:
read → write → read (позже чтение подтверждает эффект записи — тогда среда
обслуживает write-инструмент из state, а не отклоняет его).

Использование:
  python3 scripts/eval_har_recorder.py \
    --scenario scripts/eval_har_scenario_schedules.json \
    --out /tmp/session.har [--expect-json]
Выход 1 и честная диагностика — если операция вернула 5xx/не-JSON, когда
сценарий ждёт JSON: битая сессия не годится для environment-build.
"""
import argparse
import datetime as _dt
import http.client
import json
import sys
import time
from urllib.parse import ParseResult, parse_qs, urlsplit

CREATOR = {"name": "fosved-eval-har-recorder", "version": "1.0.0", "comment":
           "narjad #697 REA-4: scenario-driven HAR recording of own application"}


def _headers_list(headers):
    """[(name, value)] → HAR-список [{"name","value"}] с сохранением порядка."""
    out = []
    seen = set()
    for k, v in headers:
        lk = k.lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append({"name": k, "value": v})
    return out


def _query_list(url: ParseResult):
    """Строка запроса → HAR queryString с сохранением повторов значений."""
    out = []
    for name, values in parse_qs(url.query, keep_blank_values=True).items():
        for v in values:
            out.append({"name": name, "value": v})
    return out


def run_op(conn: http.client.HTTPConnection, op, base: ParseResult):
    """Одна операция сценария → HAR-entry (реальный запрос к живому приложению)."""
    method = str(op.get("method", "GET")).upper()
    path = op["path"]
    started = _dt.datetime.now(_dt.timezone.utc)
    t0 = time.monotonic()
    body = None
    headers = {"Accept": "application/json, text/plain, */*"}
    if "body" in op and op["body"] is not None:
        body = json.dumps(op["body"], ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    sent = list(headers.items()) + ([("Content-Length", str(len(body)))] if body is not None else [])
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    t_ms = int((time.monotonic() - t0) * 1000)

    mime = resp.getheader("Content-Type", "text/plain")
    text = raw.decode("utf-8", errors="replace")
    entry = {
        "pageref": f"page_{op['id']}",
        "startedDateTime": started.isoformat().replace("+00:00", "Z"),
        "time": t_ms,
        "request": {
            "method": method,
            "url": f"{base.scheme}://{base.netloc}{path}",
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": _headers_list(sent),
            "queryString": _query_list(urlsplit(path)),
            "headersSize": -1,
            "bodySize": len(body) if body is not None else 0,
        },
        "response": {
            "status": resp.status,
            "statusText": resp.reason or "",
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": _headers_list(resp.getheaders()),
            "content": {"size": len(raw), "mimeType": mime, "text": text},
            "redirectURL": resp.getheader("Location", ""),
            "headersSize": -1,
            "bodySize": len(raw),
        },
        "cache": {},
        "timings": {"send": 0, "wait": t_ms, "receive": 0},
    }
    if body is not None:
        entry["request"]["postData"] = {
            "mimeType": "application/json",
            "text": body.decode("utf-8"),
        }
    return entry, resp.status, mime, text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", required=True, help="JSON-сценарий сессии")
    ap.add_argument("--out", required=True, help="путь итогового .har")
    ap.add_argument("--expect-json", action="store_true",
                    help="глобальный фолбэк: ops без явного \"expect_json\" считаются JSON-гейтовыми")
    ap.add_argument("--base", default=None,
                    help="переопределить base-URL сценария (напр. порт живого стенда)")
    args = ap.parse_args(argv)

    with open(args.scenario, encoding="utf-8") as f:
        scenario = json.load(f)
    base = urlsplit(args.base or scenario["base"])
    ops = scenario["ops"]
    if not (2 <= len(ops) <= 8):
        print(f"FAIL: в сценарии {len(ops)} операций; наряд #697: короткая сессия 2–8 операций",
              file=sys.stderr)
        return 2

    conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=30)
    entries = []
    try:
        for op in ops:
            entry, status, mime, text = run_op(conn, op, base)
            entries.append(entry)
            print(f"[op {op['id']}] {op['method']} {op['path']} -> {status} "
                  f"({mime}; {len(text)} chars)")
            if status >= 500:
                print(f"FAIL: операция {op['id']} получила 5xx — битая сессия "
                      f"не годится для environment-build", file=sys.stderr)
                return 1
            want_json = bool(op.get("expect_json", args.expect_json))
            if want_json:
                try:
                    json.loads(text)
                except json.JSONDecodeError as e:
                    print(f"FAIL: операция {op['id']}: ответ не JSON ({e}) — "
                          f"expect_json", file=sys.stderr)
                    return 1
    finally:
        conn.close()

    har = {
        "log": {
            "version": "1.2",
            "creator": dict(CREATOR),
            "pages": [{"startedDateTime": entries[0]["startedDateTime"],
                       "id": "page_1", "title": scenario.get("name", "session"),
                       "pageTimings": {"onContentLoad": -1, "onLoad": -1}}],
            "entries": entries,
        }
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(har, f, ensure_ascii=False, indent=1)
    print(f"HAR: {args.out} ({len(entries)} entries, "
          f"{ops and len(ops)} ops)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
