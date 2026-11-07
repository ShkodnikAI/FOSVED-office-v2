#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #602: учёт использования по ключам отделов — лента вызовов и
агрегаты per-key (референс: anthropic-sdk v2.2.0 usage/cost reports by
dimension; LZ-дайджест 2026-10-24, R32).

SHADOW-контур (урок #581): модуль только ДОБАВЛЯЕТ записи учёта и отдаёт
отчёты; prod-поведение вызовов не меняет — record_call() глотает любые
собственные ошибки (учёт не должен ронять LLM-вызов). Существующие ленты
(token_usage, audit_log, llm-traces) не трогаются — только чтение на уровне
агрегатов не производится вовсе.

Приватность (негативный контроль Б наряда): в ленте НЕЛОГИРУЕТСЯ ни значение
ключа, ни содержимое запросов/ответов — только метаданные вызова; ключ —
исключительно маской secrets_crypto.mask_value («abc…wxyz»).
Невалидный ключ (upstream 401/403 → bucket "forbidden") попадает в ленту
как отказ с причиной (негативный контроль А) — врезка в
providers._call_single_provider покрывает все исходы, включая ранние
отказы (нет провайдера / нет ключа / circuit breaker открыт).

Доступ: GET /api/usage-by-key (routes_admin, bearer-гвард общего
before_request) + ночная лента в сводку 07:15 (форма #550, OutboxPut
в NightSlot через call_python → night_block()).
"""
import time

from proxy.core import _query, _log_error, log

_TABLE = """
CREATE TABLE IF NOT EXISTS usage_key_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_mask TEXT NOT NULL,
    provider TEXT,
    env_key TEXT,
    dept TEXT,
    route TEXT DEFAULT '',
    ok INTEGER NOT NULL DEFAULT 0,
    err_kind TEXT,
    duration_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
)
"""


def ensure_schema():
    """DDL ленты — идемпотентен; shadow-модуль самодостаточен (не зависит
    от порядка init_db core)."""
    _query(_TABLE)
    _query("CREATE INDEX IF NOT EXISTS idx_usage_key_mask ON usage_key_calls(key_mask, created_at)")
    _query("CREATE INDEX IF NOT EXISTS idx_usage_key_ts ON usage_key_calls(created_at)")


def mask_key(key_value):
    """Маска ключа для ленты — никогда не значение. Пустой/нет — плейсхолдер."""
    try:
        from secrets_crypto import mask_value
        return mask_value(key_value or "") or "(no key)"
    except Exception as e:  # noqa: BLE001 — маска не должна ломать учёт
        log.debug(f"[usage_by_key] mask failed: {e}")
        return "(masked)"


def record_call(provider, env_key, key_mask, dept, route, ok, err_kind=None, duration_ms=None):
    """Одна строка ленты. Shadow-гарантия: любые ошибки учёта — в журнал,
    НЕ в исключение (вызывающий LLM-путь не страдает)."""
    try:
        ensure_schema()
        _query(
            "INSERT INTO usage_key_calls (key_mask, provider, env_key, dept, route, ok, err_kind, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key_mask, provider, env_key, dept, route, 1 if ok else 0, err_kind,
             int(duration_ms) if duration_ms is not None else None),
        )
    except Exception as e:  # noqa: BLE001 — shadow: учёт не роняет вызовы
        _log_error(f"usage_by_key record failed: {e}", dept=dept, kind="metrics_loss")


def feed(limit=50):
    """Последние записи ленты (для /admin): метаданные, ключ маской."""
    try:
        ensure_schema()
        return [dict(r) for r in _query(
            "SELECT id, key_mask, provider, env_key, dept, route, ok, err_kind, duration_ms, created_at "
            "FROM usage_key_calls ORDER BY id DESC LIMIT ?", (int(limit),), fetch=True)]
    except Exception as e:  # noqa: BLE001
        _log_error(f"usage_by_key feed failed: {e}", dept="admin", kind="db_read")
        return []


def agg_window(days=1):
    """Агрегаты per-key за окно (сутки=1, неделя=7). Сходимость с лентой —
    сумма total по ключам = число записей ленты за окно (проверяется тестом).
    Возвращает {total, failed, fail_rate, rows:[{key_mask, provider, dept,
    calls, fails, fail_rate, avg_ms}]}."""
    try:
        ensure_schema()
        rows = _query(
            "SELECT key_mask, provider, dept, COUNT(*) AS calls, "
            "SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS fails, "
            "COALESCE(AVG(duration_ms), 0) AS avg_ms "
            "FROM usage_key_calls WHERE created_at >= datetime('now', ?) "
            "GROUP BY key_mask, provider, dept ORDER BY calls DESC",
            (f"-{int(days)} days",), fetch=True)
        total = 0
        failed = 0
        out = []
        for r in rows:
            calls = int(r["calls"] or 0)
            fails = int(r["fails"] or 0)
            total += calls
            failed += fails
            out.append({
                "key_mask": r["key_mask"], "provider": r["provider"], "dept": r["dept"],
                "calls": calls, "fails": fails,
                "fail_rate": round(fails / calls, 3) if calls else None,
                "avg_ms": int(r["avg_ms"] or 0),
            })
        return {"window_days": int(days), "total": total, "failed": failed,
                "fail_rate": round(failed / total, 3) if total else None, "rows": out}
    except Exception as e:  # noqa: BLE001
        _log_error(f"usage_by_key agg failed: {e}", dept="admin", kind="db_read")
        return {"window_days": int(days), "total": 0, "failed": 0, "fail_rate": None, "rows": []}


def _first_seen(key_mask):
    rows = _query("SELECT MIN(created_at) AS ts FROM usage_key_calls WHERE key_mask = ?",
                  (key_mask,), fetch=True)
    return (rows[0]["ts"] if rows and rows[0]["ts"] else None)


def diff_window(days=1):
    """Диф-окна по ленте: новый ключ (первое появление внутри окна),
    новый маршрут (пара ключ+маршрут, впервые внутри окна), всплеск отказов
    (fail_rate окна ≥ 2× предыдущего равного окна при n≥5 — иначе не утверждаем)."""
    out = {"new_keys": [], "new_routes": [], "fail_surge": None}
    try:
        ensure_schema()
        new_keys = _query(
            "SELECT DISTINCT key_mask, provider, dept FROM usage_key_calls "
            "WHERE created_at >= datetime('now', ?) "
            "AND created_at = (SELECT MIN(created_at) FROM usage_key_calls c2 "
            "  WHERE c2.key_mask = usage_key_calls.key_mask)",
            (f"-{int(days)} days",), fetch=True)
        out["new_keys"] = [dict(r) for r in new_keys]
        new_routes = _query(
            "SELECT DISTINCT key_mask, route, dept FROM usage_key_calls "
            "WHERE created_at >= datetime('now', ?) AND COALESCE(route, '') <> '' "
            "AND NOT EXISTS (SELECT 1 FROM usage_key_calls c2 WHERE c2.key_mask = usage_key_calls.key_mask "
            "  AND c2.route = usage_key_calls.route AND c2.created_at < datetime('now', ?))",
            (f"-{int(days)} days", f"-{int(days)} days"), fetch=True)
        out["new_routes"] = [dict(r) for r in new_routes]
        cur = agg_window(days)
        prev = _query(
            "SELECT COUNT(*) AS c, SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS f "
            "FROM usage_key_calls WHERE created_at >= datetime('now', ?) "
            "AND created_at < datetime('now', ?)",
            (f"-{int(days) * 2} days", f"-{int(days)} days"), fetch=True)
        prev_c = int(prev[0]["c"] or 0) if prev else 0
        prev_f = int(prev[0]["f"] or 0) if prev else 0
        if (cur["total"] or 0) >= 5 and prev_c >= 5:
            cur_rate = cur["fail_rate"] or 0.0
            prev_rate = prev_f / prev_c
            if prev_rate > 0 and cur_rate >= 2.0 * prev_rate:
                out["fail_surge"] = {"window_fail_rate": cur_rate, "prev_fail_rate": round(prev_rate, 3),
                                     "note": "доля отказов ≥2× предыдущего окна (n≥5 в обоих)"}
    except Exception as e:  # noqa: BLE001
        _log_error(f"usage_by_key diff failed: {e}", dept="admin", kind="db_read")
    return out


def night_block():
    """Блок для ночной сводки 07:15 (форма #550 — текстовый OutboxPut).
    Только метаданные; ключи масками; пустое окно — честное «вызовов нет»."""
    try:
        day = agg_window(1)
        week = agg_window(7)
        d = diff_window(1)
        lines = ["🔑 Учёт по ключам (сутки): вызовов " + str(day["total"])
                 + ", отказов " + str(day["failed"])
                 + (" (доля " + str(day["fail_rate"]) + ")" if day["fail_rate"] is not None else "")]
        if day["total"] == 0:
            lines = ["🔑 Учёт по ключам (сутки): вызовов нет — лента пуста"]
        for r in day["rows"][:8]:
            lines.append("· " + str(r["key_mask"]) + " " + str(r["provider"]) + "/" + str(r["dept"])
                         + ": " + str(r["calls"]) + " выз., отказов " + str(r["fails"])
                         + " (ср. " + str(r["avg_ms"]) + " мс)")
        lines.append("🔑 Неделя: вызовов " + str(week["total"]) + ", отказов " + str(week["failed"]))
        for nk in d["new_keys"][:5]:
            lines.append("· новый ключ: " + str(nk["key_mask"]) + " (" + str(nk["provider"]) + "/" + str(nk["dept"]) + ")")
        for nr in d["new_routes"][:5]:
            lines.append("· новый маршрут: " + str(nr["key_mask"]) + " → " + str(nr["route"]))
        if d.get("fail_surge"):
            fs = d["fail_surge"]
            lines.append("· ⚠️ всплеск отказов: доля " + str(fs["window_fail_rate"])
                         + " против " + str(fs["prev_fail_rate"]) + " в предыдущем окне")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001 — ночная лента не должна ломать сводку
        _log_error(f"usage_by_key night_block failed: {e}", dept="system", kind="report_loss")
        return "🔑 Учёт по ключам: отчёт недоступен (" + str(e)[:80] + ")"
