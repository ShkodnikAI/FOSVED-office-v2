#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #603 D.1: регрессия делегирования/file_id на НАСТОЯЩЕМ `bin/mlog serve`.

Стенд: дополненная копия app.mlog (`profile legacy {…}`) + заглушка прокси
на 127.0.0.1:4000, которая пишет (path, dept/text) из тела каждого запроса:
- `/ask`: dept=yana → `{"reply":"[DELEGATE: design]",…}`, остальным — текст;
- `/detect-dept` → параметр кейса;
- остальное → `{"status":"ok"}`.

Кейсы (по цели прохода #603):
1. detect-dept=yana → в логе заглушки есть `/ask dept=design` (делегирование
   дошло до отдела — F2 больше не рвёт BuildContext);
2. detect-dept="" → есть `/ask dept=design` и НЕТ `/tg-send` с текстом
   `design` (голый slug больше не уходит владельцу — F3);
3. ответ webhook не содержит `Handler error` (молчаливых обрывов нет).

Мутации (обе обязаны ловиться; результаты — в PR):
- вернуть строку `app.mlog:1149` (parse_json(to_string(rows))) → кейс 1 красный;
- убрать вызов DispatchYanaDelegation в ветке по умолчанию → кейс 2 красный.

Замечания стенда (наблюдения 0.34.1):
- /health читает VERSION через read_file — файл создаётся на время теста
  (№254 soft contract), а METALOGOS_DATA_DIR="." как в test_prod_boot,
  иначе гвард #455 режет read_file вне каталога данных;
- бут 0.34.x на медленном стенде > 120 c — дедлайн готовности 240 c;
- library/personas.mlog и т.п. под deny-list `*.mlog` — перечислены в
  METALOGOS_SENSITIVE_PATH_ALLOWLIST явно.
"""
import json
import os
import pathlib
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
MLOG = ROOT / "bin" / "mlog"
PROFILE_LINE = "profile legacy { egress: permissive_with_audit }"

OWNER_ID = "777000777"
CHAT_ID = "777"
TEXT = "Поручи отделу дизайна сделать пост про запуск"
_m = re.search(r"mlogserver\s*\{[^}]*?port:\s*(\d+)",
               (ROOT / "app.mlog").read_text(encoding="utf-8"), re.S)
PORT_MLOG = int(_m.group(1)) if _m else 10001
PROXY_PORT = 4000  # app.mlog жёстко постит на 127.0.0.1:4000

pytestmark = pytest.mark.skipif(not MLOG.exists() or os.name != "posix",
                                reason="нужен bin/mlog (Linux)")


# ── Заглушка прокси ────────────────────────────────────────────────────────


class _Stub:
    def __init__(self):
        self.calls = []          # [(path, body-dict)]
        self.detect = ""         # что отвечает /detect-dept
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # тишина в stdout pytest
                pass

            def _reply(self, obj, code=200):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    body = {}
                with outer.lock:
                    outer.calls.append((self.path, body))
                if self.path == "/ask":
                    dept = str(body.get("dept", ""))
                    reply = "[DELEGATE: design]" if dept == "yana" else f"Ответ отдела {dept}: заглушка D.1."
                    self._reply({"reply": reply, "model": "stub", "tokens_in": 1, "tokens_out": 1})
                elif self.path == "/detect-dept":
                    self._reply({"dept": outer.detect})
                else:
                    self._reply({"status": "ok"})

            def do_GET(self):
                self._reply({"status": "ok"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def asks(self):
        with self.lock:
            return [(b.get("dept"), b) for p, b in self.calls if p == "/ask"]

    def tg_sends(self):
        with self.lock:
            return [b for p, b in self.calls if p == "/tg-send"]

    def reset_calls(self):
        with self.lock:
            self.calls = []

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ── Сервер офиса ───────────────────────────────────────────────────────────


def _augmented(tmp: pathlib.Path) -> pathlib.Path:
    src = (ROOT / "app.mlog").read_text(encoding="utf-8")
    if not re.search(r"^profile legacy", src, re.M):
        src = PROFILE_LINE + "\n" + src
    out = tmp / "app_serve_candidate.mlog"
    out.write_text(src, encoding="utf-8")
    return out


def _env(tmp: pathlib.Path) -> dict:
    s = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    m = re.search(r'METALOGOS_ENV_ALLOWLIST_CENSUS="([^"]+)"', s)
    census = m.group(1) if m else ""
    extra = "OWNER_TELEGRAM_ID,TELEGRAM_BOT_TOKEN"
    allow = census + ("," if census and not census.endswith(",") else "") + extra
    # deny-list `*.mlog` (№455): все читаемые рантаймом .mlog/.md — явно
    names = ["app.mlog", "consensus.mlog", "personas.mlog", "brand.mlog"] \
        + [p.name for p in sorted((ROOT / "dept").glob("*.mlog"))] \
        + [p.name for p in sorted((ROOT / "library").glob("*"))] \
        + [p.name for p in sorted((ROOT / "memories").glob("*.mlog"))]
    env = dict(os.environ)
    env.update({
        "METALOGOS_SERVE_ALLOW_EXEC": "1",
        "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
        "METALOGOS_SERVE_BACKEND": "interpreter",
        # как в test_prod_boot: data dir = cwd (ROOT) — иначе гвард #455 режет
        # read_file('VERSION') в /health и read_file персон из library/
        "METALOGOS_DATA_DIR": ".",
        "METALOGOS_ENV_ALLOWLIST": allow,
        "METALOGOS_SENSITIVE_PATH_ALLOWLIST": ",".join(names),
        "CRON_SECRET": "n603-serve-test",
        "DATABASE_URL": f"sqlite:{tmp / 'office.db'}",
        "OWNER_TELEGRAM_ID": OWNER_ID,
        "TELEGRAM_BOT_TOKEN": "stub-token-n603",
    })
    return env


def _port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


class _OfficeServe:
    def __init__(self, aug: pathlib.Path, tmp: pathlib.Path):
        self.log = tmp / f"serve-{time.time_ns()}.log"
        env = _env(tmp)
        os.chmod(MLOG, 0o755)
        with open(self.log, "w") as fh:
            self.proc = subprocess.Popen([str(MLOG), "serve", str(aug)], cwd=ROOT,
                                         env=env, stdout=fh, stderr=subprocess.STDOUT,
                                         preexec_fn=os.setsid)
        deadline = time.time() + 240  # бут 0.34.x на медленном стенде > 120 c
        try:
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError("mlog serve умер при старте: " + self._tail())
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{PORT_MLOG}/health", timeout=2) as r:
                        if r.status == 200 and "Handler error" not in r.read().decode(errors="ignore"):
                            return  # /health же вызывает InitDB — таблицы готовы
                except Exception:
                    time.sleep(1)
            raise RuntimeError("mlog serve не поднялся за 240 c: " + self._tail())
        except Exception:
            self.stop()
            raise

    def _tail(self):
        try:
            return self.log.read_text(errors="ignore")[-500:]
        except Exception:
            return "(нет лога)"

    def webhook(self, update_id: int):
        body = {"update_id": update_id,
                "message": {"message_id": update_id,
                            "chat": {"id": int(CHAT_ID)},
                            "from": {"id": int(OWNER_ID)},
                            "text": TEXT}}
        return requests.post(f"http://127.0.0.1:{PORT_MLOG}/webhook/telegram",
                             json=body, timeout=60)

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except Exception:
                pass


@pytest.fixture(scope="module")
def stub():
    if _port_busy(PROXY_PORT):
        pytest.skip(f"порт {PROXY_PORT} занят — прокси уже запущен в этом окружении")
    s = _Stub()
    yield s
    s.stop()


@pytest.fixture(scope="module")
def office(stub):
    if _port_busy(PORT_MLOG):
        pytest.skip(f"порт {PORT_MLOG} занят — сервер уже запущен в этом окружении")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="n603-serve-"))
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("n603-serve-test\n", encoding="utf-8")  # /health читает VERSION (№254)
    serve = None
    try:
        serve = _OfficeServe(_augmented(tmp), tmp)
        yield SimpleNamespace(stub=stub, serve=serve, db=tmp / "office.db", tmp=tmp)
    finally:
        if serve is not None:
            serve.stop()
        if created:
            version.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


def _seed_owner_injection(db_path, dept="design"):
    """Инъекция владельца в team_board (from_dept='owner', delivered=0) —
    путь GetInjectedContext с НЕпустым результатом query()."""
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "INSERT INTO team_board (from_dept, kind, topic, tags, payload, sources, delivered) "
            "VALUES ('owner', 'fact', 'n603 inject test', ?, 'Пост про запуск: синий бренд-бук.', '', 0)",
            (f'["{dept}"]',))
        con.commit()
    finally:
        con.close()


def _assert_no_handler_error(resp):
    assert resp.status_code == 200, resp.text
    assert "Handler error" not in resp.text, \
        f"молчаливый обрыв обработчика: {resp.text[:300]}"


def test_case3_webhook_answers_clean(office):
    stub, serve = office.stub, office.serve
    stub.reset_calls()
    stub.detect = ""
    r = serve.webhook(9100001)
    _assert_no_handler_error(r)


def test_case1_yana_delegation_reaches_design(office):
    stub, serve = office.stub, office.serve
    stub.reset_calls()
    stub.detect = "yana"
    r = serve.webhook(9100002)
    _assert_no_handler_error(r)
    depts = [d for d, _ in stub.asks()]
    assert "yana" in depts, f"заглушка не видела /ask dept=yana; asks={depts}"
    assert "design" in depts, (
        f"делегирование не дошло до отдела design (F2-класс: BuildContext рвётся); asks={depts}")


def test_case2_default_branch_delegates_without_slug_leak(office):
    stub, serve = office.stub, office.serve
    stub.reset_calls()
    stub.detect = ""  # detect-dept вернул пусто → ветка по умолчанию
    r = serve.webhook(9100003)
    _assert_no_handler_error(r)
    depts = [d for d, _ in stub.asks()]
    assert "design" in depts, (
        f"делегирование в ветке по умолчанию не сработало; asks={depts}")
    leaked = [b for b in stub.tg_sends() if str(b.get("text", "")) == "design"]
    assert not leaked, (
        f"голый slug ушёл владельцу в /tg-send (F3): {leaked[:2]}")


def test_case4_owner_injection_reaches_context(office):
    """Сеянная инъекция владельца: GetInjectedContext читает НЕпустые строки
    query() напрямую (фикс B.1) — контекст отдела получает payload, обрывов нет."""
    stub, serve = office.stub, office.serve
    _seed_owner_injection(office.db)
    stub.reset_calls()
    stub.detect = "yana"
    r = serve.webhook(9100006)
    _assert_no_handler_error(r)
    depts = [d for d, _ in stub.asks()]
    assert "design" in depts, (
        f"с сеянной инъекцией делегирование оборвалось (класс F2 на непустых rows); asks={depts}")


# ── Мутации: обе обязаны ловиться кейсами ─────────────────────────────────


def _mutant_office(tmp: pathlib.Path, kind: str):
    """Сервер на мутантной копии app.mlog."""
    src = (ROOT / "app.mlog").read_text(encoding="utf-8")
    if kind == "revert_1149":
        fixed = 'let merged = to_string(json_get(get(rows, 0), "merged", ""))'
        mutant = src.replace(
            fixed,
            'let merged = to_string(json_get(parse_json(to_string(rows)), "[0].merged", ""))')
    elif kind == "drop_default_dispatch":
        block = ('      let del = DispatchYanaDelegation(reply, text, chat_id)\n'
                 '      if del != "1" then {')
        mutant = src.replace(block, '      if 1.0 > 0.0 then {')
    else:
        raise AssertionError(kind)
    assert mutant != src, f"мутация {kind} не применилась"
    out = tmp / f"app_mutant_{kind}.mlog"
    out.write_text(("profile legacy { egress: permissive_with_audit }\n"
                    if not re.search(r"^profile legacy", src, re.M) else "") + mutant,
                   encoding="utf-8")
    return _OfficeServe(out, tmp)


def test_mutation_revert_1149_is_killed_by_case1(stub):
    """Мутант :1149 + НЕпустые строки query() (сеянная инъекция) — кейс ловит.

    Результат мутации: ПОЙМАНА — parse_json(to_string(Row)) рвёт BuildContext,
    /ask dept=design не происходит (Handler error или обрыв делегирования)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="n603-mutA-"))
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("n603-mutant-test\n", encoding="utf-8")
    serve = None
    try:
        serve = _mutant_office(tmp, "revert_1149")
        _seed_owner_injection(tmp / "office.db")  # НЕпустые rows — иначе парс не достигается
        stub.reset_calls()
        stub.detect = "yana"
        r = serve.webhook(9100004)
        depts = [d for d, _ in stub.asks()]
        assert "design" not in depts, (
            "мутант :1149 неотличим от оригинала — кейс 1 НЕ поймал мутацию; "
            f"asks={depts}")
        # результат мутации: поймана — Handler error или делегирование оборвалось
        assert ("Handler error" in r.text) or ("yana" not in depts), (
            f"мутант проявился иначе ожидаемого: rc={r.status_code}, asks={depts}, "
            f"body={r.text[:200]}")
    finally:
        if serve is not None:
            serve.stop()
        if created:
            version.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


def test_mutation_drop_default_dispatch_is_killed_by_case2(stub):
    """Мутант «убрать DispatchYanaDelegation из ветки по умолчанию» — кейс ловит.

    Результат мутации: ПОЙМАНА — голый slug "design" уходит владельцу в /tg-send (F3)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="n603-mutB-"))
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("n603-mutant-test\n", encoding="utf-8")
    serve = None
    try:
        serve = _mutant_office(tmp, "drop_default_dispatch")
        stub.reset_calls()
        stub.detect = ""
        r = serve.webhook(9100005)
        leaked = [b for b in stub.tg_sends() if str(b.get("text", "")) == "design"]
        assert leaked, (
            "мутант «убрать DispatchYanaDelegation из ветки по умолчанию» "
            "неотличим от оригинала — кейс 2 НЕ поймал мутацию; "
            f"tg_sends={[str(b.get('text',''))[:60] for b in stub.tg_sends()][:5]}")
    finally:
        if serve is not None:
            serve.stop()
        if created:
            version.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
