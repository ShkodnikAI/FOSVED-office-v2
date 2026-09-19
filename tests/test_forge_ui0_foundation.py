#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-0 tests (#193): фундамент дизайн-системы «FOSVED».

Гварды по чек-листу наряда (проверяемые статически):
- Poppins подключён и реально используется (body literal, --f);
- точные токены тёмной темы из наряда;
- точные токены светлой темы + data-theme="light";
- старые бумажно-штамповые токены отсутствуют;
- тумблер темы: разметка + toggleTheme + localStorage restore/save;
- Newsreader выведен.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = (REPO_ROOT / "miniapp" / "index.html").read_text(encoding="utf-8")


def test_poppins_linked_and_used():
    assert "family=Poppins:wght@400;500;600;700;800" in INDEX
    assert "display=swap" in INDEX
    assert "font-family:'Poppins',system-ui,sans-serif" in INDEX  # body (A.6)
    assert "--f:'Poppins'" in INDEX
    assert "Newsreader" not in INDEX  # A.4: старый шрифт выведен


def test_dark_tokens_exact():
    for tok in ("--bg:#0A0A0C", "--surface:#151517", "--surface2:#1C1C1F",
                "--line:#232326", "--red:#E8262E", "--red-dark:#B4151C",
                "--ink:#EDEDED", "--muted:#8A8A8F", "--green:#7ED957",
                "--yellow:#F5C93E", "--nav-inactive:#6B6B70",
                "--nav-active:#FF4B52", "--red-light:#FF8A8F"):
        assert tok in INDEX, tok


def test_light_tokens_exact():
    assert 'data-theme="light"' in INDEX
    for tok in ("--bg:#F5F3F0", "--surface:#FFFFFF", "--surface2:#ECEAE6",
                "--line:#E2DFDA", "--ink:#1A1A1C", "--muted:#75747A",
                "--green:#2E9A4E", "--yellow:#B4820F", "--nav-inactive:#A3A2A8",
                "--nav-active:#E8262E", "--red-light:#B4151C"):
        assert tok in INDEX, tok


def test_old_dispatch_tokens_gone():
    assert "--paper" not in INDEX
    assert "--stamp" not in INDEX


def test_theme_toggle_marked_and_persistent():
    assert 'id="themeToggle"' in INDEX
    assert "toggleTheme()" in INDEX
    assert "localStorage.getItem('theme')" in INDEX
    assert "localStorage.setItem('theme'" in INDEX
    assert "t || 'dark'" in INDEX  # дефолт тёмная
