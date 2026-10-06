#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #480 TEAM-1 (P0): ядро взаимодействия отделов.

ADR-0016: реестр навыков, бриф коллег, тихий режим, TeamConsult,
ограничители (глубина 1, бюджет на запрос, кэш 30 мин, аудит).
Сквозное подключение: ОСП → ЛЗ factpack вместо собственного Tavily
автоматического пути; /osp tavily остаётся прямым; гейт актуальности
#474 A.2 судит live-часть разведсводки.

Уровни гвардов:
1. dept/team.mlog существует, в import-замыкании app.mlog; паттерны
   ядра на месте; отказные строки честные; env-параметры бюджетов.
2. Реестр — единственный источник объявлений: 14 отделов, lz/factpack
   единственный включённый навык (TEAM-1 не подключает отделы).
3. Тихий режим по построению у factpack: нет call_llm, нет записей в
   диалог, нет Telegram; транспорт Tavily общий (office#354).
4. Интеграция ОСП: сброс бюджета в HandleOSP, консультация в
   BuildOSPContext, извлечение live-секции, подвал «ЛЗ (разведсводка)».
5. Реальное исполнение: нативные тесты dept/team.mlog (12).

Мутационные проверки: удалить TeamBudgetReset из HandleOSP, вернуть
OSPLiveSearchBlock в BuildOSPContext, убрать TeamIsQuiet из контракта —
каждая валит минимум один тест этого файла.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_MLOG = open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8").read()
TEAM_MLOG = open(os.path.join(REPO_ROOT, "dept", "team.mlog"), encoding="utf-8").read()
LZ_MLOG = open(os.path.join(REPO_ROOT, "dept", "lz.mlog"), encoding="utf-8").read()
OSP_MLOG = open(os.path.join(REPO_ROOT, "dept", "osp.mlog"), encoding="utf-8").read()
ADR = open(os.path.join(REPO_ROOT, "docs", "adr", "0016-dept-teamwork.md"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\n// ═", start + 10)
    return source[start:nxt]


# ── 1. Модуль и ядро ──────────────────────────────────────────────────────

def test_team_module_in_import_closure():
    assert "import dept/team" in APP_MLOG, "dept/team.mlog обязан быть в import-замыкании app.mlog"


def test_core_patterns_exist():
    for name in (
        "TeamSkills", "TeamCoworkersBrief", "TeamIsRegistered", "TeamSkillCost",
        "TeamBudgetReset", "TeamBudgetUsed", "TeamBudgetCharge",
        "TeamLLMUsed", "TeamLLMCharge",
        "TeamStackBegin", "TeamStackEnd", "TeamStackActive",
        "TeamQuietBegin", "TeamQuietEnd", "TeamIsQuiet",
        "TeamCacheStore", "TeamCacheLookup",
        "TeamExtractSection", "TeamConsult",
    ):
        assert f"pattern {name}" in TEAM_MLOG, f"паттерн ядра отсутствует: {name}"


def test_consult_refusals_honest():
    body = _pattern_body(TEAM_MLOG, "TeamConsult")
    # ни один путь не возвращает пустоту — каждая причина названа
    for reason in (
        "глубина 1 исчерпана",
        "бюджет консультаций на запрос исчерпан — TEAM_MAX_CONSULTS",
        "бюджет вызовов LLM на запрос исчерпан — TEAM_MAX_LLM_CALLS",
        "отдел не в реестре командной работы",
        "ещё не подключён — TEAM-2",
        "навык вернул ошибку исполнения",
    ):
        assert reason in body, f"честная причина обязательна: {reason}"


def test_budget_env_seams():
    body = _pattern_body(TEAM_MLOG, "TeamConsult")
    assert 'TeamEnvCount("TEAM_MAX_CONSULTS", 3.0)' in body
    assert 'TeamEnvCount("TEAM_MAX_LLM_CALLS", 6.0)' in body


def test_audit_log_written_by_consult():
    body = _pattern_body(TEAM_MLOG, "TeamConsult")
    assert 'AuditLog("team_consult", from_dept,' in body
    for status in ("status=ok", "status=refused", "status=cache_hit"):
        assert status in body, f"журнал обязан различать статусы: {status}"


def test_no_new_http_bridges_between_depts():
    # ADR-0016: отказ от HTTP-мостов — team.mlog не открывает новых :4000 путей
    body = _pattern_body(TEAM_MLOG, "TeamConsult")
    body = body.split("// ── Нативные тесты")[0]
    assert "http://" not in body and "https://" not in body, (
        "консультация — внутрипроцессный вызов, не HTTP-мост (решение #446)")


# ── 2. Реестр — единственный источник объявлений ────────────────────────

def test_registry_declares_all_14_depts():
    dept_ids = re.findall(r'\{dept: "([a-z]+)", skill:', TEAM_MLOG)
    expected = {"lz", "osp", "expert", "marketing", "finance", "legal", "dev",
                "design", "qa", "visual", "engineering", "kavalnya", "admin", "yana"}
    assert set(dept_ids) == expected, f"реестр обязан покрывать 14 отделов, различие: {set(dept_ids) ^ expected}"


def test_all_skills_enabled_since_team2():
    # TEAM-2 (#481): все навыки отделов включены; Яна — оркестратор, не поставщик
    enabled = re.findall(r'\{dept: "([a-z]+)", skill: "([a-z_]+)".*enabled: true\}', TEAM_MLOG)
    disabled = re.findall(r'\{dept: "([a-z]+)", skill: "([a-z_]*)".*enabled: false\}', TEAM_MLOG)
    assert len(enabled) == 15, f"15 навыков включены (TEAM-2), найдено: {len(enabled)}"
    assert disabled == [("yana", "")], f"выключен только yana-оркестратор, найдено: {disabled}"


def test_dispatch_via_runskill_since_team2():
    # TEAM-2 (#481): диспетчеризация — через TeamSkillWired/TeamRunSkill;
    # factpack по-прежнему в диспетчере (TEAM-1 сквозное подключение)
    body = _pattern_body(TEAM_MLOG, "TeamConsult")
    assert "TeamSkillWired(to_dept, skill) == false" in body
    assert "TeamRunSkill(to_dept, skill, question)" in body
    run_body = _pattern_body(TEAM_MLOG, "TeamRunSkill")
    assert "LZFactpack(question)" in run_body


# ── 3. Тихий режим и factpack ────────────────────────────────────────────

def test_factpack_quiet_by_construction():
    body = _pattern_body(LZ_MLOG, "LZFactpack")
    assert "call_llm" not in body, "factpack — облегчённая функция, 0 LLM-вызовов (реестр cost_llm: 0)"
    assert "RecordAssistantMessage" not in body, "консультация не пишет в историю диалога владельца"
    assert "SendTelegramReply" not in body, "консультация не шлёт в Telegram"
    assert "SendReport" not in body, "консультация не пишет в SendReport"


def test_factpack_shared_tavily_transport():
    body = _pattern_body(LZ_MLOG, "LZFactpack")
    assert 'TavilySearch(q, "lz")' in body, "транспорт Tavily — общий шов utils.mlog (office#354)"
    assert "api.tavily.com" not in re.sub(r"//[^\n]*", "", body), "прямой вызов Tavily вне utils.mlog запрещён"


def test_factpack_honest_budget_cause():
    body = _pattern_body(LZ_MLOG, "LZFactpack")
    assert 'response == "(budget)"' in body
    assert "дневной бюджет Tavily исчерпан" in body


def test_factpack_markers_deterministic():
    body = _pattern_body(LZ_MLOG, "LZFactpack")
    assert '"[LIVE]\\n"' in body and '"\\n[NEWS]\\n"' in body and '"\\n[TG]\\n"' in body, (
        "секции [LIVE]/[NEWS]/[TG] — контракт извлечения для гейта #474")


# ── 4. Интеграция ОСП ────────────────────────────────────────────────────

def test_osp_resets_team_budget_per_request():
    body = _pattern_body(OSP_MLOG, "HandleOSP")
    assert "TeamBudgetReset()" in body, "сброс бюджетов командной работы — в начале каждого запроса"


def test_osp_footer_shows_lz_source():
    body = _pattern_body(OSP_MLOG, "OSPSourcesFooter")
    assert '"=== Консультация: lz/factpack ==="' in body
    assert "ЛЗ (разведсводка)" in body


def test_tavily_command_remains_direct():
    # /osp tavily — единственный прямой путь ОСП к Tavily (команда владельца),
    # OSPLiveSearchBlock жив: вызывается из OSPTavilySearch
    body = _pattern_body(OSP_MLOG, "OSPTavilySearch")
    assert "OSPLiveSearchBlock(query)" in body


def test_quiet_flag_contract_documented():
    # контракт тихого режима обязан быть выписан в team.mlog — иначе TEAM-2
    # не узнает, что обработчик проверяет TeamIsQuiet перед побочными эффектами
    assert "pattern TeamIsQuiet" in TEAM_MLOG
    assert "обязан проверять TeamIsQuiet" in TEAM_MLOG


# ── 5. Реальное исполнение ───────────────────────────────────────────────

def test_mlog_native_tests_team_pass():
    proc = subprocess.run(
        [os.path.join(REPO_ROOT, "bin", "mlog"), "test", os.path.join(REPO_ROOT, "dept", "team.mlog")],
        capture_output=True, text=True, timeout=120,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "tests passed" in combined and "0/0" not in combined
    assert "❌" not in combined, combined
    for name in (
        "реестр — 16 записей",
        "бриф коллег",
        "неизвестный навык — честный отказ",
        "глубина 1 — вложенная консультация отклонена",
        "бюджет консультаций — исчерпание даёт честный отказ",
        "бюджет LLM — исчерпание даёт честный отказ",
        "кэш — запись, чтение, протухание",
        "тихий режим — begin, check, end",
        "извлечение live-секции по маркерам",
        "контракт — ответ консультации никогда не пуст",
    ):
        assert name in combined, f"нативный тест обязателен: {name}"


def test_adr_0016_exists_and_covers_limiters():
    assert "ADR-0016" in ADR
    for topic in ("Глубина 1", "TEAM_MAX_CONSULTS", "TEAM_MAX_LLM_CALLS", "Тихий режим", "Отказ от HTTP-мостов"):
        assert topic in ADR, f"ADR-0016 обязан фиксировать: {topic}"
