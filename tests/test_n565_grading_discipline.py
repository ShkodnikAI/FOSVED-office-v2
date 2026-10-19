#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #565: гварды источника — гигиена измерений ЛЗ.

Живые проверки — батарея test_n565v3.mlog (19 проверок, CI-джоба
«v3 battery»); этот файл держит инварианты ИСТОЧНИКА (конвенция
test_n556_lz_data_integrity.py).

A.1 — prediction_keys: ключ в момент предсказания, ретроактивные запрещены;
A.2 — grading_runs: сводная цифра производна от raw (JSONL);
A.3 — честный LZRecalibrate: без ключей «нечем калибровать», не accuracy;
A.4 — дубликат «Метрики» в уставе удалён;
A.5 — caveats-дисциплина: число без n и ограничений не публикуется.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
LZMD = (REPO_ROOT / "library" / "lz.md").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _code_lines(text):
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def test_a1_prediction_keys_written_at_prediction_time():
    code = _code_lines(LZ)
    # таблица есть в фактической схеме и в inline-DDL (AGENTS.md §1)
    assert "CREATE TABLE IF NOT EXISTS prediction_keys" in APP
    assert "// CREATE TABLE prediction_keys (" in LZ
    # три писателя — в момент предсказания, alongside результата
    assert "INSERT INTO prediction_keys (artifact_id, kind, claim, verify_source, due_at) VALUES (?, 'disruption_score'" in code
    assert "INSERT INTO prediction_keys (artifact_id, kind, claim, verify_source, due_at) VALUES (?, 'hype_stage'" in code
    assert "INSERT INTO prediction_keys (artifact_id, kind, claim, verify_source, due_at) VALUES (?, 'inflection'" in code
    # ретроактивные ключи запрещены — фиксация в inline-DDL источника
    assert "ретроактивные ключи запрещены" in LZ
    # грейдеры с rule-провенансом (формат grader по #553)
    assert "pattern LZGradeKey(key_id: Float, artifact_id: Float, kind: String, claim: String) -> String" in LZ
    assert '"rule:linear-half-range"' in LZ and '"rule:stage-equality"' in LZ and '"rule:inflection-status"' in LZ


def test_a2_grading_runs_raw_derived_summary():
    assert "CREATE TABLE IF NOT EXISTS grading_runs" in APP
    assert "// CREATE TABLE grading_runs (" in LZ
    # каждый прогон журналируется
    assert "pattern LZGradingRunLog(metric: String, n: Float, raw: String, caveats: String) -> Float" in LZ
    # сводка считается ИЗ raw-строк, не из промежуточных значений
    assert "pattern LZSummaryFromRaw(raw: String) -> String" in LZ
    body = LZ[LZ.index("pattern LZSummaryFromRaw"):]
    body = body[:body.index("\n}")]
    assert 'parse_json' in body and 'split(raw' in body
    # ad-hoc пересчёты в выводах запрещены — фиксация в источнике
    assert "ad-hoc" in LZ


def test_a3_honest_recalibrate_no_fabricated_accuracy():
    code = _code_lines(LZ)
    # старый промпт «Compute accuracy rate» удалён ИЗ КОДА (в комментарии —
    # история удаления; кодовая строка вызова call_llm с этим текстом отсутствует)
    assert 'call_llm("Recalibrate all tracked technologies' not in code
    # честный ответ при пустых ключах
    assert "Нечем калибровать: ключей предсказаний — 0" in LZ
    assert "Нечем калибровать: ключей предсказаний — " in LZ
    # грейдинг только по prediction_keys, только наступившее окно
    assert "FROM prediction_keys WHERE status = 'pending' AND due_at IS NOT NULL AND due_at <= datetime('now')" in LZ
    # вывод содержит caveats (A.5)
    assert "caveats: rule grader" in LZ


def test_a4_charter_single_metrics_section():
    assert LZMD.count("## Метрики") == 1
    # формулировки метрик не менялись (запрет наряда)
    assert "**Disruption accuracy** — tracked technologies материализовались как ожидалось" in LZMD
    assert "**Investment lead time** — раньше mass market" in LZMD


def test_a5_caveats_discipline():
    # каждый прогон — caveats непустые; вывод содержит n и ограничения
    assert "caveats TEXT" in APP
    assert 'caveats = ?' in LZ
    # errata-колонка журнала (по образцу leanrea bench)
    assert "grader_errata TEXT" in APP


def test_battery_in_ci_loop():
    assert "test_n565v3.mlog" in CI
    assert "for f in test_forge{1..9}v3.mlog test_narad{1..3}v3.mlog test_n550v3.mlog test_n553v3.mlog test_n556v3.mlog test_n565v3.mlog test_n566v3.mlog" in CI
