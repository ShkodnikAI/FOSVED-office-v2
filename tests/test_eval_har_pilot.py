#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #697 (REA-4): гварды рецепта eval-стенда из HAR.

Офлайн-инварианты (CI без сети/Docker/rea-agents — импорт модулей ничего
не тянет, живые контуры только на 127.0.0.1:ephemeral):
  A.1a — драйвер .sh существует и синтаксически валиден (bash -n), пин
         rea-agents 6.8.0 и гейт node из конвенции #694–#696 на месте;
  A.1b — python-части компилируются и импортируются без внешних зависимостей;
  A.1c — интеграция recorder×demo-app: сценарий demo даёт валидный HAR 1.2
         (read→write→read, postData на POST, queryString из пути);
  A.1d — сценарии: 2–8 ops; порядок read→write→read (позже чтение
         подтверждает эффект записи); office-create expect_json=false
         (роут отвечает текстом «created <id>»), demo-create expect_json=true;
  A.1e — REST-форма демо (контраст-ветка state): seed ≥ 2 (пустой/
         одноэлементный baseline не даёт state — урок пилота), create
         возвращает entity-JSON (201);
  A.2  — docs/eval-har-env.md освещает replay-only vs state,
         credential-named-members, границу golden-evals;
  A.3  — находки прогона 10.11.2026 зафиксированы в доке (фикстуры
         REAL_*_COVERAGE — реальные coverage из environment-build);
  гигиена — .gitignore whitelist содержит файлы рецепта (конвенция scripts/).
"""
import json
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
SH = SCRIPTS / "eval_har_pilot.sh"
RECORDER = SCRIPTS / "eval_har_recorder.py"
DEMO_APP = SCRIPTS / "eval_har_demo_app.py"
SMOKE = SCRIPTS / "eval_har_mcp_smoke.py"
SCN_OFFICE = SCRIPTS / "eval_har_scenario_schedules.json"
SCN_DEMO = SCRIPTS / "eval_har_scenario_demo.json"
DOC = REPO_ROOT / "docs" / "eval-har-env.md"
GITIGNORE = REPO_ROOT / ".gitignore"

sys.path.insert(0, str(SCRIPTS))
import eval_har_recorder as recorder  # noqa: E402
import eval_har_mcp_smoke as smoke  # noqa: E402
import eval_har_demo_app as demo_app  # noqa: E402

# Реальные coverage из environment-build прогона 10.11.2026 (rea-agents@6.8.0):
# офис (RPC-поверхность /schedules/*) и REST-демо (/items) — контраст веток.
REAL_OFFICE_COVERAGE = {
    "reads": {"state": 0, "recorded": 1, "recorded_reasons": {"fields-differ": 1}},
    "writes": {"served": [], "withheld": [
        {"tool": "post_schedules_create", "effect": "none", "reason": "no-state-target"}]},
}
REAL_DEMO_COVERAGE = {
    "reads": {"state": 1, "recorded": 0, "recorded_reasons": {}},
    "writes": {"served": [{"tool": "post_items", "effect": "create"}], "withheld": []},
}


def _start_demo(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), demo_app.Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


def _wait_health(srv, tries=20):
    import http.client
    for _ in range(tries):
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=2)
            c.request("GET", "/items")
            c.getresponse().read()
            c.close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


# ── A.1a: драйвер ──────────────────────────────────────────────────────────

def test_a1a_wrapper_bash_n_and_pins():
    assert SH.exists(), "scripts/eval_har_pilot.sh отсутствует (наряд A.1)"
    r = subprocess.run(["bash", "-n", str(SH)], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n упал: {r.stderr}"
    src = SH.read_text(encoding="utf-8")
    # пин версии — конвенция #694–#696 (апгрейд только осознанным коммитом)
    assert 'REA_VERSION="6.8.0"' in src, "пин rea-agents@6.8.0 обязателен"
    # гейт node — требование README rea-agents (как в rea_inspect.sh)
    assert "22, 23, 4" in src and "24, 22, 1" in src, "гейт версий node на месте"
    # честная пометка Docker (наряд #697: недоступность не проваливает прогон)
    assert "НЕДОСТУПЕН" in src, "Docker-недоступность — честная пометка, не провал"


# ── A.1b: python-части ─────────────────────────────────────────────────────

def test_a1b_python_parts_import_offline():
    assert callable(recorder.main) and callable(recorder.run_op)
    assert callable(smoke.main) and callable(smoke._result_of)
    assert callable(demo_app.main)
    # никаких сетевых/браузерных импортов на уровне модуля
    for mod in (recorder, smoke, demo_app):
        assert "playwright" not in sys.modules, "CI без браузеров"


# ── A.1c: интеграция recorder×demo (127.0.0.1:ephemeral) ───────────────────

def test_a1c_recorder_demo_har_roundtrip(tmp_path):
    srv = _start_demo()
    try:
        assert _wait_health(srv)
        out = tmp_path / "demo.har"
        rc = recorder.main([
            "--scenario", str(SCN_DEMO),
            "--base", f"http://127.0.0.1:{srv.server_address[1]}",
            "--out", str(out),
        ])
        assert rc == 0
        har = json.loads(out.read_text(encoding="utf-8"))
        assert har["log"]["version"] == "1.2"
        # creator честно называет рекордер (не выдаетёт себя за DevTools)
        assert har["log"]["creator"]["name"] == "fosved-eval-har-recorder"
        entries = har["log"]["entries"]
        assert [e["request"]["method"] for e in entries] == ["GET", "POST", "GET"]
        # read→write→read: позже чтение подтверждает эффект записи
        before = json.loads(entries[0]["response"]["content"]["text"])
        after = json.loads(entries[2]["response"]["content"]["text"])
        assert len(before) == 2 and len(after) == 3, "seed=2 → create → 3"
        # POST несёт postData; созданная сущность — в списке после
        assert entries[1]["request"]["postData"]["mimeType"] == "application/json"
        created = json.loads(entries[1]["response"]["content"]["text"])
        assert created["id"] == 3 and created["title"] == "from-pilot-697"
        assert any(x["id"] == created["id"] for x in after)
    finally:
        srv.shutdown()


# ── A.1d: сценарии ─────────────────────────────────────────────────────────

def test_a1d_scenarios_read_write_read():
    for path, create_expect_json in ((SCN_OFFICE, False), (SCN_DEMO, True)):
        scn = json.loads(path.read_text(encoding="utf-8"))
        ops = scn["ops"]
        assert 2 <= len(ops) <= 8, f"{path.name}: короткая сессия 2–8 операций"
        assert scn.get("base", "").startswith("http://127.0.0.1"), \
            f"{path.name}: только свои приложения (localhost-стенд)"
        # порядок read → write → read (эффект записи подтверждается чтением)
        assert [o["method"] for o in ops][:3] == ["GET", "POST", "GET"]
        # подтверждающее чтение — тот же путь, что базовое
        assert ops[2]["path"] == ops[0]["path"]
        create_op = ops[1]
        assert bool(create_op.get("expect_json")) is create_expect_json, \
            f"{path.name}: expect_json create-op должен быть {create_expect_json}"
        assert create_op.get("body"), f"{path.name}: write-op без body"
    # офисный сценарий: публичный тестовый секрет стенда (не прод)
    office = json.loads(SCN_OFFICE.read_text(encoding="utf-8"))
    for o in office["ops"]:
        assert "n349-test-secret" in o["path"], "секрет — тестовый CRON_SECRET стенда"


# ── A.1e: REST-форма демо (контраст-ветка state) ──────────────────────────

def test_a1e_demo_rest_shape_two_seed():
    import http.client
    # seed ≥ 2: пустой/одноэлементный baseline не даёт state ни
    # идентичности, ни membership (README rea-agents; урок пилота #697)
    assert len(demo_app._ITEMS) >= 2
    srv = _start_demo()
    try:
        assert _wait_health(srv)
        port = srv.server_address[1]
        # GET /items — ГОЛЫЙ массив (не конверт с несколькими массивами)
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/items")
        r = c.getresponse()
        body = json.loads(r.read().decode("utf-8"))
        assert r.status == 200 and isinstance(body, list)
        # POST /items — entity-JSON (201) с identity-полем id
        payload = json.dumps({"title": "guard"}).encode("utf-8")
        c.request("POST", "/items", body=payload,
                  headers={"Content-Type": "application/json",
                           "Content-Length": str(len(payload))})
        r2 = c.getresponse()
        created = json.loads(r2.read().decode("utf-8"))
        assert r2.status == 201
        assert set(created) == {"id", "title", "done"} and created["id"] > 0
        c.close()
    finally:
        srv.shutdown()


# ── A.2/A.3: документ и зафиксированные находки прогона ────────────────────

def test_a2_doc_covers_limitations_and_boundaries():
    text = DOC.read_text(encoding="utf-8")
    # replay vs state — центральное ограничение (наряд A.2)
    for needle in ("replay-only", "state", "fields-differ", "no-state-target",
                   "credential-named-members", "test_golden_evals.py",
                   "untrusted_content", "environment-serve"):
        assert needle in text, f"docs/eval-har-env.md: нет «{needle}»"
    # границы наряда
    assert "только свои приложения" in text
    assert "не публикуются" in text or "не публикуем" in text


def test_a3_findings_fixtures_match_doc():
    # контраст веток из реального прогона 10.11.2026 зафиксирован в доке
    text = DOC.read_text(encoding="utf-8")
    assert REAL_OFFICE_COVERAGE["writes"]["withheld"][0]["tool"] in text
    assert REAL_DEMO_COVERAGE["writes"]["served"][0]["tool"] in text
    # обе ветки рецепта упомянуты как режимы драйвера
    assert "eval_har_pilot.sh" in text and "office" in text and "demo" in text


# ── A.3: SSE-парсинг smoke-клиента (offline, реальные конверты REA 6.8.0) ──

def test_a3_smoke_parses_sse_and_real_envelopes():
    # реальный конверт tools/call из прогона (streamable HTTP -> SSE)
    sse = ('event: message\ndata: {"result":{"content":[{"type":"text",'
           '"text":"{\\"status\\": 200, \\"state\\": {\\"source\\": \\"state\\", '
           '\\"view\\": \\"list\\"}}"}],"isError":false},'
           '"jsonrpc":"2.0","id":3}')
    assert 'data: {' in sse
    data_line = [l[5:].strip() for l in sse.splitlines() if l.startswith("data:")][-1]
    env = json.loads(data_line)
    payload = json.loads(env["result"]["content"][0]["text"])
    assert payload["state"]["source"] == "state" and payload["status"] == 200
    # JSON-RPC error — честный raise
    try:
        smoke._result_of({"error": {"code": -32601, "message": "nope"}})
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "JSON-RPC error обязан честно падать"
    # успешный конверт → result
    assert smoke._result_of({"result": {"x": 1}}) == {"x": 1}


# ── гигиена: whitelist ─────────────────────────────────────────────────────

def test_gitignore_whitelist_recipe_files():
    gi = GITIGNORE.read_text(encoding="utf-8")
    for f in ("eval_har_pilot.sh", "eval_har_recorder.py", "eval_har_demo_app.py",
              "eval_har_mcp_smoke.py", "eval_har_scenario_schedules.json",
              "eval_har_scenario_demo.json"):
        assert f"!scripts/{f}" in gi, f".gitignore: нет whitelist-записи scripts/{f}"
        assert (SCRIPTS / f).exists(), f"scripts/{f} отсутствует"
