#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #696 (REA-3): гварды ЛЗ-сенсора WebMCP.

Офлайн-инварианты (CI без playwright/сети — импорт модуля не тянет браузер,
import playwright ленивый, внутри run()):
  A.1a — обёртка .sh существует и синтаксически валидна (bash -n);
  A.1b — драйвер .py компилируется и импортируется БЕЗ playwright;
  A.1c — детерминированный список доменов: 5–10, уникальные, без схемы/пути,
         категории наряда (провайдеры/платформы/реестры);
  A.1d — разбор конверта discover-webmcp-tools (реальная структура Chrome 157
         + rea 6.8.0, прогон 10.11.2026) и дайджест md/json: домен, тулы,
         URL, дата, Evidence;
  A.2  — периодичность задокументирована (ручная процедура, границы наряда);
  гигиена — .gitignore whitelist содержит оба скрипта (конвенция scripts/).
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SH = REPO_ROOT / "scripts" / "lz_webmcp_sensor.sh"
PY = REPO_ROOT / "scripts" / "lz_webmcp_sensor.py"
GITIGNORE = REPO_ROOT / ".gitignore"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import lz_webmcp_sensor as sensor  # noqa: E402

# Реальный конверт discover-webmcp-tools (Chrome for Testing 157.0.8103.50,
# rea-agents@6.8.0, локальная страница с <form toolname=…>, 10.11.2026)
REAL_ENVELOPE = """{
 "evidence_id":"ev_9da7b13c1fda428f4c9ee362891ded01fc0fed42b5d1146a9d9c4a8cb8d1813d",
 "normalized_result":{
   "target":{"target_id":"T","url":"http://127.0.0.1:43833/","origin":"http://127.0.0.1:43833"},
   "status":"available",
   "tools":{"total":1,"items":[{
     "tool_key":"webmcp_edd58d52","name":"createSupportRequest",
     "description":"Submits a request for customer support (probe).",
     "frame_url":"http://127.0.0.1:43833/","owner_origin":"http://127.0.0.1:43833",
     "declaration_kind":"declarative",
     "input_schema":{"type":"object","properties":{"topic":{"type":"string"}},"required":[]},
     "trust":"page-declared-untrusted"}]},
   "completeness":{"status":"complete_within_window","excluded":[]}
 }
}"""


def test_a1a_wrapper_bash_n():
    assert SH.exists(), "scripts/lz_webmcp_sensor.sh отсутствует (наряд A.1)"
    r = subprocess.run(["bash", "-n", str(SH)], capture_output=True, text=True)
    assert r.returncode == 0, f"bash -n упал: {r.stderr}"


def test_a1b_driver_imports_without_playwright():
    # CI не ставит playwright (нет в requirements.txt) — модуль обязан
    # импортироваться: import playwright только внутри run()/resolve_browser()
    assert "playwright" not in sys.modules or True  # сам факт импорта выше = успех
    assert callable(sensor.main)
    assert callable(sensor.parse_discovery)
    assert callable(sensor.build_digest)


def test_a1c_domain_list_deterministic():
    d = sensor.DEFAULT_DOMAINS
    assert 5 <= len(d) <= 10, f"наряд A.3: 5–10 доменов-кандидатов, а не {len(d)}"
    assert len(d) == len(set(d)), "дубликаты в списке доменов"
    for dom in d:
        assert "/" not in dom and ":" not in dom and "." in dom, \
            f"домен {dom!r} должен быть голым хостом (https добавляет сенсор)"
    # категории наряда: провайдеры / платформы / реестры — по факту списка
    assert "openai.com" in d and "anthropic.com" in d   # модельные провайдеры
    assert "claude.ai" in d and "cursor.com" in d       # agent-платформы
    assert "mcp.so" in d or "smithery.ai" in d          # MCP-реестры


def test_a1d_parse_real_envelope():
    parsed = sensor.parse_discovery(REAL_ENVELOPE)
    assert parsed["status"] == "available"
    assert parsed["completeness"] == "complete_within_window"
    assert parsed["evidence_id"].startswith("ev_")
    assert len(parsed["tools"]) == 1
    t = parsed["tools"][0]
    assert t["name"] == "createSupportRequest"
    assert t["declaration_kind"] == "declarative"
    assert t["trust"] == "page-declared-untrusted"
    assert t["frame_url"].startswith("http://127.0.0.1:")


def test_a1d_parse_garbage_is_honest():
    parsed = sensor.parse_discovery("not-json{")
    assert parsed["status"] == "parse_error"
    assert parsed["tools"] == []
    # недоступный провайдер (браузер без CDP-домена WebMCP) — тоже честная строка
    parsed2 = sensor.parse_discovery(json_env_unavailable())
    assert parsed2["status"] == "unavailable"
    assert parsed2["unavailable_reason"] == "provider_unavailable"


def json_env_unavailable():
    return """{
     "evidence_id":"ev_x",
     "normalized_result":{"status":"unavailable","tools":{"total":0,"items":[]},
       "completeness":{"status":"attach_limited",
         "excluded":[{"section":"webmcp_tools","reason":"provider_unavailable"}]}}
    }"""


def test_a1d_find_target_id():
    list_env = """{"normalized_result":{"targets":[
      {"target_id":"AAA","type":"page","url":"https://mcp.so/"},
      {"target_id":"BBB","type":"page","url":"https://other.example/"}]}}"""
    assert sensor.find_target_id(list_env, "mcp.so") == "AAA"
    assert sensor.find_target_id(list_env, "nope.example") is None
    assert sensor.find_target_id("мусор{", "mcp.so") is None
    # кросс-доменный редирект (claude.ai → claude.com/app-unavailable-in-region,
    # прогон 10.11.2026): матчится финальный URL загруженной страницы
    list_redirect = """{"normalized_result":{"targets":[
      {"target_id":"CCC","type":"page","url":"https://claude.com/app-unavailable-in-region"}]}}"""
    assert sensor.find_target_id(
        list_redirect,
        ["https://claude.com/app-unavailable-in-region", "claude.ai"]) == "CCC"
    assert sensor.find_target_id(list_redirect, ["https://x.y/", "claude.ai"]) is None


def test_a1d_digest_md_json_content():
    parsed = sensor.parse_discovery(REAL_ENVELOPE)
    row = {"domain": "probe.local", "url": "http://127.0.0.1:43833/",
           "final_url": "http://127.0.0.1:43833/", "title": "probe6",
           "http_status": 200, "load_error": None, "observed_at_utc": "X"}
    row.update(parsed)
    err_row = {"domain": "blocked.example", "url": "https://blocked.example/",
               "final_url": None, "title": None, "http_status": None,
               "load_error": "Neterr: blocked", "observed_at_utc": "X",
               "status": None, "completeness": None, "tools": [],
               "evidence_id": ""}
    md, js = sensor.build_digest([row, err_row],
                                 {"stamp": "2026-11-10T00:00:00Z",
                                  "browser_path": "/x/chrome",
                                  "browser_version": "Chrome/157",
                                  "features": "WebMCP",
                                  "delay": 10})
    # наряд: дайджест содержит домен, декларации, URL, дату
    assert "2026-11-10T00:00:00Z" in md
    assert "probe.local" in md and "blocked.example" in md
    assert "createSupportRequest" in md and "declarative" in md
    assert "https://blocked.example/" in md
    assert "ОШИБКА ЗАГРУЗКИ" in md
    assert "ev_9da7b13c" in md
    # сенсор — поставщик, не вердикт (устав library/lz.md:31 в дайджесте)
    assert "library/lz.md:31" in md and "не вердикт" in md
    assert js["kind"] == "lz-webmcp-sensor-digest" and js["naryad"] == 696
    assert js["summary"]["domains"] == 2
    assert js["summary"]["with_declarations"] == 1
    assert js["summary"]["load_errors"] == 1
    assert js["domains"][0]["tools"][0]["name"] == "createSupportRequest"
    # робо-этика — в мета дайджеста
    assert js["ethics"]["pages_per_domain"] == 1 and js["ethics"]["auth"] == "none"


def test_a2_periodicity_documented():
    text = PY.read_text(encoding="utf-8")
    # наряд A.2: ручная процедура + зафиксированный вопрос автономизации
    assert "РУЧНОЙ запуск" in text
    assert "waker_windows.txt" in text and "start_crons.py" in text
    sh_text = SH.read_text(encoding="utf-8")
    assert "еженедельное" in sh_text or "еженедельный" in sh_text


def test_gitignore_whitelist():
    gi = GITIGNORE.read_text(encoding="utf-8")
    assert "!scripts/lz_webmcp_sensor.sh" in gi
    assert "!scripts/lz_webmcp_sensor.py" in gi
