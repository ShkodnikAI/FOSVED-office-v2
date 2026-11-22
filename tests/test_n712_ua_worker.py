#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#712 MEM-1, проход по аудиту 22.11 03:32 (OOM = Scanner UA поверх
накопленной базы 403/512 МБ): потоковый Scanner, воркер фаз 1–2 под
RLIMIT, malloc_trim, разбивка базы покоя в брифе.

Механизм OOM (из аудита, две ночи одинаково): NightTickSlot 02:00 →
Phase 1 Scanner 02:00:19.5 → oomKilled 02:00:24. Scanner читал ~790
файлов read_text().splitlines() в llm_proxy; 70 из 82 МБ дерева —
бинарники bin/mlog* (36+33 МБ), чей splitlines() строил список строк
пиком ~250 МБ поверх базы процесса.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from proxy import ua_scan  # noqa: E402

ROUTES_ADMIN = REPO / "proxy" / "routes_admin.py"
MEM_SAMPLER = REPO / "proxy" / "mem_sampler.py"
WORKER = REPO / "scripts" / "ua_night_worker.py"
ROUTES_SCHED = REPO / "proxy" / "routes_sched.py"


# ─────────────── A. потоковый Scanner (proxy/ua_scan.py) ───────────────

def test_count_lines_matches_splitlines_on_text(tmp_path):
    """Счёт строк стриминга = splitlines на текстовых файлах (переносы
    в середине, без завершающего, пустой, только переводы)."""
    cases = {
        "a.txt": "one\ntwo\nthree\n",
        "b.txt": "no trailing newline",
        "c.txt": "",
        "d.txt": "\n\n\n",
        "e.mlog": "pattern A(x) -> y\npattern B() -> z\n",
    }
    for name, body in cases.items():
        f = tmp_path / name
        f.write_text(body, encoding="utf-8")
        expect = len(body.splitlines())
        assert ua_scan.count_lines(f) == expect, (name, body)


def test_count_lines_chunk_boundary(tmp_path):
    """Перевод строки РОВНО на границе чанка не теряется и не дублируется."""
    big = tmp_path / "big.bin"
    # перевод РОВНО на границе чанка: «xxx…x\nyyy» = 2 строки — перевод
    # не теряется и не дублируется
    payload = b"x" * (ua_scan.READ_CHUNK - 3) + b"\n" + b"y" * 20
    big.write_bytes(payload)
    assert ua_scan.count_lines(big) == len(payload.splitlines()) == 2
    # файл РОВНО кратен чанку и кончается переводом — нет фантомной строки
    payload2 = b"a\n" * (ua_scan.READ_CHUNK // 2)
    big.write_bytes(payload2)
    assert ua_scan.count_lines(big) == len(payload2.splitlines())
    # много чанков с переводами внутри
    payload3 = (b"a\n" * (ua_scan.READ_CHUNK + 10))
    big.write_bytes(payload3)
    assert ua_scan.count_lines(big) == len(payload3.splitlines())


def test_count_lines_binary_no_memory_bomb(tmp_path):
    """РЕГРЕССИЯ OOM: 36-МБ bin/mlog через splitlines давал пик ~250 МБ
    (список строк); стриминг — пик ≤ READ_CHUNK + константа. Проверяем
    поведенчески: большой бинарник (4 МБ мусора без переводов) считается
    без роста RSS процесса теста (меряем ru_maxrss до/после)."""
    import resource
    big = tmp_path / "bomb.bin"
    chunk = bytes(range(256)) * 16 * 1024  # 4 МБ, почти без 0x0A
    big.write_bytes(chunk * 1)
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    n = ua_scan.count_lines(big)
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert n >= 1
    # ru_maxrss — монотонный максимум; рост от 4-МБ файла не должен
    # превышать нескольких МБ (прежде было ~3× размера файла)
    growth_kb = max(0, after - before)
    assert growth_kb < 8 * 1024, f"пик вырос на {growth_kb} КБ — стриминг не работает"


def test_scan_inventory_streaming_format(tmp_path):
    """Формат инвентаря прежний (files/total_*/by_type/by_dir, сортировка
    по строкам, SKIP_DIRS соблюдён) — night-cycle и /admin-ua/scan."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "one.mlog").write_text("a\nb\n", encoding="utf-8")
    (tmp_path / "two.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "data").mkdir()          # SKIP_DIRS
    (tmp_path / "data" / "skipme.txt").write_text("skip\n", encoding="utf-8")
    inv = ua_scan.scan_inventory(str(tmp_path))
    paths = {f["path"] for f in inv["files"]}
    assert paths == {"sub/one.mlog", "two.py"}
    assert inv["total_files"] == 2
    assert inv["total_lines"] == 3
    assert inv["by_type"] == {".mlog": 1, ".py": 1}
    assert inv["by_dir"] == {"sub": 1, "root": 1}
    assert inv["files"][0]["path"] == "sub/one.mlog"  # больше строк — первый


def test_analyze_files_facts_only(tmp_path):
    """Analyzer: факты .mlog/.py (patterns/routes/imports/tables),
    другие расширения пропущены, в результате нет содержимого файлов."""
    (tmp_path / "mod.mlog").write_text(
        'pattern Foo(x) -> y\nroute "/r" method=GET\nimport dept/other\n'
        'CREATE TABLE IF NOT EXISTS tbl_a (id int)\nSendTelegramReply("x")\n',
        encoding="utf-8")
    (tmp_path / "code.py").write_text(
        "def bar():\n    pass\n\n@app.route('/x')\ndef r():\n    return 1\n",
        encoding="utf-8")
    (tmp_path / "skip.txt").write_text("def ignored():\n", encoding="utf-8")
    an = ua_scan.analyze_files(str(tmp_path))
    by = {a["path"]: a for a in an}
    assert set(by) == {"mod.mlog", "code.py"}
    assert by["mod.mlog"]["patterns"][0]["name"] == "Foo"
    assert by["mod.mlog"]["routes"] == [{"path": "/r", "method": "GET"}]
    assert "dept/other" in by["mod.mlog"]["imports"]
    assert "tbl_a" in by["mod.mlog"]["tables"]
    assert "SendTelegramReply" in by["mod.mlog"]["builtins_used"]
    assert by["code.py"]["patterns"][0]["name"] == "bar"
    assert by["code.py"]["routes"] == [{"path": "/x", "method": "GET/POST"}]


def test_ua_scan_no_splitlines_no_read_all():
    """СТАТИКА: сам ua_scan не читает файл целиком — ни read().splitlines(),
    ни read_text() в count_lines (мутация-детектор возврата бомбового
    подсчёта; поведенческие тесты счёта splitlines не отличают)."""
    src = (REPO / "proxy" / "ua_scan.py").read_text(encoding="utf-8")
    body = src[src.index("def count_lines"):src.index("def _walk_office")]
    # только код: докстринг и комментарии упоминают splitlines исторически
    code = body
    # вырезаем докстринг целиком (первая тройка кавычек после подписи)
    doc = re.search(r'\s*""".*?"""\s*', body, re.S)
    if doc:
        code = body[:doc.start()] + body[doc.end():]
    code = "\n".join(l for l in code.splitlines()
                     if not l.strip().startswith("#"))
    assert ".splitlines()" not in code, "count_lines вернулся к splitlines"
    assert ".read_text(" not in code, "count_lines читает файл целиком"
    assert "f.read(READ_CHUNK)" in code, "чанковое чтение исчезло"


def test_routes_admin_delegates_no_splitlines():
    """СТАТИКА: в routes_admin больше нет read_text().splitlines() в
    Scanner/Analyzer — мутация-детектор возврата старого кода."""
    src = ROUTES_ADMIN.read_text(encoding="utf-8")
    assert "read_text(errors='ignore').splitlines()" not in src, (
        "вернулся небезопасный подсчёт строк (OOM 21–22.11)")
    assert src.count("ua_scan.scan_inventory") >= 1
    assert src.count("ua_scan.analyze_files") >= 1


# ─────────────── B. воркер фаз 1–2 под RLIMIT ───────────────

def test_worker_cli_contract(tmp_path):
    """Воркер: rc=0, JSON {inventory, analysis, worker_peak_alloc_mb} —
    контракт ночного вызова _ua_night_scan_analyze."""
    office = tmp_path / "office"
    office.mkdir()
    (office / "a.mlog").write_text("pattern P() -> x\n", encoding="utf-8")
    out = tmp_path / "out.json"
    p = subprocess.run([sys.executable, str(WORKER), str(out), str(office)],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(REPO))
    assert p.returncode == 0, p.stderr[-300:]
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["inventory"]["total_files"] == 1
    assert d["analysis"] and d["analysis"][0]["patterns"][0]["name"] == "P"
    assert d["worker_peak_alloc_mb"] >= 0


def test_worker_memoryerror_own_rc(tmp_path):
    """A.4 наряда: дочка под RLIMIT_AS ниже потребного падает САМА
    (rc=2, MemoryError в её stderr), неубитый родитель (тест) жив."""
    import resource
    office = tmp_path / "office"
    office.mkdir()
    # Предел RLIMIT_AS и объём данных подобраны так, чтобы воркер НЕ смог
    # закончить: python-старт требует ~30 МБ AS; результат воркера — JSON
    # с инвентарём + анализом. Делаем файлов много (10k) с телом, чтобы
    # итоговый JSON-пейлоад гарантированно не влез в остаток от 40 МБ:
    # 10k файлов × ~1.4 КБ записи инвентаря+анализа ≈ 14+ МБ JSON
    # (строки-пути, регулярные структуры) + сама запись json.dump
    # удваивает память (структуры + сериализация).
    for i in range(10_000):
        (office / f"f{i}.mlog").write_text("line\n" * 50, encoding="utf-8")
    out = tmp_path / "out.json"

    def _rlimit():
        lim = 40 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))

    p = subprocess.run([sys.executable, str(WORKER), str(out), str(office)],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(REPO), preexec_fn=_rlimit)
    assert p.returncode == 2, f"ожидался rc=2 (MemoryError), получен {p.returncode}: {p.stderr[-200:]}"
    assert "MemoryError" in p.stderr
    assert not out.exists() or out.stat().st_size == 0


def test_night_cycle_calls_worker_not_internal():
    """СТАТИКА: ночной цикл зовёт _ua_night_scan_analyze (дочерний
    процесс), НЕ _ua_scan/_ua_analyze_internal в теле llm_proxy."""
    src = ROUTES_ADMIN.read_text(encoding="utf-8")
    impl = src[src.index("def _ua_night_cycle_impl_inner"):src.index("def admin_ua_night_cycle")]
    assert "_ua_night_scan_analyze()" in impl, "фазы 1–2 не в воркере"
    assert "_ua_scan_internal()" not in impl, "ночной скан вернулся в llm_proxy"
    assert "_ua_analyze_internal()" not in impl, "анализ вернулся в llm_proxy"


def test_worker_run_tracked_with_rlimit():
    """СТАТИКА: воркер запускается через run_tracked с mem_limit_mb
    (метки RSS + предел A.4 + live-срезы — весь учёт #712)."""
    src = ROUTES_ADMIN.read_text(encoding="utf-8")
    m = re.search(r"def _ua_night_scan_analyze\(.*?\n(def|\Z)", src, re.S)
    assert m, "_ua_night_scan_analyze не найден"
    body = m.group(0)
    assert "run_tracked(" in body
    assert "mem_limit_mb=UA_NIGHT_WORKER_MEM_LIMIT_MB" in body
    assert "ua_night_worker.py" in body


def test_worker_failure_loud_message(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ: rc≠0 воркера → RuntimeError с пределом и хвостом stderr
    (не тихий пропуск с пустыми данными ночи)."""
    import proxy.routes_admin as ra

    class FakeProc:
        returncode = 2
        stderr = "[ua-worker] MemoryError в фазах Scanner/Analyzer"

    def fake_run_tracked(cmd, **kw):
        return FakeProc()

    monkeypatch.setattr(ra, "run_tracked", fake_run_tracked)
    with pytest.raises(RuntimeError) as ei:
        ra._ua_night_scan_analyze()
    msg = str(ei.value)
    assert "предел" in msg and "rc=2" in msg
    assert "MemoryError" in msg


# ─────────────── C. снижение базы покоя ───────────────

def test_malloc_trim_glibc_or_none():
    """malloc_trim: на glibc — число (МБ, может быть 0.0), на другой
    libc — None; вызов не падает и не трогает занятые данные."""
    from proxy.mem_sampler import malloc_trim
    r = malloc_trim()
    assert r is None or (isinstance(r, float) and r >= 0)


def test_malloc_trim_wired_boot_loop_slot():
    """СТАТИКА: трим на буте llm_proxy, ежечасно в петле сборщика и в
    MemRecycleSlot (три точки снижения базы покоя)."""
    sampler = MEM_SAMPLER.read_text(encoding="utf-8")
    assert "boot malloc_trim" in sampler, "нет бут-трима"
    assert re.search(r"malloc_trim\(\)\s*\n\s*if freed", sampler), "нет ежечасного трима в петле"
    sched = ROUTES_SCHED.read_text(encoding="utf-8")
    assert "from proxy.mem_sampler import malloc_trim" in sched
    assert "malloc_trim_freed_mb" in sched, "MemRecycleSlot не отдаёт результат трима"


def test_mem_report_idle_breakdown(tmp_path, monkeypatch):
    """РАЗБИВКА ПОКОЯ (аудит 21.11 04:33): mem_report отдаёт
    idle_breakdown_mb — последний тик каждого процесса; строка брифа
    содержит топ-3 процесса в скобках."""
    from proxy import mem_sampler as ms
    from proxy.core import DB_FILE
    # редирект БД на тестовую
    db = tmp_path / "mem.db"
    import proxy.core as core
    monkeypatch.setattr(core, "DB_FILE", str(db))
    monkeypatch.setattr(ms, "_connect", lambda: __import__("sqlite3").connect(str(db)))
    conn = __import__("sqlite3").connect(str(db))
    ms.ensure_schema(conn)
    conn.close()
    # 3 процесса, свежие тики
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = [("llm_proxy.py", 1, 240.0), ("mlog:serve", 2, 90.0), ("reverse_proxy.py", 3, 40.0)]
    conn = __import__("sqlite3").connect(str(db))
    conn.executemany(
        "INSERT INTO mem_samples (ts, name, pid, rss_mb, kind, ref, phase) VALUES (?,?,?,?,?,?,?)",
        [(ts, n, pid, mb, "tick", "container", "") for n, pid, mb in rows])
    conn.commit()
    conn.close()
    rep = ms.mem_report(hours=1)
    assert rep["idle_breakdown_mb"] == {
        "llm_proxy.py": 240.0, "mlog:serve": 90.0, "reverse_proxy.py": 40.0}
    line = ms.mem_report_line(hours=1)
    assert "llm_proxy.py 240" in line, line
    assert "mlog:serve 90" in line, line
    assert line.count(",") >= 3, f"в строке нет разбивки по процессам: {line}"


def test_brief_line_grows_and_totals(tmp_path, monkeypatch):
    """Строка 💾: сейчас/пик/растёт — прежний формат не сломан
    (регрессия формулы аудита 20.11: сейчас ≤ пик)."""
    from proxy import mem_sampler as ms
    import proxy.core as core
    db = tmp_path / "mem.db"
    monkeypatch.setattr(core, "DB_FILE", str(db))
    monkeypatch.setattr(ms, "_connect", lambda: __import__("sqlite3").connect(str(db)))
    conn = __import__("sqlite3").connect(str(db))
    ms.ensure_schema(conn)
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    # рост llm_proxy за окно: 100 → 180
    rows = [
        ((now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), "llm_proxy.py", 1, 100.0, "tick", "container", ""),
        ((now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), "llm_proxy.py", 1, 180.0, "tick", "container", ""),
        ((now - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"), "mlog:serve", 2, 60.0, "tick", "container", ""),
    ]
    conn.executemany(
        "INSERT INTO mem_samples (ts, name, pid, rss_mb, kind, ref, phase) VALUES (?,?,?,?,?,?,?)",
        rows)
    conn.commit()
    conn.close()
    line = ms.mem_report_line(hours=24)
    assert "сейчас" in line and "пик" in line
    assert "растёт: llm_proxy.py +80" in line, line
    assert "llm_proxy.py 180" in line, line


# ─────────────── D. регрессии прошлых проходов ───────────────

def test_old_n712_guards_still_green():
    """Прежние гварды прохода 1–3 не сломаны: лимит дочек 256,
    live-срезы, RC-строка (файл test_n712_mem_sampler.py на месте)."""
    assert (REPO / "tests" / "test_n712_mem_sampler.py").exists()
    sampler = MEM_SAMPLER.read_text(encoding="utf-8")
    assert "SUBPROCESS_MEM_LIMIT_MB = 256" in sampler
    assert "phase='live'" in sampler or 'phase="live"' in sampler
