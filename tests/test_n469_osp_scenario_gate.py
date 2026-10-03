#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #469 (P1): методология ОСП — вероятности сценариев одной величины.

Два уровня проверки:
1. РЕАЛЬНОЕ ИСПОЛНЕНИЕ: test-блоки dept/osp.mlog (гейт, парсер, фильтр числа)
   прогоняются интерпретатором bin/mlog — subprocess в этом файле.
   Мутационные проверки (команды/вывод в отчёте PR, каждая валит минимум
   один test-блок):
   (1) снять проверку суммы 98–102% → инцидент-тест OSP-GOLD-01 валится;
   (2) снять попарную проверку пересечений → одноимённый тест валится;
   (3) снять фильтр формата вероятности → тест «нечисловая вероятность» валится.
2. СТАТИЧЕСКИЕ ГВАРДЫ (конвенция репо): гейт вызывается в OSPDeepAnalyze/
   OSPFullAnalyze после генерации; один повтор с текстом ошибки; повторный
   провал — пометка «не принят к верификации» и OSPDraftAnalysis не
   вызывается; методология library/osp.md содержит правила.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSP_MLOG_PATH = os.path.join(REPO_ROOT, "dept", "osp.mlog")
OSP_MLOG = open(OSP_MLOG_PATH, encoding="utf-8").read()
OSP_MD = open(os.path.join(REPO_ROOT, "library", "osp.md"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\ntest ", start + 10)
    return source[start:nxt]


# ── 1. Реальное исполнение test-блоков mlog ─────────────────────────────

def test_mlog_test_blocks_pass():
    mlog = os.path.join(REPO_ROOT, "bin", "mlog")
    assert os.path.exists(mlog), "интерпретатор bin/mlog обязан быть в репо"
    os.chmod(mlog, 0o755)
    proc = subprocess.run(
        [mlog, "test", OSP_MLOG_PATH],
        capture_output=True, text=True, timeout=300, cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, f"test-блоки osp.mlog упали:\n{proc.stdout}\n{proc.stderr}"
    # итоговая строка «N/N tests passed» пишет в stderr
    combined = proc.stdout + proc.stderr
    assert "tests passed" in combined, combined
    assert "0/0" not in combined, "test-блоки гейта должны реально исполняться"
    assert "❌" not in combined, combined


# ── 2. Гейт встроен в генерацию (Deep и Full) ───────────────────────────

@pytest.mark.parametrize("pattern_name,depth", [("OSPDeepAnalyze", "3"), ("OSPFullAnalyze", "4")])
def test_gate_wired_into_generation(pattern_name, depth):
    body = _pattern_body(OSP_MLOG, pattern_name)
    # первый прогон гейта после генерации
    assert "let gate1 = OSPScenarioGateCheck(reply)" in body
    # один повтор с текстом ошибки гейта
    assert body.index("let gate1 = OSPScenarioGateCheck(reply)") < body.index("ОТВЕРГНУТ ГЕЙТОМ КАЧЕСТВА")
    assert "call_llm(prompt_fix, query)" in body
    # финальный прогон и пометка при повторном провале
    assert "let gate = OSPScenarioGateCheck(reply)" in body
    assert "ПРОГНОЗ НЕ ПРИНЯТ К ВЕРИФИКАЦИИ" in body
    assert "вероятности не согласованы" in body
    # повтор только один: prompt_fix строится единожды
    assert body.count("ОТВЕРГНУТ ГЕЙТОМ КАЧЕСТВА") == 1


@pytest.mark.parametrize("pattern_name", ["OSPDeepAnalyze", "OSPFullAnalyze"])
def test_draft_skipped_when_not_accepted(pattern_name):
    body = _pattern_body(OSP_MLOG, pattern_name)
    # #469 A.3: запись прогноза (Brier) — только при согласованном распределении
    assert 'if not_accepted == "" then { let aid = OSPDraftAnalysis(' in body
    assert "scenario_gate=" in body, "гейт обязан попадать в audit-лог"
    idx_draft = body.index("OSPDraftAnalysis")
    idx_notacc = body.index("ПРОГНОЗ НЕ ПРИНЯТ К ВЕРИФИКАЦИИ")
    assert idx_notacc < idx_draft


def test_gate_is_pure_and_self_contained():
    body = _pattern_body(OSP_MLOG, "OSPScenarioGateCheck")
    # гейт не читает env/db/сеть — только разбор текста
    for forbidden in ("env(", "db_", "http_", "call_llm", "query("):
        assert forbidden not in body
    # числовой разбор через форматный фильтр (to_float на мусоре отдаёт 0.0 молча)
    assert "OSPStrIsNumber(" in body


def test_prompt_requires_consent_scenarios():
    # промпты Deep/Full требуют формат P= и сумму 100%
    for marker in ("P=<число>%", "сумма середин = 100%"):
        assert marker in _pattern_body(OSP_MLOG, "OSPDeepAnalyze")
        assert marker in _pattern_body(OSP_MLOG, "OSPFullAnalyze")


# ── 3. Методология library/osp.md ────────────────────────────────────────

def test_methodology_documented():
    for marker in (
        "Сценарии одной величины",
        "100% ±2",
        "≤15 п.п.",
        "метка К числу",
        "null-гипотеза",
        "OSPScenarioGateCheck",
        "ПРОГНОЗ НЕ ПРИНЯТ К ВЕРИФИКАЦИИ",
    ):
        assert marker in OSP_MD, f"методология обязана фиксировать: {marker}"


def test_sherman_kent_scale_untouched():
    # гвард #423: 12 гейтов ОСП не затронуты нарядом #469
    gates = _pattern_body(OSP_MLOG, "OSPCheckQualityGates")
    assert "g1_" in gates and "g12_noUncalib" in gates
    assert "g13" not in gates, "сценарный гейт — отдельный механизм, не 13-й гейт"
