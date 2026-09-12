"""FO-017: Dialog v2 — Part-модель сообщений + event-log с per-session seq.

Наряд #83 (пакет G, волна G1). Эталон: sst/opencode — packages/schema/src/v1/
session.ts (12 типов Part, ToolPart state-машина) + packages/core/src/session/
sql.ts (part — отдельная таблица; session_message — event-sourced лог с
per-session seq UNIQUE). Урок opencode: схема выбирается один раз.

Схема v1 (типы Part по наряду: text, tool_call, tool_result, retry,
compaction, voice):
  dialog_message(id, session_id, role, dept, data JSON, created_at)
  dialog_part(id, message_id, type, data JSON, created_at)
  session_message(id, session_id, type, seq, data JSON, created_at)
                  UNIQUE(session_id, seq) — append-only лента событий

Принципы:
- dialog_history (legacy) НЕ трогается до ревизии FM3 — обратимо; миграция
  копирует реплики в message+TextPart с водяным знаком и откатом.
- Каждая запись идёт через ленту событий: message.created → part.added*;
  порядок восстановления по seq, темпоральность из коробки.
- Совместимость: llm_verifier/call_python контракты не затронуты;
  compaction (FO-016) пишет Part-тип record_compaction().
"""
import json
import sqlite3
import threading

from proxy.core import _db, db_lock, log
# ВАЖНО: _log_error НЕ импортируется на верхнем уровне — init_db() создаёт
# схему v2 до того, как core определит _log_error (частичная инициализация
# модуля); в рантайме берём лениво внутри обработчиков ошибок.

# Типы Part v1 (наряд #83). Расширение — новым литералом, не перезаписью.
PART_TYPES = ("text", "tool_call", "tool_result", "retry", "compaction", "voice")
EVENT_TYPES = ("message.created", "part.added", "part.updated", "compaction")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dialog_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    dept TEXT DEFAULT '',
    data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS dialog_part (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS session_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    type TEXT NOT NULL,
    seq INTEGER NOT NULL,
    data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_dmsg_session ON dialog_message(session_id, id);
CREATE INDEX IF NOT EXISTS idx_dpart_message ON dialog_part(message_id, id);
CREATE INDEX IF NOT EXISTS idx_sev_session ON session_message(session_id, seq);
"""

_MIGRATION_WATERMARK = "dialog_v2_migrated_upto"


def ensure_dialog_schema():
    """Создать таблицы v2, если их нет. Вызывается из init_db (лениво —
    локальный импорт, чтобы не зациклить core ↔ dialog) и из эндпоинтов."""
    with db_lock:
        c = _db()
        try:
            c.executescript(_SCHEMA)
            c.commit()
        finally:
            c.close()


def _log_err(msg, **kw):
    """Ленивая обёртка _log_error (см. комментарий к импортам)."""
    try:
        from proxy.core import _log_error
        _log_error(msg, **kw)
    except Exception as e:
        log.warning(f"dialog: error-log failed ({e}): {msg}")


def _j(data):
    return json.dumps(data or {}, ensure_ascii=False)


def _next_seq(c, session_id):
    row = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS nxt FROM session_message WHERE session_id = ?",
                    (session_id,)).fetchone()
    return int(row["nxt"])


def _emit(c, session_id, ev_type, data):
    """Событие в ленту. UNIQUE(session_id, seq) — гонки ловим ретраем."""
    for attempt in range(3):
        try:
            seq = _next_seq(c, session_id)
            c.execute("INSERT INTO session_message (session_id, type, seq, data) VALUES (?, ?, ?, ?)",
                      (session_id, ev_type, seq, _j(data)))
            return seq
        except sqlite3.IntegrityError:
            if attempt == 2:
                raise
            log.warning(f"dialog: seq race on {session_id}, retry {attempt + 1}")
    return None


# ────────────────────────── запись ──────────────────────────

def save_message(session_id, role, content="", dept="", parts=None,
                 source=None, source_id=None, meta=None, created_at=None):
    """Сохранить реплику как message + Parts + события ленты.

    parts: None → один TextPart {"text": content}; иначе список
    {"type": "...", "data": {...}} (type ∈ PART_TYPES).
    source/source_id — происхождение (dialog_history, app.mlog, api).
    Возврат: {"message_id", "part_ids", "seq"} | None при ошибке БД.
    """
    if not session_id:
        raise ValueError("session_id required")
    if parts is None:
        parts = [{"type": "text", "data": {"text": content or ""}}]
    for p in parts:
        if p.get("type") not in PART_TYPES:
            raise ValueError(f"unknown part type: {p.get('type')!r} (v1: {PART_TYPES})")
    ensure_dialog_schema()
    data = {"source": source or "api", **(meta or {})}
    if source_id is not None:
        data["source_id"] = source_id
    with db_lock:
        c = _db()
        try:
            if created_at:
                cur = c.execute("INSERT INTO dialog_message (session_id, role, dept, data, created_at) VALUES (?, ?, ?, ?, ?)",
                                (session_id, role, dept, _j(data), created_at))
            else:
                cur = c.execute("INSERT INTO dialog_message (session_id, role, dept, data) VALUES (?, ?, ?, ?)",
                                (session_id, role, dept, _j(data)))
            message_id = cur.lastrowid
            seq = _emit(c, session_id, "message.created",
                        {"message_id": message_id, "role": role, "dept": dept})
            part_ids = []
            for p in parts:
                cur = c.execute("INSERT INTO dialog_part (message_id, type, data) VALUES (?, ?, ?)",
                                (message_id, p["type"], _j(p.get("data"))))
                part_id = cur.lastrowid
                part_ids.append(part_id)
                _emit(c, session_id, "part.added",
                      {"message_id": message_id, "part_id": part_id, "part_type": p["type"]})
            c.commit()
            return {"message_id": message_id, "part_ids": part_ids, "seq": seq}
        except sqlite3.Error as e:
            _log_err(f"dialog save_message failed: {e}", source="dialog", kind="data_loss")
            return None
        finally:
            c.close()


def add_part(message_id, part_type, data):
    """Добавить Part к существующей реплике (+ part.added в ленту).
    Возврат: part_id | None."""
    if part_type not in PART_TYPES:
        raise ValueError(f"unknown part type: {part_type!r} (v1: {PART_TYPES})")
    ensure_dialog_schema()
    with db_lock:
        c = _db()
        try:
            row = c.execute("SELECT session_id FROM dialog_message WHERE id = ?", (message_id,)).fetchone()
            if not row:
                return None
            cur = c.execute("INSERT INTO dialog_part (message_id, type, data) VALUES (?, ?, ?)",
                            (message_id, part_type, _j(data)))
            part_id = cur.lastrowid
            _emit(c, row["session_id"], "part.added",
                  {"message_id": message_id, "part_id": part_id, "part_type": part_type})
            c.commit()
            return part_id
        except sqlite3.Error as e:
            _log_err(f"dialog add_part failed: {e}", source="dialog", kind="data_loss")
            return None
        finally:
            c.close()


def add_tool_call(session_id, message_id, tool_name, arguments=None, meta=None):
    """tool_call Part: {"tool": name, "arguments": …, "status": "pending"}.
    Возврат: part_id | None."""
    data = {"tool": tool_name, "arguments": arguments or {},
            "status": "pending", **(meta or {})}
    return add_part(message_id, "tool_call", data)


def add_tool_result(session_id, tool_call_part_id, result=None, ok=True, error=None):
    """tool_result Part, спаренный с tool_call (data.tool_call_part).
    Возврат: part_id | None."""
    data = {"tool_call_part": tool_call_part_id,
            "status": "completed" if ok else "error",
            "result": result, "error": error}
    return add_part_message_by_part(session_id, tool_call_part_id, "tool_result", data)


def add_part_message_by_part(session_id, part_id, part_type, data):
    """Внутреннее: добавить Part к message, которому принадлежит part_id."""
    ensure_dialog_schema()
    with db_lock:
        c = _db()
        try:
            row = c.execute("SELECT message_id FROM dialog_part WHERE id = ?", (part_id,)).fetchone()
            if not row:
                return None
            mid = row["message_id"]
            cur = c.execute("INSERT INTO dialog_part (message_id, type, data) VALUES (?, ?, ?)",
                            (mid, part_type, _j(data)))
            new_id = cur.lastrowid
            _emit(c, session_id, "part.added",
                  {"message_id": mid, "part_id": new_id, "part_type": part_type})
            c.commit()
            return new_id
        except sqlite3.Error as e:
            _log_err(f"dialog tool_result failed: {e}", source="dialog", kind="data_loss")
            return None
        finally:
            c.close()


def record_compaction(session_id, stats, dept=""):
    """Compaction-Part (связка с FO-016): компакция как типизированное
    событие ленты, а не текст в dialog_history. Возврат: part_id | None."""
    res = save_message(session_id, "system", content="", dept=dept,
                       parts=[{"type": "compaction", "data": stats}],
                       source="compaction")
    return res["part_ids"][0] if res else None


# ────────────────────────── чтение / восстановление ──────────────────────────

def get_session_events(session_id, from_seq=0, limit=1000):
    """Лента событий сессии по порядку seq (основа восстановления)."""
    ensure_dialog_schema()
    with db_lock:
        c = _db()
        try:
            rows = c.execute(
                "SELECT id, session_id, type, seq, data, created_at FROM session_message "
                "WHERE session_id = ? AND seq > ? ORDER BY seq ASC LIMIT ?",
                (session_id, int(from_seq), int(limit))).fetchall()
            return [dict(r) | {"data": json.loads(r["data"] or "{}")} for r in rows]
        finally:
            c.close()


def replay_session(session_id, upto_seq=None):
    """Восстановление состояния сессии из ленты событий (fold по seq).

    Возврат: {"messages": [{id, role, dept, data, parts: [{id, type, data}]}],
              "events_replayed": N, "max_seq": M}.
    Чистая функция поверх событий — детерминизм проверяется тестом на 1000.
    """
    events = get_session_events(session_id, limit=100000)
    if upto_seq is not None:
        events = [e for e in events if e["seq"] <= int(upto_seq)]
    messages_by_id = {}
    parts_by_id = {}
    order = []
    for ev in events:
        d = ev["data"]
        if ev["type"] == "message.created":
            mid = d.get("message_id")
            if mid not in messages_by_id:
                messages_by_id[mid] = {"id": mid, "parts": []}
                order.append(mid)
        elif ev["type"] == "part.added":
            mid, pid = d.get("message_id"), d.get("part_id")
            if mid not in messages_by_id:
                messages_by_id[mid] = {"id": mid, "parts": []}
                order.append(mid)
            parts_by_id[pid] = {"id": pid, "type": d.get("part_type"), "message_id": mid}
            messages_by_id[mid]["parts"].append(parts_by_id[pid])
    msgs = [messages_by_id[mid] for mid in order]
    return {"messages": msgs, "events_replayed": len(events),
            "max_seq": events[-1]["seq"] if events else 0}


def get_session_messages(session_id, limit=200):
    """Реплики сессии с вложенными Parts (обычное чтение, минуя ленту)."""
    ensure_dialog_schema()
    with db_lock:
        c = _db()
        try:
            mrows = c.execute(
                "SELECT id, session_id, role, dept, data, created_at FROM dialog_message "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, int(limit))).fetchall()
            out = []
            for m in reversed(mrows):
                prows = c.execute(
                    "SELECT id, type, data, created_at FROM dialog_part WHERE message_id = ? ORDER BY id",
                    (m["id"],)).fetchall()
                out.append({
                    "id": m["id"], "role": m["role"], "dept": m["dept"],
                    "data": json.loads(m["data"] or "{}"),
                    "created_at": m["created_at"],
                    "parts": [{"id": p["id"], "type": p["type"],
                               "data": json.loads(p["data"] or "{}"),
                               "created_at": p["created_at"]} for p in prows],
                })
            return out
        finally:
            c.close()


def get_part(part_id):
    """Один Part по id (для трейсов/графа — ссылка part_id разрешима)."""
    ensure_dialog_schema()
    with db_lock:
        c = _db()
        try:
            r = c.execute("SELECT id, message_id, type, data, created_at FROM dialog_part WHERE id = ?",
                          (part_id,)).fetchone()
            if not r:
                return None
            d = dict(r)
            d["data"] = json.loads(d["data"] or "{}")
            return d
        finally:
            c.close()


# ────────────────────────── миграция dialog_history ──────────────────────────

def migrate_dialog_history(batch=500, dry_run=False):
    """Копия реплик dialog_history → message + TextPart (+ события).

    - Старая таблица НЕ модифицируется (обратимо, до ревизии FM3).
    - Водяной знак system_settings["dialog_v2_migrated_upto"] — идемпотентно.
    - created_at реплики сохраняется; seq выдаётся в порядке (chat_id, id).
    Возврат: {"migrated", "dry_run", "watermark"}.
    """
    ensure_dialog_schema()
    from proxy.core import _get_setting, _query
    watermark = int(_get_setting(_MIGRATION_WATERMARK, "0") or 0)
    rows = _query(
        "SELECT id, chat_id, role, dept, content, created_at FROM dialog_history "
        "WHERE id > ? ORDER BY id ASC LIMIT ?", (watermark, int(batch)), fetch=True) or []
    migrated = 0
    last_id = watermark
    if not dry_run:
        with db_lock:
            c = _db()
            try:
                for r in rows:
                    sid = r["chat_id"] or "unknown"
                    data = {"source": "dialog_history", "source_id": r["id"]}
                    cur = c.execute(
                        "INSERT INTO dialog_message (session_id, role, dept, data, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (sid, r["role"] or "user", r["dept"] or "", _j(data), r["created_at"]))
                    mid = cur.lastrowid
                    _emit(c, sid, "message.created", {"message_id": mid, "role": r["role"]})
                    cur = c.execute("INSERT INTO dialog_part (message_id, type, data) VALUES (?, 'text', ?)",
                                    (mid, _j({"text": r["content"] or ""})))
                    pid = cur.lastrowid
                    _emit(c, sid, "part.added",
                          {"message_id": mid, "part_id": pid, "part_type": "text"})
                    migrated += 1
                    last_id = r["id"]
                if rows:
                    c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                              (_MIGRATION_WATERMARK, str(last_id)))
                c.commit()
            except sqlite3.Error as e:
                c.rollback()
                _log_err(f"dialog migration failed: {e}", source="dialog", kind="data_loss")
                return {"migrated": 0, "dry_run": False, "error": str(e)}
            finally:
                c.close()
    else:
        migrated = len(rows)
    return {"migrated": migrated, "dry_run": bool(dry_run), "watermark": last_id if not dry_run else watermark}


def rollback_migration():
    """Обратимость: удалить все v2-строки, происшедшие от dialog_history,
    и сбросить водяной знак. dialog_history не трогается — ничего не теряется."""
    ensure_dialog_schema()
    with db_lock:
        c = _db()
        try:
            cur = c.execute(
                "SELECT id FROM dialog_message WHERE json_extract(data, '$.source') = 'dialog_history'")
            mids = [r["id"] for r in cur.fetchall()]
            if not mids:
                c.execute("UPDATE system_settings SET value = '0' WHERE key = ?", (_MIGRATION_WATERMARK,))
                c.commit()
                return {"messages": 0, "parts": 0, "events": 0}
            ph = ",".join("?" * len(mids))
            srows = c.execute(
                f"SELECT DISTINCT session_id FROM dialog_message WHERE id IN ({ph})", mids).fetchall()
            sessions = [r["session_id"] for r in srows]
            cur = c.execute(f"SELECT COUNT(*) AS n FROM dialog_part WHERE message_id IN ({ph})", mids)
            removed_parts = cur.fetchone()["n"]
            c.execute(f"DELETE FROM dialog_part WHERE message_id IN ({ph})", mids)
            c.execute(f"DELETE FROM dialog_message WHERE id IN ({ph})", mids)
            # события чистим только в затронутых сессиях и только для
            # сообщений, которых больше не существует
            removed_events = 0
            for sid in sessions:
                cur = c.execute(
                    "DELETE FROM session_message WHERE session_id = ? AND "
                    "type IN ('message.created','part.added') AND "
                    "json_extract(data, '$.message_id') NOT IN (SELECT id FROM dialog_message)",
                    (sid,))
                removed_events += max(cur.rowcount, 0)
            c.execute("UPDATE system_settings SET value = '0' WHERE key = ?", (_MIGRATION_WATERMARK,))
            c.commit()
            return {"messages": len(mids), "parts": removed_parts, "events": removed_events}
        except sqlite3.Error as e:
            c.rollback()
            _log_err(f"dialog rollback failed: {e}", source="dialog", kind="data_loss")
            return {"error": str(e)}
        finally:
            c.close()
