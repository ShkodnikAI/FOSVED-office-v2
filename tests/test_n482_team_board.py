#!/usr/bin/env python3
"""Гвард TEAM-3 (#482): доска находок — DDL, публикация, подписки, перевод inject.

Статика + sqlite-валидность (по образцу test_fo376_ddl_pack):
1. DDL team_board в InitDB (app.mlog): исполняем на in-memory sqlite, колонки наряда.
2. team.mlog: TeamPublish redact'ит все входные строки, дедуп (from, topic, день),
   честный отказ на чужом kind; реестр подписок покрывает отделы.
3. Контексты: TeamBoardBlock в BuildContext (context.mlog), BuildExpertContext,
   BuildLZContext, BuildOSPContext — секция «=== Доска команды ===» с подписью источника.
4. Перевод inject: InjectContext → TeamBoardInsert("owner", …), GetInjectedContext —
   one-shot (delivered=1), ячейки kv "inject:" больше нет.
5. Публикации: оба LZ-реферала и OSPForecast пишут на доску.
6. Mini App: action "board"; /admin: ветка board + TeamBoardAdminLine.
Запуск: python -m pytest tests/test_n482_team_board.py -v
"""
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
TEAM = (REPO_ROOT / "dept" / "team.mlog").read_text(encoding="utf-8")
CONTEXT = (REPO_ROOT / "dept" / "context.mlog").read_text(encoding="utf-8")
EXPERT = (REPO_ROOT / "dept" / "expert.mlog").read_text(encoding="utf-8")
OSP = (REPO_ROOT / "dept" / "osp.mlog").read_text(encoding="utf-8")
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")
MINIAPP = (REPO_ROOT / "dept" / "miniapp.mlog").read_text(encoding="utf-8")

BOARD_DDL = re.search(r'CREATE TABLE IF NOT EXISTS team_board \((.*)\)"', APP).group(1)


def test_ddl_team_board_executable_and_columns():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE IF NOT EXISTS team_board (" + BOARD_DDL + ")")
    cols = {r[1] for r in con.execute("PRAGMA table_info(team_board)")}
    for c in ["id", "from_dept", "kind", "topic", "tags", "payload", "sources",
              "severity", "delivered", "created_at", "expires_at"]:
        assert c in cols, f"колонка {c} отсутствует в team_board"
    con.execute("INSERT INTO team_board (from_dept, kind, topic, tags, payload, sources, expires_at) "
                "VALUES ('lz','alert','т','[]','п','','2026-01-01')")
    con.execute("DELETE FROM team_board WHERE expires_at < datetime('now')")
    con.close()


def test_kind_whitelist_five_types():
    assert 'json_encode(["fact", "alert", "forecast", "decision", "risk"])' in TEAM
    assert "refused: unknown kind" in TEAM, "честный отказ на чужом kind"


def test_publish_redacts_all_inputs():
    body = TEAM[TEAM.index("pattern TeamPublish("):]
    body = body[:body.index("\n}\n") + 3]
    n_redact = len(re.findall(r"redact\(to_string\(", body))
    assert n_redact >= 4, f"TeamPublish redact'ит входные строки (найдено {n_redact})"
    assert "date(created_at) = date('now')" in TEAM, "дедуп по (from, topic, день)"


def test_subscriptions_registry_covers_depts():
    registry = TEAM[TEAM.index("pattern TeamBoardSubscriptions"):]
    assert len(re.findall(r"\{dept: \"", registry)) >= 10, "реестр подписок покрывает отделы"


def test_board_block_in_all_context_builders():
    assert "TeamBoardBlock(dept)" in CONTEXT, "BuildContext (все отделы HandleDeptQuery)"
    assert 'TeamBoardBlock("expert")' in EXPERT
    assert 'TeamBoardBlock("osp")' in OSP
    assert 'TeamBoardBlock("lz")' in LZ
    assert "=== Доска команды ===" in TEAM, "секция с подписью источника"


def test_inject_translated_to_board():
    seg = APP[APP.index("pattern InjectContext("):APP.index("pattern SteerDept(")]
    assert 'TeamBoardInsert("owner"' in seg, "InjectContext публикует на доску от owner"
    assert 'kv_get("inject:' not in seg, "ячейка KV inject:<dept> выведена"
    assert "delivered = 1" in seg, "one-shot чтение инъекций (delivered=1)"


def test_lz_and_osp_publications():
    assert LZ.count('TeamPublish("lz", "alert"') >= 2, "оба LZ-реферала публикуют алерты"
    assert 'TeamPublish("osp", "forecast"' in OSP, "прогнозы ОСП на доске"


def test_miniapp_and_admin_visibility():
    assert 'action == "board"' in MINIAPP, "экран Mini App"
    assert 'if query == "board"' in APP and "TeamBoardAdminLine" in APP, "/admin board"
