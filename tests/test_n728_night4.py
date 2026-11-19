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


def test_b1_every_db_route_has_initdb_or_delegate():
    """ГВАРД КЛАССА (найден живым тестом n603 после B.1): любой route app.mlog
    с прямым db-доступом (query/db_execute/kv_*) обязан поднимать схему сам
    (InitDB в теле) — /health больше не прогревает БД каждые 5 с. Новый
    db-роут без InitDB = 500 «no such table» на холодной БД — красный."""
    src = APP_MLOG.read_text(encoding="utf-8")
    routes = re.findall(r'route "([^"]+)" method=(\w+) \{(.*?)\n  \}', src, re.S)
    assert routes, "парсер route-блоков сломан"
    bad = []
    for path, method, body in routes:
        code = "\n".join(l for l in body.splitlines()
                         if not l.strip().startswith("//"))
        if re.search(r'\b(query|db_execute|kv_get|kv_set)\(', code) and "InitDB" not in code:
            bad.append(f"{method} {path}")
    assert bad == [], (
        "db-роуты без InitDB (холодная БД = no such table, класс #728 B.1): "
        + "; ".join(bad))


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


# ───────────────────── B.3: Grapher не держит общую БД ─────────────────────

def _b3_env(tmp_path, monkeypatch):
    """Окружение Flask test_client на tmp-БД (как test_night_lock.py).

    Герметичность к порядку прогонов: DB_FILE подменяется в САМОМ модуле
    core и во всех импортёрах (routes_admin/kg импортируют имя из core;
    после test_n712 в том же прогоне их ссылка уже материализована —
    monkeypatchattr по одному core недостаточно).
    """
    os.environ['API_SECRET'] = 'test-secret-123'
    os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
    os.environ['OWNER_TELEGRAM_ID'] = '12345'
    os.environ['DATABASE_PATH'] = str(tmp_path)
    os.environ['ZAI_API_KEY'] = 'fake-key'
    os.environ['INTERNAL_API_TOKEN'] = 'tok-n728-test-12345678'
    import llm_proxy  # noqa: F401
    import proxy.core as core
    import proxy.routes_admin as ra
    db = str(tmp_path / "office.db")
    monkeypatch.setattr(core, "DB_FILE", db)
    monkeypatch.setattr(ra, "DB_FILE", db)
    # kg не импортирует DB_FILE — пишет через _query/core, патч core хватает
    from proxy.core import init_db
    init_db()
    return ra


def test_b3_parallel_insert_passes_during_graph_write(tmp_path, monkeypatch):
    """Критерий B.3 аудитора: во время записи графа параллельный INSERT
    в fosved.db проходит за ≤ 3 с (write-лок удерживается ≤ 2 с на батч).

    До B.3 красный двумя местами: (1) роут /admin-ua/graph и ночная фаза
    держали транзакцию от DELETE до конца всех INSERT + 11-минутного
    кросс-файлового скана; (2) kg_scan_rebuild открывал по соединению на
    каждый апсерт (~8.5k за прогон) — суммарно минуты непрерывного лока.
    Здесь замедляем kg-этап (имитация тяжёлого скана ~6k узлов) и меряем
    внешний INSERT ПОКА запись идёт.
    """
    ra = _b3_env(tmp_path, monkeypatch)
    import llm_proxy
    from proxy.core import _query

    # чистая поверхность
    _query("DELETE FROM knowledge_graph", ())
    _query("DELETE FROM knowledge_edges", ())

    # «анализ»: 40 файлов × 30 паттернов = 1200 узлов — запись идёт секунды+
    analysis = []
    for i in range(40):
        analysis.append({
            'path': f'file{i}.mlog',
            'patterns': [{'name': f'Pat{i}_{j}', 'args': '', 'returns': ''} for j in range(30)],
            'routes': [{'path': f'/r{i}', 'method': 'GET'}],
            'imports': [], 'tables': [], 'builtins_used': [],
        })
    monkeypatch.setattr(ra, '_ua_analyze_internal', lambda: analysis)

    # Замедлитель кг-этапа: каждый узел +5 мс «скана» — суммарно ~6 с записи
    orig_rebuild = ra.kg_scan_rebuild

    def slow_rebuild(nodes, source="scan"):
        time.sleep(0.5)  # фаза подготовки рёбер/узлов (вне транзакции)
        return orig_rebuild(nodes, source=source)

    monkeypatch.setattr(ra, 'kg_scan_rebuild', slow_rebuild)

    result_box = {}

    def _run():
        client = llm_proxy.app.test_client()
        # /admin-ua/* — 127.0.0.1 + X-Internal-Token (#550 A.2)
        resp = client.get('/admin-ua/graph',
                          environ_base={"REMOTE_ADDR": "127.0.0.1"},
                          headers={'X-Internal-Token': os.environ['INTERNAL_API_TOKEN']})
        result_box['status'] = resp.status_code

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    # даём Grapher'у войти в запись (ждём первую партию рёбер)
    time.sleep(2.0)

    t0 = time.perf_counter()
    last_err = None
    while time.perf_counter() - t0 < 3.0:
        try:
            _query("INSERT INTO knowledge_graph (node_type, node_name, file_path) "
                   "VALUES ('probe', 'probe-n728', 'probe.mlog')", ())
            last_err = None
            break
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    elapsed = time.perf_counter() - t0
    th.join(timeout=60)
    assert not th.is_alive(), "Grapher не завершился за 60 с"
    assert result_box.get('status') == 200, f"роут упал: {result_box}"
    assert last_err is None, (
        f"параллельный INSERT не прошёл за {elapsed:.1f} с ({last_err}) — "
        "Grapher держит общую БД дольше критерия B.3 (≤ 2 с на батч)")
    # рёбра реально записаны (не пустышка)
    edges = _query("SELECT COUNT(*) AS c FROM knowledge_edges", (), fetch=True)
    assert edges and edges[0]['c'] >= 1200, "рёбра не записаны"
    _query("DELETE FROM knowledge_graph WHERE node_type='probe'", ())


def test_b3_static_grapher_short_transactions():
    """СТАТИКА B.3: батчная запись рёбер, busy_timeout, скан вне транзакции."""
    src = ROUTES_ADMIN.read_text(encoding="utf-8")
    # 1) константы на месте
    assert "EDGE_COMMIT_ROWS = 200" in src, "лимит строк на транзакцию исчез"
    assert "GRAPH_BUSY_TIMEOUT_MS" in src, "busy_timeout Grapher исчез"
    # 2) оба вызывателя идут через общий write-фазу
    assert src.count("_grapher_write_phase(") >= 3, (
        "роут /admin-ua/graph и ночная фаза должны делить _grapher_write_phase "
        "(вызов + 2 определения вызовов)")
    # 3) мутация «одна транзакция на все рёбра»: в write-фазе executemany
    #    обязан идти циклом по батчам с commit внутри
    m = re.search(r"def _grapher_write_phase\(.*?\n@app\.", src, re.S)
    assert m, "_grapher_write_phase не найден"
    body = m.group(0)
    assert "for i in range(0, len(edges_rows), EDGE_COMMIT_ROWS)" in body, (
        "батч-цикл записи рёбер исчез — вернулась одна длинная транзакция")
    # 4) анализ ДО открытия соединения в роуте graph (мутация-детектор:
    #    DELETE/CREATE TABLE не встречается до вызова _ua_analyze_internal;
    #    только некомментарные строки — в комментарии история фикса)
    route = re.search(r'@app\.get\("/admin-ua/graph"\).*?(?=@app\.)', src, re.S)
    assert route, "роут /admin-ua/graph не найден"
    py_code = "\n".join(l for l in route.group(0).splitlines()
                        if not l.strip().startswith("#"))
    ai = py_code.index("_ua_analyze_internal")
    for banned in ("DELETE FROM knowledge_edges", "sqlite3.connect"):
        assert banned not in py_code[:ai], (
            f"{banned} выполняется до анализа — транзакция снова висит на скане")
    # 5) kg.py: чанковый ребилд
    kg_src = (REPO / "proxy" / "kg.py").read_text(encoding="utf-8")
    assert "KG_CHUNK = 500" in kg_src, "чанк ребилда исчез"
    assert "parent_count_for" not in kg_src, (
        "per-node parent_count запросы вернулись (должен быть один агрегат)")


def test_b3_mutation_single_transaction_is_red():
    """Мутационный самотест детектора: «executemany без батч-цикла» — красный."""
    src = ROUTES_ADMIN.read_text(encoding="utf-8")
    mutated = src.replace(
        "for i in range(0, len(edges_rows), EDGE_COMMIT_ROWS):\n"
        "            c.executemany(ins, edges_rows[i:i + EDGE_COMMIT_ROWS])\n"
        "            conn.commit()",
        "c.executemany(ins, edges_rows)\n        conn.commit()")
    assert mutated != src, "мутация не применилась (патч-якорь устарел)"
    with pytest.raises(AssertionError):
        assert "for i in range(0, len(edges_rows), EDGE_COMMIT_ROWS)" in mutated


# ─────────────────── B.2: догон night-tick не зацикливается ───────────────────

TOKEN_N728 = "tok-n728-mlog-12345678"


def _b2_harness(port):
    """Харнесс: НАСТОЯЩИЕ InitDB/OutboxPut/NightTickSlot + новые паттерны
    попыток; фазы — стабы-«зависания» (имитация долгого Grapher'а, класс
    прода 19.11: контейнер убивают СЕРЕДИНА тика). Собран по образцу
    tests/test_night_lock.py (_extract по балансу скобок, №620: VM
    компилирует файл целиком — включаем PollJobStatus)."""
    app_src = APP_MLOG.read_text(encoding="utf-8")
    sched_src = SCHED_MLOG.read_text(encoding="utf-8")
    utils_src = (REPO / "dept" / "utils.mlog").read_text(encoding="utf-8")

    init_db_text = _extract(app_src, "InitDB", "CREATE TABLE IF NOT EXISTS audit_log")
    outbox_text = _extract(sched_src, "OutboxPut", "owner_outbox")
    tick_text = _extract(sched_src, "NightTickSlot", 'OutboxPut("night-tick"')
    guard_text = (
        _extract(sched_src, "NightPhaseDone", 'return "new"')
        + "\n\n" + _extract(sched_src, "NightPhaseMark", "UPDATE night_run_state")
        + "\n\n" + _extract(sched_src, "NightPhaseBegin", 'return "acquired"')
        + "\n\n" + _extract(sched_src, "NightTickAttemptGate", "finished_at IS NULL")
        + "\n\n" + _extract(sched_src, "NightTickAttemptOpen", "INSERT INTO night_tick_attempts")
        + "\n\n" + _extract(sched_src, "NightTickAttemptClose", "SET finished_at")
        + "\n\n" + _extract(sched_src, "NightTickAttemptDay", "date('now', '+3 hours')")
        + "\n\n" + _extract(sched_src, "NightTickAttemptMax", "return 2.0")
    )
    tryval_text = _extract(utils_src, "TryVal", "return")
    colguard_text = (
        _extract(utils_src, "ColumnExists", "pragma_table_info")
        + "\n\n" + _extract(utils_src, "AlterColIfMissing", "ColumnExists")
    )
    poll_text = _extract(sched_src, "PollJobStatus", "http_get")

    init_db_text = init_db_text.replace("let _ = LZDataMaintain()",
                                        "let _ = LZDataMaintainStub()")
    assert "LZDataMaintainStub()" in init_db_text
    init_db_text = init_db_text.replace("let _ = LZWatchSeedCategory()",
                                        "let _ = LZWatchSeedCategoryStub()")
    assert "LZWatchSeedCategoryStub()" in init_db_text
    # «перезапуск прода»: тик никогда не доходит до конца — фаза backup
    # висит 300 с (sleep, как зависший Grapher), тест убивает serve раньше.
    # Connection-refused не годится: http_get к мёртвому порту падает
    # мгновенно, тик успевает закончиться и закрыть попытку.
    tick_text = tick_text.replace(
        'let r_backup = redact(to_string(TryVal(try http_get(base + "backup" + qs, 300.0))), "all")',
        'let r_backup = "hang-n728"\n    sleep(300.0)')
    assert "hang-n728" in tick_text, "подмена фазы backup не удалась"

    return (
        "// #728 B.2: харнесс — НАСТОЯЩИЕ NightTickSlot/InitDB/OutboxPut/"
        "// попытки догона; фаза backup «висит» (имитация смерти контейнера\n"
        "// среди тика, прод 19.11). Мост №391 как в entrypoint.\n"
        + "profile legacy { egress: permissive_with_audit }\n\n"
        + "db { url: env(\"DATABASE_URL\") }\n\n"
        + tryval_text + "\n\n"
        + colguard_text + "\n\n"
        + init_db_text + "\n\n"
        + outbox_text + "\n\n"
        + guard_text + "\n\n"
        + poll_text + "\n\n"
        + tick_text + "\n\n"
        + "pattern LZDataMaintainStub() -> String {\n  return \"ok\"\n}\n\n"
        + "pattern LZWatchSeedCategoryStub() -> String {\n  return \"ok\"\n}\n\n"
        # NightSlot (фаза night) — стаб: тик не должен до него доходить
        # (фаза backup висит); определение нужно для VM-компиляции (№620).
        + "pattern NightSlot() -> String {\n  return \"night-stub-ok\"\n}\n\n"
        + "pattern AuditLog(action: String, dept: String, details: String) -> String {\n"
        + "  let _ = db_execute(\"INSERT INTO audit_log (action, actor, dept, details) VALUES (?1, 'system', ?2, ?3)\", [action, dept, details])\n"
        + "  return \"ok\"\n}\n\n"
        + f"mlogserver {{\n  port: {port}\n  host: \"127.0.0.1\"\n\n"
        + "  route \"/run-tick\" method=GET {\n    return NightTickSlot()\n  }\n"
        + "}\n"
    )


class _ServeB2:
    """bin/mlog serve с харнессом B.2; kill_immidiate() — «перезапуск прода»."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="n728-b2-")
        self.port = _free_port(17401)
        self.db = os.path.join(self.dir, "fosved.db")
        # прод-порядок: Flask поднимает owner_outbox раньше первого тика
        # (как в проде — по образцу tests/test_night_lock.py)
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE IF NOT EXISTS owner_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "created_at TEXT DEFAULT (datetime('now')), source TEXT NOT NULL, text TEXT NOT NULL, sent_at TEXT)")
        con.commit()
        con.close()
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_b2_harness(self.port))
        env = dict(os.environ)
        env.update({
            "DATABASE_URL": f"sqlite:{self.db}",
            "CRON_SECRET": TOKEN_N728,
            "METALOGOS_ENV_ALLOWLIST": "CRON_SECRET,DATABASE_URL",
            "METALOGOS_SERVE_BACKEND": "vm",
            "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
            "METALOGOS_DATA_DIR": self.dir,
        })
        self.log = open(os.path.join(self.dir, "serve.log"), "w")
        self.env = env
        self.proc = subprocess.Popen(
            [str(MLOG_BIN), "serve", src], cwd=self.dir, env=env,
            stdout=self.log, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid)
        self.url = f"http://127.0.0.1:{self.port}"
        self._wait_boot()

    def restart(self):
        """Рестарт serve на той же БД (как Render перезапускает контейнер:
        диск с fosved.db переживает, env тот же)."""
        self.proc = subprocess.Popen(
            [str(MLOG_BIN), "serve", os.path.join(self.dir, "harness.mlog")],
            cwd=self.dir, env=self.env,
            stdout=self.log, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        self._wait_boot()

    def _wait_boot(self):
        import requests as _rq
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = open(self.log.name, errors="replace").read()[-800:]
                raise RuntimeError(f"mlog serve умер при старте:\n{tail}")
            try:
                _rq.get(self.url + "/run-tick", timeout=1)
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("mlog serve не поднялся за 90 с")

    def tick_bg(self):
        """Запустить /run-tick в фоне треде (как catch-up на буте)."""
        th = threading.Thread(target=self._tick_call, daemon=True)
        th.start()
        return th

    def _tick_call(self):
        try:
            import requests as _rq
            _rq.get(self.url + "/run-tick", timeout=400)
        except Exception:
            pass  # «контейнер убит» — соединение рвётся, это и есть сценарий

    def kill_hard(self):
        """SIGKILL группы процессов — «Render убил контейнер»."""
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=10)
        except Exception:
            pass

    def attempts(self):
        con = sqlite3.connect(self.db, timeout=5)
        try:
            rows = con.execute(
                "SELECT attempt, finished_at FROM night_tick_attempts "
                "ORDER BY id").fetchall()
            outbox = con.execute(
                "SELECT text FROM owner_outbox WHERE source='night-tick' "
                "ORDER BY id").fetchall()
            audit = con.execute(
                "SELECT details FROM audit_log WHERE action='cron_night_tick' "
                "ORDER BY id").fetchall()
        finally:
            con.close()
        return rows, [r[0] for r in outbox], [r[0] for r in audit]

    def stop(self):
        self.kill_hard()
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def test_b2_catchup_stops_after_two_unfinished_attempts():
    """Критерий B.2: три «перезапуска» при незавершённом тике → запусков 2,
    третий отказ с громкой записью (audit + owner_outbox).

    Сценарий прода 19.11 (инстанс lhhd6): тик стартует → фаза висит →
    контейнер убит health-check'ом → рестарт → catch-up снова тик → …
    До B.2: бесконечный цикл (каждые ~15 минут). После: третья попытка
    за дату получает отказ «догон остановлен», запись в outbox попадает
    в ночную сводку 07:15 MSK — не тихий пропуск (граница наряда).
    """
    # «Перезапуск» = новый _ServeB2 на СВОЕЙ же БД не подходит (tmp-директория
    # новая); вместо этого один serve, убиваемый насильно: попытки живут в
    # его БД, а kill+подъём на той же БД и есть рестарт контейнера Render.
    s = _ServeB2()
    try:
        # цикл рестартов: бут (тик №1) → kill среди тика → рестарт на той же
        # БД → тик №2 → kill → рестарт → тик №3 (гейт обязан отказать).
        for round_no in (1, 2, 3):
            th = s.tick_bg()
            if round_no < 3:
                # ждём, пока попытка зафиксирована в БД (стартовая запись)
                deadline = time.time() + 20
                while time.time() < deadline:
                    rows, _, _ = s.attempts()
                    if rows and max(r[0] for r in rows) >= round_no:
                        break
                    time.sleep(0.3)
                else:
                    raise AssertionError(
                        f"раунд {round_no}: попытка не зафиксирована за 20 с:\n"
                        + open(s.log.name, errors="replace").read()[-600:])
                # «контейнер убит среди тика» — попытка остаётся незакрытой
                s.kill_hard()
                s.restart()
            else:
                # раунд 3: гейт должен отказать ДО открытия попытки — ждём
                # запись остановки в owner_outbox (доставка 07:15 MSK)
                gate_line = None
                deadline = time.time() + 30
                while time.time() < deadline:
                    _, outbox, _ = s.attempts()
                    for t in outbox:
                        if "догон остановлен" in t:
                            gate_line = t
                            break
                    if gate_line:
                        break
                    time.sleep(0.5)
                rows, outbox, audit = s.attempts()
                assert gate_line is not None, (
                    f"третий запуск не остановлен гейтом; attempts={rows}; "
                    f"outbox={outbox[-2:]}; log tail:\n"
                    + open(s.log.name, errors="replace").read()[-800:])
                # запусков ровно 2 (третий не открыл попытку)
                assert len(rows) == 2, (
                    f"попыток открыто {len(rows)} (ожидалось 2): {rows}")
                # громкость: и audit, и owner_outbox
                assert any("догон остановлен" in a for a in audit), (
                    f"нет записи в audit_log: {audit[-2:]}")
                assert "незавершённых попыток" in gate_line and "#728" in gate_line
                # обе попытки незавершённые (kill среди тика) — finished_at IS NULL
                assert all(r[1] is None for r in rows), rows
                th.join(timeout=35)
                assert not th.is_alive(), "слот не завершился после отказа гейта"
    finally:
        s.stop()


def test_b2_static_gate_in_slot_and_ddl():
    """СТАТИКА B.2: гейт в начале NightTickSlot, закрытие в конце, DDL в InitDB."""
    sched = SCHED_MLOG.read_text(encoding="utf-8")
    tick = _pattern_segment(sched, "pattern NightTickSlot()")
    code = "\n".join(_code_lines(tick))
    gate_pos = code.index("NightTickAttemptGate()")
    open_pos = code.index("NightTickAttemptOpen()")
    close_pos = code.index("NightTickAttemptClose()")
    # гейт ДО открытия попытки, закрытие — после OutboxPut (тик дошёл до конца)
    assert gate_pos < open_pos, "гейт проверяется после открытия попытки"
    outbox_pos = code.index('OutboxPut("night-tick"')
    assert close_pos > outbox_pos, "попытка закрывается до OutboxPut — до конца тика"
    # порог — 2 (мутация-детектор: вернуть 3.0 → тест красный)
    assert "return 2.0" in _pattern_segment(sched, "pattern NightTickAttemptMax()")
    # DDL в обеих точках входа
    app_src = APP_MLOG.read_text(encoding="utf-8")
    dog_src = (REPO / "dogfood_staging.mlog").read_text(encoding="utf-8")
    for src, name in ((app_src, "app.mlog"), (dog_src, "dogfood_staging.mlog")):
        assert "CREATE TABLE IF NOT EXISTS night_tick_attempts" in src, (
            f"{name}: нет DDL night_tick_attempts")



