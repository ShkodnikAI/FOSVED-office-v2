#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #569: ночная блокировка базы — держатель найден и устранён.

Гварды:
- ИНТЕГРАЦИЯ (A.1/A.2): реальный обработчик /admin-ua/night-cycle через
  test_client в отдельном треде (как waitress в проде). Фазы 1/2/4 стабы,
  фаза 3 и kg_scan_rebuild — НАСТОЯЩИЕ. До правки обработчик падал на
  само-блокировке (kg писал через _query под собственным незакоммиченным
  локом raw-conn), conn не закрывался на пути исключения — фрейм+traceback
  образуют цикл, соединение-зомби держит WRITE-лок после смерти треда
  (прод 19.10: 02:00:39–03:42Z, /supply/next и mlog-слот ловили
  database is locked). Тест: после ответа обработчика внешнее соединение
  пишет в базу не позже 30 с (критерий A.2 наряда). gc.disable() на время
  запроса делает красное поведение детерминированным (ночью в проде GC
  тоже не собирал цикл десятки минут);
- ИНТЕГРАЦИЯ A.4 (настоящий bin/mlog serve): харнесс с НАСТОЯЩИМ InitDB,
  OutboxPut и NightTickSlot; NightSlot-стаб бросает SQL-ошибку (= prod
  "database is locked" в фазе), AuditLog-стаб падает всегда (= прод-лок
  на записи аудита). Критерий: в outbox есть запись night-tick с текстом
  ошибки — слот не умирает до OutboxPut (до правки: AuditLog после try
  NightSlot() убивал слот → dispatch error → outbox пуст);
- СТАТИКА A.3: у http_post /admin-ua/night-cycle есть 4-й аргумент-таймаут;
- СТАТИКА A.1: golden-evals вызывается с ?secret= (источник 403 02:00:04Z);
- СТАТИКА A.4: перед OutboxPut("night-tick") аудит обёрнут в TryVal(try …).

Мутационные проверки по наряду (A.5): снять правку A.2 в routes_admin.py →
интеграционный тест красный; снять правку A.4 в scheduler.mlog → харнесс-тест
красный. Процедура — в отчёте наряда.
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
import gc

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n569-lock-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['INTERNAL_API_TOKEN'] = 'tok-n569-test-12345678'

import llm_proxy  # noqa: E402,F401 — конвенция: env до импорта
from proxy import routes_admin as ra  # noqa: E402
from proxy.core import DB_FILE, _query, init_db  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MLOG_BIN = os.path.join(REPO, "bin", "mlog")
APP_MLOG = os.path.join(REPO, "app.mlog")
SCHED_MLOG = os.path.join(REPO, "dept", "scheduler.mlog")

pytestmark_n569 = None  # noqa (документационная)

# ── ИНТЕГРАЦИЯ A.1/A.2: обработчик не оставляет WRITE-лок ────────────────


def _stub_analysis():
    """Один файл с паттерном/роутом/импортом — calls-цикл пуст (pfile==rel)."""
    return [{'path': 'a.mlog',
             'patterns': [{'name': 'PatA'}],
             'routes': [{'path': '/ra', 'method': 'GET'}],
             'imports': ['b']}]


@pytest.fixture()
def night_env():
    init_db()
    # чистая поверхность: kg-таблицы пусты
    _query("DELETE FROM knowledge_graph", ())
    _query("DELETE FROM knowledge_edges", ())
    yield
    gc.enable()
    gc.collect()


def test_night_cycle_failure_releases_write_lock(night_env, monkeypatch):
    """A.2: после сбоя/успеха обработчика второе соединение пишет <= 30 с.

    До правки #569 красный: kg_scan_rebuild падал на само-блокировке,
    raw-conn оставался с незавершённой транзакцией — WRITE-лок держался.
    """
    monkeypatch.setattr(ra, '_ua_scan_internal',
                        lambda: {'total_files': 1, 'total_lines': 10})
    monkeypatch.setattr(ra, '_ua_analyze_internal', _stub_analysis)
    monkeypatch.setattr(ra, '_ua_review_internal',
                        lambda: {'findings': [], 'health_score': 9})

    result_box = {}

    def _run():
        client = llm_proxy.app.test_client()
        try:
            resp = client.post(
                '/admin-ua/night-cycle',
                headers={'X-Internal-Token': os.environ['INTERNAL_API_TOKEN']},
                json={})
            result_box['status'] = resp.status_code
            result_box['body'] = resp.get_json(silent=True) or {}
        except Exception as e:  # pragma: no cover — диагностика красного прогона
            result_box['error'] = repr(e)

    # Как в проде (waitress): запрос выполняется в отдельном треде; без GC
    # цикл frame↔traceback держит незакрытый conn — красное поведение
    # детерминировано (ночью в проде GC не собирал цикл ~100 минут).
    gc.disable()
    try:
        th = threading.Thread(target=_run, daemon=True)
        th.start()
        th.join(timeout=120)
        assert not th.is_alive(), "обработчик не завершился за 120 с"
    finally:
        gc.enable()

    status = result_box.get('status')
    assert status in (200, 500), f"неожиданный статус: {result_box}"

    # Критерий A.2: второе соединение пишет успешно не позже чем через 30 с.
    t0 = time.perf_counter()
    last_err = None
    while time.perf_counter() - t0 < 30:
        try:
            _query("INSERT INTO knowledge_graph (node_type, node_name, file_path) "
                   "VALUES ('probe', 'probe-n569', 'probe.mlog')", ())
            last_err = None
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    elapsed = time.perf_counter() - t0
    assert last_err is None, (
        f"WRITE-лок не снялся за {elapsed:.1f} с (последняя ошибка: {last_err}) — "
        f"держатель блокировки воспроизведён; статус обработчика {status}")
    assert elapsed <= 30.0

    # Успешный прогон: фаза 3 закоммичена ДО kg (рёбра на месте), kg вставил узлы.
    if status == 200:
        edges = _query("SELECT COUNT(*) AS c FROM knowledge_edges", (), fetch=True)
        assert edges and edges[0]['c'] >= 2, "рёбра фазы 3 не закоммичены"
        nodes = _query("SELECT COUNT(*) AS c FROM knowledge_graph "
                       "WHERE valid_to IS NULL", (), fetch=True)
        assert nodes and nodes[0]['c'] >= 2, "kg_scan_rebuild не вставил узлы"
        _query("DELETE FROM knowledge_graph WHERE node_type='probe'", ())


# ── ИНТЕГРАЦИЯ A.4: настоящий bin/mlog serve — OutboxPut при сбое фаз ─────

TOKEN_N569 = "tok-n569-mlog-12345678"


def _extract(pattern_name, src, extra_assert=None, path="app.mlog"):
    m = re.search(r"pattern %s\(.*?\n\}" % pattern_name, src, re.S)
    assert m, f"pattern {pattern_name} не найден в {path}"
    text = m.group(0)
    if extra_assert:
        assert extra_assert in text, f"{pattern_name}: нет {extra_assert!r}"
    return text


def _harness_mlog(port):
    """Харнесс: настоящий InitDB + OutboxPut + NightTickSlot; NightSlot и
    AuditLog — стабы, падающие SQL-ошибкой (имитация прод-лока 19.10).
    Декларация БД — как в app.mlog:29 (db_execute требует db { url: … })."""
    app_src = open(APP_MLOG, encoding='utf-8').read()
    sched_src = open(SCHED_MLOG, encoding='utf-8').read()
    utils_src = open(os.path.join(REPO, "dept", "utils.mlog"), encoding='utf-8').read()

    init_db_text = _extract("InitDB", app_src,
                            "CREATE TABLE IF NOT EXISTS audit_log")
    outbox_text = _extract("OutboxPut", sched_src, "owner_outbox")
    tick_text = _extract("NightTickSlot", sched_src, 'OutboxPut("night-tick"')
    tryval_text = _extract("TryVal", utils_src, "return")  # офисный, не builtin
    # хвост InitDB вызывает LZDataMaintain (dept/lz.mlog) — стаб для харнесса
    init_db_text = init_db_text.replace("let _ = LZDataMaintain()",
                                        "let _ = LZDataMaintainStub()")
    assert "LZDataMaintainStub()" in init_db_text, "подмена LZDataMaintain не удалась"
    # прод-сценарий: NightSlot бросает database-locked-класс ошибку
    tick_text = tick_text.replace("let tr_night = try NightSlot()",
                                  "let tr_night = try NightSlotStub()")
    assert "NightSlotStub()" in tick_text, "подмена NightSlot не удалась"

    return (
        "// #569 A.4: автогенерируемый харнесс — НАСТОЯЩИЕ InitDB/OutboxPut/\n"
        "// NightTickSlot из прода; NightSlot и AuditLog — стабы-падалки.\n"
        "// Мост как в entrypoint.sh прода (№391 redact-барьеры: db_execute/\n"
        "// http_post sink-clearance под permissive_with_audit).\n"
        + "profile legacy { egress: permissive_with_audit }\n\n"
        + "db { url: env(\"DATABASE_URL\") }\n\n"
        + tryval_text + "\n\n"
        + init_db_text + "\n\n"
        + outbox_text + "\n\n"
        + tick_text + "\n\n"
        + "pattern NightSlotStub() -> String {\n"
        + "  let _ = db_execute(\"UPDATE no_such_table_n569 SET x = 1\", [])\n"
        + "  return \"ok\"\n"
        + "}\n\n"
        + "pattern LZDataMaintainStub() -> String {\n"
        + "  return \"ok\"\n"
        + "}\n\n"
        + "pattern AuditLog(action: String, dept: String, details: String) -> String {\n"
        + "  let _ = db_execute(\"INSERT INTO audit_no_such_table_n569 (x) VALUES (1)\", [action])\n"
        + "  return \"ok\"\n"
        + "}\n\n"
        + f"mlogserver {{\n  port: {port}\n  host: \"127.0.0.1\"\n\n"
        + "  route \"/run-tick\" method=GET {\n    return NightTickSlot()\n  }\n"
        + "}\n"
    )


def _free_port(preferred):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class _Serve:
    """subprocess bin/mlog serve (по образцу tests/test_chain_step_contract.py)."""

    def __init__(self, port):
        self.dir = tempfile.mkdtemp(prefix="n569-serve-")
        self.port = _free_port(port)
        self.db = os.path.join(self.dir, "fosved.db")
        # прод-порядок: Flask поднимает схему раньше первого тика —
        # owner_outbox создаёт Python init_db (в харнессе делаем то же)
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE IF NOT EXISTS owner_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "created_at TEXT DEFAULT (datetime('now')), source TEXT NOT NULL, text TEXT NOT NULL, sent_at TEXT)")
        con.commit()
        con.close()
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_harness_mlog(self.port))
        env = dict(os.environ)
        env.update({
            "DATABASE_URL": f"sqlite:{self.db}",
            "CRON_SECRET": TOKEN_N569,
            "METALOGOS_ENV_ALLOWLIST": "CRON_SECRET,DATABASE_URL",
            "METALOGOS_SERVE_BACKEND": "interpreter",
            "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
            "METALOGOS_DATA_DIR": self.dir,
        })
        os.chmod(MLOG_BIN, 0o755)
        self.log = open(os.path.join(self.dir, "serve.log"), "w")
        self.proc = subprocess.Popen(
            [MLOG_BIN, "serve", src], cwd=self.dir, env=env,
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
                _rq.get(self.url + "/run-tick", timeout=2)
                return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("mlog serve не поднялся за 90 c")

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


@pytest.mark.skipif(not os.path.exists(MLOG_BIN),
                    reason="bin/mlog отсутствует (нестендовая песочница)")
def test_night_tick_outbox_survives_slot_failure():
    """A.4: NightSlot бросает ошибку → в outbox ЕСТЬ запись night-tick."""
    s = _Serve(11169)
    try:
        import requests as _rq
        resp = _rq.get(s.url + "/run-tick", timeout=120)
        report = resp.text
        assert "night=FAIL(" in report, (
            f"NightSlot-стаб должен был упасть, report: {report[:300]}")
        con = sqlite3.connect(s.db)
        rows = con.execute(
            "SELECT text FROM owner_outbox WHERE source='night-tick'").fetchall()
        con.close()
        assert rows, (
            "OutboxPut('night-tick') не выполнен при сбое фаз — слот умер "
            "до outbox (прод-симптом 19.10: dispatch error до OutboxPut)")
        assert any("night=FAIL(" in r[0] for r in rows), \
            f"текст ошибки не попал в report: {rows[:1]}"
    finally:
        s.stop()


# ── СТАТИЧЕСКИЕ ГВАРДЫ ───────────────────────────────────────────────────


def test_app_mlog_night_cycle_call_has_timeout():
    """A.3: у http_post /admin-ua/night-cycle есть явный 4-й аргумент-таймаут."""
    src = open(APP_MLOG, encoding='utf-8').read()
    m = re.search(r'http_post\("http://127\.0\.0\.1:4000/admin-ua/night-cycle\?itok="[^\n]*', src)
    assert m, "вызов admin-ua/night-cycle не найден в app.mlog"
    call = m.group(0)
    assert re.search(r",\s*\d+\.0\s*\)+\s*$", call), (
        f"у вызова night-cycle нет аргумента-таймаута: {call}")


def test_scheduler_golden_evals_call_has_secret():
    """A.1: ВСЕ вызовы golden-evals несут secret (raw qs / hash_only №443)."""
    src = open(SCHED_MLOG, encoding='utf-8').read()
    calls = re.findall(r'http_post\("http://127\.0\.0\.1:4000/scheduler/golden-evals[^\n]*', src)
    assert calls, "вызовы golden-evals не найдены в scheduler.mlog"
    for call in calls:
        assert ('+ qs' in call) or ('hash_only' in call), (
            f"golden-evals без секрета — гард cron_secret_ok даёт 403: {call}")


def test_scheduler_outboxput_last_and_audit_guarded():
    """A.4: перед OutboxPut("night-tick") аудит под TryVal(try …)."""
    src = open(SCHED_MLOG, encoding='utf-8').read()
    tick = _extract("NightTickSlot", src, 'OutboxPut("night-tick"')
    audit_pos = tick.find('TryVal(try AuditLog("cron_night_tick"')
    outbox_pos = tick.find('OutboxPut("night-tick"')
    assert audit_pos != -1, "AuditLog cron_night_tick не обёрнут в TryVal(try …)"
    assert outbox_pos != -1 and audit_pos < outbox_pos, (
        "OutboxPut должен идти после (защищённого) аудита — иначе сбой аудита "
        "снова убивает слот до outbox")
