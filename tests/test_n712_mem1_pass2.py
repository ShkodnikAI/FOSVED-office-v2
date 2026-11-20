#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#712 MEM-1 (P0), проход 2: A.2 (отчёт по mem_samples), A.3 (mem-recycle),
A.4 (RLIMIT_AS дочерним процессам).

Слои (паттерн офиса: поведение + структура + мутационный самотест):
  A.2: mem_report на сидированной tmp-БД (рост/пик/топ-слоты/исчезнувшие),
       роут /admin-ua/mem-report (гвард 401 без токена, JSON с гвардом
       префикса — 200 с X-Internal-Token), mem_report_line — строка брифа.
  A.3: /scheduler/mem-recycle — gc+caches в audit_log, реестр содержит
       запись mem-recycle enabled:false (правило №419), паттерн MemRecycleSlot
       зовёт /scheduler/mem-recycle.
  A.4: run_tracked c mem_limit_mb=200: дочерний python, выделяющий 300 МБ,
       падает САМ (ненулевой код/исключение у родителя), родитель жив,
       stderr-строка «не хватило памяти» напечатана; лимит реально применён
       (проверка через resource.getrlimit в дочернем).
"""
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MEM_SAMPLER = REPO_ROOT / "proxy" / "mem_sampler.py"
ROUTES_SCHED = REPO_ROOT / "proxy" / "routes_sched.py"
ROUTES_ADMIN = REPO_ROOT / "proxy" / "routes_admin.py"
SCHED_MLOG = REPO_ROOT / "dept" / "scheduler.mlog"
SCHEDULES_MLOG = REPO_ROOT / "dept" / "schedules.mlog"


# ────────────────────────── A.2: mem_report ──────────────────────────

@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    """tmp-БД с сидированными mem_samples: llm_proxy растёт 200→310,
    mlog стабилен, слот backup даёт ступень +25; pid 999 исчез."""
    db = tmp_path / "mem.db"
    con = sqlite3.connect(db)
    # прод-схема llm_proxy (init_db) минимально: audit_log для _log_audit
    # слота mem-recycle (тест A.3) — таблицы, в которые пишет прокси
    con.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT (datetime('now')),
        action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT DEFAULT 'ok')""")
    con.execute("""CREATE TABLE IF NOT EXISTS mem_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT DEFAULT (datetime('now')),
        name TEXT NOT NULL, pid INTEGER, rss_mb REAL NOT NULL,
        kind TEXT NOT NULL DEFAULT 'tick', ref TEXT DEFAULT '', phase TEXT DEFAULT '')""")
    # тики за окно: llm_proxy 200→310 (рост +110), mlog 140→142
    # (ts строками utcnow — окно 24 ч покрывает)
    from datetime import datetime, timedelta, timezone
    def ts(minutes_ago):
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)) \
            .strftime("%Y-%m-%d %H:%M:%S")
    for i, mb in enumerate([200.0, 220.0, 260.0, 310.0]):
        con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?, 'tick')",
                    (ts(60 * (4 - i)), "llm_proxy.py", 10, mb))
    # mlog стабилен 140→142 (разные минуты: ORDER BY ts детерминирован)
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?, 'tick')",
                (ts(300), "mlog", 20, 140.0))
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?, 'tick')",
                (ts(100), "mlog", 20, 142.0))
    # свежие тики живых процессов (последняя минута) — иначе все процессы
    # попадут в disappeared («не писали 10 минут»)
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?, 'tick')",
                (ts(1), "llm_proxy.py", 10, 312.0))
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?, 'tick')",
                (ts(1), "mlog", 20, 143.0))
    # исчезнувший процесс: писал час назад, последние 10 минут — нет
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?,'tick')",
                (ts(60), "edge-tts", 999, 88.0))
    # ступень слота backup: llm_proxy before 220 → after 245
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind,ref,phase) "
                "VALUES (?,?,10,?, 'slot','/cron/backup','before')", (ts(50), "llm_proxy.py", 220.0))
    con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind,ref,phase) "
                "VALUES (?,?,10,?, 'slot','/cron/backup','after')", (ts(49), "llm_proxy.py", 245.0))
    con.commit()
    con.close()
    import proxy.core
    monkeypatch.setattr(proxy.core, "DB_FILE", str(db))
    return db


class TestMemReport:
    def test_processes_growth_and_peak(self, mem_db, monkeypatch):
        from proxy import mem_sampler as ms
        monkeypatch.setattr(ms, "_SCHEMA_READY", True)  # схема не нужна: read-only
        rep = ms.mem_report(hours=24)
        by_name = {p["name"]: p for p in rep["processes"]}
        lp = by_name["llm_proxy.py"]
        assert lp["growth_mb"] == pytest.approx(112.0, abs=1.5), lp  # 200→312 (свежий тик)
        assert lp["rss_max_mb"] == pytest.approx(312.0, abs=0.5), lp
        assert by_name["mlog"]["growth_mb"] == pytest.approx(2.0, abs=1.0)

    def test_disappeared_pid_listed(self, mem_db):
        from proxy import mem_sampler as ms
        rep = ms.mem_report(hours=24)
        names = [d["name"] for d in rep.get("disappeared", [])]
        assert "edge-tts" in names, rep.get("disappeared")
        assert "llm_proxy.py" not in names  # живой — не «исчез»

    def test_top_slots_step(self, mem_db):
        from proxy import mem_sampler as ms
        rep = ms.mem_report(hours=24)
        steps = {s["ref"]: s["avg_step_mb"] for s in rep["top_slots"]}
        assert steps.get("/cron/backup") == pytest.approx(25.0, abs=1.0), rep["top_slots"]

    def test_report_line_format(self, mem_db):
        from proxy import mem_sampler as ms
        line = ms.mem_report_line(hours=24)
        assert line.startswith("💾 Память:"), line
        assert "llm_proxy.py +112" in line, line  # топ роста — по имени процесса
        assert "растёт:" in line


class TestMemReportRoute:
    def test_route_401_without_token(self, mem_db):
        os.environ.setdefault("API_SECRET", "test-secret-123")
        import llm_proxy
        client = llm_proxy.app.test_client()
        r = client.get("/admin-ua/mem-report")
        assert r.status_code == 401, "гвард префикса /admin-ua/* не сработал"

    def test_route_200_with_token(self, mem_db):
        os.environ["INTERNAL_API_TOKEN"] = "tok-n712p2-1234567890"
        os.environ["API_SECRET"] = "test-secret-123"
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = "tg-wh"
        os.environ["OWNER_TELEGRAM_ID"] = "1"
        os.environ["DATABASE_PATH"] = "/tmp/fosved-n712p2"
        import llm_proxy  # noqa: F401
        client = llm_proxy.app.test_client()
        r = client.get("/admin-ua/mem-report",
                       environ_base={"REMOTE_ADDR": "127.0.0.1"},
                       headers={"X-Internal-Token": os.environ["INTERNAL_API_TOKEN"]})
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        data = r.get_json()
        assert "processes" in data and "disappeared" in data and "top_slots" in data


# ────────────────────────── A.3: mem-recycle ──────────────────────────

class TestMemRecycle:
    def test_slot_endpoint_runs_gc_and_logs(self, mem_db):
        os.environ["INTERNAL_API_TOKEN"] = "tok-n712p2-1234567890"
        os.environ["API_SECRET"] = "test-secret-123"
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = "tg-wh"
        os.environ["OWNER_TELEGRAM_ID"] = "1"
        os.environ["DATABASE_PATH"] = "/tmp/fosved-n712p2"
        import llm_proxy  # noqa: F401
        from proxy.core import _query
        client = llm_proxy.app.test_client()
        r = client.post("/scheduler/mem-recycle",
                        json={"owner_id": "1"})
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        data = r.get_json()
        assert data["status"] == "ok" and "gc_collected" in data
        rows = _query("SELECT details FROM audit_log WHERE action='scheduler_mem_recycle' "
                      "ORDER BY id DESC LIMIT 1", fetch=True)
        assert rows, "слот не записал итог в audit_log"

    def test_slot_does_not_touch_live_provider_cache(self, mem_db):
        """CI-регрессия (PR #733, test_n715 KeyError): _cfg_cache —
        live-критичный (priority_provider читается на каждом call_llm),
        слот памяти НЕ имеет права его чистить. Гвард класса."""
        os.environ["INTERNAL_API_TOKEN"] = "tok-n712p2-1234567890"
        os.environ["API_SECRET"] = "test-secret-123"
        os.environ["TELEGRAM_WEBHOOK_SECRET"] = "tg-wh"
        os.environ["OWNER_TELEGRAM_ID"] = "1"
        os.environ["DATABASE_PATH"] = "/tmp/fosved-n712p2"
        import llm_proxy  # noqa: F401
        from proxy import providers
        before = dict(providers._cfg_cache)
        client = llm_proxy.app.test_client()
        r = client.post("/scheduler/mem-recycle", json={"owner_id": "1"})
        assert r.status_code == 200
        assert providers._cfg_cache == before, (
            "слот mem-recycle изменил _cfg_cache — live-кэш провайдеров "
            "трогать нельзя (KeyError в call_llm, CI PR #733)")

    def test_registry_entry_disabled_by_default(self):
        """№419: новая запись реестра — enabled: false (владелец включает)."""
        src = SCHEDULES_MLOG.read_text(encoding="utf-8")
        m = [l for l in src.splitlines() if '"mem-recycle"' in l and not l.strip().startswith("//")]
        assert m, "записи mem-recycle нет в реестре"
        assert "enabled: false" in m[0], f"правило №419 нарушено: {m[0]}"
        assert 'cron: "40 3 * * *"' in m[0], "окно не 03:40 MSK (тихое окно наряда)"

    def test_slot_pattern_calls_endpoint(self):
        src = SCHED_MLOG.read_text(encoding="utf-8")
        start = src.index("pattern MemRecycleSlot()")
        seg = src[start:src.index("\npattern ", start) if "\npattern " in src[start:] else len(src)]
        assert "/scheduler/mem-recycle" in seg, "слот не зовёт эндпоинт"
        assert "try http_post" in seg, "вызов не под try (идиома слотов)"

    def test_brief_has_mem_line_wiring(self):
        """Строка 💾 дописывается в бриф дословно (не через модель)."""
        src = ROUTES_SCHED.read_text(encoding="utf-8")
        assert "mem_report_line" in src, "бриф не зовёт mem_report_line"
        i = src.index("mem_report_line(hours=24)")
        seg = src[max(0, i - 400):i]
        assert "kk_line" in seg, "строка памяти не рядом с машинными строками брифа"


# ────────────────────────── A.4: RLIMIT_AS ──────────────────────────

class TestRlimit:
    def test_child_allocating_300mb_under_200mb_limit_dies(self, tmp_path):
        """Критерий наряда: дочерний скрипт, выделяющий 300 МБ при пределе
        200 МБ, падает сам (rc≠0 / собственный traceback MemoryError);
        родитель жив (run_tracked вернул результат, не бросил)."""
        from proxy.mem_sampler import run_tracked
        child = tmp_path / "hog.py"
        child.write_text(textwrap.dedent("""
            buf = bytearray(300 * 1024 * 1024)
            for i in range(0, len(buf), 4096):
                buf[i] = 1
            print("allocated ok")
        """), encoding="utf-8")
        r = run_tracked([sys.executable, str(child)], mem_limit_mb=200,
                        capture_output=True, text=True, timeout=60)
        assert r.returncode != 0, (
            f"дочка пережила аллокацию 300 МБ при пределе 200 МБ: rc=0, "
            f"stdout={r.stdout[:100]!r}")
        # дочка упала сама с честной причиной в своём выводе
        assert "MemoryError" in (r.stderr or "") or r.returncode < 0, (
            f"нет MemoryError в stderr дочки: rc={r.returncode}, "
            f"stderr={ (r.stderr or '')[:200]!r}")

    def test_child_under_limit_succeeds(self, tmp_path):
        from proxy.mem_sampler import run_tracked
        child = tmp_path / "small.py"
        child.write_text("import resource\n"
                         "print(resource.getrlimit(resource.RLIMIT_AS)[0] // (1024*1024))\n",
                         encoding="utf-8")
        r = run_tracked([sys.executable, str(child)], mem_limit_mb=200,
                        capture_output=True, text=True, timeout=60)
        assert r.returncode == 0
        assert "200" in r.stdout, f"предел не применён к дочернему: {r.stdout!r}"

    def test_default_limit_256_and_no_preexec_override(self):
        from proxy.mem_sampler import SUBPROCESS_MEM_LIMIT_MB, _make_preexec
        assert SUBPROCESS_MEM_LIMIT_MB == 256
        fn = _make_preexec(100)
        assert callable(fn)  # preexec_fn совместим с subprocess.run

    def test_mutation_no_limit_is_red(self):
        """Мутация «mem_limit_mb=0 у всех» — детектор красный: константа
        дефолта обязана остаться в сигнатуре run_tracked."""
        src = MEM_SAMPLER.read_text(encoding="utf-8")
        assert "mem_limit_mb=SUBPROCESS_MEM_LIMIT_MB" in src, (
            "дефолт предела исчез из run_tracked — A.4 отключён")
        assert "resource.setrlimit(resource.RLIMIT_AS" in src, (
            "setrlimit исчез — предел не применяется")

    def test_stderr_line_on_nonzero_exit(self, tmp_path, capsys):
        """Громкая строка при падении дочки с пределом (не глушим)."""
        from proxy.mem_sampler import run_tracked
        child = tmp_path / "fail.py"
        child.write_text("import sys; sys.exit(3)", encoding="utf-8")
        r = run_tracked([sys.executable, str(child)], mem_limit_mb=200,
                        capture_output=True, text=True, timeout=60)
        assert r.returncode == 3
        err = capsys.readouterr().err
        assert "не хватило памяти" in err and "200" in err, err


# ═══════════════════════════════════════════════════════════════════════
# Аудит 20.11 05:12: строка брифа считала неверно — «сейчас 1961 МБ,
# пик 184 МБ» (сумма ВСЕХ тиков за 5 мин ≈ каждый процесс ×5; «пик» —
# максимум ОДНОГО процесса). Требование: «сейчас» = сумма RSS по
# процессам последнего тика; «пик» = максимум суммы по минутному
# срезу за окно; тест на 5 тиков × 3 процесса.
# ═══════════════════════════════════════════════════════════════════════

class TestMemReportPass3Totals:
    """5 тиков × 3 процесса: latest_total — ПОСЛЕДНИЙ тик (не ×5),
    peak_total — максимум минутной СУММЫ (не одного процесса)."""

    @pytest.fixture
    def five_ticks_db(self, tmp_path, monkeypatch):
        db = tmp_path / "five.db"
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE IF NOT EXISTS mem_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT (datetime('now')),
            name TEXT NOT NULL, pid INTEGER, rss_mb REAL NOT NULL,
            kind TEXT NOT NULL DEFAULT 'tick', ref TEXT DEFAULT '', phase TEXT DEFAULT '')""")
        from datetime import datetime, timedelta, timezone
        def ts(minutes_ago, second=0):
            t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            return t.replace(second=second, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        # 5 минутных тиков × 3 процесса; llm_proxy растёт, пик суммы —
        # на 4-й минуте (100+40+20=160), последний тик ниже (90+40+20=150)
        per_tick = [
            (4, [("llm_proxy.py", 10, 80.0), ("mlog", 20, 40.0), ("reverse_proxy.py", 30, 20.0)]),
            (3, [("llm_proxy.py", 10, 90.0), ("mlog", 20, 40.0), ("reverse_proxy.py", 30, 20.0)]),
            (2, [("llm_proxy.py", 10, 95.0), ("mlog", 20, 41.0), ("reverse_proxy.py", 30, 21.0)]),
            (1, [("llm_proxy.py", 10, 100.0), ("mlog", 20, 40.0), ("reverse_proxy.py", 30, 20.0)]),
            (0, [("llm_proxy.py", 10, 90.0), ("mlog", 20, 40.0), ("reverse_proxy.py", 30, 20.0)]),
        ]
        for minutes_ago, procs in per_tick:
            for name, pid, mb in procs:
                con.execute("INSERT INTO mem_samples (ts,name,pid,rss_mb,kind) VALUES (?,?,?,?, 'tick')",
                            (ts(minutes_ago), name, pid, mb))
        con.commit()
        con.close()
        import proxy.core
        monkeypatch.setattr(proxy.core, "DB_FILE", str(db))
        return db

    def test_latest_total_is_last_tick_sum_not_all_ticks(self, five_ticks_db, monkeypatch):
        """«Сейчас» = сумма ПОСЛЕДНЕГО тика 3 процессов = 150 МБ.
        Прежняя формула (SUM за 5 мин) дала бы ~756 МБ — каждый процесс
        посчитан 5 раз (прод 20.11: «сейчас 1961 МБ» при лимите 512)."""
        from proxy import mem_sampler as ms
        monkeypatch.setattr(ms, "_SCHEMA_READY", True)
        rep = ms.mem_report(hours=24)
        assert rep["latest_total_mb"] == pytest.approx(150.0, abs=0.5), \
            rep["latest_total_mb"]

    def test_peak_total_is_max_minute_sum(self, five_ticks_db, monkeypatch):
        """«Пик» = максимум СУММЫ по минутному срезу = 160 МБ (тик 4-й
        минуты: 100+40+20). Прежний «пик» был максимумом одного
        процесса (100) — метрика другой природы (аудит 05:12)."""
        from proxy import mem_sampler as ms
        monkeypatch.setattr(ms, "_SCHEMA_READY", True)
        rep = ms.mem_report(hours=24)
        assert rep["peak_total_mb"] == pytest.approx(160.0, abs=0.5), \
            rep["peak_total_mb"]

    def test_report_line_uses_sum_metrics(self, five_ticks_db, monkeypatch):
        """Строка брифа: обе метрики про сумму контейнера и согласованы
        (сейчас ≤ пик; сейчас < 512 — лимит Render сравним напрямую)."""
        from proxy import mem_sampler as ms
        monkeypatch.setattr(ms, "_SCHEMA_READY", True)
        line = ms.mem_report_line(hours=24)
        assert "сейчас 150" in line, line
        assert "пик за окно 160" in line, line
        # инвариант согласованности метрик одной природы
        now_mb = float(line.split("сейчас ")[1].split(" МБ")[0])
        peak_mb = float(line.split("пик за окно ")[1].split(" МБ")[0])
        assert now_mb <= peak_mb, f"сейчас ({now_mb}) > пик ({peak_mb}) — метрики несогласованы"
        assert now_mb < 512, f"сейчас ({now_mb}) ≥ лимит контейнера — формула всё ещё ×5"


class TestGrapherMemMarks:
    """#712 (аудит 20.11 03:31): RSS-метки по фазам KG-перестройки —
    graph:write-phase и graph:kg-rebuild (before/after, full-срез)."""

    def test_grapher_marks_static(self):
        src = ROUTES_ADMIN.read_text(encoding="utf-8")
        seg = src[src.index("def _grapher_write_phase"):src.index('@app.get("/admin-ua/graph")')]
        for ref in ("graph:write-phase", "graph:kg-rebuild"):
            assert f'_mem_mark("slot", "{ref}", "before", full=True)' in seg, \
                f"нет RSS-метки before для {ref}"
            assert f'_mem_mark("slot", "{ref}", "after", full=True)' in seg, \
                f"нет RSS-метки after для {ref}"
