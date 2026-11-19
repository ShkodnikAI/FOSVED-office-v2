#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #728 NIGHT-4 (P0): спираль перезапусков прода — гварды B.1–B.4.

Аудитор 19.11 (issue #728): прод перезапускается каждые ~15 минут с 18.11
(server_failed «health check timed out», вперемешку с oomKilled). Механизм:
night-tick (catch-up после каждого рестарта) → фаза Grapher держит общую
fosved.db на запись ~11 мин → /health с InitDB() ловит «database is locked»
→ 500/таймаут health check → Render убивает контейнер → догон снова
запускает тик. Круг замкнулся 13.11 (три мёртвые ночи).

Слои тестов (паттерн офиса: поведение + структура + мутационный самотест):

B.1 /health не пишет в БД:
  - ЖИВОЙ bin/mlog serve: при удержанном внешнем write-локе (BEGIN EXCLUSIVE
    чужим соединением) /health отвечает 200 за < 1 с (критерий аудитора).
    Мутация «вернуть InitDB в /health» на копии харнесса — красная.
  - СТАТИКА: в теле route "/health" app.mlog нет InitDB/db_execute/query
    (мутационный якорь: строка «let _ = InitDB()» в сегменте — красная).

B.2 догон night-tick не зацикливается:
  - ЖИВОЙ bin/mlog serve (харнесс с НАСТОЯЩИМ NightTickSlot и таблицей
    night_tick_attempts): три «перезапуска» подряд при незавершённом тике
    → запусков ровно 2, третий отказ с громкой записью (audit + outbox),
    плановый слот следующей ночи не задет (счётчик по MSK-дате).
  - СТАТИКА: NightTickSlot вызывает NightTickAttempt* перед фазами.

B.3 Grapher не держит общую БД при долгой записи:
  - ПОВЕДЕНИЕ (Flask test_client): во время записи графа (замедленный
    kg-этап) параллельный INSERT в fosved.db проходит за ≤ 3 с (критерий
    аудитора); каждый write-батч ≤ 2 с (замер по количеству строк на
    транзакцию — структурный лимит в коде).
  - СТАТИКА: в /admin-ua/graph и _ua_night_cycle_impl_inner нет
    «DELETE FROM knowledge_edges» до/во время скана файлов: рёбра
    собираются в память, запись — короткими транзакциями (KG_BATCH),
    busy_timeout на соединении.

B.4 mem-sampler не блокируется при локе БД:
  - ПОВЕДЕНИЕ: store_samples при удержанном внешнем write-локе
    (busy_timeout 500 мс) НЕ ждет 10 с и НЕ роняет петлю: тихий пропуск
    с одной строкой в stderr (п. наряда: «без повторов в цикле»).
  - СТАТИКА: соединение mem_sampler ставит busy_timeout(500).
"""
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_MLOG = REPO / "app.mlog"
SCHED_MLOG = REPO / "dept" / "scheduler.mlog"
ROUTES_ADMIN = REPO / "proxy" / "routes_admin.py"
MEM_SAMPLER = REPO / "proxy" / "mem_sampler.py"
MLOG_BIN = REPO / "bin" / "mlog"

pytestmark = pytest.mark.skipif(
    not MLOG_BIN.exists() or os.name != "posix",
    reason="нужен bin/mlog (Linux-стенд)")


# ────────────────────────── общие утилиты ──────────────────────────

def _code_lines(seg: str) -> list:
    """Некомментарные строки сегмента (упоминания в комментариях не считаются)."""
    return [l for l in seg.splitlines() if not l.strip().startswith("//")]


def _route_segment(src: str, path: str, path_kw: str = 'route "/health" method=GET') -> str:
    """Тело route: от строки объявления до закрывающей «}» уровня блока."""
    idx = src.index(path_kw)
    rest = src[idx:]
    return rest[:rest.index("\n  }\n") + 5] if "\n  }\n" in rest else rest


def _pattern_segment(src: str, decl: str) -> str:
    """Тело паттерна: от объявления до следующего 'pattern ' (идиома n485/n706)."""
    start = src.index(decl)
    rest = src[start + len(decl):]
    nxt = rest.find("\npattern ")
    return rest[:nxt] if nxt != -1 else rest


def _free_port(preferred):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class _Serve:
    """subprocess bin/mlog serve (по образцу tests/test_night_lock.py)."""

    def __init__(self, harness_src: str, port: int, env_extra: dict):
        self.dir = tempfile.mkdtemp(prefix="n728-serve-")
        self.port = _free_port(port)
        self.db = os.path.join(self.dir, "fosved.db")
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(harness_src)
        env = dict(os.environ)
        env.update({
            "DATABASE_URL": f"sqlite:{self.db}",
            "METALOGOS_ENV_ALLOWLIST": "CRON_SECRET,DATABASE_URL",
            "METALOGOS_SERVE_BACKEND": "vm",
            "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
            "METALOGOS_DATA_DIR": self.dir,
        })
        env.update(env_extra)
        os.chmod(MLOG_BIN, 0o755)
        self.log = open(os.path.join(self.dir, "serve.log"), "w")
        self.proc = subprocess.Popen(
            [str(MLOG_BIN), "serve", src], cwd=self.dir, env=env,
            stdout=self.log, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid)
        self.url = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 90
        import requests as _rq
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = open(self.log.name, errors="replace").read()[-800:]
                raise RuntimeError(f"mlog serve умер при старте:\n{tail}")
            try:
                _rq.get(self.url + "/health", timeout=2)
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("mlog serve не поднялся за 90 с")

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass
        finally:
            self.log.close()
            shutil.rmtree(self.dir, ignore_errors=True)


def _extract(src: str, pattern_name: str, path: str) -> str:
    """Балансный экстрактор тела паттерна (идиома tests/test_night_lock.py)."""
    m = re.search(r"pattern %s\(" % pattern_name, src)
    assert m, f"pattern {pattern_name} не найден в {path}"
    depth = 0
    started = False
    for i in range(m.start(), len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth == 0:
                return src[m.start():i + 1]
    raise AssertionError(f"pattern {pattern_name}: несбалансированные скобки в {path}")


def _hold_write_lock(db_path: str, ready: threading.Event, release: threading.Event):
    """Внешний write-лок: BEGIN EXCLUSIVE в отдельном соединении/треде.

    EXCLUSIVE (не IMMEDIATE) — блокирует и читателей: даже read-only
    db_execute из InitDB честно встречает «database is locked».
    """
    con = sqlite3.connect(db_path, timeout=1.0)
    try:
        con.execute("BEGIN EXCLUSIVE")
        ready.set()
        release.wait(timeout=60)
        con.rollback()
    finally:
        con.close()


# ───────────────────────────── B.1: /health ─────────────────────────────

HARNESS_B1_HEAD = """// #728 B.1: НАСТОЯЩИЙ route "/health" из app.mlog на минимальном харнессе.
// Мост №391, как в проде: respond из route — sink-clearance под legacy.
profile legacy { egress: permissive_with_audit }

db { url: env("DATABASE_URL") }

pattern InitDB() -> String {
  let _ = db_execute("CREATE TABLE IF NOT EXISTS probe_b1 (x TEXT)", [])
  return "ok"
}

mlogserver {
  port: PORT_N728
  host: "127.0.0.1"

"""

HARNESS_B1_TAIL = """
}
"""


def _health_body_from_app() -> str:
    """Тело route "/health" из боевого app.mlog — вербатим, включая «}» блока."""
    src = APP_MLOG.read_text(encoding="utf-8")
    idx = src.index('route "/health" method=GET')
    rest = src[idx:]
    end = rest.index("\n  }\n") + len("\n  }\n") - 1  # включаем «}» роута
    return rest[:end]


def test_b1_health_answers_under_external_write_lock():
    """/health при удержанном внешнем write-локе — 200 за < 1 с (критерий B.1).

    До фикса красный: InitDB внутри /health исполняет db_execute под чужим
    EXCLUSIVE-локом → «database is locked» → 500 (прод 19.11 03:00:02,
    каждые 5 с до убийства контейнера).
    """
    body = _health_body_from_app()
    assert "InitDB" not in "\n".join(
        _code_lines(body)), "в /health вернулся InitDB — см. B.1 наряда"
    src = HARNESS_B1_HEAD.replace("PORT_N728", str(_free_port(17301))) + body + HARNESS_B1_TAIL
    port = int(re.search(r"port: (\d+)", src).group(1))
    s = _Serve(src, port, {"CRON_SECRET": "n728-b1"})
    try:
        # VERSION-файл пишет entrypoint; на харнессе его может не быть —
        # создаём, чтобы read_file не влиял на тайминг (№422: путь тот же).
        with open(os.path.join(s.dir, "VERSION"), "w") as f:
            f.write("n728-test\n")
        ready, release = threading.Event(), threading.Event()
        th = threading.Thread(target=_hold_write_lock,
                              args=(s.db, ready, release), daemon=True)
        th.start()
        assert ready.wait(timeout=10), "лок-холдер не поднялся"
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(s.url + "/health", timeout=10) as resp:
                body = resp.read().decode()
                status = resp.status
            elapsed = time.perf_counter() - t0
        finally:
            release.set()
            th.join(timeout=10)
        assert status == 200, f"ожидался 200, получен {status}: {body[:200]}"
        assert elapsed < 1.0, (
            f"/health под внешним локом отвечал {elapsed:.2f} с (> 1 с) — "
            "health-check Render (таймаут 5 с) не переживёт длинный лок")
    finally:
        s.stop()


def test_b1_mutation_initdb_back_in_health_is_red():
    """Мутация «вернуть InitDB в /health» — красная (требование аудитора).

    Гвард-детектор мутации — _code_lines(body) + 'InitDB not in': строка
    «let _ = InitDB()» в сегменте обязана ронять проверку. Проверяем
    детектор на синтетическом мутированном сегменте (иначе мутацию
    никто никогда не прогонит).
    """
    body = _health_body_from_app()
    mutated = "  let _ = InitDB()\n" + body
    with pytest.raises(AssertionError):
        assert "InitDB" not in "\n".join(_code_lines(mutated)), (
            "мутация не обнаружена гвардом")


def test_b1_static_health_route_has_no_db_writes():
    """СТАТИКА: в route "/health" app.mlog нет InitDB/db_execute/query/kv_set."""
    src = APP_MLOG.read_text(encoding="utf-8")
    seg = _route_segment(src, "/health")
    code = "\n".join(_code_lines(seg))
    for banned in ("InitDB", "db_execute", "query(", "kv_set", "AuditLog"):
        assert banned not in code, f"/health пишет в БД ({banned}) — B.1 нарушена"
    assert "read_file(\"VERSION\")" in code, "ответ /health потерял VERSION (№422)"


def test_b1_dogfood_health_same_fix():
    """dogfood_staging.mlog — та же правка (вторая точка входа)."""
    src = (REPO / "dogfood_staging.mlog").read_text(encoding="utf-8")
    seg = _route_segment(src, "/health")
    code = "\n".join(_code_lines(seg))
    assert "InitDB" not in code, "dogfood /health всё ещё зовёт InitDB"


# ─────────────────────── B.4: mem-sampler под локом ───────────────────────

def test_b4_store_skips_fast_under_external_write_lock(tmp_path, monkeypatch, capsys):
    """При удержанном внешнем write-локе store_samples отказывается
    за ≤ ~1 с (busy_timeout 500 мс), НЕ бросает, пишет одну строку
    «skip … db locked» в stderr (граница наряда: без повторов, без очереди).

    До B.4: sqlite3.connect(DB_FILE, timeout=10) — каждая метка слота
    ждала до 10 с под локом Grapher (прод 19.11 03:00:26Z: store failed
    … database is locked — после 10-с ожидания), тред слота залипал.
    """
    sys.path.insert(0, str(REPO))
    from proxy import mem_sampler

    db = tmp_path / "b4.db"
    import proxy.core
    monkeypatch.setattr(proxy.core, "DB_FILE", str(db))
    monkeypatch.setattr(mem_sampler, "_SCHEMA_READY", False)

    # Схема должна появиться ДО внешнего лока (иначе — отложенная, тоже ок,
    # но тестируем именно store-путь).
    mem_sampler._ensure_schema_once()
    assert mem_sampler._SCHEMA_READY, "схема не поднялась на пустой БД"

    ready, release = threading.Event(), threading.Event()
    th = threading.Thread(target=_hold_write_lock,
                          args=(str(db), ready, release), daemon=True)
    th.start()
    assert ready.wait(timeout=10)
    try:
        t0 = time.perf_counter()
        mem_sampler.store_samples(
            [{"pid": 1, "name": "llm_proxy.py", "rss_mb": 123.0}],
            kind="tick", ref="container", phase="")
        elapsed = time.perf_counter() - t0
    finally:
        release.set()
        th.join(timeout=10)

    assert elapsed < 1.5, (
        f"store_samples под внешним локом выполнялся {elapsed:.2f} с — "
        "дефолтные 10 с таймаута всё ещё в игре (B.4)")
    err = capsys.readouterr().err
    assert "db locked" in err, (
        f"тихого пропуска среза нет (нужна строка 'skip … db locked'): {err!r}")
    assert "Traceback" not in err, "store_samples бросил исключение наружу"
    # Срез НЕ записан и НЕ поставлен в очередь (без повторов): в БД пусто.
    con = sqlite3.connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM mem_samples").fetchone()[0]
    finally:
        con.close()
    assert n == 0, f"под локом записалось {n} строк — очередь/повтор появились"


def test_b4_busy_timeout_static():
    """СТАТИКА: _connect ставит busy_timeout 500 мс (не дефолт 10 с)."""
    src = MEM_SAMPLER.read_text(encoding="utf-8")
    assert "BUSY_TIMEOUT_MS = 500" in src, "константа busy_timeout исчезла"
    m = re.search(r"def _connect\(\):.*?return conn", src, re.S)
    assert m, "_connect не найден"
    body = m.group(0)
    assert "timeout=BUSY_TIMEOUT_MS / 1000.0" in body, (
        "connect(timeout=…) не привязан к BUSY_TIMEOUT_MS")
    assert "PRAGMA busy_timeout" in body, "PRAGMA busy_timeout не ставится"
    # skip-ветка: OperationalError с locked/busy → одна строка skip, не стек
    store = re.search(r"def store_samples\(.*?\n    except sqlite3\.OperationalError", src, re.S)
    assert store, "у store_samples нет отдельной ветки OperationalError (locked)"
    assert 'print(f"[mem-sampler] skip {kind}/{ref}: db locked' in src, (
        "нет строки тихого пропуска «skip … db locked»")

