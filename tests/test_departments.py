"""FO-018 tests: декларативные департаменты — frontmatter-парсер, строгая валидация,
иерархия, {env:VAR}, миграция 1-в-1 (CONDENSED_PROMPTS), permission → Guardian-overlay."""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402
from proxy import departments  # noqa: E402
from proxy.departments import (  # noqa: E402
    DepartmentsConfigError, parse_frontmatter, validate_declaration,
    load_declaration, load_all, temperature_for, model_for, prompt_for,
    apply_guardian_overlays,
)


@pytest.fixture()
def tmp_dept(tmp_path, monkeypatch):
    """departments/ в tmp + чистый кэш."""
    monkeypatch.setattr(departments, "DEPARTMENTS_DIR", tmp_path)
    departments._cache["version"] = 0
    yield tmp_path
    departments._cache["version"] = 0


class TestParser:
    def test_scalars_and_body(self):
        fm, body = parse_frontmatter("---\nmodel: glm-4.5\ntemperature: 0.3\n---\nPROMPT", "t")
        assert fm["model"] == "glm-4.5" and fm["temperature"] == 0.3 and body == "PROMPT"

    def test_list_inline_and_block(self):
        fm, _ = parse_frontmatter("---\ntools: [a, b]\n---\nX", "t")
        assert fm["tools"] == ["a", "b"]
        fm2, _ = parse_frontmatter("---\ntools:\n  - a\n  - b\n---\nX", "t")
        assert fm2["tools"] == ["a", "b"]

    def test_permission_dict(self):
        fm, _ = parse_frontmatter("---\npermission:\n  http_*: deny\n  shell_git*: ask\n---\nP", "t")
        assert fm["permission"] == {"http_*": "deny", "shell_git*": "ask"}

    def test_unclosed_frontmatter_loud(self):
        with pytest.raises(DepartmentsConfigError):
            parse_frontmatter("---\nmodel: x\nBODY", "t")

    def test_env_substitution(self, monkeypatch):
        monkeypatch.setenv("FOO_MODEL", "glm-4.6")
        fm, _ = parse_frontmatter("---\nmodel: {env:FOO_MODEL}\n---\nB", "t")
        assert fm["model"] == "glm-4.6"

    def test_env_missing_loud(self, monkeypatch):
        monkeypatch.delenv("NOPE_VAR", raising=False)
        with pytest.raises(DepartmentsConfigError):
            parse_frontmatter("---\nmodel: {env:NOPE_VAR}\n---\nB", "t")


class TestValidation:
    def test_unknown_field_raises(self):
        with pytest.raises(DepartmentsConfigError, match="неизвестные поля"):
            validate_declaration("dev", {"model": "x", "bogus": 1}, "body", "s")

    def test_bad_action_raises(self):
        with pytest.raises(DepartmentsConfigError, match="allow|ask|deny"):
            validate_declaration("dev", {"permission": {"http_*": "maybe"}}, "b", "s")

    def test_bad_mode_raises(self):
        with pytest.raises(DepartmentsConfigError, match="mode"):
            validate_declaration("dev", {"mode": "chaos"}, "b", "s")

    def test_empty_body_raises(self):
        with pytest.raises(DepartmentsConfigError, match="пусто"):
            validate_declaration("dev", {}, "  ", "s")

    def test_load_all_propagates_loud_error(self, tmp_dept):
        (tmp_dept / "broken.md").write_text("---\nbogus_field: 1\n---\nbody", encoding="utf-8")
        with pytest.raises(DepartmentsConfigError):
            load_all()  # офис не поднимается


class TestHierarchyAndAccessors:
    def test_declaration_found(self, tmp_dept):
        (tmp_dept / "qa.md").write_text("---\ntemperature: 0.2\nmode: all\n---\nQA PROMPT", encoding="utf-8")
        d = load_declaration("qa")
        assert d["temperature"] == 0.2 and d["mode"] == "all" and d["prompt"] == "QA PROMPT"

    def test_missing_file_returns_none(self, tmp_dept):
        assert load_declaration("ghost") is None
        assert prompt_for("ghost") is None
        assert temperature_for("ghost") == 0.7  # прежний хардкод
        assert model_for("ghost") is None

    def test_temperature_default_matches_legacy_hardcode(self, tmp_dept):
        (tmp_dept / "dev.md").write_text("---\nmode: primary\n---\nB", encoding="utf-8")
        assert temperature_for("dev") == 0.7


class TestMigrationOneToOne:
    def test_all_14_depts_have_declarations(self):
        decls = load_all()
        assert set(decls) == {"yana", "osp", "lz", "expert", "marketing", "finance", "legal",
                              "dev", "design", "qa", "visual", "engineering", "kavalnya", "admin"}

    def test_prompts_are_verbatim_condensed(self):
        """Миграция без изменения поведения: тело декларации = CONDENSED_PROMPTS 1-в-1."""
        from proxy.core import CONDENSED_PROMPTS
        for dept, expected in CONDENSED_PROMPTS.items():
            actual = prompt_for(dept).rstrip()
            assert actual == expected.rstrip(), f"промпт {dept} изменился при миграции"

    def test_get_dept_prompt_uses_declaration(self):
        from proxy.core import get_dept_prompt, CONDENSED_PROMPTS, FORMAT_INSTRUCTION
        for dept in ("osp", "dev", "qa"):
            expected = CONDENSED_PROMPTS[dept].rstrip()
            assert get_dept_prompt(dept).rstrip() == expected
        # fmt-суффикс для аналитических не потерян
        from proxy.core import _ANALYTICAL_DEPTS
        for dept in _ANALYTICAL_DEPTS:
            assert get_dept_prompt(dept).endswith(FORMAT_INSTRUCTION)


class TestGuardianOverlay:
    def test_permission_flows_to_guardian(self, tmp_dept):
        from proxy import guardian
        llm_proxy._query("DELETE FROM guardian_rules WHERE source='frontmatter'", fetch=False)
        (tmp_dept / "dev.md").write_text(
            "---\npermission:\n  shell_git*: ask\n  mcp__github__*: allow\n---\nB", encoding="utf-8")
        n = apply_guardian_overlays()
        assert n == 2
        rows = llm_proxy._query("SELECT permission, action FROM guardian_rules WHERE dept='dev' AND source='frontmatter'",
                                fetch=True)
        got = {r["permission"]: r["action"] for r in rows}
        assert got == {"shell_git*": "ask", "mcp__github__*": "allow"}
        # идемпотентно
        assert apply_guardian_overlays() == 0
