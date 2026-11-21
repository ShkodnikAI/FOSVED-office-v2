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
# #728 B.4: при чужом write-локе (прод 19.11: фаза Grapher ночи, ~11 мин)
# store_samples не ждёт дефолтные 10 с: короткий busy_timeout + тихий
# пропуск среза. Учёт памяти — наблюдатель, не участник: 60-с тик следующей
# минуты запишется, когда лок снимется; повторы/очередь запретлены нарядом
# («без повторов в цикле»). Данные A.2 не теряются: держатель лока — свой
# же ночной этап, а не внешний писатель.
BUSY_TIMEOUT_MS = 500

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
    """Свое соединение на запись (WAL): короткая транзакция, не держим.

    #728 B.4: busy_timeout 500 мс — при чужом write-локе store_samples
    отказывается быстро (тихий пропуск среза), не блокируя тред слота/
    петлю на дефолтные 10 с.OperationalError("database is locked")
    ловится вызывающим except'ом.
    """
    from proxy.core import DB_FILE
    conn = sqlite3.connect(DB_FILE, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
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
        try:
            conn = _connect()
            try:
                ensure_schema(conn)
                _SCHEMA_READY = True
            finally:
                conn.close()
        except sqlite3.Error as e:
            # #728 B.4: бут под чужим локом — схема отложена до первого
            # успешного тика (тихий пропуск, не роняем петлю/процесс).
            print(f"[mem-sampler] schema deferred: {e}", file=sys.stderr, flush=True)


def _now_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def store_samples(rows, kind, ref, phase, proc_root=None):
    """INSERT среза rows в mem_samples. Ошибка БД — строка в stderr,
    вызов НЕ роняется (учёт памяти не должен валить слот/контейнер).

    #728 B.4: при чужом write-локе (прод 19.11 03:00:26Z: «[mem-sampler]
    store failed … database is locked») — быстрый отказ по busy_timeout
    (500 мс) и тихий пропуск среза: НЕТ повторов в цикле и НЕТ очереди
    (граница наряда). Следующий 60-с тик запишется после снятия лока.
    """
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
    except sqlite3.OperationalError as e:
        # B.4: лок БД — ожидаемое состояние под нагрузкой (Grapher ночи);
        # отдельная строка (не общий стек) — чтобы прод-лог отличал пропуск
        # по локу от настоящей ошибки записи.
        if "locked" in str(e) or "busy" in str(e):
            print(f"[mem-sampler] skip {kind}/{ref}: db locked ({BUSY_TIMEOUT_MS}ms busy_timeout)",
                  file=sys.stderr, flush=True)
        else:
            print(f"[mem-sampler] store failed kind={kind} ref={ref} phase={phase}: {e}",
                  file=sys.stderr, flush=True)
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

# #712 A.4: предел адресного пространства дочернего процесса. Лимит
# контейнера 512 МБ; тяжёлая дочка (OCR/рендер карточки/backup), вышедшая
# из-под контроля, обязана упасть САМА (MemoryError в ней), а не забрать
# контейнер (oomKilled 11.11 04:38: убийца выбил процесс за секунды,
# mlog serve выжил — по факту наряда умирал дочерний). Дефолт 256 МБ:
# наблюдаемые пики дочек — десятки МБ (backup/git/mlog-мост/edge-tts),
# 256 = запас ×2+ от самого тяжёлого; вызывающий может задать свой
# mem_limit_mb= (тяжёлые — по фактам A.2 следующего прохода).
SUBPROCESS_MEM_LIMIT_MB = 256


def _make_preexec(mem_limit_mb):
    """preexec_fn с RLIMIT_AS (наряд A.4). None → без предела (легаси-
    вызов с уже существующим preexec_fn не перезаписываем)."""
    import resource

    def _apply():
        if mem_limit_mb and mem_limit_mb > 0:
            lim = int(mem_limit_mb) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    return _apply


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


# ─────────────── #712 A.2: отчёт по mem_samples (кто копит) ───────────────

def mem_report(hours=24):
    """Сводка A.2 по mem_samples за последние `hours` часов (таблица наряда:
    процесс → рост/пик; топ-слоты по RSS-ступеням; исчезнувшие пиды).

    Read-only: своё соединение (WAL), не мешает писателям. Возврат — dict
    (роут /admin-ua/mem-report отдаёт его как JSON; краткая строка для
    утреннего брифа — mem_report_line).
    """
    from proxy.core import DB_FILE
    out = {"window_hours": hours, "processes": [], "top_slots": [],
           "latest_total_mb": None, "samples": 0}
    try:
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=3000")
            n = conn.execute("SELECT COUNT(*) FROM mem_samples").fetchone()
            out["samples"] = n[0] if n else 0
            if not out["samples"]:
                return out

            # 1) процессы: первый/последний/макс RSS по (name) за окно
            #    (pid меняется между рестартами — агрегируем по имени;
            #     исчезнувший pid ловим отдельно, ниже)
            procs = conn.execute(
                "SELECT name, MIN(rss_mb) AS mb_min, MAX(rss_mb) AS mb_max, "
                "AVG(rss_mb) AS mb_avg, COUNT(*) AS n "
                "FROM mem_samples WHERE kind='tick' "
                "AND ts >= datetime('now', ?) GROUP BY name ORDER BY mb_max DESC",
                (f"-{int(hours)} hours",)).fetchall()
            for r in procs:
                name, mb_min, mb_max, mb_avg, n = r
                # рост: последний тик минус первый тик ИМЕНИ за окно
                # (id в сортировке — tie-break при равных секундах ts)
                first = conn.execute(
                    "SELECT rss_mb FROM mem_samples WHERE kind='tick' AND name=? "
                    "AND ts >= datetime('now', ?) ORDER BY ts ASC, id ASC LIMIT 1",
                    (name, f"-{int(hours)} hours")).fetchone()
                last = conn.execute(
                    "SELECT rss_mb FROM mem_samples WHERE kind='tick' AND name=? "
                    "AND ts >= datetime('now', ?) ORDER BY ts DESC, id DESC LIMIT 1",
                    (name, f"-{int(hours)} hours")).fetchone()
                grow = round((last[0] - first[0]), 1) if first and last else None
                out["processes"].append({
                    "name": name, "rss_first_mb": round(first[0], 1) if first else None,
                    "rss_last_mb": round(last[0], 1) if last else None,
                    "rss_max_mb": round(mb_max, 1), "rss_avg_mb": round(mb_avg, 1),
                    "growth_mb": grow, "ticks": n})

            # 2) текущая сумма по ПОСЛЕДНЕМУ тику каждого живого процесса.
            #    #712 (аудит 20.11 05:12): прежде SUM по всем тикам за 5 мин
            #    считал каждый процесс ~5 раз (бриф 20.11: «сейчас 1961 МБ»
            #    при лимите контейнера 512). Правильно: один (самый свежий)
            #    тик на процесс.
            latest = conn.execute(
                "SELECT SUM(rss_mb) FROM mem_samples m "
                "WHERE m.kind='tick' AND m.id = ("
                "  SELECT t2.id FROM mem_samples t2 WHERE t2.kind='tick' "
                "  AND t2.name = m.name AND t2.ts >= datetime('now', '-10 minutes') "
                "  ORDER BY t2.ts DESC, t2.id DESC LIMIT 1)").fetchone()
            out["latest_total_mb"] = round(latest[0], 1) if latest and latest[0] else None

            # 2б) пик СУММЫ по минутному срезу (максимум по окну).
            #     #712 (аудит 20.11 05:12): прежний «пик» был максимумом
            #     ОДНОГО процесса (184 МБ рядом с «сейчас 1961») — метрики
            #     разной природы стояли под общими словами. Теперь обе
            #     метрики про сумму контейнера: сейчас — последний срез,
            #     пик — максимум минутных срезов за окно.
            per_minute = conn.execute(
                "SELECT MAX(s) FROM ("
                "  SELECT strftime('%Y-%m-%d %H:%M', ts) AS minute, SUM(rss_mb) AS s"
                "  FROM mem_samples WHERE kind='tick' "
                "  AND ts >= datetime('now', ?) GROUP BY minute)",
                (f"-{int(hours)} hours",)).fetchone()
            out["peak_total_mb"] = round(per_minute[0], 1) if per_minute and per_minute[0] else None

            # 3) топ-слоты по ступени RSS (after − before по llm_proxy,
            #    главный кандидат-копитель по факту наряда)
            slots = conn.execute(
                "SELECT b.ref AS slot_ref, AVG(a.rss_mb - b.rss_mb) AS step, COUNT(*) AS n "
                "FROM mem_samples b JOIN mem_samples a "
                "ON a.kind=b.kind AND a.ref=b.ref AND a.phase='after' "
                "AND b.phase='before' AND a.ts > b.ts "
                "AND a.ts <= datetime(b.ts, '+30 minutes') "
                "AND b.name = a.name "
                "WHERE b.kind='slot' AND b.name='llm_proxy.py' "
                "AND b.ts >= datetime('now', ?) "
                "GROUP BY b.ref HAVING n >= 1 ORDER BY step DESC LIMIT 8",
                (f"-{int(hours)} hours",)).fetchall()
            out["top_slots"] = [{"ref": r[0], "avg_step_mb": round(r[1], 1),
                                 "runs": r[2]} for r in slots]

            # 4) исчезнувшие пиды (кандидаты на OOM-жертву 11.11 04:38):
            #    имя писало тики, но не пишет последние 10 минут
            gone = conn.execute(
                "SELECT name, MAX(pid) AS pid, MAX(ts) AS last_ts, MAX(rss_mb) AS mb_max "
                "FROM mem_samples WHERE kind='tick' "
                "AND ts >= datetime('now', ?) AND name NOT IN ("
                "  SELECT DISTINCT name FROM mem_samples WHERE kind='tick' "
                "  AND ts >= datetime('now', '-10 minutes')) GROUP BY name",
                (f"-{int(hours)} hours",)).fetchall()
            out["disappeared"] = [{"name": r[0], "pid": r[1], "last_ts": r[2],
                                   "rss_max_mb": round(r[3], 1)} for r in gone]
        finally:
            conn.close()
    except sqlite3.Error as e:
        # read-only отчёт: недоступность БД — честная строка, не 500-трейс
        out["error"] = str(e)[:200]
    return out


def mem_report_line(hours=24):
    """Одна строка для утреннего брифа: сумма сейчас + топ-2 роста.

    Формат (владелец читает в Telegram):
    «💾 Память: 262 МБ (пик за сутки 411); растёт: llm_proxy +84, mlog +12»

    #712 (аудит 20.11 05:12): «сейчас» — сумма RSS по процессам
    ПОСЛЕДНЕГО тика (не всех тиков за 5 мин), «пик» — максимум СУММЫ по
    минутному срезу за окно (не максимум одного процесса). Обе метрики —
    про сумму контейнера; лимит Render 512 МБ теперь сравним напрямую.
    """
    rep = mem_report(hours=hours)
    if rep.get("error"):
        return f"💾 Память: сводка недоступна ({rep['error'][:60]})"
    if not rep["samples"]:
        return "💾 Память: mem_samples пуст (сборщик A.1 не писал)"
    total = rep.get("latest_total_mb")
    peak = rep.get("peak_total_mb")
    grows = sorted((p for p in rep["processes"]
                    if p.get("growth_mb") and p["growth_mb"] > 5),
                   key=lambda p: -p["growth_mb"])[:2]
    parts = []
    if total is not None:
        parts.append(f"сейчас {total} МБ")
    if peak is not None:
        parts.append(f"пик за окно {peak} МБ")
    line = "💾 Память: " + ", ".join(parts)
    if grows:
        line += "; растёт: " + ", ".join(
            f"{p['name']} +{p['growth_mb']}" for p in grows)
    return line


def run_tracked(cmd, mem_limit_mb=SUBPROCESS_MEM_LIMIT_MB, **kwargs):
    """subprocess.run + RSS-метки полного среза до/после (kind='subprocess')
    + предел памяти дочернему процессу (#712 A.4)
    + срезы ВО ВРЕМЯ дочки каждые 5 с (#712, аудит 21.11).

    Дочерний процесс с RLIMIT_AS=mem_limit_mb: превышение → дочка падает
    сама (MemoryError / exit non-zero), контейнер жив — «тяжёлая разовая
    задача падает одна, а не роняет контейнер» (цель наряда). Дефолт —
    SUBPROCESS_MEM_LIMIT_MB (256); вызывающий может передать свой предел
    (тяжёлые задачи — по фактам A.2) или 0/None для снятия предела.

    Понятная ошибка вызывающему: при падении по пределу в stderr пишется
    строка «<ref>: не хватило памяти (предел N МБ)» (не глушим, наряд:
    громкая запись); исключение subprocess пробрасывается как есть —
    вызывающие слоты уже переводят его в честные строки отчётов.
    Аргументы — как у subprocess.run (кроме preexec_fn: наш совместим по
    смыслу — если вызывающий передал свой, предел НЕ применяется).

    #712 (аудит 21.11 03:31): OOM 02:00:20 через 16 с после старта
    NightTickSlot — до первой UA-фазы, подозреваемый backup. Тики
    сборщика раз в 60 с: 16-секундный пик дочки попадал МЕЖДУ тиками,
    mem_samples его не видел (только before/after вокруг мёртвой дочки).
    Live-срезы каждые 5 с (kind='subprocess', ref тот же, phase='live')
    закрывают окно: пик виден с именем процесса-виновника.
    """
    ref = _cmd_ref(cmd)
    mark("subprocess", ref, "before", full=True)

    def _live_sample():
        """Срез всех процессов каждые 5 с, пока дочка жива (daemon-тред)."""
        while not _live_stop.is_set():
            _live_stop.wait(5.0)
            if _live_stop.is_set():
                break
            try:
                store_samples(sample_processes(), kind="subprocess", ref=ref, phase="live")
            except Exception:  # noqa: BLE001 — телеметрия не роняет дочку
                pass

    _live_stop = threading.Event()
    _live_t = threading.Thread(target=_live_sample, daemon=True,
                               name=f"mem-live-{ref}")
    _live_t.start()
    try:
        if kwargs.get("preexec_fn") is None and mem_limit_mb:
            kwargs["preexec_fn"] = _make_preexec(mem_limit_mb)
        proc = subprocess.run(cmd, **kwargs)
        # A.4: дочка умерла не-нулём при активном пределе — громкая строка
        # (check=True у большинства вызовов нет: слоты сами разбирают код).
        rc = getattr(proc, "returncode", None)
        if rc is not None and rc != 0 and mem_limit_mb:
            _report_rlimit_kill(ref, mem_limit_mb, rc)
        return proc
    except subprocess.CalledProcessError as e:
        # check=True у вызывающего: то же сообщение, исключение пробрасывается
        _report_rlimit_kill(ref, mem_limit_mb, getattr(e, "returncode", None))
        raise
    finally:
        _live_stop.set()
        _live_t.join(timeout=2.0)
        mark("subprocess", ref, "after", full=True)


def _report_rlimit_kill(ref, mem_limit_mb, rc=None):
    """A.4: громкая строка о падении дочки при активном пределе памяти.
    rc ≠ 0 при RLIMIT_AS — как правило MemoryError (python) либо сигнал;
    финальный разбор — по отчёту слота, здесь — сигнал владельцу в лог."""
    print(f"[mem-sampler] subprocess {ref}: не хватило памяти? "
          f"(предел {mem_limit_mb} МБ, rc={rc}) — проверь отчёт слота",
          file=sys.stderr, flush=True)


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
