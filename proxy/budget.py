#!/usr/bin/env python3
"""proxy/budget.py — FO-024: enforcement бюджетов llm_proxy (soft/hard/stop).

Эталон дисциплины расхода — LiteLLM budgets/spend-tracking: счётчик дня,
soft-алерт ДО исчерпания (ровно один раз в день на департамент), жёсткий
порог (эконом-модель), стоп департамента, ролловер по UTC.

Данные: таблица token_usage (FO-004) — тот же источник, что /api/economics.
Кэш в памяти процесса инвалидируется по каждой записи token_usage
(budget.invalidate()) + TTL-подстраховка.

Пороги (от лимита департамента):
  < 80%  → ok
  ≥ 80%  → soft  — Telegram-алерт владельцу ОДИН раз в день на департамент
                   + audit_log budget_soft
  ≥ 100% → hard  — эконом-режим: модель = последний элемент fallback-цепи
                   (зеркало GetModelFallbackChain app.mlog), heavy deny
                   + audit_log budget_hard
  ≥ 120% → stop  — департамент остановлен до ролловера дня (UTC)
                   + audit_log budget_stop

Исключения (никогда не стопятся): dept='admin', аварийные команды
(/start /help /status /budget /admin /lockdown /unlock), shadow-вызовы
(FO-025 помечаются request_type LIKE 'shadow%' и не считаются в бюджет).
"""
import os
import threading
import time
from datetime import datetime, timezone

from proxy.core import _get_setting, _log_audit, _query, log

SOFT_RATIO = 0.8
HARD_RATIO = 1.0
STOP_RATIO = 1.2

# TTL кэша — подстраховка инвалидации по записям (крошечный, не счётчик "врёт")
_CACHE_TTL = 5.0
_cache = {"day": None, "total": None, "per_dept": None, "ts": 0.0}
_cache_lock = threading.Lock()

_EMERGENCY_COMMANDS = {
    "/start", "/help", "/status", "/budget", "/admin", "/lockdown", "/unlock",
}

_EXEMPT_DEPTS = {"admin"}


def day_start_iso() -> str:
    """Начало текущего UTC-дня в формате created_at (datetime('now'))."""
    now = datetime.now(timezone.utc)
    return f"{now:%Y-%m-%d} 00:00:00"


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Кэш счётчика дня ─────────────────────────────────────────────────────
def invalidate() -> None:
    """Инвалидация по каждой записи token_usage (вызывается из INSERT-точек)."""
    with _cache_lock:
        _cache["ts"] = 0.0


def _fetch_spent():
    day = day_start_iso()
    rows = _query(
        "SELECT dept, COALESCE(SUM(CAST(cost_usd AS REAL)),0) AS spent FROM token_usage "
        "WHERE created_at >= ? AND (request_type IS NULL OR request_type NOT LIKE 'shadow%') "
        "GROUP BY dept",
        (day,), fetch=True)
    per_dept = {}
    total = 0.0
    for r in rows or []:
        spent = float(r["spent"] or 0.0)
        per_dept[r["dept"]] = spent
        total += spent
    return total, per_dept, day


def _cached():
    with _cache_lock:
        if time.time() - _cache["ts"] > _CACHE_TTL or _cache["day"] != day_start_iso():
            total, per_dept, day = _fetch_spent()
            _cache.update({"day": day, "total": total, "per_dept": per_dept, "ts": time.time()})
        return _cache["total"], dict(_cache["per_dept"])


def spent_today(dept=None) -> float:
    """Сумма cost_usd с начала UTC-дня (без shadow-строк FO-025)."""
    total, per_dept = _cached()
    if dept is None:
        return round(total, 6)
    return round(per_dept.get(dept, 0.0), 6)


# ── Лимиты: per-dept оверрайд → глобальный ──────────────────────────────
def limit_for(dept) -> float:
    """daily_budget_<dept> из system_settings, fallback глобальный daily_budget.
    0.0 / не установлен = лимита нет (enforcement не активен)."""
    raw = _get_setting(f"daily_budget_{dept}", "")
    if raw in (None, ""):
        raw = _get_setting("daily_budget", "")
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return 0.0


# ── Эконом-модель (зеркало хвоста GetModelFallbackChain, app.mlog) ───────
def econom_model_for(dept) -> str:
    """Последний элемент fallback-цепи департамента = самая дешёвая модель.
    Зеркало mlog: config/override_<dept>.txt → config/priority_model.txt → glm-4.6."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in (f"config/override_{dept}.txt", "config/priority_model.txt"):
        path = os.path.join(base, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f
                         if ln.strip() and not ln.strip().startswith("#")]
            if lines:
                return lines[-1]
        except OSError:
            continue
    return "glm-4.6"


# ── Telegram-алерт (soft) — один раз в день на департамент ──────────────
def _alert_dedup_key(dept) -> str:
    return f"budget_soft_alert_{dept}_{today_iso()}"


def _alert_once(dept, spent, limit) -> bool:
    """True если алерт отправлен (первый раз за день)."""
    if _get_setting(_alert_dedup_key(dept), "") == "sent":
        return False
    _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, 'sent')",
           (_alert_dedup_key(dept),))
    try:
        # env читаем на вызове (import-time константы core зависят от порядка
        # импорта в тестах и деплое); отправка — через модуль (monkeypatch-friendly)
        from proxy import telegram as _tg
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        owner = os.environ.get("OWNER_TELEGRAM_ID", "")
        if token and owner:
            _tg._tg_send_message(
                owner,
                f"⚠️ Budget SOFT (≥80%): dept={dept} spent=${spent:.2f} / limit=${limit:.2f}. "
                f"При 100% — эконом-модель, при 120% — стоп до ролловера (UTC).")
    except Exception as e:
        from proxy.core import _log_error
        _log_error(f"budget soft alert failed: {e}", dept=dept, kind="budget_alert")
    return True


# ── Читаемый статус (для /api/budget/status — без побочек) ──────────────
def probe(dept) -> dict:
    """Состояние департамента без алертов/аудита."""
    limit = limit_for(dept)
    spent = spent_today(dept)
    return _state_of(spent, limit, dept)


def _state_of(spent, limit, dept) -> dict:
    if limit <= 0:
        state = "unlimited"
        ratio = 0.0
    else:
        ratio = spent / limit
        if ratio >= STOP_RATIO:
            state = "stop"
        elif ratio >= HARD_RATIO:
            state = "hard"
        elif ratio >= SOFT_RATIO:
            state = "soft"
        else:
            state = "ok"
    return {
        "dept": dept,
        "spent": round(spent, 4),
        "limit": round(limit, 4) if limit else None,
        "ratio": round(ratio, 4) if limit else None,
        "state": state,
        "econom_model": econom_model_for(dept),
    }


# ── Enforcement-точка (вызывается из call_llm перед выбором провайдера) ──
def enforce(dept, command="") -> dict:
    """Возвращает состояние бюджета; на soft/hard пишет audit + алерт.
    Исключения: admin-канал, аварийные команды — всегда ok."""
    first = (command or "").strip().split(" ")[0] if (command or "").strip() else ""
    if dept in _EXEMPT_DEPTS or first in _EMERGENCY_COMMANDS:
        st = probe(dept)
        st["state"] = "ok"
        st["exempt"] = True
        return st

    limit = limit_for(dept)
    spent = spent_today(dept)
    st = _state_of(spent, limit, dept)

    if st["state"] == "soft":
        _log_audit("budget_soft", {"dept": dept, "threshold": SOFT_RATIO,
                                   "spent": st["spent"], "limit": st["limit"],
                                   "ratio": st["ratio"]}, dept=dept)
        st["alerted"] = _alert_once(dept, st["spent"], st["limit"])
    elif st["state"] == "hard":
        _log_audit("budget_hard", {"dept": dept, "threshold": HARD_RATIO,
                                   "spent": st["spent"], "limit": st["limit"],
                                   "ratio": st["ratio"],
                                   "econom_model": st["econom_model"]}, dept=dept)
    elif st["state"] == "stop":
        _log_audit("budget_stop", {"dept": dept, "threshold": STOP_RATIO,
                                   "spent": st["spent"], "limit": st["limit"],
                                   "ratio": st["ratio"]}, dept=dept)
    return st


def status_snapshot() -> dict:
    """Срез для /budget (/api/budget/status): глобал + по департаментам."""
    total, per_dept = _cached()
    global_limit_raw = _get_setting("daily_budget", "")
    try:
        global_limit = float(global_limit_raw)
    except (TypeError, ValueError):
        global_limit = 0.0

    depts = set(per_dept.keys())
    # департаменты с оверрайдами — тоже показываем, даже без расхода
    try:
        rows = _query("SELECT key FROM system_settings WHERE key LIKE 'daily_budget_%'",
                      fetch=True)
        for r in rows or []:
            depts.add(str(r["key"]).replace("daily_budget_", ""))
    except Exception as e:
        from proxy.core import _log_error
        _log_error(f"budget snapshot overrides read failed: {e}", kind="budget_snapshot")

    items = [_state_of(per_dept.get(d, 0.0), limit_for(d), d) for d in sorted(depts)]
    econom = [d["dept"] for d in items if d["state"] in ("hard", "stop")]
    g = _state_of(total, global_limit, "__global__")
    g["dept"] = "__global__"
    return {
        "date_utc": today_iso(),
        "global": {"spent": g["spent"], "limit": g["limit"],
                   "ratio": g["ratio"], "state": g["state"]},
        "depts": items,
        "econom": econom,
    }
