#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #546 A.2: сравнение секретов на настоящем `bin/mlog serve` (0.32.0).

Харнесс собирается при каждом прогоне из app.mlog: НАСТОЯЩИЕ pattern
SecretMatches и RequireInternalAuth + НАСТОЯЩИЕ route-блоки
/schedules/bootstrap, /cron/morning, /version (анти-drift: текст = код
прода). Тела маршрутов, зовущие dept-паттерны, работают с HARNESS STUB
заглушками (InitDB/BootstrapSchedules/MorningBrief/YanaSelfLearn) —
сравнение секретов идёт на настоящем коде call-site.

Схема сравнения (#546 A.1): на call-site received обёрнут
redact(..., "hash_only") — one-way-redact требуется taint-валидатором
(Wave 15, интерпроцедурный), а "hash_only" (в отличие от "all") не
маскирует токен-подобные значения — рецепт Metalogos-#1317. Сравнение —
двойной фингерпринт: сырой секрет любого вида и его hash-форма (канал
моста №318) проходят, неверный/пустой — нет. Пустой env — отказ.

Значения секретов — только тестовые; значения и хеши секретов нигде не
печатаются (в том числе в serve.log — mlog не логирует query).

Кейсы по тексту наряда:
| Что прислано                              | Ответ |
|-------------------------------------------|-------|
| верный секрет, похожий на токен           | 200   |
| верный секрет из одних букв               | 200   |
| вид хеша верного секрета                  | 200   |
| неверный                                  | 403   |
| пусто                                     | 403   |
| env не задан                              | 403   |
/version с X-Internal-Token: верный (похожий на токен) → 200; неверный → 401.

Мутация по тексту наряда («вернуть redact(..., "all")»): call-site
hash_only → all — кейс «похожий на токен» обязан упасть (403 вместо 200).
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time

import pytest
import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MLOG_BIN = os.path.join(REPO, "bin", "mlog")
APP_MLOG = os.path.join(REPO, "app.mlog")

# тестовые секреты (gh#1317-класс «похож на токен» — ≥24 b64-класса,
# цифра И hex-буква; буквенный; неверный)
TOKENLIKE = "abcdefgh1369abcdefghi13ab"
ALPHA = "abcdefghiabcdefghi"
WRONG = "wrong-value-999"
PORT_BASE = 10995 + os.getpid() % 40

pytestmark = pytest.mark.skipif(
    not (os.path.exists(MLOG_BIN) and os.path.exists(APP_MLOG)),
    reason="bin/mlog или app.mlog отсутствуют (нестендовая песочница)")


def _src() -> str:
    return open(APP_MLOG, encoding="utf-8").read()


def _extract_block(src: str, start_marker: str) -> str:
    """Текст блока от start_marker до сбалансированной закрывающей скобки."""
    i = src.find(start_marker)
    assert i >= 0, f"не найден блок: {start_marker}"
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError(f"несбалансированный блок: {start_marker}")


def _pattern(src: str, name: str) -> str:
    return _extract_block(src, f"pattern {name}(")


def _route(src: str, path: str) -> str:
    return _extract_block(src, f'route "{path}" method=')


STUBS = """// HARNESS STUBS (тест #546): dept-паттерны заглушены; тексты маршрутов
// и паттернов — НАСТОЯЩИЕ из app.mlog (извлекаются при каждом прогоне).
pattern InitDB() -> String { return "stub-ok" }
pattern BootstrapSchedules() -> String { return "boot-stub-ok" }
pattern MorningBrief() -> String { return "brief-stub-ok" }
pattern YanaSelfLearn() -> String { return "learn-stub-ok" }
"""

# HARNESS-роут: канал «вид хеша» (мост №318 шлёт фингерпринт). Настоящий
# SecretMatches; фингерпринт подаёт сам mlog — значение не покидает сервер
# и нигде не печатается.
SELFSHA = """  // HARNESS: канал «вид хеша» — настоящий SecretMatches
  route "/selfhash" method=GET {
    let h = redact(env("CRON_SECRET"), "hash_only")
    if SecretMatches(h, "CRON_SECRET") == false then { return respond("403 hash-ne") }
    return respond("200 hashform-ok")
  }
"""


def _harness(port: int, mutation: str = None) -> str:
    src = _src()
    sm = _pattern(src, "SecretMatches")
    ria = _pattern(src, "RequireInternalAuth")
    boot = _route(src, "/schedules/bootstrap")
    morning = _route(src, "/cron/morning")
    version = _route(src, "/version")
    if mutation == "all_on_query":
        old = 'redact(query_param("secret"), "hash_only")'
        new = 'redact(query_param("secret"), "all")'
        # мутация «вернуть all» по тексту наряда — на обоих настоящих маршрутах
        assert old in boot and old in morning
        boot = boot.replace(old, new)
        morning = morning.replace(old, new)
    return (
        "// #546 A.2: автогенерируемый харнесс — НАСТОЯЩИЕ паттерны и маршруты\n"
        "// из app.mlog (анти-drift), dept-тела заглушены (HARNESS STUB).\n"
        "// Мост ADR-0161 — как на проде: entrypoint служит augmented copy\n"
        "// («profile legacy { egress: permissive_with_audit }» + app.mlog),\n"
        "// без него serve-старт блокируется легальными clearance-ошибками\n"
        "// моста №391 (42 шт. — те же, что в статическом аудите main).\n"
        "profile legacy { egress: permissive_with_audit }\n"
        + STUBS + "\n" + sm + "\n\n" + ria + "\n\n"
        + f"mlogserver {{\n  port: {port}\n  host: \"127.0.0.1\"\n\n"
        + boot + "\n\n" + morning + "\n\n" + version + "\n\n" + SELFSHA
        + "}\n")


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

    def __init__(self, cron_secret, token, mutation=None):
        self.dir = tempfile.mkdtemp(prefix="n546-serve-")
        # read_file("dept/yana.mlog") — из репо (анти-drift); VERSION —
        # в репо нет (штампуется деплоем) — тестовый стаб
        os.makedirs(os.path.join(self.dir, "dept"))
        shutil.copy(os.path.join(REPO, "dept", "yana.mlog"),
                    os.path.join(self.dir, "dept", "yana.mlog"))
        with open(os.path.join(self.dir, "VERSION"), "w", encoding="utf-8") as f:
            f.write("n546-test-harness\n")
        self.port = _free_port(PORT_BASE + os.getpid() % 50)
        src = os.path.join(self.dir, "harness.mlog")
        with open(src, "w", encoding="utf-8") as f:
            f.write(_harness(self.port, mutation))
        env = dict(os.environ)
        env.update({
            "CRON_SECRET": cron_secret,
            "INTERNAL_API_TOKEN": token,
            "METALOGOS_ENV_ALLOWLIST": "CRON_SECRET,INTERNAL_API_TOKEN",
            "METALOGOS_SERVE_BACKEND": "interpreter",
            "METALOGOS_HTTP_ALLOW_PRIVATE": "1",
            "METALOGOS_DATA_DIR": self.dir,
            # прод-эквивалент (entrypoint M455_NAMES): read_file("dept/yana.mlog")
            # и read_file("VERSION") вне deny-list — иначе /version отвечает
            # 500 SANDBOX_SENSITIVE_PATH и readiness-проба не проходит
            "METALOGOS_SENSITIVE_PATH_ALLOWLIST": "app.mlog,consensus.mlog,yana.mlog,VERSION",
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
                # readiness: /version без заголовка → 401 (auth жив) или 200
                if requests.get(self.url + "/version", timeout=2).status_code in (200, 401):
                    return
            except requests.RequestException:
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


@pytest.fixture(scope="module")
def serve_tokenlike():
    s = _Serve(TOKENLIKE, TOKENLIKE)
    yield s
    s.stop()


@pytest.fixture(scope="module")
def serve_alpha():
    s = _Serve(ALPHA, ALPHA)
    yield s
    s.stop()


@pytest.fixture(scope="module")
def serve_empty_env():
    s = _Serve("", "")
    yield s
    s.stop()


@pytest.fixture(scope="module")
def serve_mutant():
    s = _Serve(TOKENLIKE, TOKENLIKE, mutation="all_on_query")
    yield s
    s.stop()


# ── Кейсы наряда: /schedules/bootstrap ────────────────────────────────────

def test_bootstrap_tokenlike_secret_200(serve_tokenlike):
    # верный секрет, похожий на токен → 200 (цель наряда: класс 403 #536)
    r = requests.get(serve_tokenlike.url + "/schedules/bootstrap",
                     params={"secret": TOKENLIKE}, timeout=5)
    assert r.status_code == 200, r.text
    assert "key_mismatch" not in r.text and "cron_key_unset" not in r.text


def test_bootstrap_alpha_secret_200(serve_alpha):
    # верный секрет из одних букв → 200
    r = requests.get(serve_alpha.url + "/schedules/bootstrap",
                     params={"secret": ALPHA}, timeout=5)
    assert r.status_code == 200, r.text


def test_bootstrap_hashform_200(serve_tokenlike):
    # вид хеша верного секрета → 200 (канал моста №318, как сейчас)
    r = requests.get(serve_tokenlike.url + "/selfhash", timeout=5)
    assert r.status_code == 200, r.text
    assert "hashform-ok" in r.text


def test_bootstrap_wrong_403(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/schedules/bootstrap",
                     params={"secret": WRONG}, timeout=5)
    assert r.status_code == 403, r.text


def test_bootstrap_empty_403(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/schedules/bootstrap",
                     params={"secret": ""}, timeout=5)
    assert r.status_code == 403, r.text


def test_bootstrap_no_secret_param_403(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/schedules/bootstrap", timeout=5)
    assert r.status_code == 403, r.text


def test_bootstrap_env_unset_403(serve_empty_env):
    # env не задан (пустое значение) → 403, проверка не ослаблена
    r = requests.get(serve_empty_env.url + "/schedules/bootstrap",
                     params={"secret": ALPHA}, timeout=5)
    assert r.status_code == 403, r.text


# ── Кейсы наряда: /cron/morning (один из внешних cron) ───────────────────

def test_cron_morning_tokenlike_200(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/cron/morning",
                     params={"secret": TOKENLIKE}, timeout=5)
    assert r.status_code == 200, r.text


def test_cron_morning_wrong_403(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/cron/morning",
                     params={"secret": WRONG}, timeout=5)
    assert r.status_code == 403, r.text


# ── Кейсы наряда: /version с X-Internal-Token ────────────────────────────

def test_version_tokenlike_header_200(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/version",
                     headers={"X-Internal-Token": TOKENLIKE}, timeout=5)
    assert r.status_code == 200, r.text


def test_version_wrong_header_401(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/version",
                     headers={"X-Internal-Token": WRONG}, timeout=5)
    assert r.status_code == 401, r.text


def test_version_missing_header_401(serve_tokenlike):
    r = requests.get(serve_tokenlike.url + "/version", timeout=5)
    assert r.status_code == 401, r.text


# ── Мутация по тексту наряда: вернуть redact(..., "all") ──────────────────


def test_mutation_all_policy_is_killed(serve_tokenlike, serve_mutant):
    """Мутант call-site hash_only→all обязан пасть на кейсе «похожий на токен».

    serve_tokenlike (оригинал): секрет похожий на токен → 200.
    serve_mutant: тот же запрос → 403 (redact("all") маскирует значение).
    Если мутант неотличим — кейсы нечувствительны к этому классу регрессии.
    """
    ok = requests.get(serve_tokenlike.url + "/schedules/bootstrap",
                      params={"secret": TOKENLIKE}, timeout=5)
    assert ok.status_code == 200
    mutant = requests.get(serve_mutant.url + "/schedules/bootstrap",
                          params={"secret": TOKENLIKE}, timeout=5)
    assert mutant.status_code == 403, (
        "мутант redact(...,\"all\") неотличим от оригинала на токен-подобном "
        "секрете — регрессия gh#1317 не была бы поймана")


# ── Статические гварды app.mlog (анти-drift) ─────────────────────────────


def test_app_mlog_no_all_redact_on_secrets():
    src = _src()
    assert src.count('redact(query_param("secret"), "all")') == 0, \
        "app.mlog: остался redact(...,\"all\") на секрете из query (gh#1317)"
    assert src.count('redact(request_header("X-Internal-Token"), "all")') == 0, \
        "app.mlog: RequireInternalAuth вернулся к redact(...,\"all\")"
    assert "if ct_eq(" not in src, \
        "app.mlog: ct_eq по сырой строке вернулся (ломается на gh#1317-значениях)"


def test_app_mlog_secretmatches_coverage():
    src = _src()
    assert "pattern SecretMatches(received: String, env_name: String) -> Bool" in src
    calls = (src.count('SecretMatches(secret, "CRON_SECRET")')
             + src.count('SecretMatches(token, "INTERNAL_API_TOKEN")'))
    assert calls == 30, f"вызовов SecretMatches: {calls}, ожидалось 30 (30 мест наряда)"
    # 29 query-мест + 1 заголовок X-Internal-Token = 30 мест наряда
    assert src.count('redact(query_param("secret"), "hash_only")') == 29, \
        "app.mlog: call-site обёртка hash_only не на всех query-местах"
    assert src.count('redact(request_header("X-Internal-Token"), "hash_only")') == 1, \
        "app.mlog: RequireInternalAuth без hash_only-обёртки"


def test_app_mlog_bootstrap_reason_codes_kept():
    # #428 A.1: различение причин отказа сохранено
    src = _src()
    assert 'respond("403 cron_key_unset")' in src
    assert 'respond("403 key_mismatch")' in src


def test_app_mlog_empty_env_still_denied():
    # «Не ослаблять проверки: пустой env → отказ»
    pat = _pattern(_src(), "SecretMatches")
    assert 'if expected_raw == "" then { return false }' in pat
