#!/usr/bin/env python3
"""proxy/mcp_server.py — FO-021: Memory-MCP-сервер офиса (память наружу агентам).

Офис становится ПРОВАЙДЕРОМ памяти, не только потребителем (restack-эдж MCP × taint;
эталоны: supermemory apps/mcp — тулзы/spaces/percent-релевантность; sst/opencode
mcp/index.ts — статус-union, server-instructions).

Транспорт: stdio (`python3 proxy/mcp_server.py --stdio`) и HTTP (`/mcp` JSON-RPC).
Протокол: MCP поверх JSON-RPC 2.0 — initialize / tools/list / tools/call.

Тулзы (read-only по умолчанию):
  search_memory(query, space, limit) — профиль (FO-019) + recent + совпадения с процентами
  list_memory(space)                  — последние записи контейнера
  graph(space, entity)                — связи сущности по фактам
  add_memory(text, space, tags)       — только при FOSVED_MCP_ALLOW_WRITE=1

Контейнеры: space = департамент (жёсткая изоляция, containerTag-семантика supermemory);
«owner» — отдельный контейнер (профиль FO-019). Cross-space доступ — громкая ошибка.

Taint-контур: SECRET-записи (secrets_store) не покидают офис никогда; каждый ответ
тулзы проходит env-redact (общий модуль proxy/redact.py — задел FO-022).

Guardian: каждое подключение = check('mcp-agent', 'mcp_connect'); каждый вызов —
лог mcp_call (кто/что/зачем) поверх transport-лога. Инструкции сервера → агенту
в initialize (instructions-injection, паттерн opencode).
"""
import json
import math
import os
import re
import sys
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from proxy.redact import redact_text  # noqa: E402 — общий модуль (FO-022 задел)

SERVER_NAME = "fosved-memory"
SERVER_VERSION = "1.0.0"
OWNER_SPACE = "owner"

SERVER_INSTRUCTIONS = (
    "Fosved Office memory server. Контейнеры (spaces): слаги департаментов "
    "(dev, finance, legal, ...) + 'owner' — профиль владельца. search_memory возвращает "
    "профиль, свежие записи и совпадения с процентами релевантности одним ответом. "
    "Записи с taint=SECRET не покидают офис. Read-only по умолчанию."
)

# in-proc реестр подключений для /health
_CONNECTIONS = {}


def _allow_write():
    """FO-021: запись в память — только при явном FOSVED_MCP_ALLOW_WRITE=1.
    Читается на вызове (env может выставить деплой после импорта модуля)."""
    return os.environ.get("FOSVED_MCP_ALLOW_WRITE", "0") == "1"


# ── Доступ к БД офиса (лениво, без подъёма Flask) ────────────────────────
def _conn():
    os.environ.setdefault("DATABASE_PATH", str(BASE_DIR / "data"))
    db_dir = Path(os.environ["DATABASE_PATH"])
    db_dir.mkdir(parents=True, exist_ok=True)
    import sqlite3
    c = sqlite3.connect(str(db_dir / "custom.db"))
    c.row_factory = sqlite3.Row
    return c


def ensure_tables():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, chat_id TEXT DEFAULT '0',
            content TEXT NOT NULL, status TEXT DEFAULT 'active',
            source_dialog_ids TEXT DEFAULT '[]', confidence REAL DEFAULT 0.8,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))
        """)
        c.execute("""CREATE TABLE IF NOT EXISTS mcp_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, space TEXT NOT NULL, content TEXT NOT NULL,
            tags TEXT DEFAULT '[]', source TEXT DEFAULT 'mcp',
            created_at TEXT DEFAULT (datetime('now')))
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_mcp_memory_space ON mcp_memory(space)")


def list_spaces():
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT dept FROM facts WHERE dept IS NOT NULL").fetchall()
        spaces = {r["dept"] for r in rows if r["dept"]}
        spaces.add(OWNER_SPACE)
        rows2 = c.execute("SELECT DISTINCT space FROM mcp_memory").fetchall()
        spaces |= {r["space"] for r in rows2}
    return sorted(spaces)


def _check_space(space):
    """Жёсткая изоляция контейнеров: чужой/несуществующий space — громкая ошибка."""
    if not space:
        raise ValueError("space обязателен (департамент или 'owner')")
    if space not in list_spaces():
        raise ValueError(f"space '{space}' не существует. Доступные: {list_spaces()}")


# ── Скор релевантности (percent, семантика supermemory без векторов) ─────
def _relevance_percent(query, text):
    q_tokens = {t for t in re.findall(r"[a-zа-я0-9]{3,}", (query or "").lower())}
    t_tokens = {t for t in re.findall(r"[a-zа-я0-9]{3,}", (text or "").lower())}
    if not q_tokens:
        return 0
    overlap = len(q_tokens & t_tokens)
    return round(100.0 * overlap / len(q_tokens))


def _search_facts(space, query, limit):
    with _conn() as c:
        rows = c.execute(
            "SELECT content, confidence, created_at FROM facts WHERE dept=? AND status='active' ORDER BY id DESC LIMIT 500",
            [space if space != OWNER_SPACE else "__none__"]).fetchall()
    scored = []
    for r in rows:
        pct = _relevance_percent(query, r["content"])
        if pct > 0:
            scored.append({"source": "facts", "content": r["content"], "confidence": r["confidence"],
                           "relevance_pct": pct, "created_at": r["created_at"]})
    scored.sort(key=lambda x: -x["relevance_pct"])
    return scored[:limit]


def _search_mcp_memory(space, query, limit):
    with _conn() as c:
        rows = c.execute("SELECT content, tags, created_at FROM mcp_memory WHERE space=? ORDER BY id DESC LIMIT 500",
                         [space]).fetchall()
    scored = []
    for r in rows:
        pct = _relevance_percent(query, r["content"])
        if pct > 0:
            scored.append({"source": "memory", "content": r["content"], "tags": json.loads(r["tags"] or "[]"),
                           "relevance_pct": pct, "created_at": r["created_at"]})
    scored.sort(key=lambda x: -x["relevance_pct"])
    return scored[:limit]


def _owner_profile_block():
    """Профиль владельца FO-019 одним вызовом (static + buckets summary)."""
    try:
        from proxy.owner_profile import get_owner_profile
        prof = get_owner_profile()
        return {"static": prof.get("static", {}), "version": prof.get("version")}
    except Exception as e:
        return {"error": f"profile unavailable: {e}"}


# ── Тулзы ────────────────────────────────────────────────────────────────
def tool_search_memory(args):
    query = args.get("query", "")
    space = args.get("space") or OWNER_SPACE
    limit = min(int(args.get("limit", 10)), 50)
    _check_space(space)
    matches = _search_facts(space, query, limit) + _search_mcp_memory(space, query, limit)
    matches.sort(key=lambda x: -x["relevance_pct"])
    matches = matches[:limit]
    result = {
        "space": space,
        "profile": _owner_profile_block() if space == OWNER_SPACE else None,
        "recent": _recent(space, 3),
        "matches": matches,
        "count": len(matches),
    }
    return result


def _recent(space, limit):
    with _conn() as c:
        if space == OWNER_SPACE:
            rows = c.execute("SELECT content, created_at FROM mcp_memory WHERE space=? ORDER BY id DESC LIMIT ?",
                             [space, limit]).fetchall()
        else:
            rows = c.execute("SELECT content, created_at FROM facts WHERE dept=? AND status='active' ORDER BY id DESC LIMIT ?",
                             [space, limit]).fetchall()
    return [{"content": r["content"], "created_at": r["created_at"]} for r in rows]


def tool_list_memory(args):
    space = args.get("space") or OWNER_SPACE
    limit = min(int(args.get("limit", 20)), 100)
    _check_space(space)
    return {"space": space, "items": _recent(space, limit), "spaces": list_spaces()}


def tool_graph(args):
    space = args.get("space") or OWNER_SPACE
    entity = args.get("entity", "")
    _check_space(space)
    with _conn() as c:
        rows = c.execute("SELECT content FROM facts WHERE dept=? AND status='active' ORDER BY id DESC LIMIT 800",
                         [space if space != OWNER_SPACE else "__none__"]).fetchall()
        rows += c.execute("SELECT content FROM mcp_memory WHERE space=? ORDER BY id DESC LIMIT 800",
                          [space]).fetchall()
    links = []
    ent_l = entity.lower()
    for r in rows:
        text_l = r["content"].lower()
        if ent_l and ent_l in text_l:
            links.append(r["content"])
    return {"space": space, "entity": entity, "degree": len(links), "linked": links[:30]}


def tool_add_memory(args):
    if not _allow_write():
        raise PermissionError("add_memory: сервер в read-only (FOSVED_MCP_ALLOW_WRITE=1 чтобы включить)")
    space = args.get("space") or OWNER_SPACE
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text пуст")
    _check_space(space)
    tags = json.dumps(args.get("tags") or [], ensure_ascii=False)
    with _conn() as c:
        c.execute("INSERT INTO mcp_memory (space, content, tags, source) VALUES (?,?,?,?)",
                  [space, text, tags, "mcp"])
    return {"ok": True, "space": space, "bytes": len(text)}


TOOLS = [
    {"name": "search_memory", "description": "Профиль (owner) + recent + совпадения с процентами релевантности одним ответом",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "space": {"type": "string"}, "limit": {"type": "integer"}},
         "required": ["query"]}},
    {"name": "list_memory", "description": "Последние записи контейнера + список контейнеров",
     "inputSchema": {"type": "object", "properties": {
         "space": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "graph", "description": "Связи сущности в фактах контейнера",
     "inputSchema": {"type": "object", "properties": {
         "space": {"type": "string"}, "entity": {"type": "string"}}, "required": ["entity"]}},
    {"name": "add_memory", "description": "Добавить запись (read-only по умолчанию)",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string"}, "space": {"type": "string"}, "tags": {"type": "array"}},
         "required": ["text"]}},
]

TOOL_FUNCS = {"search_memory": tool_search_memory, "list_memory": tool_list_memory,
              "graph": tool_graph, "add_memory": tool_add_memory}


# ── MCP JSON-RPC слой ────────────────────────────────────────────────────
def handle_request(payload, client_id=None):
    """Один JSON-RPC вызов → ответ. Лог mcp_call + Guardian на каждый tools/call."""
    method = payload.get("method", "")
    req_id = payload.get("id")
    params = payload.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    try:
        if method == "initialize":
            cid = client_id or uuid.uuid4().hex[:12]
            _CONNECTIONS[cid] = {"ts": time.time(), "client": (params.get("clientInfo") or {}).get("name", "unknown")}
            _audit_mcp_call(cid, "initialize", params.get("clientInfo"))
            return ok({"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                       "instructions": SERVER_INSTRUCTIONS})

        if method == "tools/list":
            return ok({"tools": TOOLS})

        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            # Guardian: внешний агент действует под правилами FO-015; лог mcp_call
            from proxy.guardian import check
            verdict = check("mcp-agent", f"mcp__{name}", _ask=False)
            if verdict["verdict"] != "allow":
                _audit_mcp_call(client_id, name, args, denied=True)
                return err(-32001, f"Guardian: mcp__{name} denied")
            _audit_mcp_call(client_id, name, args)
            func = TOOL_FUNCS.get(name)
            if not func:
                return err(-32602, f"unknown tool: {name}")
            result = func(args)
            # Taint-контур: ничего секретного наружу (env-redact, общий модуль с FO-022)
            return ok({"content": [{"type": "text", "text": json.dumps(
                json.loads(redact_text(json.dumps(result, ensure_ascii=False))), ensure_ascii=False)}]})

        if method == "ping":
            return ok({})

        return err(-32601, f"method not found: {method}")
    except ValueError as e:
        return err(-32000, str(e))  # громкая ошибка cross-space/изоляции
    except PermissionError as e:
        return err(-32002, str(e))
    except Exception as e:
        return err(-32603, f"internal: {e}")


def _audit_mcp_call(client_id, what, details, denied=False):
    """Лог mcp_call: кто/что/зачем — поверх transport-лога (требование наряда)."""
    try:
        from proxy.core import _log_audit
        _log_audit("mcp_call", {"client": client_id, "tool": what,
                                "args_keys": sorted((details or {}).keys()) if isinstance(details, dict) else None,
                                "denied": denied}, "mcp")
    except Exception:
        pass  # аудит не должен ронять транспорт; дублирующий след — в _CONNECTIONS


def connections_status():
    return {"count": len(_CONNECTIONS),
            "clients": [{"id": k, "client": v["client"], "connected_at": v["ts"]} for k, v in _CONNECTIONS.items()]}


# ── stdio-транспорт ──────────────────────────────────────────────────────
def run_stdio():
    ensure_tables()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32700, "message": f"parse error: {e}"}}), flush=True)
            continue
        cid = (payload.get("params") or {}).get("_client_id")
        print(json.dumps(handle_request(payload, client_id=cid), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        run_stdio()
    else:
        print("usage: python3 proxy/mcp_server.py --stdio", file=sys.stderr)
