#!/usr/bin/env python3
"""proxy/narad_queue.py — FO-047: диспетчер нарядной очереди (диспатч #161).

Дополняет нарядную модель FO-046 исполнением: наряды в статусе
approved/queued с назначенным отделом берутся в работу и исполняются через
готовый мост /chain/step (mlogserve → ChainDispatchDept, единая
диспетчеризация FO-026). Наряды анализа-отделов проходят тем же путём,
что и цепочки.

Durable-паттерн — по образцу chain_durable (FO-027, Temporal):
  - степа персистится ДО вызова (status=pending), результат — ПОСЛЕ (ok/failed):
    крах процесса между ними возобновляем (авто-resume на следующем тике);
  - наряд берётся по одному за тик (worst-отдел не держит очередь);
  - attempts > NARAD_MAX_ATTEMPTS → наряд блокируется (внимание владельца),
    причина в result.

Точки входа:
  - tick()            — один такт: resume зависшего → или исполнить следующий;
  - queue_counts()    — счётчики по открытым статусам (бриф);
  - /cron/narad-tick  — внешний такт (render.yaml keep-alive, каждые 14 мин);
  - approve-эндпоинт miniapp запускает такт в фоне (threading) —
    мгновенное исполнение без ожидания крона.
"""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

import requests as http_requests

from proxy.core import _log_audit, _query, log, _internal_auth_headers

MLOGSERVE_URL = os.environ.get("MLOGSERVE_URL", "http://127.0.0.1:10001")
STEP_TIMEOUT_SECS = float(os.environ.get("CHAIN_STEP_TIMEOUT_SECS", "90"))
NARAD_MAX_ATTEMPTS = int(os.environ.get("NARAD_MAX_ATTEMPTS", "3"))
OWNER_ID = os.environ.get("OWNER_TELEGRAM_ID", "")

OPEN_STATUSES = ('pending', 'approved', 'queued', 'in_work', 'testing', 'blocked')


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_schema():
    """Таблица narad_steps — по образцу chain_steps (FO-027). Одна степа
    на наряд в v1: наряд = шаг его отдела; структура таблицы оставляет
    место для многошаговых нарядов без миграции."""
    _query("""CREATE TABLE IF NOT EXISTS narad_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            narad_id TEXT, dept TEXT, input_hash TEXT, reply TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""")
    _query("CREATE INDEX IF NOT EXISTS idx_narad_steps_narad ON narad_steps(narad_id, id)")


def step_hash(narad_id, dept, query):
    raw = f"{narad_id}|{dept}|{query}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def queue_counts():
    """Счётчики открытых нарядов по статусам. Отсутствие таблицы (до
    первого InitDB) — честные нули, не ошибка."""
    counts = {s: 0 for s in OPEN_STATUSES}
    try:
        rows = _query(
            "SELECT status, COUNT(*) AS cnt FROM narads "
            "WHERE status IN (" + ",".join(f"'{s}'" for s in OPEN_STATUSES) + ") "
            "GROUP BY status", fetch=True)
        for r in rows:
            if r["status"] in counts:
                counts[r["status"]] = r["cnt"]
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        log.warning(f"narad_queue.queue_counts: {e}")
    return counts


def next_narad():
    """Следующий наряд к исполнению: одобрен/в очереди, с исполнителем;
    приоритет high → normal → low, внутри — старые вперёд."""
    return _query(
        "SELECT id, title, description, plan, acceptance, dept, priority, risk_level, "
        "test_status, test_log, rework_count "
        "FROM narads WHERE status IN ('approved','queued') AND dept IS NOT NULL AND dept != '' "
        "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, "
        "created_at ASC LIMIT 1", fetch=True)


def _row_get(row, key, default=None):
    """Чтение поля из sqlite3.Row или dict без AttributeError."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def build_query(row):
    """Текст задачи для отдела: наряд целиком — задача, детали, план,
    критерии приёмки, а при доработке (FO-048) — замечания приёмки."""
    parts = [f"НАРЯД {row['id']} (приоритет {row['priority'] or 'normal'}, риск {row['risk_level'] or 'low'})",
             f"Задача: {row['title']}"]
    if row["description"]:
        parts.append(f"Детали: {row['description']}")
    if row["plan"]:
        parts.append(f"План работ: {row['plan']}")
    if row["acceptance"]:
        parts.append(f"Критерии приёмки (сделано, когда): {row['acceptance']}")
    if _row_get(row, "test_status") == "failed" and _row_get(row, "test_log"):
        parts.append(f"ПРЕДЫДУЩАЯ ПОПЫТКА ОТКЛОНЕНА НА ПРИЁМКЕ (rework {_row_get(row, 'rework_count') or 0}): "
                     f"{_row_get(row, 'test_log')}. Устрани замечания и повтори отчёт.")
    parts.append("Работай по нарядной дисциплине: выполни план, проверь себя по критериям приёмки и отчитайся по форме: что сделано / что НЕ трогалось / как проверялось.")
    return "\n".join(parts)[:20000]


def _invoke_step(dept, query, chat_id):
    """Мост в mlogserve /chain/step (monkeypatch-friendly, как chain_parallel)."""
    payload = {"dept": dept, "query": query, "chat_id": chat_id, "group_id": f"narad-{chat_id}"}
    # #536 A.2 (эволюция #517): токен — в заголовке X-Internal-Token, не в URL
    resp = http_requests.post(f"{MLOGSERVE_URL}/chain/step", json=payload, headers=_internal_auth_headers(), timeout=STEP_TIMEOUT_SECS)
    resp.raise_for_status()
    return str(resp.json().get("result", ""))


def _accept_markup(narad_id):
    """Кнопки приёмки (FO-048) в уведомлении о результате."""
    return {"inline_keyboard": [[
        {"text": "✅ Принять", "callback_data": f"na_ok_{narad_id}"},
        {"text": "↩️ На доработку", "callback_data": f"na_fail_{narad_id}"},
    ]]}


def _notify_owner(text, markup=None):
    """Уведомление владельца (не валим тик при ошибке отправки)."""
    if not OWNER_ID:
        return
    try:
        from proxy.telegram import _tg_send_message
        _tg_send_message(OWNER_ID, text[:3500], reply_markup=markup)
    except Exception as e:  # noqa: BLE001 — уведомление не должно валить исполнение
        log.warning(f"narad_queue._notify_owner: {e}")


def _attempts(narad_id):
    rows = _query("SELECT COUNT(*) AS c FROM narad_steps WHERE narad_id=?", (narad_id,), fetch=True)
    return rows[0]["c"] if rows else 0


def execute_next(invoke_fn=None):
    """Исполнить следующий наряд очереди. Возвращает dict-сводку тика."""
    ensure_schema()
    rows = next_narad()
    if not rows:
        return {"action": "idle"}
    row = rows[0]
    narad_id, dept = row["id"], row["dept"]
    query = build_query(row)
    chat_id = OWNER_ID or "0"
    h = step_hash(narad_id, dept, query)

    # persist before run (Temporal)
    _query("INSERT INTO narad_steps (narad_id, dept, input_hash, status) VALUES (?,?,?, 'pending')",
           (narad_id, dept, h))
    _query("UPDATE narads SET status='in_work', in_work_at=datetime('now') WHERE id=?", (narad_id,))
    _log_audit("narad_execute_start", {"narad_id": narad_id, "dept": dept, "attempt": _attempts(narad_id)}, dept="narad")

    invoke = invoke_fn or _invoke_step
    try:
        reply = invoke(dept, query, chat_id)
    except Exception as e:  # noqa: BLE001 — провал степы фиксируется, наряд возобновится
        err = str(e)[:500]
        _query("UPDATE narad_steps SET status='failed', reply=?, updated_at=? "
               "WHERE narad_id=? AND status='pending'",
               (err, _now_iso(), narad_id))
        _log_audit("narad_execute_failed", {"narad_id": narad_id, "dept": dept, "error": err}, dept="narad")
        if _attempts(narad_id) >= NARAD_MAX_ATTEMPTS:
            _query("UPDATE narads SET status='blocked', result=? WHERE id=?",
                   (f"исполнение не удалось {NARAD_MAX_ATTEMPTS} раз: {err[:200]}", narad_id))
            _log_audit("narad_blocked", {"narad_id": narad_id, "attempts": NARAD_MAX_ATTEMPTS}, dept="narad")
            _notify_owner(f"⚠️ Наряд {narad_id} заблокирован после {NARAD_MAX_ATTEMPTS} неудачных попыток исполнения ({dept}).\n{err[:300]}")
            return {"action": "blocked", "narad_id": narad_id, "dept": dept, "error": err}
        _notify_owner(f"🔁 Наряд {narad_id} ({dept}): попытка {_attempts(narad_id)} не удалась, авто-resume на следующем тике.\n{err[:300]}")
        return {"action": "failed", "narad_id": narad_id, "dept": dept, "error": err}

    _query("UPDATE narad_steps SET status='ok', reply=?, updated_at=? "
           "WHERE narad_id=? AND status='pending'",
           (reply[:20000], _now_iso(), narad_id))
    _query("UPDATE narads SET status='testing', testing_at=datetime('now'), result=? WHERE id=?",
           (reply[:500], narad_id))
    _log_audit("narad_execute_done", {"narad_id": narad_id, "dept": dept, "reply_len": len(reply)}, dept="narad")
    _notify_owner(f"✅ Наряд {narad_id} исполнен отделом {dept}, переведён на приёмку (testing).\n{reply[:600]}",
                  _accept_markup(narad_id))
    return {"action": "executed", "narad_id": narad_id, "dept": dept, "reply_len": len(reply)}


def _stuck_narad():
    """Наряд в in_work с незавершённой степой (крах между persist и done)."""
    return _query(
        "SELECT n.id AS id, n.dept AS dept FROM narads n "
        "JOIN narad_steps s ON s.narad_id = n.id "
        "WHERE n.status='in_work' AND s.status IN ('pending','failed') "
        "GROUP BY n.id ORDER BY MIN(s.created_at) ASC LIMIT 1", fetch=True)


def resume_stuck(invoke_fn=None):
    """Авто-resume: зависший in_work наряд переисполняется. Порог попыток —
    общий с execute_next (блокировка после NARAD_MAX_ATTEMPTS)."""
    ensure_schema()
    rows = _stuck_narad()
    if not rows:
        return {"action": "idle"}
    row = rows[0]
    narad_id, dept = row["id"], row["dept"]
    nar = _query("SELECT title, description, plan, acceptance, priority, risk_level FROM narads WHERE id=?",
                 (narad_id,), fetch=True)
    if not nar or not dept:
        return {"action": "idle"}
    full = {"id": narad_id, "dept": dept, **nar[0]}
    query = build_query(full)
    chat_id = OWNER_ID or "0"
    h = step_hash(narad_id, dept, query)
    _query("INSERT INTO narad_steps (narad_id, dept, input_hash, status) VALUES (?,?,?, 'pending')",
           (narad_id, dept, h))
    _log_audit("narad_resume", {"narad_id": narad_id, "dept": dept, "attempt": _attempts(narad_id)}, dept="narad")

    invoke = invoke_fn or _invoke_step
    try:
        reply = invoke(dept, query, chat_id)
    except Exception as e:  # noqa: BLE001
        err = str(e)[:500]
        _query("UPDATE narad_steps SET status='failed', reply=?, updated_at=? "
               "WHERE narad_id=? AND status='pending'",
               (err, _now_iso(), narad_id))
        if _attempts(narad_id) >= NARAD_MAX_ATTEMPTS:
            _query("UPDATE narads SET status='blocked', result=? WHERE id=?",
                   (f"исполнение не удалось {NARAD_MAX_ATTEMPTS} раз: {err[:200]}", narad_id))
            _notify_owner(f"⚠️ Наряд {narad_id} заблокирован после {NARAD_MAX_ATTEMPTS} неудачных попыток ({dept}).\n{err[:300]}")
            return {"action": "blocked", "narad_id": narad_id, "dept": dept}
        return {"action": "failed", "narad_id": narad_id, "dept": dept, "error": err}

    _query("UPDATE narad_steps SET status='ok', reply=?, updated_at=? "
           "WHERE narad_id=? AND status='pending'",
           (reply[:20000], _now_iso(), narad_id))
    _query("UPDATE narads SET status='testing', testing_at=datetime('now'), result=? WHERE id=?",
           (reply[:500], narad_id))
    _notify_owner(f"✅ Наряд {narad_id} ({dept}) восстановлен и исполнен после сбоя, на приёмке (testing).\n{reply[:600]}",
                  _accept_markup(narad_id))
    return {"action": "resumed", "narad_id": narad_id, "dept": dept}


def tick(invoke_fn=None):
    """Один такт диспетчера: сначала возобновить зависшего, иначе — новый."""
    resume = resume_stuck(invoke_fn)
    if resume.get("action") != "idle":
        return resume
    return execute_next(invoke_fn)


def trigger_async():
    """Фоновый такт (после approve в miniapp) — ответ HTTP не ждёт."""
    import threading

    def _run():
        try:
            tick()
        except Exception as e:  # noqa: BLE001
            log.warning(f"narad_queue.trigger_async: {e}")

    threading.Thread(target=_run, daemon=True, name="narad-tick").start()


def narad_stats_week_line():
    """Недельный срез закрытых нарядов — строка для утреннего брифа
    (по понедельникам, зеркало forge_edit_stats_week_line FO-043).

    Метрики: закрыто / first-try / доработки / средний цикл.
    Вердикт: доля first-try < 50% — «процесс требует внимания».
    Пустая неделя или отсутствие таблицы — пустая строка (честная
    деградация, бриф не падает).
    """
    try:
        rows = _query(
            "SELECT COUNT(*) AS n, COALESCE(SUM(first_try), 0) AS ft, "
            "COALESCE(SUM(rework_count), 0) AS rw, COALESCE(AVG(lead_seconds), 0) AS lead "
            "FROM narad_stats WHERE created_at > datetime('now', '-7 days')", fetch=True)
    except Exception:  # noqa: BLE001 — нет таблицы/БД не готова → пустая строка (честная деградация брифа)
        return ""
    if not rows or not rows[0]["n"]:
        return ""
    r = rows[0]
    n = int(r["n"])
    ft = int(r["ft"] or 0)
    rw = int(r["rw"] or 0)
    lead = int(r["lead"] or 0)
    share = round(100.0 * ft / n)
    hours, mins = lead // 3600, (lead % 3600) // 60
    lead_str = f"{hours}ч {mins}м" if hours else f"{mins}м"
    verdict = "дисциплина ок" if share >= 50 else "процесс требует внимания"
    return (f"Наряды: закрыто {n}, с первой попытки {ft} из {n} ({share}%), "
            f"доработок {rw}, средний цикл {lead_str} — {verdict}")
