#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #566: гварды источника — watchlist-категория «тонкие скиллы против
жирных tool-слоёв».

Живые проверки — батарея test_n566v3.mlog (12 проверок, CI-джоба
«v3 battery»); инварианты источника — по конвенции test_n556.

A.1 — seed-запись с осмысленным доменом (не auto), идемпотентная;
A.2 — досье с URL/датами, self-reported-пометками бенчмарка;
A.3 — индикаторная сетка 30/60/90/180, день 0, правило cooled;
A.4 — 2 подтверждения < 3: писателей disruption_alerts в коде нет.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
DOSSIER = (REPO_ROOT / "docs" / "departments" / "lz-watchlist-thin-skills.md").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _code_lines(text):
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))


def test_a1_seed_idempotent_meaningful_domain():
    code = _code_lines(LZ)
    assert "pattern LZWatchSeedCategory() -> String" in code
    assert "INSERT INTO watchlist_entries (topic, domain, status) SELECT 'thin-skills-vs-fat-tool-layers', 'Computational', 'active' WHERE NOT EXISTS (SELECT 1 FROM watchlist_entries WHERE topic = 'thin-skills-vs-fat-tool-layers')" in code
    # seed вызывается из InitDB — запись существует на любом старте прода
    assert "let _ = LZWatchSeedCategory()" in APP
    # домен Computational из «Технологии (10)» устава, не auto
    assert "Технологии (10)" in LZ


def test_a1_lab_watch_routes_wired():
    code = _code_lines(LZ)
    # устав library/lz.md:119 объявляет /lab-watch — роуты заведены
    assert 'starts_with(t, "/lab-watch add")' in code
    assert 'starts_with(t, "/lab-watch remove")' in code
    assert 'starts_with(t, "/lab-watch")' in code
    assert 'starts_with(text, "/lab-watch")' in APP
    # срезы за пробелом префикса: тема без ведущего пробела
    assert "substring(query, 15.0, 300.0)" in code
    assert "substring(query, 18.0, 300.0)" in code


def test_a4_no_alerts_before_three_confirmations():
    code = _code_lines(LZ + "\n" + APP)
    # 2 независимых подтверждения < 3 (устав lz.md:31): алерт не создаётся нигде
    assert "INSERT INTO disruption_alerts" not in code
    # правило третьего подтверждения зафиксировано в досье
    assert "library/lz.md:31" in DOSSIER


def test_a2_a3_dossier_complete():
    # seed-сигналы с [источник](URL) и датами
    assert "https://github.com/whiteguo233/OpenBiliClaw" in DOSSIER
    assert "https://github.com/aicodeking/leanrea" in DOSSIER
    assert "18.10.2026" in DOSSIER and "19.10.2026" in DOSSIER
    # бенчмарк self-reported — пометка честности (гигиена по духу #565)
    assert "self-reported" in DOSSIER
    assert "n=3" in DOSSIER
    # сетка iw-watchlist 30/60/90/180 с днём 0 и правилом cooled
    assert "30 дней" in DOSSIER and "60 дней" in DOSSIER and "90 дней" in DOSSIER and "180 дней" in DOSSIER
    assert "19.10.2026" in DOSSIER
    assert "cooled" in DOSSIER
    # как есть / как будет / границы / competing alternatives №7
    assert "Как есть" in DOSSIER and "Как будет" in DOSSIER and "Границы" in DOSSIER
    assert "Competing alternatives" in DOSSIER
    assert "deferred tool search" in DOSSIER
    # автотриггер ОСП при пороге
    assert "library/lz.md:153" in DOSSIER


def test_battery_in_ci_loop():
    assert "test_n566v3.mlog" in CI
    assert "for f in test_forge{1..9}v3.mlog test_narad{1..3}v3.mlog test_n550v3.mlog test_n553v3.mlog test_n556v3.mlog test_n565v3.mlog test_n566v3.mlog" in CI
