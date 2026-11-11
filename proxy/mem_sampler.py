#!/usr/bin/env python3
"""proxy/mem_sampler.py — #712 MEM-1 (P0), A.1: учёт памяти по процессам.

Прод-факты (issue #712): Render starter, лимит 512 МБ; OOM-убийства
06.11 02:00 (night-tick), 09.11 04:00 (KKResolveSlot), 11.11 04:38
(без слота, всплеск > 160 МБ за секунды, в лог не записано). Память
копится за сутки 200→410 МБ и не отдаётся. До наряда RSS-учёта не было
(проверено по коду: log_mem в core.py — логгер FosvedMemory, не RSS).

A.1 наряда:
  1. Раз в 60 с — RSS каждого процесса контейнера из /proc → mem_samples.
  2. Сумма > 400 МБ → ОДНА строка в лог с топ-3 процессами; в норме
     каждую минуту — тишина (никакого шума).
  3. Каждый слот (/cron/*, /scheduler/*, /admin-ua/night-cycle) и каждый
     call_python / subprocess.run пишут RSS до и после.

Решения (обоснование — в отчёте по наряду):
  • Сборщик — поток В llm_proxy.py, не отдельный процесс: отдельный
    python-процесс стоит ~30 МБ RSS — недопустимо при лимите 512 МБ.
  • Таблица mem_samples в общей fosved.db (персистентный диск Render):
    данные переживают рестарт контейнера — нужны для разбора A.2 через
    сутки. Retention 7 суток (наряд), чистка раз в час.
  • Слоты и subprocess — ПОЛНЫЙ срез всех процессов до/после (ступени
    по слотам, рост любого процесса); call_python — RSS только процесса
    llm_proxy (частые вызовы, полный срез замусорил бы таблицу).
  • Статусные поллинг-роуты (golden-evals/status, night-cycle/status) —
    НЕ слоты и не декорируются: поллинг каждые ~20 с во время ночи дал
    бы ~1k лишних строк за ночь.
  • Ошибки БД/чтения /proc НЕ роняют слот и НЕ глушатся молча: одна
    строка в stderr с причиной (наряд: «не глушить ошибки» — но учёт
    памяти не должен ронять контейнер).
"""

import functools
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("fosved.mem_sampler")

# ── Параметры наряда #712 A.1 (фиксированные, не env: план Render не меняем) ──
SAMPLER_INTERVAL_SECS = 60        # п.1: раз в 60 с
TOTAL_WARN_MB = 400.0             # п.2: порог топ-3 строки
RETENTION_DAYS = 7                # хранение 7 суток
PURGE_EVERY_SECS = 3600           # чистка раз в час

# Переопределяется в тестах (фикстура /proc, tmp_path).
PROC_ROOT = "/proc"
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

# Self-имя для записей kind=call_python (процесс, где живёт endpoint).
_SELF_NAME = None

_SCHEMA_READY = False
_schema_lock = threading.Lock()
_write_lock = threading.Lock()
_purge_lock = threading.Lock()
_last_purge = 0.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mem_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT DEFAULT (datetime('now')),
    name TEXT NOT NULL,
    pid INTEGER,
    rss_mb REAL NOT NULL,
    kind TEXT NOT NULL DEFAULT 'tick',
    ref TEXT DEFAULT '',
    phase TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_mem_samples_ts ON mem_samples(ts);
CREATE INDEX IF NOT EXISTS idx_mem_samples_kind_ref ON mem_samples(kind, ref);
"""


# ───────────────────────────── /proc чтение ─────────────────────────────

def _proc_name(cmdline_bytes):
    """Короткое стабильное имя процесса из cmdline.

    python3 llm_proxy.py …  -> llm_proxy.py (по скрипту, не по интерпретатору)
    ./bin/mlog serve …      -> mlog
    bash entrypoint.sh …    -> bash:entrypoint.sh
    """
    try:
        tokens = [t.decode("utf-8", "replace") for t in cmdline_bytes.split(b"\0") if t]
    except Exception:
        return "unknown"
    if not tokens:
        return "kernel-ish"
    first = os.path.basename(tokens[0])
    if first.startswith("python"):
        if len(tokens) > 1:
            return os.path.basename(tokens[1])
        return first
    if len(tokens) > 1 and not tokens[1].startswith("-"):
        return f"{first}:{os.path.basename(tokens[1])}"
    return first


def sample_processes(proc_root=None):
    """RSS каждого процесса контейнера: [{pid, name, rss_mb}], по /proc.

    Чтение statm (поле resident, страницы). Процесс, умерший между
    листингом и чтением, пропускается молча — это штатная гонка, не
    ошибка. Имя — из cmdline (см. _proc_name).
    """
    root = proc_root or PROC_ROOT
    rows = []
    try:
        pids = [p for p in os.listdir(root) if p.isdigit()]
    except OSError:
        return rows
    for pid in pids:
        try:
            with open(os.path.join(root, pid, "statm"), "rb") as f:
                resident_pages = int(f.read().split()[1])
            with open(os.path.join(root, pid, "cmdline"), "rb") as f:
                cmd = f.read()
            rows.append({
                "pid": int(pid),
                "name": _proc_name(cmd),
                "rss_mb": round(resident_pages * PAGE_SIZE / (1024.0 * 1024.0), 2),
            })
        except (OSError, ValueError, IndexError):
            continue
    return rows


def self_rss_mb():
    """RSS собственного процесса (для kind=call_python — быстрый mark)."""
    try:
        with open(os.path.join(PROC_ROOT, str(os.getpid()), "statm"), "rb") as f:
            return round(int(f.read().split()[1]) * PAGE_SIZE / (1024.0 * 1024.0), 2)
    except (OSError, ValueError, IndexError) as e:
        log.warning("[mem-sampler] self statm unreadable: %s", e)
        return None


def self_name():
    global _SELF_NAME
    if _SELF_NAME is None:
        _SELF_NAME = _proc_name(open(os.path.join(PROC_ROOT, str(os.getpid()), "cmdline"), "rb").read())
    return _SELF_NAME


# ───────────────────────────── хранение ─────────────────────────────

def _connect():
    """Свое соединение на запись (WAL): короткая транзакция, не держим."""
    from proxy.core import DB_FILE
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_schema(conn):
    conn.executescript(_SCHEMA)
    conn.commit()


def _ensure_schema_once():
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _schema_lock:
        if _SCHEMA_READY:
            return
        conn = _connect()
        try:
            ensure_schema(conn)
            _SCHEMA_READY = True
        finally:
            conn.close()


def _now_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def store_samples(rows, kind, ref, phase, proc_root=None):
    """INSERT среза rows в mem_samples. Ошибка БД — строка в stderr,
    вызов НЕ роняется (учёт памяти не должен валить слот/контейнер)."""
    if not rows:
        return
    try:
        _ensure_schema_once()
        ts = _now_ts()
        with _write_lock:
            conn = _connect()
            try:
                conn.executemany(
                    "INSERT INTO mem_samples (ts, name, pid, rss_mb, kind, ref, phase) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(ts, r["name"], r["pid"], r["rss_mb"], kind, ref, phase) for r in rows],
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001 — учёт не роняет офис
        print(f"[mem-sampler] store failed kind={kind} ref={ref} phase={phase}: {e}",
              file=sys.stderr, flush=True)


def mark(kind, ref, phase, full=False):
    """RSS-метка до/после события.

    full=True  — срез ВСЕХ процессов контейнера (слоты, subprocess):
                 показывает ступень любого процесса.
    full=False — только RSS своего процесса (call_python: частые вызовы).
    """
    if full:
        store_samples(sample_processes(), kind=kind, ref=ref, phase=phase)
    else:
        rss = self_rss_mb()
        if rss is not None:
            store_samples([{"pid": os.getpid(), "name": self_name(), "rss_mb": rss}],
                          kind=kind, ref=ref, phase=phase)


def purge_old(days=RETENTION_DAYS, conn=None):
    """Хранение 7 суток: DELETE старше cutoff. Возвращает число строк."""
    own = conn is None
    if own:
        _ensure_schema_once()
        conn = _connect()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S")
        cur = conn.execute("DELETE FROM mem_samples WHERE ts < ?", (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        if own:
            conn.close()


# ───────────────────────────── топ-3 и порог ─────────────────────────────

def total_and_top3(rows):
    """(сумма RSS МБ, топ-3 по убыванию) по срезу rows."""
    total = round(sum(r["rss_mb"] for r in rows), 1)
    top3 = sorted(rows, key=lambda r: r["rss_mb"], reverse=True)[:3]
    return total, top3


def top3_line(rows, threshold_mb=TOTAL_WARN_MB):
    """Одна строка топ-3 или None, если сумма ≤ порога (тишина в норме)."""
    total, top3 = total_and_top3(rows)
    if total <= threshold_mb:
        return None
    parts = " ".join(f"{r['name']}(pid={r['pid']})={r['rss_mb']}MB" for r in top3)
    return f"[mem-sampler] total={total}MB > {int(threshold_mb)}MB top3: {parts}"


def log_top3_if_over(rows, threshold_mb=TOTAL_WARN_MB):
    """П.2 наряда: при сумме > 400 МБ — ОДНА строка в лог. Возврат для теста."""
    line = top3_line(rows, threshold_mb=threshold_mb)
    if line:
        print(line, file=sys.stderr, flush=True)
    return line


# ───────────────────────────── декораторы ─────────────────────────────

def slot_mem_guard(fn):
    """Слоты (/cron/*, /scheduler/*, /admin-ua/night-cycle): полный срез
    RSS всех процессов до и после (kind='slot', ref=path, phase=before/after)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            from flask import request
            ref = request.path
        except Exception:  # noqa: BLE001 — вне request context (прямой вызов)
            ref = fn.__name__
        mark("slot", ref, "before", full=True)
        try:
            return fn(*args, **kwargs)
        finally:
            mark("slot", ref, "after", full=True)
    return wrapper


def call_python_mem_guard(fn):
    """Каждый /call-python: RSS llm_proxy до/после (kind='call_python',
    ref='module.function' по телу запроса). Полный срез не нужен: вызов
    исполняется в этом же процессе."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            from flask import request
            d = request.get_json(force=True, silent=True) or {}
            ref = f"{d.get('module', '?')}.{d.get('function', '?')}"
        except Exception:  # noqa: BLE001
            ref = fn.__name__
        mark("call_python", ref, "before", full=False)
        try:
            return fn(*args, **kwargs)
        finally:
            mark("call_python", ref, "after", full=False)
    return wrapper


# ───────────────────────────── subprocess ─────────────────────────────

def _cmd_ref(cmd):
    """Короткий ref из командной строки: backup_db.py / mlog:run / git:show."""
    tokens = [t for t in (cmd or []) if not str(t).startswith("-")]
    if not tokens:
        return "subprocess"
    first = os.path.basename(str(tokens[0]))
    if first.startswith("python"):
        ref = os.path.basename(str(tokens[1])) if len(tokens) > 1 else first
    elif first in ("git", "mlog") and len(tokens) > 1:
        ref = f"{first}:{os.path.basename(str(tokens[1]))}"
    else:
        ref = first
    return ref[:60]


def run_tracked(cmd, **kwargs):
    """subprocess.run + RSS-метки полного среза до/после (kind='subprocess').

    Дочерний процесс после завершения мёртв — его собственный пик поймает
    A.4 (RLIMIT) на следующем проходе; здесь фиксируется ступень памяти
    контейнера, которую дал запуск дочки. Аргументы — как у subprocess.run.
    """
    ref = _cmd_ref(cmd)
    mark("subprocess", ref, "before", full=True)
    try:
        return subprocess.run(cmd, **kwargs)
    finally:
        mark("subprocess", ref, "after", full=True)


# ───────────────────────────── петля 60 с ─────────────────────────────

def sampler_loop(interval=SAMPLER_INTERVAL_SECS, threshold_mb=TOTAL_WARN_MB,
                 once=False):
    """П.1: раз в 60 с полный срез → mem_samples (kind='tick'); п.2: топ-3
    при > threshold_mb; чистка 7 суток раз в час. Ошибка итерации — строка
    в stderr, петля продолжает (учёт не роняет офис)."""
    global _last_purge
    _ensure_schema_once()
    _last_purge = time.monotonic()
    while True:
        try:
            rows = sample_processes()
            store_samples(rows, kind="tick", ref="container", phase="")
            log_top3_if_over(rows, threshold_mb=threshold_mb)
            if time.monotonic() - _last_purge >= PURGE_EVERY_SECS:
                _last_purge = time.monotonic()
                with _purge_lock:
                    purge_old()
        except Exception as e:  # noqa: BLE001 — петля живёт
            print(f"[mem-sampler] loop iteration failed: {e}", file=sys.stderr, flush=True)
        if once:
            break
        time.sleep(interval)


def start_sampler_thread(interval=SAMPLER_INTERVAL_SECS,
                         threshold_mb=TOTAL_WARN_MB):
    """Daemon-поток в llm_proxy (решение: без отдельного процесса — экономия
    ~30 МБ RSS при лимите 512 МБ). Повторный вызов — no-op (одна петля)."""
    for t in threading.enumerate():
        if t.name == "mem-sampler":
            return t
    t = threading.Thread(target=sampler_loop, name="mem-sampler",
                         args=(interval, threshold_mb), daemon=True)
    t.start()
    log.info("[mem-sampler] started: interval=%ss threshold=%sMB retention=%sd",
             interval, int(threshold_mb), RETENTION_DAYS)
    return t


if __name__ == "__main__":
    # Ручной прогон одной итерации (smoke, не для entrypoint):
    #   python3 -m proxy.mem_sampler
    sampler_loop(once=True)
    print("[mem-sampler] one tick done")
