#!/usr/bin/env python3
"""#712 MEM-1 (P0) A.1 — тесты учётника памяти по процессам.

Слои (паттерн офиса: поведение + структура + мутационный самотест):
  1. Поведение на фикстуре /proc (sample_processes, имена, гонка мёртвого pid).
  2. Хранение: mem_samples в sqlite (kind/ref/phase), retention 7 суток.
  3. Порог топ-3: тишина при ≤ 400 МБ, одна строка при > 400 МБ.
  4. Метки слотов / call_python / subprocess — реальным прогоном через
     Flask test_client (reminder-check без OWNER_TELEGRAM_ID → 400 быстро)
     и run_tracked с живым дочерним процессом.
  5. Структурные гварды: все /cron/* и /scheduler/* слот-роуты декорированы
     (кроме поллинг-статусов), все subprocess.run в proxy/ обёрнуты,
     llm_proxy стартует поток, DDL в init_db — + мутационный самотест.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from proxy import mem_sampler  # noqa: E402


# ───────────────────────── фикстура /proc ─────────────────────────

def _fake_proc(root, pid, resident_pages, cmdline):
    d = root / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    # statm: size resident shared text lib data dt (в страницах)
    (d / "statm").write_text(f"{resident_pages} {resident_pages} 100 200 300 400 0\n")
    (d / "cmdline").write_bytes(cmdline)


@pytest.fixture
def fake_proc_root(tmp_path, monkeypatch):
    """Три процесса контейнера + один мёртвый pid + один не-pid каталог."""
    _fake_proc(tmp_path, 10, 256, b"python3\x00llm_proxy.py\x00")           # 1 MiB/256 стр * PAGE
    _fake_proc(tmp_path, 20, 1024, b"./bin/mlog\x00serve\x00app.mlog\x00")
    _fake_proc(tmp_path, 30, 2048, b"bash\x00entrypoint.sh\x00")
    (tmp_path / "99").mkdir()                                                # мёртвый: нет statm
    (tmp_path / "net").mkdir()                                               # не-pid каталог
    monkeypatch.setattr(mem_sampler, "PROC_ROOT", str(tmp_path))
    return tmp_path


def _pages_to_mb(pages):
    return round(pages * mem_sampler.PAGE_SIZE / (1024.0 * 1024.0), 2)


# ───────────────────────── 1. /proc чтение ─────────────────────────

class TestSampleProcesses:
    def test_names_and_rss(self, fake_proc_root):
        rows = mem_sampler.sample_processes()
        by_pid = {r["pid"]: r for r in rows}
        assert set(by_pid) == {10, 20, 30}          # мёртвый и не-pid пропущены
        assert by_pid[10]["name"] == "llm_proxy.py"  # python → по скрипту
        assert by_pid[20]["name"] == "mlog:serve"    # mlog serve → mlog:serve
        assert by_pid[30]["name"] == "bash:entrypoint.sh"
        assert by_pid[10]["rss_mb"] == _pages_to_mb(256)
        assert by_pid[20]["rss_mb"] == _pages_to_mb(1024)

    def test_dead_pid_race_skipped_silently(self, fake_proc_root):
        # каталог 99 без statm не должен ни появиться, ни уронить срез
        rows = mem_sampler.sample_processes()
        assert all(r["pid"] != 99 for r in rows)

    def test_self_rss_positive(self):
        rss = mem_sampler.self_rss_mb()  # реальный /proc тест-раннера
        assert rss is not None and rss > 1.0


# ───────────────────────── 2. хранение + retention ─────────────────────────

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """mem_samples в отдельной sqlite; сброс ленивой схемы."""
    import proxy.core
    db = tmp_path / "mem_test.db"
    monkeypatch.setattr(proxy.core, "DB_FILE", str(db))
    monkeypatch.setattr(mem_sampler, "_SCHEMA_READY", False)
    yield db
    if mem_sampler._SCHEMA_READY:  # вернуть флаг к честному состоянию
        pass


class TestStore:
    def test_store_rows_and_fields(self, fake_proc_root, tmp_db):
        rows = mem_sampler.sample_processes()
        mem_sampler.store_samples(rows, kind="slot", ref="/cron/backup", phase="before")
        conn = sqlite3.connect(tmp_db)
        try:
            got = conn.execute(
                "SELECT name, pid, rss_mb, kind, ref, phase FROM mem_samples").fetchall()
        finally:
            conn.close()
        assert len(got) == 3
        assert {g[3] for g in got} == {"slot"}
        assert {g[4] for g in got} == {"/cron/backup"}
        assert {g[5] for g in got} == {"before"}
        by_name = {g[0]: g for g in got}
        assert by_name["llm_proxy.py"][2] == _pages_to_mb(256)

    def test_purge_7_days(self, fake_proc_root, tmp_db):
        mem_sampler.store_samples(mem_sampler.sample_processes(), "tick", "container", "")
        conn = sqlite3.connect(tmp_db)
        old = "2026-01-01 00:00:00"
        conn.execute(
            "INSERT INTO mem_samples (ts, name, pid, rss_mb, kind, ref, phase) "
            "VALUES (?, 'old.py', 1, 10.0, 'tick', 'container', '')", (old,))
        conn.commit()
        conn.close()
        removed = mem_sampler.purge_old()
        assert removed == 1
        conn = sqlite3.connect(tmp_db)
        try:
            left = conn.execute("SELECT COUNT(*) FROM mem_samples").fetchone()[0]
            names = [r[0] for r in conn.execute("SELECT name FROM mem_samples")]
        finally:
            conn.close()
        assert left == 3 and "old.py" not in names

    def test_store_failure_does_not_raise(self, fake_proc_root, tmp_db, monkeypatch):
        # БД недоступна → строка в stderr, вызов не роняется (наряд: учёт
        # памяти не должен валить слот/контейнер)
        import proxy.core
        monkeypatch.setattr(proxy.core, "DB_FILE", "/nonexistent-dir/x.db")
        monkeypatch.setattr(mem_sampler, "_SCHEMA_READY", False)
        mem_sampler.store_samples(  # не должно бросить
            mem_sampler.sample_processes(), "tick", "container", "")


# ───────────────────────── 3. порог топ-3 ─────────────────────────

class TestTop3Threshold:
    ROWS = [
        {"pid": 1, "name": "llm_proxy.py", "rss_mb": 250.0},
        {"pid": 2, "name": "mlog:serve", "rss_mb": 120.0},
        {"pid": 3, "name": "reverse_proxy.py", "rss_mb": 40.0},
        {"pid": 4, "name": "tg", "rss_mb": 10.0},
    ]

    def test_silence_below_400(self):
        rows = [{"pid": 1, "name": "a", "rss_mb": 250.0},
                {"pid": 2, "name": "b", "rss_mb": 120.0},
                {"pid": 3, "name": "c", "rss_mb": 29.9}]  # 399.9 ≤ 400
        assert mem_sampler.top3_line(rows) is None

    def test_line_over_400(self):
        # 250+120+40+10 = 420 > 400 → строка с топ-3
        line = mem_sampler.top3_line(self.ROWS)
        assert line is not None
        assert "420" in line and "> 400MB" in line
        assert "llm_proxy.py(pid=1)=250.0MB" in line
        assert "mlog:serve(pid=2)=120.0MB" in line
        assert "tg(pid=4)" not in line  # топ-3, 4-й не входит

    def test_exactly_400_is_silence(self):
        rows = [{"pid": 1, "name": "a", "rss_mb": 200.0},
                {"pid": 2, "name": "b", "rss_mb": 200.0}]
        assert mem_sampler.top3_line(rows) is None  # 400.0 ≤ 400 → тишина

    def test_log_top3_if_over_prints_once(self, capsys):
        line = mem_sampler.log_top3_if_over(self.ROWS)
        assert line is not None
        out = capsys.readouterr().err
        assert "[mem-sampler]" in out and "top3:" in out
        # тишина в норме
        assert mem_sampler.log_top3_if_over(self.ROWS[:1]) is None


# ───────────────────────── 4. метки: слот / call_python / subprocess ─────────────────────────

class TestMarks:
    def test_mark_full_writes_all_processes(self, fake_proc_root, tmp_db):
        mem_sampler.mark("slot", "/cron/backup", "before", full=True)
        conn = sqlite3.connect(tmp_db)
        try:
            got = conn.execute("SELECT COUNT(*) FROM mem_samples").fetchone()[0]
        finally:
            conn.close()
        assert got == 3

    def test_mark_self_single_row(self, tmp_db):
        mem_sampler.mark("call_python", "statistics.mean", "before", full=False)
        conn = sqlite3.connect(tmp_db)
        try:
            got = conn.execute(
                "SELECT name, pid, rss_mb, kind, ref, phase FROM mem_samples").fetchall()
        finally:
            conn.close()
        assert len(got) == 1
        assert got[0][3] == "call_python" and got[0][4] == "statistics.mean"
        assert got[0][5] == "before" and got[0][2] > 0

    def test_run_tracked_subprocess_marks(self, tmp_db, monkeypatch):
        # реальный /proc: полный срез до/после живой дочки
        r = mem_sampler.run_tracked([sys.executable, "-c", "print(7)"],
                                    capture_output=True, text=True, timeout=30)
        assert r.returncode == 0 and r.stdout.strip() == "7"
        conn = sqlite3.connect(tmp_db)
        try:
            got = conn.execute(
                "SELECT phase, COUNT(*) FROM mem_samples WHERE kind='subprocess' "
                "GROUP BY phase").fetchall()
            ref = conn.execute(
                "SELECT DISTINCT ref FROM mem_samples WHERE kind='subprocess'").fetchall()
        finally:
            conn.close()
        # пустой срез тоже записывается схемой? store_samples([]) — no-op;
        # в CI /proc непуст → по 1+ строке на фазу
        assert {g[0] for g in got} == {"before", "after"}
        assert ref and ref[0][0]  # ref = имя интерпретатора

    def test_run_tracked_timeout_marks_after(self, tmp_db):
        with pytest.raises(subprocess.TimeoutExpired):
            mem_sampler.run_tracked([sys.executable, "-c", "import time; time.sleep(5)"],
                                    capture_output=True, timeout=0.3)
        conn = sqlite3.connect(tmp_db)
        try:
            after = conn.execute(
                "SELECT COUNT(*) FROM mem_samples WHERE kind='subprocess' "
                "AND phase='after'").fetchone()[0]
        finally:
            conn.close()
        assert after >= 1  # finally: метка «после» есть и при таймауте


class TestFlaskMarks:
    """Реальный прогон декорированных роутов через test_client."""

    @pytest.fixture
    def client(self, tmp_db, monkeypatch):
        monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
        import llm_proxy  # noqa: F401 — полная сборка роутов (routes_* на app)
        from proxy.core import app
        app.config["TESTING"] = True
        return app.test_client()

    def _select(self, db, kind):
        conn = sqlite3.connect(db)
        try:
            return conn.execute(
                "SELECT ref, phase, COUNT(*) FROM mem_samples WHERE kind=? "
                "GROUP BY ref, phase ORDER BY phase", (kind,)).fetchall()
        finally:
            conn.close()

    def test_slot_route_marks_before_after(self, client, tmp_db, fake_proc_root):
        # без OWNER_TELEGRAM_ID роут быстро отвечает 400 — метки всё равно
        # пишутся (декоратор: before … finally after)
        r = client.post("/scheduler/reminder-check")
        assert r.status_code == 400
        got = self._select(tmp_db, "slot")
        by_phase = {g[1]: g[2] for g in got}
        assert by_phase.get("before", 0) >= 1
        assert by_phase.get("after", 0) >= 1
        assert all(g[0] == "/scheduler/reminder-check" for g in got)

    def test_call_python_marks_self_rss(self, client, tmp_db):
        r = client.post("/call-python", json={
            "module": "statistics", "function": "mean", "args": [[1, 2, 3, 4]]})
        assert r.status_code == 200 and r.get_json()["result"] == 2.5
        got = self._select(tmp_db, "call_python")
        assert {(g[0], g[1]) for g in got} == {("statistics.mean", "before"),
                                               ("statistics.mean", "after")}


# ───────────────────────── 5. структурные гварды + мутации ─────────────────────────

SRC = {
    "mem_sampler": (REPO_ROOT / "proxy" / "mem_sampler.py").read_text(),
    "core": (REPO_ROOT / "proxy" / "core.py").read_text(),
    "llm_proxy": (REPO_ROOT / "llm_proxy.py").read_text(),
    "routes_tail": (REPO_ROOT / "proxy" / "routes_tail.py").read_text(),
    "routes_sched": (REPO_ROOT / "proxy" / "routes_sched.py").read_text(),
    "lz_github": (REPO_ROOT / "proxy" / "lz_github.py").read_text(),
    "routes_admin": (REPO_ROOT / "proxy" / "routes_admin.py").read_text(),
    "routes_core": (REPO_ROOT / "proxy" / "routes_core.py").read_text(),
    "shop_collectors": (REPO_ROOT / "proxy" / "shop_collectors.py").read_text(),
    "voice": (REPO_ROOT / "proxy" / "voice.py").read_text(),
    "forge_backup": (REPO_ROOT / "proxy" / "forge_backup.py").read_text(),
}

# Статус-поллинги — НЕ слоты (каждые ~20 с во время ночи): не декорируются.
_NON_SLOT_ROUTES = {"/scheduler/golden-evals/status", "/admin-ua/night-cycle/status"}

_SLOT_ROUTE_RE = None  # заполняется в _slot_routes()


def _slot_routes(src):
    """[(модуль, путь)] всех /cron/* и /scheduler/* роутов в исходнике."""
    import re
    out = []
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        m = re.search(r'@app\.(?:route|post|get)\("(/(?:cron|scheduler)/[^"]+)"', ln)
        if not m:
            continue
        # между декоратором роута и def не должно быть другой @app-строки
        window = lines[i + 1:i + 4]
        if any("@app." in w for w in window[:1]):
            continue
        out.append((i, m.group(1), window))
    return out


def _guard_decorated_slots():
    bad = []
    for mod in ("routes_tail", "routes_sched", "lz_github", "routes_admin"):
        for i, path, window in _slot_routes(SRC[mod]):
            if path in _NON_SLOT_ROUTES:
                if any("@slot_mem_guard" in w for w in window):
                    bad.append(f"{mod}: поллинг {path} НЕ должен декорироваться")
                continue
            if not any("@slot_mem_guard" in w for w in window):
                bad.append(f"{mod}: слот {path} без @slot_mem_guard")
    return bad


def _guard_subprocess_wrapped():
    bad = []
    for mod, src in SRC.items():
        if mod == "mem_sampler":
            continue  # сам обёртчик: subprocess.run внутри run_tracked
        for i, ln in enumerate(src.splitlines(), 1):
            if "subprocess.run(" in ln and not ln.strip().startswith("#"):
                bad.append(f"proxy/{mod}.py:{i} прямой subprocess.run (нужен run_tracked)")
    return bad


def _guards():
    bad = []
    bad += _guard_decorated_slots()
    bad += _guard_subprocess_wrapped()
    # поток в llm_proxy
    if "start_sampler_thread()" not in SRC["llm_proxy"]:
        bad.append("llm_proxy.py: поток учётника не стартует в __main__")
    # DDL в init_db
    if "CREATE TABLE IF NOT EXISTS mem_samples" not in SRC["core"]:
        bad.append("core.init_db: нет DDL mem_samples")
    # параметры наряда
    ms = SRC["mem_sampler"]
    for needle, why in [
        ("SAMPLER_INTERVAL_SECS = 60", "интервал 60 с (п.1)"),
        ("TOTAL_WARN_MB = 400.0", "порог 400 МБ (п.2)"),
        ("RETENTION_DAYS = 7", "хранение 7 суток"),
        ('mark("slot",', "метки слотов"),
        ('mark("call_python",', "метки call_python"),
        ('mark("subprocess",', "метки subprocess"),
        ('kind="tick"', "60-с тики петли"),
    ]:
        if needle not in ms:
            bad.append(f"mem_sampler.py: пропало {why}: {needle!r}")
    # call_python задекорирован
    if "@call_python_mem_guard" not in SRC["routes_tail"]:
        bad.append("routes_tail: /call-python без @call_python_mem_guard")
    # UA-ночь: impl-обёртка (async-путь тоже пишет RSS)
    if 'mark("slot", "admin-ua/night-cycle:impl"' not in SRC["routes_admin"].replace(
            "_mem_mark(", "mark(") and "_mem_mark(\"slot\", \"admin-ua/night-cycle:impl\"" not in SRC["routes_admin"]:
        bad.append("routes_admin: UA-ночь без RSS-обёртки impl")
    return bad


class TestStructuralGuards:
    def test_all_guards_green(self):
        assert _guards() == [], "нарушения: " + "; ".join(_guards())

    # ── мутационный самотест: каждая мутация краснеет ──
    def test_mutation_removes_slot_decorator(self):
        src = SRC["routes_tail"].replace(
            '@app.route("/cron/backup", methods=["GET"])\n@slot_mem_guard',
            '@app.route("/cron/backup", methods=["GET"])')
        orig = SRC["routes_tail"]
        SRC["routes_tail"] = src
        try:
            assert _guards() != []
        finally:
            SRC["routes_tail"] = orig

    def test_mutation_threshold_900(self):
        src = SRC["mem_sampler"].replace("TOTAL_WARN_MB = 400.0", "TOTAL_WARN_MB = 900.0")
        orig = SRC["mem_sampler"]
        SRC["mem_sampler"] = src
        try:
            assert _guards() != []
        finally:
            SRC["mem_sampler"] = orig

    def test_mutation_raw_subprocess_back(self):
        src = SRC["routes_tail"].replace("run_tracked(cmd, capture_output=True",
                                         "subprocess.run(cmd, capture_output=True")
        orig = SRC["routes_tail"]
        SRC["routes_tail"] = src
        try:
            assert _guards() != []
        finally:
            SRC["routes_tail"] = orig

    def test_mutation_no_thread_start(self):
        src = SRC["llm_proxy"].replace("start_sampler_thread()", "pass  # mutation")
        orig = SRC["llm_proxy"]
        SRC["llm_proxy"] = src
        try:
            assert _guards() != []
        finally:
            SRC["llm_proxy"] = orig

    def test_mutation_decoration_of_status_poll(self):
        # поллинг-статус задекорирован → гвард ругается (замусоривание)
        src = SRC["routes_tail"].replace(
            '@app.get("/scheduler/golden-evals/status")\ndef',
            '@app.get("/scheduler/golden-evals/status")\n@slot_mem_guard\ndef')
        orig = SRC["routes_tail"]
        SRC["routes_tail"] = src
        try:
            assert _guards() != []
        finally:
            SRC["routes_tail"] = orig


class TestLoopOnce:
    def test_sampler_loop_once(self, fake_proc_root, tmp_db):
        # одна итерация петли: тик записан, исключений нет
        mem_sampler.sampler_loop(once=True)
        conn = sqlite3.connect(tmp_db)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM mem_samples WHERE kind='tick'").fetchone()[0]
        finally:
            conn.close()
        assert n == 3  # три процесса фикстуры

    def test_start_sampler_thread_idempotent(self):
        t1 = mem_sampler.start_sampler_thread()
        t2 = mem_sampler.start_sampler_thread()
        assert t1 is t2
        assert any(th.name == "mem-sampler" for th in __import__("threading").enumerate())
