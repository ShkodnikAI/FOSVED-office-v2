#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #687 NIGHT-1 (P0): живой прогон NightSlot против моков фаз.

Прод-факт 08.11: night-tick падал с 05.11 — night=FAIL(parse_json() error:
expected value at line 1 column 1); фаза ключей не выполнялась; в ночной
ленте — сырой конверт call-python вместо текста.

Здесь РЕАЛЬНЫЙ app.mlog (mlog serve, как в проде) вызывает РЕАЛЬНЫЙ NightSlot,
а фазы отвечают из мок-сервера на 127.0.0.1:4000 (конвенция «моки фаз» наряда):

- зелёный сценарий: UA-задание отвечает done с dict-результатом (класс прода
  05.11) → слот НЕ падает, разбор проходит (фикс источника json_encode в
  PollJobStatus), фаза ключей выполняется, запись в admin_night_reports есть,
  лента usage-by-key — текст без обёртки;
- красный сценарий: старт UA отвечает 200 «Internal Server Error» (не JSON) →
  UA=FAIL с причиной «ответ не JSON: …», ОСТАЛЬНЫЕ фазы выполняются (фаза
  ключей — в том числе), запись в admin_night_reports есть — слот переживает
  сбой одной фазы. Мутация «вернуть голый parse_json» делает оба сценария
  красными (см. также структурную гвардию в test_n687_guards.py).
"""
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MLOG = REPO_ROOT / "bin" / "mlog"
PROFILE_LINE = "profile legacy { egress: permissive_with_audit }"
VM_PORT = 10001
UPSTREAM_PORT = 4000
CRON_SECRET = "n687-night-test"

pytestmark = pytest.mark.skipif(not MLOG.exists() or os.name != "posix", reason="нужен bin/mlog (Linux)")


# ──────────────────────────── мок фаз на 127.0.0.1:4000 ────────────────────────────

DEFAULT_UPSTREAM = {
    # UA async: старт → job_id, статус → done с dict-результатом (как прод 05.11)
    "POST /admin-ua/night-cycle": (200, {"status": "accepted", "job_id": "job-t1"}),
    "GET /admin-ua/night-cycle/status": (200, {"status": "done", "error": None,
                                               "result": {"status": "ok", "summary": "UA NIGHT CYCLE TEST OK",
                                                          "health_score": 8.5}}),
    # ЛЗ nocturnal: JSON со вложенным scan (второй класс to_string(dict))
    "POST /scheduler/lz-daily": (200, {"status": "ok", "deliver": "none",
                                       "scan": {"repos_found": 3, "releases_found": 1}}),
    "POST /memory/maintenance": (200, {"result": "memory maintenance ok"}),
    "POST /admin/keys/night-check": (200, {"status": "ok", "problems_line": "",
                                           "ok_count": 17, "total": 17,
                                           "checked_at": "2026-11-08 02:05:00"}),
    "POST /call-python": (200, {"result": "🔑 Учёт по ключам: всего 0 вызовов за сутки", "type": "str"}),
    "POST /scheduler/golden-evals": (200, {"status": "accepted", "job_id": "job-g1"}),
    "GET /scheduler/golden-evals/status": (200, {"status": "done", "error": None, "result": {"ok": True}}),
    "GET /cron/backup": (200, {"ok": True}),
    "GET /cron/shop-tick": (200, {"ok": True}),
    "POST /scheduler/indicator-pre-reminders": (200, {"sent": 0}),
}


class UpstreamHandler(BaseHTTPRequestHandler):
    upstream = {"hits": {}, "config": {}}

    def _key(self, method: str) -> str:
        return f"{method} {self.path.split('?')[0]}"

    def _reply(self, status: int, body) -> None:
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode()
            ctype = "application/json"
        else:
            payload = str(body).encode()
            ctype = "text/plain"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _dispatch(self, method: str) -> None:
        key = self._key(method)
        self.upstream["hits"][key] = self.upstream["hits"].get(key, 0) + 1
        cfg = self.upstream["config"].get(key)
        if cfg is None and key not in DEFAULT_UPSTREAM:
            # незнакомые пути (внутренние вызовы AdminNightCycle и пр.) — JSON-заглушка
            self._reply(200, {"ok": True})
            return
        status, body = cfg if cfg else DEFAULT_UPSTREAM[key]
        self._reply(status, body)

    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
        except Exception:  # noqa: BLE001 — тело мок не разбирает
            pass
        self._dispatch("POST")

    def log_message(self, *args):  # noqa: N802 — тишина в логах теста
        pass


@pytest.fixture(scope="module")
def upstream():
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", UPSTREAM_PORT)) == 0:
            pytest.skip(f"порт {UPSTREAM_PORT} занят — в этом окружении мок не поднять")
    server = ThreadingHTTPServer(("127.0.0.1", UPSTREAM_PORT), UpstreamHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    yield UpstreamHandler.upstream
    server.shutdown()


# ──────────────────────────── бут VM (как в проде) ────────────────────────────

def _serve_env(tmp_path: Path) -> dict:
    src = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    census = re.search(r'METALOGOS_ENV_ALLOWLIST_CENSUS="([^"]+)"', src).group(1)
    names = ["app.mlog", "consensus.mlog"] + [p.name for p in sorted((REPO_ROOT / "dept").glob("*.mlog"))]
    env = dict(os.environ)
    env.update({
        "METALOGOS_SERVE_ALLOW_EXEC": "1",
        "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
        "METALOGOS_SERVE_BACKEND": "vm",
        "METALOGOS_DATA_DIR": ".",
        "METALOGOS_ENV_ALLOWLIST": census,
        "METALOGOS_SENSITIVE_PATH_ALLOWLIST": ",".join(names),
        "METALOGOS_MOCK_LLM": "1",
        "CRON_SECRET": CRON_SECRET,
        "DATABASE_URL": f"sqlite:{tmp_path / 'office.db'}",
        "OWNER_TELEGRAM_ID": "1",
        "TELEGRAM_BOT_TOKEN": "",
        "ZAI_API_KEY": "fake-zai-key",
        "TAVILY_API_KEY": "",
        "GITHUB_TOKEN_METALOGOS": "",
    })
    return env


def _candidate(tmp_path: Path) -> Path:
    src = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    if not re.search(r"^profile legacy", src, re.M):
        src = PROFILE_LINE + "\n" + src
    out = tmp_path / "app_serve_n687.mlog"
    out.write_text(src, encoding="utf-8")
    return out


def _db_rows(db_path: Path, sql: str, args=()):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _wait_health(proc, deadline_s: int = 180) -> None:
    for _ in range(deadline_s):
        if proc.poll() is not None:
            raise RuntimeError("mlog serve завершился до готовности")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{VM_PORT}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("mlog serve не поднялся за отведённое окно")


def _wait_night_artifacts(db_path: Path, timeout_s: int):
    """Ждём запись NightSlot (admin_night_reports, scan_data='night-slot')."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            rows = _db_rows(db_path, "SELECT id FROM admin_night_reports WHERE scan_data='night-slot' LIMIT 1")
            if rows:
                return True
        except sqlite3.Error:
            pass
        time.sleep(3)
    return False


def _trigger_tick_if_idle(db_path: Path, wait_catchup_s: int = 45):
    """Catch-up слота (run_once) стреляет на буте; если окна не наступили —
    дёргаем /cron/night-tick вручную (тот же код NightTickCore)."""
    time.sleep(wait_catchup_s)
    if _wait_night_artifacts(db_path, timeout_s=1):
        return "catchup"
    def _poke():
        try:
            url = f"http://127.0.0.1:{VM_PORT}/cron/night-tick?secret={CRON_SECRET}"
            with urllib.request.urlopen(url, timeout=600) as resp:
                resp.read()
        except Exception:
            pass
    th = threading.Thread(target=_poke, daemon=True)
    th.start()
    return "manual"


def _outbox_texts(db_path: Path, source: str):
    try:
        return [r[0] for r in _db_rows(
            db_path, "SELECT text FROM owner_outbox WHERE source=? ORDER BY id", (source,))]
    except sqlite3.Error:
        return []


def _precreate_flask_tables(db_path: Path) -> None:
    """Таблицы, которые в проде создаёт Flask-сторона (proxy/core.py DDL на буте).

    В мок-сценарии Flask на :4000 нет — а OutboxPut (mlog) пишет в owner_outbox
    своей базы. Без прекомпиляции лента пустая (TryVal глотает no such table) —
    и ночной отчёт не собирается, как и в проде при отсутствии Flask DDL.
    """
    import sqlite3 as _sq
    con = _sq.connect(db_path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS owner_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "created_at TEXT DEFAULT (datetime('now')), source TEXT NOT NULL, text TEXT NOT NULL, sent_at TEXT)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_owner_outbox_sent ON owner_outbox(sent_at)")
        con.commit()
    finally:
        con.close()


def _run_night_scenario(tmp_path, upstream, ua_start_override=None):
    """Бут VM + ожидание ночного прогона. Возвращает (db_path, proc)."""
    upstream["hits"] = {}
    upstream["config"] = {}
    if ua_start_override is not None:
        upstream["config"]["POST /admin-ua/night-cycle"] = ua_start_override
    db_path = tmp_path / "office.db"
    _precreate_flask_tables(db_path)
    env = _serve_env(tmp_path)
    version = REPO_ROOT / "VERSION"
    created_version = not version.exists()
    if created_version:
        version.write_text("n687-night-test\n", encoding="utf-8")
    log = tmp_path / "serve.log"
    with open(log, "w") as fh:
        proc = subprocess.Popen([str(MLOG), "serve", str(_candidate(tmp_path))],
                                cwd=str(REPO_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)
    try:
        _wait_health(proc)
        _trigger_tick_if_idle(db_path)
        assert _wait_night_artifacts(db_path, timeout_s=420), \
            "NightSlot не записал итог в admin_night_reports:\n" + \
            "\n".join(log.read_text(errors="ignore").splitlines()[-25:])
        yield db_path, proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        if created_version:
            version.unlink(missing_ok=True)


# ──────────────────────────── сценарии ────────────────────────────

def test_night_slot_survives_and_parses_phases(tmp_path, upstream):
    """Зелёный сценарий (класс прода 05.11: UA-задание done с dict-результатом).

    - слот не падает: night=FAIL(parse_json) нет; запись в admin_night_reports есть (A.2);
    - разбор результата UA прошёл: в отчёте — summary из dict (A.1, фикс источника);
    - фаза ключей выполнена и разобрана (A.3);
    - лента usage-by-key — текст без обёртки call-python (A.5).
    """
    for db_path, _proc in _run_night_scenario(tmp_path, upstream):
        tick = "\n".join(_outbox_texts(db_path, "night-tick"))
        night = "\n".join(_outbox_texts(db_path, "night"))
        assert "night=FAIL" not in tick, tick[-1500:]
        assert "parse_json" not in tick, tick[-1500:]
        assert "UA NIGHT CYCLE TEST OK" in night, night[-2500:]
        assert "Phase 5: Ключи и провайдеры" in night and "ok (17/17)" in night, night[-2500:]
        assert upstream["hits"].get("POST /admin/keys/night-check", 0) >= 1, "фаза ключей не вызывалась"
        usage = _outbox_texts(db_path, "usage-by-key")
        assert usage, "лента usage-by-key пуста"
        assert usage[-1].startswith("🔑 Учёт по ключам"), usage
        assert '{"result"' not in usage[-1] and '"type"' not in usage[-1], usage[-1]


def test_night_slot_survives_non_json_phase(tmp_path, upstream):
    """Красный сценарий наряда (A.2): старт UA — 200 «Internal Server Error».

    UA=FAIL с причиной «ответ не JSON: …», остальные фазы выполняются
    (фаза ключей — в том числе), запись в admin_night_reports есть.
    """
    for db_path, _proc in _run_night_scenario(
            tmp_path, upstream, ua_start_override=(200, "Internal Server Error")):
        tick = "\n".join(_outbox_texts(db_path, "night-tick"))
        night = "\n".join(_outbox_texts(db_path, "night"))
        assert "night=FAIL" not in tick, "слот упал целиком:\n" + tick[-1500:]
        assert "ответ не JSON: Internal Server Error" in night, night[-2500:]
        assert "Phase 5: Ключи и провайдеры" in night and "ok (17/17)" in night, night[-2500:]
        assert upstream["hits"].get("POST /admin/keys/night-check", 0) >= 1, "фаза ключей не выполнилась после сбоя UA"
        assert "partial" in night, "честный статус partial потерян:\n" + night[-800:]
