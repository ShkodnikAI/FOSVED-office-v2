#!/usr/bin/env python3
"""proxy/chain_durable.py — FO-027: durable-степы цепочек (чекпоинты + resume).

Эталон паттерна — Temporal/Inngest durable execution:
  - каждая степа персистится ДО запуска (status=pending), результат — ПОСЛЕ
    (ok/failed): крах процесса между ними возобновляем;
  - идемпотентность: input_hash = sha256(chain_id + step_num + dept + query
    [+ hash_extra для peer-контекста раунда]); степа со status=ok и тем же
    hash переиспользуется БЕЗ LLM-вызова (счётчик вызовов = 0);
  - hash разошёлся (query/контекст изменился) → степа инвалидна,
    исполняется заново (детерминизм против молчаливой неактуальности);
  - TTL: цепочки старше 14 дней удаляются; pending/failed без прогресса
    >24 ч → status=expired (алерт владельцу — из /cron/night, mlog-фаза).

Место: слой ПОД ExecuteChain v2 (FO-026) — sequential персистится mlog-хуками
в dept/chain.mlog (та же таблица), parallel/debate — здесь, через
run_durable_step, обёртку над _invoke_step.
"""
import hashlib
import os
from datetime import datetime, timezone

from proxy.core import _log_audit, _query, log

TTL_DAYS = 14
EXPIRE_HOURS = 24


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema():
    """Таблица chain_steps по образцу quest_checkpoints (app.mlog:173).
    Расширения против минимальной схемы наряда: dept_chain + query —
    нужны для resume (/chain continue) и авто-resume.
    Схема через _query — та же БД, что и все операции (в тестах путь
    DATABASE_PATH фиксируется первым импортом core)."""
    _query("""CREATE TABLE IF NOT EXISTS chain_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chain_id TEXT, chat_id TEXT, step_num REAL, dept TEXT, mode TEXT,
            input_hash TEXT, reply TEXT, model TEXT, tokens_in TEXT, tokens_out TEXT,
            cost_usd TEXT, status TEXT DEFAULT 'pending',
            dept_chain TEXT DEFAULT '', query TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""")
    _query("CREATE INDEX IF NOT EXISTS idx_chain_steps_chain ON chain_steps(chain_id, step_num, dept)")


def step_hash(chain_id, step_num, dept, query, hash_extra=""):
    """Идемпотентность степы: sha256(chain_id + step_num + dept + query[+extra])."""
    raw = f"{chain_id}|{step_num}|{dept}|{query}|{hash_extra}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mark_pending(chain_id, step_num, dept, mode, chat_id, h, dept_chain="", query=""):
    """Запись ДО вызова (Temporal: persist before run)."""
    row = _query("SELECT id FROM chain_steps WHERE chain_id=? AND step_num=? AND dept=? ORDER BY id DESC LIMIT 1",
                 (chain_id, step_num, dept), fetch=True)
    if row:
        _query("UPDATE chain_steps SET status='pending', input_hash=?, updated_at=? WHERE id=?",
               (h, _now_iso(), row[0]["id"]))
    else:
        _query("""INSERT INTO chain_steps (chain_id, chat_id, step_num, dept, mode, input_hash, status, dept_chain, query, created_at, updated_at)
                  VALUES (?,?,?,?,?,?, 'pending', ?, ?, ?, ?)""",
               (chain_id, chat_id, step_num, dept, mode, h, dept_chain, query,
                _now_iso(), _now_iso()))


def _mark_done(chain_id, step_num, dept, status, reply="", model="",
               tokens_in="0", tokens_out="0", cost_usd="0"):
    _query("""UPDATE chain_steps SET status=?, reply=?, model=?, tokens_in=?, tokens_out=?,
              cost_usd=?, updated_at=?
              WHERE chain_id=? AND step_num=? AND dept=? AND status='pending'""",
           (status, reply[:20000], model, str(tokens_in), str(tokens_out),
            str(cost_usd), _now_iso(), chain_id, step_num, dept))


def run_durable_step(dept, query, chat_id, chain_id, step_num, mode,
                     invoke_fn, hash_extra="", dept_chain="", peer_context=None):
    """Идемпотентная степа: reuse ok-степы без LLM-вызова, pending→invoke→ok/failed.

    invoke_fn(dept, query, chat_id, chain_id, step_num, peer_context) -> str.
    peer_context (raунд 2 debate) входит в invoke-вызов и НЕ входит в hash
    отдельно от hash_extra — вызывающий обязан включить его в hash_extra
    (детерминизм: другой peer → другой hash → переисполнение).
    Исключение invoke_fn → status=failed + проброс (caller решает деградацию).
    """
    ensure_schema()
    h = step_hash(chain_id, step_num, dept, query, hash_extra)
    row = _query("SELECT status, reply, input_hash FROM chain_steps WHERE chain_id=? AND step_num=? AND dept=? ORDER BY id DESC LIMIT 1",
                 (chain_id, step_num, dept), fetch=True)
    if row and row[0]["status"] == "ok" and row[0]["input_hash"] == h:
        _log_audit("chain_step_reused", {"chain_id": chain_id, "step_num": step_num,
                                         "dept": dept, "hash": h[:12]}, dept=dept)
        return {"reply": row[0]["reply"] or "", "reused": True}

    _mark_pending(chain_id, step_num, dept, mode, chat_id, h, dept_chain, query)
    try:
        reply = invoke_fn(dept, query, chat_id, chain_id, step_num, peer_context)
        _mark_done(chain_id, step_num, dept, "ok", reply=reply)
        return {"reply": reply, "reused": False}
    except Exception as e:
        _mark_done(chain_id, step_num, dept, "failed", reply=f"error: {e}")
        raise


def cleanup():
    """TTL: удалить степы старше 14 дней; pending/failed без прогресса >24 ч
    → status=expired. Возвращает данные для алерта владельцу."""
    ensure_schema()
    _query("DELETE FROM chain_steps WHERE created_at < datetime('now', ?)",
           (f"-{TTL_DAYS} days",))
    rows = _query("""SELECT chain_id, COUNT(*) AS c FROM chain_steps
                     WHERE status IN ('pending','failed')
                       AND updated_at < datetime('now', ?)
                     GROUP BY chain_id""",
                  (f"-{EXPIRE_HOURS} hours",), fetch=True)
    expired = [{"chain_id": r["chain_id"], "steps": r["c"]} for r in rows or []]
    if expired:
        _query("""UPDATE chain_steps SET status='expired', updated_at=?
                  WHERE status IN ('pending','failed')
                    AND updated_at < datetime('now', ?)""",
               (_now_iso(), f"-{EXPIRE_HOURS} hours"))
    return {"expired_chains": expired, "ttl_days": TTL_DAYS,
            "expire_hours": EXPIRE_HOURS}
