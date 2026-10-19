#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #559: гварды источника — метрики ЛЗ из собственных таблиц.

Живые проверки — батарея test_n559v3.mlog (18 проверок, CI-джоба
«v3 battery»); инварианты источника — по конвенции test_n556.

A.1 — outcome в disruption_alerts (confirmed|retracted|pending) + миграция;
A.1 — LZLabScore: FPR по разрешившимся, честные пометки «не хватает данных»;
A.2 — baseline в досье категории (первая точка калибровки);
Запреты — определения метрик устава не менялись, внешние данные не подтягиваются.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
LZMD = (REPO_ROOT / "library" / "lz.md").read_text(encoding="utf-8")
DOSSIER = (REPO_ROOT / "docs" / "departments" / "lz-watchlist-thin-skills.md").read_text(encoding="utf-8")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _code_lines(text):
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def test_a1_outcome_field_and_migration():
    # inline-DDL и фактическая схема не разошлись (AGENTS.md §1)
    assert "outcome TEXT DEFAULT 'pending'" in LZ
    # колонка появляется миграцией: CREATE-строка disruption_alerts без outcome
    create_line = next(l for l in APP.splitlines() if "CREATE TABLE IF NOT EXISTS disruption_alerts" in l)
    assert "outcome" not in create_line
    # миграция по конвенции TryVal+grant (без удаления данных)
    assert 'grant_issue("db:alter:disruption_alerts", 3600.0, "once"), "ALTER TABLE disruption_alerts ADD COLUMN outcome TEXT DEFAULT \'pending\'"' in APP


def test_a1_lab_score_implementation():
    code = _code_lines(LZ)
    assert "pattern LZLabScore() -> String" in code
    # FPR — по разрешившимся (outcome проставлен), pending не считаются
    assert "FROM disruption_alerts WHERE outcome IN ('retracted', 'confirmed')" in code
    # disruption_accuracy — из грейденных ключей #565, не из ниотчего
    assert "FROM prediction_keys WHERE status = 'graded'" in code
    # честные пометки вместо заглушек (Тест 2 наряда)
    assert "не хватает данных: разрешившихся алертов" in LZ
    assert "не хватает данных: дата первой публикации источником не фиксируется" in LZ
    assert "не хватает данных: индикаторная сетка категории вне БД" in LZ
    assert "не хватает данных: грейденных ключей предсказаний — 0" in LZ
    assert "не хватает данных: исходов cross-domain предсказаний" in LZ
    assert "не хватает данных: сверок с mass market" in LZ
    # caveats-дисциплина (#565 A.5) — в численных строках
    assert "caveats: автоподсчёт по outcome" in LZ
    assert "caveats: rule grader" in LZ
    # последний прогон — производные от raw (#565)
    assert "производны от raw, #565" in LZ


def test_no_external_data_and_charter_untouched():
    # формулировки метрик устава не менялись
    assert "**False positive rate** — преждевременные/ошибочные alerts" in LZMD
    assert LZMD.count("## Метрики") == 1
    # расчёт только из собственных таблиц офиса (запрет наряда)
    lab_body = LZ[LZ.index("pattern LZLabScore"):]
    lab_body = lab_body[:lab_body.index("\n}")]
    for forbidden in ("http_post", "http_get", "tavily", "call_llm"):
        assert forbidden.lower() not in lab_body.lower(), f"LZLabScore тянет внешнее: {forbidden}"


def test_routes_and_detector_and_readme():
    code = _code_lines(LZ + "\n" + APP)
    # устав library/lz.md:123 объявляет команды — роуты заведены
    assert 'starts_with(t, "/lab-score")' in code
    assert 'starts_with(t, "/lab-recalibrate")' in code
    assert 'starts_with(text, "/lab-score")' in APP
    assert 'starts_with(text, "/lab-recalibrate")' in APP
    assert "`/lab-score`" in README


def test_a2_baseline_in_dossier():
    # первая точка калибровки зафиксирована в досье категории
    assert "Baseline" in DOSSIER and "#559" in DOSSIER
    assert "не хватает данных" in DOSSIER
    assert "прод-прогон" in DOSSIER


def test_battery_in_ci_loop():
    assert "test_n559v3.mlog" in CI
    assert "for f in test_forge{1..9}v3.mlog test_narad{1..3}v3.mlog test_n550v3.mlog test_n553v3.mlog test_n556v3.mlog test_n565v3.mlog test_n566v3.mlog test_n559v3.mlog" in CI
