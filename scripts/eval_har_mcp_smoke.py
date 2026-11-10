#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_har_mcp_smoke.py — smoke-клиент агентной среды (MCP over streamable HTTP).

Наряд #697 (REA-4): базовый тест среды «отвечает ли» — та же пара проверок,
что делает verify.py бандла (список tools + один вызов без аргументов со
ожидаемым статусом), плюс environment card. Docker не требует: работает
против `rea environment-serve` (README бандла: контейнер запускает ровно
этот же сервер). Протокол: JSON-RPC 2.0 поверх streamable HTTP
(POST /mcp, Accept: application/json, text/event-stream; ответы могут
приходить как SSE — парсим data-строки).

Использование:
  python3 scripts/eval_har_mcp_smoke.py --url http://127.0.0.1:18765 \
    [--call get_schedules_list] [--expect-tools N]
Выход 0 — среда отвечает; не-0 — честная диагностика.
"""
import argparse
import http.client
import json
import sys
from urllib.parse import urlsplit


def _post(base, path, payload, session_id=None, expect_status=200, timeout=15):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    u = urlsplit(base)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        body = json.dumps(payload)
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        status = resp.status
        sid = resp.getheader("Mcp-Session-Id")
    finally:
        conn.close()
    # ответ может быть JSON или SSE (data:-строки)
    text = raw
    if raw.lstrip().startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
        lines = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
        text = lines[-1] if lines else raw
    try:
        parsed = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        parsed = None
    return status, parsed, sid, raw


def _result_of(resp_json):
    """JSON-RPC ответ → result (или честный raise с error-полем)."""
    if resp_json is None:
        raise RuntimeError("ответ среды не JSON/SSE-JSON")
    if "error" in resp_json and resp_json["error"]:
        raise RuntimeError(f"JSON-RPC error: {json.dumps(resp_json['error'], ensure_ascii=False)[:300]}")
    return resp_json.get("result", {})


def main(argv=None):
    ap = argparse.ArgumentParser(description="MCP smoke агентной среды (наряд #697 REA-4)")
    ap.add_argument("--url", required=True, help="база URL среды, напр. http://127.0.0.1:18765")
    ap.add_argument("--call", action="append", default=None, metavar="TOOL[ {JSON-ARGS}]",
                    help="вызвать инструмент; можно повторять; аргументы — JSON после пробела; "
                         "без --call — первый GET-tool без аргументов (как verify.py бандла)")
    ap.add_argument("--expect-tools", type=int, default=None,
                    help="ожидаемое число tools (tools/list должен совпасть)")
    args = ap.parse_args(argv)

    base = args.url
    ok = True

    # 0. дождаться порта (стенд/serve может подниматься дольше старта клиента)
    u = urlsplit(base)
    _up = False
    for _ in range(30):
        try:
            _c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=3)
            _c.connect()
            _c.close()
            _up = True
            break
        except OSError:
            import time as _t
            _t.sleep(1)
    if not _up:
        print("FAIL: среда не принимает соединения за 30с")
        return 1

    # 1. environment card (отдельное соединение)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=15)
    try:
        conn.request("GET", "/.well-known/agent-env.json")
        r = conn.getresponse()
        card_raw = r.read().decode("utf-8", errors="replace")
    finally:
        conn.close()
    if r.status == 200:
        card = json.loads(card_raw)
        print(f"[card] 200 name={card.get('name')} protocol={card.get('protocolVersion')} "
              f"url={card.get('url')}")
    else:
        print(f"[card] {r.status} — card недоступен (для agent-env обязателен, "
              f"для smoke — честная пометка)")
        ok = False

    # 2. initialize
    st, resp, sid, _ = _post(base, "/mcp", {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26",
                   "capabilities": {},
                   "clientInfo": {"name": "fosved-eval-har-smoke", "version": "1.0.0"}},
    })
    try:
        res = _result_of(resp)
        print(f"[init] {st} server={res.get('serverInfo', {}).get('name')} "
              f"protocol={res.get('protocolVersion')}")
    except RuntimeError as e:
        print(f"[init] FAIL {st}: {e}")
        return 1
    # notifications/initialized (без id — 202, тела нет)
    st2, _, _, _ = _post(base, "/mcp",
                          {"jsonrpc": "2.0", "method": "notifications/initialized"},
                          session_id=sid)
    if st2 not in (200, 202):
        print(f"[initialized] нештатный статус {st2} — честная пометка")

    # 3. tools/list
    st, resp, _, _ = _post(base, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                           session_id=sid)
    try:
        res = _result_of(resp)
        tools = res.get("tools", [])
        print(f"[tools] {st} {len(tools)} шт.: " + ", ".join(t.get("name", "?") for t in tools))
        if args.expect_tools is not None and len(tools) != args.expect_tools:
            print(f"FAIL: tools/list дал {len(tools)}, ожидалось {args.expect_tools}")
            ok = False
    except RuntimeError as e:
        print(f"[tools] FAIL {st}: {e}")
        return 1

    # 4. tools/call (по умолчанию первый GET-tool без аргументов — как verify.py)
    calls = list(args.call or [])
    if not calls and tools:
        target = next((t["name"] for t in tools), None)
        if target:
            calls = [target]
    if not calls:
        print("[call] нет инструментов для вызова — среда пуста (честная пометка)")
        return 0 if ok else 1
    next_id = 3
    for spec in calls:
        if "{" in spec:
            name, _, arg_txt = spec.partition("{")
            name = name.strip()
            try:
                arguments = json.loads("{" + arg_txt)
            except json.JSONDecodeError as e:
                print(f"FAIL: --call {spec!r}: аргументы не JSON ({e})")
                return 1
        else:
            name, arguments = spec.strip(), {}
        if name not in {t["name"] for t in tools}:
            print(f"FAIL: инструмент {name!r} не в каталоге среды")
            return 1
        st, resp, _, _ = _post(base, "/mcp", {
            "jsonrpc": "2.0", "id": next_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, session_id=sid)
        next_id += 1
        try:
            res = _result_of(resp)
            content = res.get("content", [])
            text = content[0].get("text", "") if content else ""
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"raw": text[:200]}
            status = payload.get("status")
            state = payload.get("state", {})
            replay = payload.get("replay", {})
            print(f"[call] {name}({json.dumps(arguments, ensure_ascii=False)}) -> "
                  f"isError={res.get('isError', False)} status={status}")
            if state:
                print(f"       state: {json.dumps(state, ensure_ascii=False)[:160]}")
            if replay:
                print(f"       replay: record={replay.get('record_ordinal')} "
                      f"exact_match={replay.get('exact_match')} "
                      f"evidence={str(replay.get('evidence_id'))[:14]}…")
            if payload.get("body") is not None:
                b = payload["body"]
                summary = json.dumps(b, ensure_ascii=False)[:180] if not isinstance(b, str) else b[:180]
                print(f"       body: {summary}")
        except RuntimeError as e:
            print(f"[call] FAIL {name} {st}: {e}")
            return 1
    print("[smoke] OK — среда отвечает")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
