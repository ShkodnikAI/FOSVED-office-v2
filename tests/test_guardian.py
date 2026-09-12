"""FO-015 tests: Guardian permission-matrix — last-match-wins, двойной контур,
ask-flow (Раз/Всегда/Нет), session-approvals, shell-парсер, seed-инвариант SG-F3."""
import json
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
from proxy import guardian  # noqa: E402
from proxy.guardian import (  # noqa: E402
    GuardianDenied, add_rule, remove_rule, approve_session, reset_session,
    check, enforce, match_action, rules_for, visible_tools, shell_permission,
)


@pytest.fixture(autouse=True)
def _clean_rules():
    """Чистый overlay на каждый тест (база из guardian_base.json остаётся)."""
    llm_proxy._query("DELETE FROM guardian_rules", fetch=False)
    reset_session()
    yield
    llm_proxy._query("DELETE FROM guardian_rules", fetch=False)
    reset_session()


def _audit_count(action):
    rows = llm_proxy._query("SELECT COUNT(*) as c FROM audit_log WHERE action=?", [action], fetch=True)
    return rows[0]["c"] if rows else 0


class TestEngine:
    def test_base_deny_web_search_sg_f3(self):
        """Инвариант SG-F3: web/search запрещён у всех департаментов до явного решения владельца."""
        for dept in ("dev", "lz", "osp", "marketing", "yana"):
            assert check(dept, "http_post", _ask=False)["verdict"] == "deny"
            assert check(dept, "web_search", _ask=False)["verdict"] == "deny"
            assert check(dept, "tavily_search", _ask=False)["verdict"] == "deny"

    def test_default_allow_for_unknown(self):
        assert check("dev", "db_query", _ask=False)["verdict"] == "allow"

    def test_wildcard_and_last_match_wins(self):
        add_rule("dev", "mcp__*", "deny", source="test")
        assert check("dev", "mcp__github__push", _ask=False)["verdict"] == "deny"
        # более позднее правило перекрывает (last-match-wins)
        add_rule("dev", "mcp__github__*", "allow", source="test")
        assert check("dev", "mcp__github__push", _ask=False)["verdict"] == "allow"
        # но прочие mcp остаются deny
        assert check("dev", "mcp__slack__post", _ask=False)["verdict"] == "deny"

    def test_dept_rule_does_not_leak_to_other_dept(self):
        add_rule("dev", "http_*", "allow", source="test")
        assert check("dev", "http_get", _ask=False)["verdict"] == "allow"
        assert check("qa", "http_get", _ask=False)["verdict"] == "deny"

    def test_overlay_order_by_insertion(self):
        add_rule("qa", "tool_x", "allow", source="test")
        add_rule("qa", "tool_x", "deny", source="test")
        assert check("qa", "tool_x", _ask=False)["verdict"] == "deny"

    def test_rule_changes_audited(self):
        before = _audit_count("guardian_rule_add") + _audit_count("guardian_rule_remove")
        add_rule("dev", "p1", "allow", source="test")
        remove_rule(llm_proxy._query("SELECT id FROM guardian_rules WHERE permission='p1'", fetch=True)[0]["id"])
        assert _audit_count("guardian_rule_add") + _audit_count("guardian_rule_remove") == before + 2


class TestTwoContours:
    def test_visible_tools_hides_deny(self):
        """1-й контур: deny скрывает тулзу из выдачи — агент её физически не видит."""
        tools = [{"name": "db_query"}, {"name": "http_post"}, {"name": "mcp__github__push"},
                 "shell_git_status", "tavily_search"]
        vis = visible_tools("dev", tools)
        names = [t if isinstance(t, str) else t["name"] for t in vis]
        assert "http_post" not in names and "tavily_search" not in names
        assert "db_query" in names and "mcp__github__push" in names

    def test_enforce_raises_on_deny(self):
        """2-й контур: прямой вызов запрещённого — отказ независимо от модели."""
        with pytest.raises(GuardianDenied):
            enforce("dev", "http_post")

    def test_enforce_allows_permitted(self):
        res = enforce("dev", "py_math_ceil")
        assert res["verdict"] == "allow"

    def test_deny_audited(self):
        before = _audit_count("guardian_deny")
        check("dev", "http_post", _ask=False)
        assert _audit_count("guardian_deny") == before + 1

    def test_call_python_endpoint_guardian_second_contour(self):
        """call-python: deny на py-модуль гасит вызов 403 даже до whitelist-логики."""
        add_rule("dev", "py_os_*", "deny", source="test")
        client = llm_proxy.app.test_client()
        resp = client.post("/call-python", json={"module": "os", "function": "getcwd",
                                                 "args": [], "dept": "dev"})
        assert resp.status_code == 403
        assert "Guardian" in resp.get_json()["error"]


class TestAskFlow:
    def test_ask_sends_telegram_and_denies_until_answer(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(guardian, "_tg_send_message",
                            lambda cid, text, parse_mode=None, reply_markup=None:
                            sent.update({"chat_id": cid, "text": text, "kb": reply_markup}) or {"ok": True})
        add_rule("dev", "shell_git*", "ask", source="test")
        res = check("dev", "shell_git_status", chat_id="42")
        assert res["verdict"] == "deny" and res.get("ask_id")
        kb = json.dumps(sent["kb"], ensure_ascii=False)
        assert "Раз" in kb and "Всегда" in kb and "Нет" in kb

        # «Раз» → allow одноразовый
        res2 = guardian.answer_ask(res["ask_id"], "once")
        assert res2["verdict"] == "allow"
        # «Всегда» живёт в session-approved
        add_rule("qa", "shell_docker*", "ask", source="test")
        res3 = check("qa", "shell_docker_ps", chat_id="42")
        res4 = guardian.answer_ask(res3["ask_id"], "always")
        assert res4["verdict"] == "allow"
        assert check("qa", "shell_docker_ps", _ask=False)["verdict"] == "allow"

    def test_always_does_not_survive_process_restart(self, monkeypatch):
        """«Всегда» переживает рестарт задачи, но не деплой: reset_session() стирает."""
        monkeypatch.setattr(guardian, "_tg_send_message",
                            lambda cid, text, parse_mode=None, reply_markup=None: {"ok": True})
        add_rule("dev", "shell_make*", "ask", source="test")
        ask = check("dev", "shell_make_build", chat_id="42")
        guardian.answer_ask(ask["ask_id"], "always")
        assert check("dev", "shell_make_build", _ask=False)["verdict"] == "allow"
        reset_session()  # = рестарт процесса/деплой
        assert check("dev", "shell_make_build", _ask=False)["verdict"] == "deny"

    def test_answers_audited(self, monkeypatch):
        monkeypatch.setattr(guardian, "_tg_send_message",
                            lambda cid, text, parse_mode=None, reply_markup=None: {"ok": True})
        add_rule("dev", "shell_curl*", "ask", source="test")
        ask = check("dev", "shell_curl_localhost", chat_id="42")
        before = _audit_count("guardian_ask_answer")
        guardian.answer_ask(ask["ask_id"], "deny")
        assert _audit_count("guardian_ask_answer") == before + 1
        assert check("dev", "shell_curl_localhost", _ask=False)["verdict"] == "deny"


class TestShellParsing:
    def test_git_status(self):
        assert shell_permission("git status --porcelain") == "shell_git_status"

    def test_path_stripped(self):
        assert shell_permission("/usr/bin/rm -rf /") == "shell_rm"

    def test_empty_and_garbage(self):
        assert shell_permission("") == "shell_empty"
        assert shell_permission("  ") == "shell_empty"

    def test_shell_rule_integration(self):
        add_rule("dev", "shell_git*", "ask", source="test")
        assert match_action("dev", shell_permission("git push origin main"))[0] == "ask"


class TestSeedAndSchema:
    def test_seed_idempotent(self):
        guardian.seed_from_base()
        n1 = len(llm_proxy._query("SELECT id FROM guardian_rules", fetch=True))
        guardian.seed_from_base()
        n2 = len(llm_proxy._query("SELECT id FROM guardian_rules", fetch=True))
        assert n1 == n2 and n1 > 0  # повторный seed ничего не добавляет

    def test_base_config_versioned_in_repo(self):
        assert guardian._base_config_path().exists()
        cfg = json.loads(guardian._base_config_path().read_text(encoding="utf-8"))
        assert cfg["default_action"] in ("allow", "ask", "deny")
        perms = [r["permission"] for r in cfg["rules"]]
        assert "http_*" in perms and "mcp__github__*" in perms
