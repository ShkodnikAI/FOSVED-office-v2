#!/usr/bin/env python3
"""Наряд #447 [P1][ARCH] — гвард единственного источника текста промпта отдела.

Класс бага (аудит 2026-09-30): departments/<dept>.md и library/<dept>.md
различаются во всех парах, контракт «кто что определяет» нигде не закреплён.

ADR-0013: departments/<dept>.md = ТОЛЬКО машинная декларация (frontmatter),
текст промпта — один, в library/<dept>.md (секция «## Системный промпт»),
декларация ссылается директивой @include. Дублирующий текст в декларации =
падение (расхождение полей структурно исключено).
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n447-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy import departments  # noqa: E402
from proxy.departments import (  # noqa: E402
    INCLUDE_PREFIX, PROMPT_SECTION_HEADER, DepartmentsConfigError,
    load_all, load_declaration, prompt_for, extract_prompt_section,
)

DECLS = load_all()  # реальный контур: ошибка загрузки = падение сбора
DEPT_NAMES = sorted(DECLS)
LIBRARY_DIR = REPO_ROOT / "library"


# ── A.1: пары существуют, контракт зафиксирован ─────────────────────────────

def test_all_14_depts_have_declarations():
    assert set(DEPT_NAMES) == {"yana", "osp", "lz", "expert", "marketing", "finance",
                               "legal", "dev", "design", "qa", "visual",
                               "engineering", "kavalnya", "admin"}


def test_every_declaration_has_library_counterpart():
    for dept in DEPT_NAMES:
        assert (LIBRARY_DIR / f"{dept}.md").exists(), (
            f"{dept}: departments есть, library/<dept>.md нет — единый источник сломан"
        )


# ── A.2: декларация = frontmatter + директива, текст один ───────────────────

def test_declaration_body_is_include_directive_only():
    """Дублирующий текст промпта в departments/<dept>.md = два источника = падение."""
    for dept in DEPT_NAMES:
        dpath = REPO_ROOT / "departments" / f"{dept}.md"
        text = dpath.read_text(encoding="utf-8")
        end = text.find("\n---", 3)
        body = text[end + 4:].strip() if end != -1 else text.strip()
        assert body.startswith(INCLUDE_PREFIX), (
            f"{dept}: тело декларации не @include-директива — текст промпта дублируется"
        )
        target = body[len(INCLUDE_PREFIX):].strip()
        assert target == f"library/{dept}.md", (
            f"{dept}: @include указывает на {target!r}, ожидается library/{dept}.md"
        )


def test_library_has_prompt_section():
    for dept in DEPT_NAMES:
        lpath = LIBRARY_DIR / f"{dept}.md"
        text = lpath.read_text(encoding="utf-8")
        assert PROMPT_SECTION_HEADER in text, (
            f"{dept}: в library нет секции «{PROMPT_SECTION_HEADER}» — нет единого источника"
        )


def test_prompt_for_resolves_from_library():
    """prompt_for обязан возвращать секцию из library, а не тело декларации."""
    for dept in DEPT_NAMES:
        ltext = (LIBRARY_DIR / f"{dept}.md").read_text(encoding="utf-8")
        assert prompt_for(dept) == extract_prompt_section(ltext), (
            f"{dept}: prompt_for не совпадает с секцией library — резолв сломан"
        )


# ── A.2: нулевой поведенческий дрейф (миграция 1-в-1) ───────────────────────

def test_prompts_verbatim_condensed_unchanged():
    from proxy.core import CONDENSED_PROMPTS
    for dept, expected in CONDENSED_PROMPTS.items():
        assert prompt_for(dept).rstrip() == expected.rstrip(), (
            f"{dept}: текст промпта изменился при миграции (#447 обязан быть 1-в-1)"
        )


# ── Механика резолва: громкие ошибки ────────────────────────────────────────

def test_include_missing_target_loud():
    d = load_declaration("admin")
    # легаси-путь (тело без директивы) обратно совместим
    assert d["prompt"]
    with pytest.raises(DepartmentsConfigError):
        extract_prompt_section("нет секции тут", source="x")


def test_include_path_traversal_forbidden():
    (departments.DEPARTMENTS_DIR / "evil.md").write_text(
        "---\nmode: primary\n---\n@include:../secrets/keys.md", encoding="utf-8"
    )
    departments._cache["version"] = 0
    try:
        with pytest.raises(DepartmentsConfigError):
            load_declaration("evil")
    finally:
        (departments.DEPARTMENTS_DIR / "evil.md").unlink(missing_ok=True)
        departments._cache["version"] = 0


def test_include_missing_file_loud():
    (departments.DEPARTMENTS_DIR / "ghost_inc.md").write_text(
        "---\nmode: primary\n---\n@include:library/no_such_file.md", encoding="utf-8"
    )
    departments._cache["version"] = 0
    try:
        with pytest.raises(DepartmentsConfigError):
            load_declaration("ghost_inc")
    finally:
        (departments.DEPARTMENTS_DIR / "ghost_inc.md").unlink(missing_ok=True)
        departments._cache["version"] = 0


def test_library_mtime_invalidates_cache(tmp_path, monkeypatch):
    """Правка текста в library/<dept>.md обязана сбрасывать кэш деклараций."""
    import time
    lib = REPO_ROOT / "library"
    target = lib / "admin.md"
    old = target.read_text(encoding="utf-8")
    try:
        time.sleep(1.1)  # mtime зернистость — секунды
        target.write_text(old + "\n<!-- n447 cache probe -->\n", encoding="utf-8")
        v1 = departments._mtime_version()
        time.sleep(1.1)
        target.write_text(old, encoding="utf-8")
        v2 = departments._mtime_version()
        assert v1 != v2, "mtime library не входит в версию кэша — правка текста не подхватится"
    finally:
        target.write_text(old, encoding="utf-8")
