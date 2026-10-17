#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #542 A.1+A.2: единый контракт /chain/step (JSON {"result": ...}).

Гварды:
- статический: в app.mlog маршрут /chain/step отвечает
  respond("200 " + json_encode({result: result})) — не сырым текстом;
- статический: все три вызывателя (routes_core, chain_parallel,
  narad_queue) читают ответ через _chain_step_json (громкая ошибка на
  не-JSON), а не сырым resp.json();
- интеграционный на НАСТОЯЩЕМ bin/mlog serve: поднимается минимальный
  харнесс с НАСТОЯЩИМ текстом маршрута /chain/step и RequireInternalAuth,
  извлечёнными из app.mlog (ChainDispatchDept/AuditLog — стабы); запрос
  отправляется РЕАЛЬНЫМИ функциями вызывателей (_invoke_step
  chain_parallel и narad_queue) с заголовком X-Internal-Token;
  result — непустая строка;
- helper: не-JSON тело → RuntimeError с первыми 200 символами тела в
  сообщении (без секретов); JSON без result → RuntimeError;
- мутация по тексту наряда: «вернуть respond(result) → тест обязан
  упасть» — мета-тест поднимает харнесс со СТАРЫМ контрактом (сырой
  текст) и проверяет, что вызыватель ГРОМКО падает (RuntimeError), т.е.
  регрессия контракта ловится.

bin/mlog serve не поддерживает METALOGOS_LLM_MOCK (проверено strings по
бинарю 0.32.0) — потому минимальная копия маршрута, разрешённая текстом
наряда. Диспетчер стабится — LLM-логика отделов не предмет контракта.
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n542-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401 — конвенция тестов Flask: импорт до прокси-роутов
from proxy.core import _chain_step_json  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MLOG_BIN = os.path.join(REPO, "bin", "mlog")
APP_MLOG = os.path.join(REPO, "app.mlog")

TOKEN = "tok-n542-test-12345678"
STUB_REPLY = "СТАБ-ОТВЕТ ОТДЕЛА: osp"
PORT_BASE = 11043  # харнесс / мутация — порты +0/+1

pytestmark = pytest.mark.skipif(
    not (os.path.exists(MLOG_BIN) and os.path.exists(APP_MLOG)),
    reason="bin/mlog или app.mlog отсутствуют (нестендовая песочница)")


def _extract_route():
    """Настоящий маршрут /chain/step из app.mlog (текст = код прода)."""
    src = open(APP_MLOG, encoding="utf-8").read()
    m = re.search(r'route "/chain/step" method=POST \{.*?\n  \}', src, re.S)
    assert m, "маршрут /chain/step не найден в app.mlog"
    return m.group(0)


def _extract_auth_pattern():
    """Настоящий pattern RequireInternalAuth из app.mlog."""
    src = open(APP_MLOG, encoding="utf-8").read()
    m = re.search(r"pattern RequireInternalAuth\(\) -> String \{.*?\n\}", src, re.S)
    assert m, "pattern RequireInternalAuth не найден в app.mlog"
    return m.group(0)


def _harness(port, route_text):
    """Минимальный mlogserver-файл: настоящий RequireInternalAuth + настоящий
    маршрут /chain/step; диспетчер и аудитор — стабы (LLM не предмет теста)."""
    route = route_text.replace(
        "let result = ChainDispatchDept(dept, q, chat_id)",
        'let result = ChainDispatchStub(dept, q, chat_id)')
    assert "ChainDispatchStub" in route, "подмена диспетчера не удалась"
    return (
        "// #542 A.2: автогенерируемый харнесс (тест) — НАСТОЯЩИЙ маршрут\n"
        "// /chain/step и RequireInternalAuth из app.mlog, диспетчер — стаб\n"
        + _extract_auth_pattern() + "\n\n"
        + "pattern ChainDispatchStub(dept: String, query: String, chat_id: String) -> String {\n"
        + f'  return "{STUB_REPLY}"\n'
        + "}\n\n"
        + "pattern AuditLog(action: String, dept: String, details: String) -> String {\n"
        + '  return "ok"\n'
        + "}\n\n"
        + f"mlogserver {{\n  port: {port}\n  host: \"127.0.0.1\"\n\n"
        + route + "\n}\n"
    )


def _mutated_route():
    """Мутация по наряду: вернуть СТАРЫЙ контракт respond(result)."""
    route = _extract_route()
    mutated = route.replace(
        'return respond("200 " + json_encode({result: result}))',
        "return respond(result)")
    assert mutated != route, "мутация не применилась — старой строки нет?"
    return mutated


def _free_port(preferred):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


class _Serve:
    """subprocess bin/mlog serve + ожидание готовности; гарантированная уборка."""

    def __init__(self, route_text, port):
        self.dir = tempfile.mkdtemp(prefix="n542-serve-")
        self.port = _free_port(port)
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_harness(self.port, route_text))
        env = dict(os.environ)
        env.update({
            "INTERNAL_API_TOKEN": TOKEN,
            "METALOGOS_ENV_ALLOWLIST": "INTERNAL_API_TOKEN,CRON_SECRET",
            "METALOGOS_SERVE_BACKEND": "interpreter",
            "METALOGOS_SERVE_ALLOW_EXEC": "1",
            "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
            "METALOGOS_DATA_DIR": self.dir,
        })
        os.chmod(MLOG_BIN, 0o755)
        log = open(os.path.join(self.dir, "serve.log"), "w")
        self.proc = subprocess.Popen(
            [MLOG_BIN, "serve", src], cwd=self.dir, env=env,
            stdout=log, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid)
        self.url = f"http://127.0.0.1:{self.port}"
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = open(log.name, errors="replace").read()[-600:]
                raise RuntimeError(f"mlog serve умер при старте:\n{tail}")
            try:
                import requests as _rq
                _rq.get(self.url + "/chain/step", timeout=2)
                return  # любой HTTP-ответ — сервер поднялся
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("mlog serve не поднялся за 60 c")

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
            shutil.rmtree(self.dir, ignore_errors=True)


# ── Статические гварды контракта ─────────────────────────────────────────

def test_app_mlog_chain_step_returns_json():
    """A.1: маршрут отвечает respond("200 " + json_encode({result: result}))."""
    route = _extract_route()
    assert 'respond("200 " + json_encode({result: result}))' in route, (
        "маршрут /chain/step в app.mlog не отдаёт JSON {result} — "
        "регрессия к сырому тексту (причина #542 факт 1)")


def test_all_three_callers_use_loud_parser():
    """A.1: три вызывателя читают ответ через _chain_step_json."""
    for rel in ("proxy/routes_core.py", "proxy/chain_parallel.py", "proxy/narad_queue.py"):
        src = open(os.path.join(REPO, rel), encoding="utf-8").read()
        assert "_chain_step_json(" in src, f"{rel} не использует _chain_step_json"


# ── Интеграция с настоящим bin/mlog serve ────────────────────────────────

@pytest.fixture()
def serve_contract():
    s = _Serve(_extract_route(), PORT_BASE)
    yield s
    s.stop()


@pytest.fixture()
def serve_mutated():
    s = _Serve(_mutated_route(), PORT_BASE + 1)
    yield s
    s.stop()


def _with_caller_env(monkeypatch, url):
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    import proxy.chain_parallel as cp
    import proxy.narad_queue as nq
    monkeypatch.setattr(cp, "MLOGSERVE_URL", url)
    monkeypatch.setattr(nq, "MLOGSERVE_URL", url)
    return cp, nq


def test_real_callers_parse_real_mlog_contract(serve_contract, monkeypatch):
    """A.2: запрос через РЕАЛЬНЫЕ функции вызывателей с заголовком токена;
    result — непустая строка."""
    cp, nq = _with_caller_env(monkeypatch, serve_contract.url)
    out_cp = cp._invoke_step("osp", "тестовый вопрос", "123", "grp-n542")
    assert isinstance(out_cp, str) and out_cp.strip() == STUB_REPLY
    out_nq = nq._invoke_step("osp", "тестовый вопрос", "123")
    assert isinstance(out_nq, str) and out_nq.strip() == STUB_REPLY


def test_mutation_old_contract_is_caught(serve_mutated, monkeypatch):
    """Мутация наряда: respond(result) (сырой текст) → вызыватель громко падает."""
    cp, _ = _with_caller_env(monkeypatch, serve_mutated.url)
    with pytest.raises(RuntimeError, match="не JSON"):
        cp._invoke_step("osp", "тестовый вопрос", "123", "grp-n542")


def test_non_json_body_loud_error_without_secrets():
    """A.1: не-JSON → RuntimeError с первыми 200 символами тела; секретов нет."""
    class FakeResp:
        text = "сырой текст отдела " + "x" * 300

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with pytest.raises(RuntimeError) as ei:
        _chain_step_json(FakeResp())
    msg = str(ei.value)
    assert "не JSON" in msg and "Expecting value" in msg
    assert "сырой текст отдела" in msg          # тело видно (причина из лога)
    assert len(msg.split("тело[:200]: ")[1]) <= 200  # не более 200 символов тела
    assert TOKEN not in msg                      # секретов в сообщении нет


def test_json_without_result_is_loud():
    """A.1: валидный JSON без поля result — тоже громкая ошибка."""
    class FakeResp:
        text = '{"reply": "нет result"}'

        def json(self):
            return {"reply": "нет result"}

    with pytest.raises(RuntimeError, match="нет поля result"):
        _chain_step_json(FakeResp())
