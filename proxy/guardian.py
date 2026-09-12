#!/usr/bin/env python3
"""proxy/guardian.py — FO-015: Guardian permission-matrix.

Двойной контур прав департаментов (эталон: sst/opencode permission engine):
  1-й контур: visible_tools() — deny скрывает тулзу из выдачи/схем для департамента;
  2-й контур: check()/enforce() — отказ на уровне исполнения независимо от послушания модели.

Матрица: guardian_rules {dept, permission, pattern, action}, оценка last-match-wins
(правила в порядке добавления; последний совпавший паттерн решает). Wildcard — fnmatch
(`mcp__github__*`, `http_*`, `shell_git*`).

action=ask: запрос владельцу в Telegram (inline «Раз / Всегда / Нет»);
«Всегда» → session-approved (живёт в памяти процесса: переживает рестарт задачи,
умирает на деплое). Каждая выдача права и каждый отказ — в audit_log.

Базовая политика — guardian_base.json в репо (версионируется коммитом, условие SG-F3);
per-dept overlay — в таблице guardian_rules; любое изменение правил — запись в audit_log.
"""
import fnmatch
import json
import re
import shlex
import threading
import time
import uuid

from flask import request, jsonify

from proxy.core import app, DB_FILE, _db, _query, _log_audit, _get_setting, log
from proxy.telegram import _tg_send_message, TELEGRAM_BOT_TOKEN

BASE_CONFIG_PATH = None  # выставляется из BASE_DIR при импорте (см. ниже)
GUARDIAN_DEFAULT_ACTION = "allow"

_lock = threading.Lock()
# session-approved: {(dept, permission_pattern)} — «Всегда» до рестарта процесса
_session_approved = set()
# ожидающие ask-запросы: {ask_id: {dept, permission, chat_id, ts, status}}
_pending_asks = {}
ASK_TTL_SECONDS = 3600

# ── Схема БД ─────────────────────────────────────────────────────────────
def ensure_guardian_schema():
    with _db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS guardian_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dept TEXT NOT NULL DEFAULT '*',
            permission TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('allow','ask','deny')),
            source TEXT NOT NULL DEFAULT 'overlay',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS guardian_asks (
            ask_id TEXT PRIMARY KEY,
            dept TEXT NOT NULL,
            permission TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_guardian_rules_dept ON guardian_rules(dept)")


# ── Базовая политика (репо) + overlay (БД) ───────────────────────────────
def _load_base_rules():
    """Базовые правила из guardian_base.json рядом с модулем (версионируется)."""
    path = _base_config_path()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("rules", []), cfg.get("default_action", GUARDIAN_DEFAULT_ACTION)
    except Exception as e:
        log.warning(f"[guardian] base config read failed ({e}); default_action={GUARDIAN_DEFAULT_ACTION}")
        return [], GUARDIAN_DEFAULT_ACTION


def _base_config_path():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "guardian_base.json"


def rules_for(dept):
    """Все правила, применимые к dept: базовые (репо) + overlay (БД), в порядке приоритета.

    Порядок = last-match-wins: сначала базовые, затем overlay (overlay добавлен позже —
    перекрывает базу при совпадении обоих).
    """
    base_rules, _ = _load_base_rules()
    rules = [{"dept": r.get("dept", "*"), "permission": r["permission"],
              "action": r["action"], "source": "base"} for r in base_rules]
    rows = _query("SELECT dept, permission, action, source FROM guardian_rules WHERE dept IN (?, '*') ORDER BY id",
                  [dept], fetch=True) or []
    for r in rows:
        rules.append({"dept": r["dept"], "permission": r["permission"],
                      "action": r["action"], "source": f"overlay:{r['source']}"})
    return rules


def match_action(dept, permission):
    """Last-match-wins: последний совпавший паттерн решает. Возвращает (action, rule|None)."""
    _, default_action = _load_base_rules()
    decision = (default_action, None)
    for r in rules_for(dept):
        if fnmatch.fnmatchcase(permission, r["permission"]):
            decision = (r["action"], r)
    return decision


# ── Session-approved («Всегда») ──────────────────────────────────────────
def approve_session(dept, permission):
    with _lock:
        _session_approved.add((dept, permission))
    _log_audit("guardian_approved_always", {"dept": dept, "permission": permission}, "guardian")


def _is_session_approved(dept, permission):
    with _lock:
        if (dept, permission) in _session_approved:
            return True
        # точечное совпадение с wildcard-паттерном из approvals
        return any(fnmatch.fnmatchcase(permission, p) for d, p in _session_approved if d == dept)


def reset_session():
    """Деплой/рестарт процесса сбрасывает «Всегда» (инвариант наряда)."""
    with _lock:
        _session_approved.clear()


# ── ask-flow: Telegram inline «Раз / Всегда / Нет» ───────────────────────
def request_ask(dept, permission, chat_id=None):
    """Отправляет владельцу запрос права. Возвращает ask_id."""
    ask_id = uuid.uuid4().hex[:16]
    chat_id = chat_id or _owner_chat_id()
    with _db() as conn:
        conn.execute("INSERT INTO guardian_asks (ask_id, dept, permission, chat_id) VALUES (?,?,?,?)",
                     [ask_id, dept, permission, str(chat_id)])
    kb = {"inline_keyboard": [[
        {"text": "Раз", "callback_data": f"guardian:{ask_id}:once"},
        {"text": "Всегда", "callback_data": f"guardian:{ask_id}:always"},
        {"text": "Нет", "callback_data": f"guardian:{ask_id}:deny"},
    ]]}
    _tg_send_message(
        str(chat_id),
        f"🛡 Guardian: департамент «{dept}» запрашивает право\n<code>{permission}</code>",
        reply_markup=kb,
    )
    _log_audit("guardian_ask", {"dept": dept, "permission": permission, "ask_id": ask_id}, "guardian")
    with _lock:
        _pending_asks[ask_id] = {"dept": dept, "permission": permission, "chat_id": str(chat_id),
                                 "ts": time.time(), "status": "pending"}
    return ask_id


def answer_ask(ask_id, decision):
    """decision ∈ once|always|deny. Возвращает итоговый вердикт."""
    with _lock:
        ask = _pending_asks.get(ask_id)
    if not ask:
        row = _query("SELECT dept, permission, chat_id, status FROM guardian_asks WHERE ask_id = ?",
                     [ask_id], fetch=True)
        if not row:
            return {"ok": False, "error": "unknown ask_id"}
        ask = {"dept": row[0]["dept"], "permission": row[0]["permission"], "status": row[0]["status"]}
    dept, permission = ask["dept"], ask["permission"]
    if decision == "once":
        verdict = "allow"
        note = "owner granted once"
    elif decision == "always":
        approve_session(dept, permission)
        verdict = "allow"
        note = "owner granted for session"
    else:
        verdict = "deny"
        note = "owner denied"
    with _db() as conn:
        conn.execute("UPDATE guardian_asks SET status = ? WHERE ask_id = ?", [decision, ask_id])
    with _lock:
        _pending_asks.pop(ask_id, None)
    _log_audit("guardian_ask_answer", {"dept": dept, "permission": permission,
                                       "decision": decision, "verdict": verdict}, "guardian")
    return {"ok": True, "verdict": verdict, "note": note}


def _owner_chat_id():
    val = _get_setting("owner_chat_id")
    if val:
        return val
    import os
    return os.environ.get("OWNER_CHAT_ID") or os.environ.get("TELEGRAM_ARCHIVE_CHANNEL_ID", "")


# ── Главный вход: check (2-й контур) ─────────────────────────────────────
def check(dept, permission, chat_id=None, _ask=True):
    """Вердикт на (dept, permission). deny → запрет; ask → запрос владельцу (или session-approve).

    Возвращает {verdict: allow|deny, action, rule, reason}.
    """
    action, rule = match_action(dept, permission)
    if action == "allow":
        return {"verdict": "allow", "action": action, "rule": rule, "reason": "matched allow"}
    if action == "deny":
        _log_audit("guardian_deny", {"dept": dept, "permission": permission}, "guardian")
        return {"verdict": "deny", "action": action, "rule": rule, "reason": "matched deny"}
    # action == ask
    if _is_session_approved(dept, permission):
        return {"verdict": "allow", "action": action, "rule": rule, "reason": "session-approved"}
    if not _ask:
        return {"verdict": "deny", "action": action, "rule": rule, "reason": "ask required but interactive ask disabled"}
    ask_id = request_ask(dept, permission, chat_id)
    return {"verdict": "deny", "action": action, "rule": rule,
            "reason": "ask sent to owner", "ask_id": ask_id}


class GuardianDenied(PermissionError):
    """Второй контур: прямой отказ на исполнении."""


def enforce(dept, permission, chat_id=None):
    """Как check, но deny бросает GuardianDenied (защита не зависит от послушания модели)."""
    res = check(dept, permission, chat_id=chat_id)
    if res["verdict"] != "allow":
        raise GuardianDenied(f"Guardian: {dept} denied '{permission}' ({res['reason']})")
    return res


# ── 1-й контур: deny скрывает тулзу из выдачи ────────────────────────────
def visible_tools(dept, tools):
    """Фильтр схем тулз/системного промпта: запрещённые не попадают к LLM вообще."""
    visible = []
    for t in tools:
        name = t if isinstance(t, str) else t.get("name", "")
        action, _ = match_action(dept, name)
        if action != "deny":
            visible.append(t)
    return visible


# ── bash-подстраховка: префикс-паттерн из разобранной команды ────────────
def shell_permission(command):
    """git status --porcelain → shell_git_status; rm -rf / → shell_rm.
    Префикс + подкоманда (argv-арность без tree-sitter, как решено в наряде)."""
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = command.split()
    if not argv:
        return "shell_empty"
    prog = argv[0].rsplit("/", 1)[-1]
    sub = ""
    for a in argv[1:]:
        if a.startswith("-"):
            continue
        clean = re.sub(r"[^a-z0-9]", "", a.lower())[:24]
        if clean:
            sub = f"_{clean}"
            break
    return f"shell_{prog}{sub}"


# ── Управление правилами (overlay) — каждое изменение в audit_log ────────
def add_rule(dept, permission, action, source="api"):
    assert action in ("allow", "ask", "deny"), "bad action"
    with _db() as conn:
        conn.execute("INSERT INTO guardian_rules (dept, permission, action, source) VALUES (?,?,?,?)",
                     [dept, permission, action, source])
    _log_audit("guardian_rule_add", {"dept": dept, "permission": permission, "action": action}, "guardian")


def remove_rule(rule_id):
    row = _query("SELECT id FROM guardian_rules WHERE id = ?", [rule_id], fetch=True)
    with _db() as conn:
        conn.execute("DELETE FROM guardian_rules WHERE id = ?", [rule_id])
    _log_audit("guardian_rule_remove", {"rule_id": rule_id, "existed": bool(row)}, "guardian")


def seed_from_base():
    """Совместимость: базовая политика читается из guardian_base.json на каждой оценке
    (живой источник; аудит изменения = коммит файла, условие SG-F3). В DB-оверлей
    правила базы НЕ копируются — оверлей только для per-dept правил (API/frontmatter),
    иначе оверлей навсегда перебивал бы правки базового конфига."""
    ensure_guardian_schema()
    return 0


# ── HTTP API ─────────────────────────────────────────────────────────────
@app.post("/guardian/check")
def guardian_check_endpoint():
    """mlog/департаменты спрашивают право: {dept, permission, chat_id?} → verdict."""
    d = request.get_json(force=True) or {}
    dept, permission = d.get("dept", ""), d.get("permission", "")
    if not dept or not permission:
        return jsonify({"error": "dept and permission required"}), 400
    res = check(dept, permission, chat_id=d.get("chat_id"), _ask=d.get("interactive", True))
    return jsonify(res)


@app.get("/guardian/rules")
def guardian_rules_endpoint():
    dept = request.args.get("dept", "*")
    return jsonify({"dept": dept, "rules": rules_for(dept)})


@app.post("/guardian/rules")
def guardian_add_rule_endpoint():
    d = request.get_json(force=True) or {}
    if not d.get("permission") or d.get("action") not in ("allow", "ask", "deny"):
        return jsonify({"error": "permission and action (allow|ask|deny) required"}), 400
    add_rule(d.get("dept", "*"), d["permission"], d["action"], source="api")
    return jsonify({"ok": True})


@app.delete("/guardian/rules/<int:rule_id>")
def guardian_remove_rule_endpoint(rule_id):
    remove_rule(rule_id)
    return jsonify({"ok": True})


@app.post("/guardian/answer")
def guardian_answer_endpoint():
    d = request.get_json(force=True) or {}
    ask_id, decision = d.get("ask_id", ""), d.get("decision", "")
    if not ask_id or decision not in ("once", "always", "deny"):
        return jsonify({"error": "ask_id and decision (once|always|deny) required"}), 400
    return jsonify(answer_ask(ask_id, decision))


@app.post("/guardian/telegram-callback")
def guardian_telegram_callback():
    """Приём callback_query от Telegram (маршрутизация из mlog-вебхука или прямой вебхук)."""
    d = request.get_json(force=True) or {}
    cq = d.get("callback_query") or {}
    data = cq.get("data", "")
    if not data.startswith("guardian:"):
        return jsonify({"ok": False, "error": "not a guardian callback"}), 400
    _, ask_id, decision = data.split(":", 2)
    res = answer_ask(ask_id, decision)
    if TELEGRAM_BOT_TOKEN and cq.get("id"):
        try:
            import requests as _rq
            _rq.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                     json={"callback_query_id": cq["id"], "text": str(res.get("verdict", res))}, timeout=5)
        except Exception as e:
            log.warning(f"[guardian] answerCallbackQuery failed: {e}")
    return jsonify(res)


# Импорт модуля = схема готова, seeded (идемпотентно), при деплое «Всегда» умирает само.
try:
    ensure_guardian_schema()
    seed_from_base()
except Exception as e:  # pragma: no cover — БД может быть недоступна в момент сбора тестов
    log.warning(f"[guardian] deferred schema init: {e}")
