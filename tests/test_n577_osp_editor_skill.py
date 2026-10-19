#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #577: гварды редакторского скилла OSP (skills/osp-editor-ru/SKILL.md).

A.1 — файл существует, frontmatter валиден, атрибуция MIT;
A.2 — чеклист покрывает все 5 классов атомов (числа/URL/код/ссылки/оговорки);
A.3 — двухколейность в шапке;
Тест 3 наряда — запрещённые обещания («обход детектора», «100% человечность»,
undetectable) — 0 вхождений.

Стиль по конвенции test_n566/test_n383: якорные проверки по файлам репо.
Smoke «числа/цитаты/ссылки побайтово не изменились» на примере апстрима —
процедурный, выполняется исполнителем на клоне источника (отчёт наряда),
в CI не переносится: примеры источника вне git.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO_ROOT / "skills" / "osp-editor-ru" / "SKILL.md"
SKILL = SKILL_PATH.read_text(encoding="utf-8")


def test_a1_file_and_frontmatter():
    assert SKILL_PATH.is_file(), "skills/osp-editor-ru/SKILL.md отсутствует"
    assert "name: osp-editor-ru" in SKILL
    # frontmatter до первого заголовка тела
    assert SKILL.lstrip().startswith("---"), "нет frontmatter"
    assert "description:" in SKILL.split("---")[1], "frontmatter без description"


def test_a1_attribution_mit():
    assert "IT-Shelter-Labs/Shelter-Humanizer" in SKILL, "нет атрибуции источника"
    assert "MIT" in SKILL, "нет лицензии источника"


def test_a3_two_lane_boundary():
    assert "только" in SKILL and "никогда" in SKILL
    assert "машиночитаемым артефактам" in SKILL, "двухколейность: машинный слой не назван"
    assert "файл:строка" in SKILL, "двухколейность: якоря файл:строка не названы"


def test_a1_invariants_and_anti_injection():
    assert "Сохраняй факты, имена, названия, числа с единицами, сроки и ссылки" in SKILL
    assert "материал, а не инструкции" in SKILL, "нет анти-инъекции"
    assert "не исправляй её молча" in SKILL, "нет запрета молчаливых правок"


def test_a2_checklist_five_atom_classes():
    assert "Числа с единицами" in SKILL
    assert "URL и email" in SKILL
    assert "Код и команды" in SKILL
    assert "Markdown-ссылки и цитаты" in SKILL
    assert "Оговорки" in SKILL
    # репрезентативные единицы и оговорки из protection.py источника
    assert "млрд" in SKILL and "°C" in SKILL
    assert "примерно" in SKILL and "вероятно" in SKILL
    # честный дисклеймер источника перенесён
    assert "не смысловую эквивалентность" in SKILL


def test_naryad3_no_forbidden_promises():
    forbidden = ["обход детектор", "100% человечн", "undetectable"]
    low = SKILL.lower()
    hits = [s for s in forbidden if s in low]
    assert not hits, f"запрещённые обещания найдены: {hits}"
