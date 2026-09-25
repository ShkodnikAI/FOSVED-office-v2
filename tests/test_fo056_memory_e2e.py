#!/usr/bin/env python3
"""FO-056 (office#373): memory E2E dogfood офисного пути на боевом бинаре.

Цепочка наряда (аудит 24.09, P1-1): memory_put (ttl/priority) → recall с
consent ([MEM]-провенанс) → негатив: recall БЕЗ consent на private
(memory.recall.denied) → derive → forget dry_run=true (preview, ничего не
уничтожено) → forget apply с грантом (грантconsumed on success) → чтение
derived-ключа → MEMORY_POISONED (не silent empty) → ttl-expiry sweep →
retain-ttl → ledger_export + ledger_verify (структурный вердикт).

Негативные ветки (мутационное расширение офисного пути) несут origin-stamped
коды (ADR-0169): MEMORY_RECALL_CONSENT_REQUIRED / GRANT_SCOPE_MISMATCH /
MEMORY_FORGET_CONSENT_REQUIRED / MEMORY_POISONED. Каждая — с ledger-записью.

Сценарий: test_memory_fo056.mlog (16 меток PASS/FAILED, конвенция
test_naryad366.mlog). Запуск локально:
    python -m pytest tests/test_fo056_memory_e2e.py -v
(cwd = корень репо; бинарь ./bin/mlog; ledger-экспорт в data/fo056_ledger.jsonl
— data/ в .gitignore).

Находки 0.24.0 для отчёта PR (языковые дефекты — отдельный наряд в Metalogos-):
1) отказ grant-лестницы (GRANT_SCOPE_MISMATCH) не классифицируется через try
   в стабильный код — r.error.code == "RUNTIME_ERROR", штамп живёт в message;
2) memory_retained видит только пины (memory_retain), TTL-ключи в списке не
   видны (факт memory.retain_ttl верифицируется по JSONL);
3) ledger_verify: anchored_start == false на свежем экспорте при ok == true
   (первая запись цепочки — генезис без якоря предыдущей).
"""
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BINARY = REPO_ROOT / "bin" / "mlog"
SCENARIO = REPO_ROOT / "test_memory_fo056.mlog"
LEDGER = REPO_ROOT / "data" / "fo056_ledger.jsonl"

MARKS = [
    "m01_put_read_public",
    "m02_keys_after_put",
    "m05_derive_provenance",
    "m03_recall_denied_private",
    "m04_recall_hit_mem_provenance",
    "m06_forget_grant_scope_mismatch",
    "m07_forget_consent_required",
    "m08_forget_dry_run_preview",
    "m08b_dry_run_no_state_change",
    "m09_forget_apply",
    "m09b_keys_after_apply",
    "m10_poisoned_read_refused",
    "m11_ttl_expired_sweep",
    "m12_retain_ttl_live",
    "m13_retain_ttl_poisoned_refused",
    "m14_ledger_verify_ok",
]

# Каждый шаг E2E-цепочки обязан оставить подписанную запись (ADR-0167).
EXPECTED_ACTIONS = [
    "memory.open",
    "memory.put",
    "memory.read",
    "memory.recall",
    "memory.recall.denied",
    "memory.forget",
    "memory.forget.denied",
    "irreversible.memory_forget",
    "memory.ttl_expired",
    "memory.retain_ttl",
    "grant.issued",
    "grant.used",
]


def _run_scenario():
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    try:
        BINARY.chmod(0o755)  # в репо бинарь хранится 644; CI chmod-ает только mlog-check
    except OSError:
        pass
    return subprocess.run(
        [str(BINARY), "run", str(SCENARIO)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
    )


def test_scenario_all_marks_pass():
    """Живой прогон цепочки на боевом бинаре: 16/16 PASS, ни одной FAILED."""
    proc = _run_scenario()
    assert proc.returncode == 0, (
        f"бинарь упал: rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )
    out = proc.stdout
    for mark in MARKS:
        assert f"PASS {mark}" in out, f"нет PASS {mark}\n{out[-2000:]}"
    assert "FAILED" not in out, f"есть FAILED:\n{out}"


def test_ledger_chain_covers_memory_family():
    """Ledger-цепочка: каждый шаг E2E оставил запись; dry_run не тратит грант."""
    proc = _run_scenario()  # свежий экспорт — независимость от порядка тестов
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert LEDGER.exists(), "ledger_export не записал data/fo056_ledger.jsonl"
    actions = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            actions.append(json.loads(line).get("action", ""))
    for expected in EXPECTED_ACTIONS:
        assert expected in actions, (
            f"в ledger нет записи {expected}; есть: {sorted(set(actions))}"
        )
    # №280 preview-дисциплина: dry_run не потребляет грант.
    assert actions.count("grant.issued") > actions.count("grant.used"), (
        "грант тратится на dry_run — нарушение preview-дисциплины"
    )


def test_static_guards_no_silent_paths():
    """Статика: негативные ветки несут origin-stamped коды, верификация в языке."""
    code = SCENARIO.read_text(encoding="utf-8")
    for needle in [
        "MEMORY_RECALL_CONSENT_REQUIRED",
        "MEMORY_FORGET_CONSENT_REQUIRED",
        "MEMORY_POISONED",
        "GRANT_SCOPE_MISMATCH",
        "ledger_verify",
        "ledger_export",
    ]:
        assert needle in code, f"в сценарии нет {needle}"
