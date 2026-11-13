#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #717 SEC-1 (P1): офис без «швов» — инвентарь потоков секретов/LLM
через паттерны (п.1) и изоляция `check --root` в CI (п.2). п.3–4 — на
кандидате Metalogos с №950, исполняются отдельно.

Гварды:
- A (п.2, окружение): sanitize_env() — deny-by-default, DATABASE_URL всегда
  sqlite::memory:, боевые переменные (TELEGRAM_BOT_TOKEN, ключи провайдеров,
  CRON_SECRET, …) не наследуются даже с загрязнённого родителя; нейтральные
  переменные ОС выживают; MLOG_BIN (кандидат стенда #655) пробрасывается;
  живой прогон --print-env под загрязнённым родителем;
- B (п.2, CI-гигиена): в .github/workflows/ci.yml нет прямого
  `bin/mlog check … --root` — только через scripts/mlog_check_root_env.py;
  mlog_baseline_gate.run_check использует общий санитайзер (не os.environ);
- C (п.1, инвентарь): docs/office/interproc_inventory.md существует, несёт
  все разделы; канонические швы с верными якорями; числа §1 и множества
  env-читателей/стоков равны живому скану scripts/n717_inventory_scan.py —
  документ не может разойтись с кодом (регенерация — §8 документа).
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
DOC = os.path.join(REPO_ROOT, "docs", "office", "interproc_inventory.md")
CI = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
GATE = os.path.join(SCRIPTS, "mlog_baseline_gate.py")
WRAPPER = os.path.join(SCRIPTS, "mlog_check_root_env.py")

sys.path.insert(0, SCRIPTS)

from mlog_check_root_env import (  # noqa: E402
    NEUTRAL_ALLOWLIST, PROD_ENV_VARS, sanitize_env,
)


def _load_scanner():
    spec = importlib.util.spec_from_file_location(
        "n717_inventory_scan", os.path.join(SCRIPTS, "n717_inventory_scan.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── A. Санитайзер окружения (п.2) ────────────────────────────────────────────

def test_a1_database_url_always_memory():
    env = sanitize_env({"DATABASE_URL": "postgres://prod:hunter2@db/office",
                        "PATH": "/usr/bin"})
    assert env["DATABASE_URL"] == "sqlite::memory:"
    env2 = sanitize_env({"PATH": "/usr/bin"})
    assert env2["DATABASE_URL"] == "sqlite::memory:"


def test_a2_prod_vars_never_inherited():
    parent = {name: "LEAK-CANARY" for name in PROD_ENV_VARS}
    parent["PATH"] = "/usr/bin"
    env = sanitize_env(parent)
    leaked = sorted(set(PROD_ENV_VARS) & set(env))
    assert not leaked, f"боевые переменные просочились в окружение ребёнка: {leaked}"
    assert "LEAK-CANARY" not in set(env.values())


def test_a3_deny_by_default_unknown_vars_dropped():
    env = sanitize_env({"PATH": "/usr/bin", "FOO_SECRET": "x",
                        "TOTALLY_NEW_PROD_TOKEN": "y", "AWS_SECRET_ACCESS_KEY": "z"})
    for name in ("FOO_SECRET", "TOTALLY_NEW_PROD_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        assert name not in env


def test_a4_neutral_vars_survive():
    parent = {"PATH": "/usr/bin:/bin", "HOME": "/home/z", "LANG": "C.UTF-8",
              "LC_ALL": "C.UTF-8", "TMPDIR": "/tmp", "USER": "z", "TERM": "xterm"}
    env = sanitize_env(parent)
    for k, v in parent.items():
        assert env.get(k) == v


def test_a5_mlog_bin_passthrough():
    env = sanitize_env({"PATH": "/usr/bin", "MLOG_BIN": "/tmp/candidate-mlog"})
    assert env.get("MLOG_BIN") == "/tmp/candidate-mlog"
    env2 = sanitize_env({"PATH": "/usr/bin", "MLOG_BIN": ""})
    assert "MLOG_BIN" not in env2


def test_a6_allowlist_disjoint_from_prod_registry():
    overlap = sorted(set(NEUTRAL_ALLOWLIST) & set(PROD_ENV_VARS))
    assert not overlap, f"нейтральный белый список пересекается с боевым: {overlap}"


def test_a7_live_print_env_under_polluted_parent():
    """Живой прогон обёртки: дочернее окружение чисто, даже если родитель загрязнён."""
    pollute = {name: "LIVE-LEAK-" + name for name in
               ("TELEGRAM_BOT_TOKEN", "CRON_SECRET", "ZAI_API_KEY", "OWNER_TELEGRAM_ID")}
    env = dict(os.environ)
    env.update(pollute)
    env["DATABASE_URL"] = "postgres://prod/office"  # попытка навязать боевую БД
    proc = subprocess.run(
        [sys.executable, WRAPPER, "--print-env"],
        capture_output=True, text=True, timeout=60, env=env, cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr[:400]
    child = json.loads(proc.stdout)
    # п.2: только sqlite::memory:, даже при боевом DATABASE_URL в родителе
    assert child["DATABASE_URL"] == "sqlite::memory:"
    for name in pollute:
        assert name not in child, f"{name} просочился в живой прогон"
    assert "PATH" in child  # нейтральный базис на месте


# ── B. CI-гигиена: check --root только через обёртку (п.2) ──────────────────

def test_b1_ci_closure_guard_uses_wrapper_no_raw_root():
    src = open(CI, encoding="utf-8").read()
    # шаг гварда замкнутости зовёт обёртку
    assert "scripts/mlog_check_root_env.py" in src, (
        "closure guard в ci.yml не идёт через санитайзер n717")
    # прямых вызовов bin/mlog с --root в workflow нет (кроме комментариев)
    raw = [ln.strip() for ln in src.splitlines()
           if re.search(r"bin/mlog\s+check\s+\S+\s+--root", ln)
           and not ln.strip().startswith("#")]
    assert not raw, f"прямой 'bin/mlog check … --root' в ci.yml (мимо обёртки): {raw}"


def test_b2_ci_all_root_lines_are_comment_or_wrapper():
    """Каждая строка ci.yml с '--root' — комментарий или комментарий-строка шага."""
    src = open(CI, encoding="utf-8").read()
    for ln in src.splitlines():
        if "--root" in ln:
            stripped = ln.strip()
            assert stripped.startswith("#") or "mlog_check_root_env" in ln or \
                "mlog_baseline_gate" in ln, \
                f"подозрительная строка с --root вне обёртки/гейта: {stripped!r}"


def test_b3_baseline_gate_uses_sanitizer_not_os_environ():
    src = open(GATE, encoding="utf-8").read()
    assert "sanitize_env" in src, "mlog_baseline_gate не использует общий санитайзер"
    rc_fn = re.search(r"def run_check\(.*?\n(.*?)\n\n", src, re.S)
    assert rc_fn, "run_check не найден в mlog_baseline_gate.py"
    assert "dict(os.environ)" not in rc_fn.group(1), (
        "run_check наследует os.environ — бой переменных может утечь в check --root")


# ── C. Инвентарь (п.1) ──────────────────────────────────────────────────────

def test_c1_inventory_doc_exists_with_sections():
    assert os.path.isfile(DOC), "docs/office/interproc_inventory.md отсутствует"
    text = open(DOC, encoding="utf-8").read()
    for section in (
        "## 1. Метод и сводка",
        "### 2.0 Конфиг-блоки верхнего уровня",
        "### 2.1 Паттерны-источники: env / env_or",
        "### 2.4 Паттерны-стоки",
        "### 2.5 Прямые рёбра",
        "## 4. Трассировка `TELEGRAM_BOT_TOKEN`",
        "## 5. Трассировка ключей провайдеров",
        "## 6. Швы: реестр и что изменит №950",
        "## 7. План миграции",
        "## 8. Регенерация и верификация",
    ):
        assert section in text, f"в инвентаре нет раздела: {section}"


def test_c2_doc_headline_numbers_match_live_scan():
    mod = _load_scanner()
    d = mod.scan()
    text = open(DOC, encoding="utf-8").read()
    expected = {
        "files": len(d["files"]),
        "pattern_count": d["pattern_count"],
        "unique_names": d["unique_pattern_names"],
        "config_blocks": len(d["config_blocks"]),
        "source_patterns": len(d["source_patterns"]),
        "env_readers": len(d["env_readers"]),
        "sink_patterns": len(d["sink_patterns"]),
        "routes": len(d["routes"]),
        "flows": len(d["flows"]),
        "direct_edges": len(d["direct_edges"]),
        "seams": len(d["seams"]),
        "intra": len(d["intra"]),
    }
    # §1 сводка: строки вида «| Файлов в поверхности | 36 |»
    table = dict(re.findall(r"\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|", text))
    checks = [
        ("Файлов в поверхности", expected["files"]),
        ("Паттернов (вхождений)", expected["pattern_count"]),
        ("Уникальных имён паттернов", expected["unique_names"]),
        ("Конфиг-блоков верхнего уровня с env", expected["config_blocks"]),
        ("Паттернов-источников всего", expected["source_patterns"]),
        ("env/env_or-читатели (имена)", expected["env_readers"]),
        ("Паттернов-стоков (уникальных имён)", expected["sink_patterns"]),
        ("HTTP-маршрутов serve", expected["routes"]),
        ("Транзитивных потоков источник→сток", expected["flows"]),
        ("Прямых рёбер «источник→сток»", expected["direct_edges"]),
        ("Швов — источников, чьё значение достигает стока в ДРУГОМ теле", expected["seams"]),
        ("Интра-процедурных потоков", expected["intra"]),
    ]
    for label, value in checks:
        # ячейка может нести уточнение в скобках — матчим по префиксу подписи
        got = next((v for k, v in table.items() if k.startswith(label)), None)
        assert got == str(value), (
            f"число §1 «{label}» в доке = {got}, живой скан = {value} — "
            f"регенерируй инвентарь (docs/office/interproc_inventory.md §8)")


def test_c3_canonical_seams_anchored_in_doc():
    mod = _load_scanner()
    d = mod.scan()
    text = open(DOC, encoding="utf-8").read()
    for seam, var in (
        ("TgToken", "TELEGRAM_BOT_TOKEN"),
        ("TavilyKey", "TAVILY_API_KEY"),
        ("AvKey", "ALPHAVANTAGE_API_KEY"),
        ("ArchiveChannelId", "TELEGRAM_ARCHIVE_CHANNEL_ID"),
        ("RenderUrl", "RENDER_URL"),
        ("OwnerTelegramId", "OWNER_TELEGRAM_ID"),
    ):
        ents = d["source_patterns"].get(seam)
        assert ents, f"канонический шов {seam} исчез из живого кода — обнови инвентарь"
        anchor = f"dept/utils.mlog:{ents[0]['line']}"
        assert f"`{seam}`" in text and anchor in text, (
            f"шов {seam} с якорем {anchor} не описан в инвентаре")
        assert var in text


def test_c4_doc_env_reader_set_equals_live_scan():
    """Множество env-читателей в §2.1 равно живому скану — новый шов нельзя завести мимо инвентаря."""
    mod = _load_scanner()
    d = mod.scan()
    text = open(DOC, encoding="utf-8").read()
    # §2.1 — таблица между заголовком 2.1 и заголовком 2.2; имя — ПЕРВЫЙ бэктик строки
    m = re.search(r"### 2\.1 .*?\n(.*?)### 2\.2", text, re.S)
    assert m, "таблица §2.1 не найдена"
    doc_names = set()
    for row in m.group(1).splitlines():
        rm = re.match(r"\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|", row.strip())
        if rm:
            doc_names.add(rm.group(1))
    live_names = set(d["env_readers"])
    missing = sorted(live_names - doc_names)
    stale = sorted(doc_names - live_names)
    assert not missing, (
        f"env-читатели без инвентарной записи (новые швы?): {missing} — "
        f"регенерируй §2 (scripts/n717_inventory_scan.py --md)")
    assert not stale, f"в инвентаре призраки (удалённые читатели): {stale}"


def test_c5_doc_sink_set_equals_live_scan():
    mod = _load_scanner()
    d = mod.scan()
    text = open(DOC, encoding="utf-8").read()
    m = re.search(r"### 2\.4 .*?\n(.*?)### 2\.5", text, re.S)
    assert m, "таблица §2.4 не найдена"
    doc_names = set()
    for row in m.group(1).splitlines():
        rm = re.match(r"\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|", row.strip())
        if rm:
            doc_names.add(rm.group(1))
    live_names = set(d["sink_patterns"])
    missing = sorted(live_names - doc_names)
    stale = sorted(doc_names - live_names)
    assert not missing, f"стоки без инвентарной записи: {missing} — регенерируй §2"
    assert not stale, f"в инвентаре стоки-призраки: {stale}"


def test_c6_scanner_selfcheck_summary_runs():
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "n717_inventory_scan.py")],
        capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr[:400]
    assert "потоков источник→сток" in proc.stdout
