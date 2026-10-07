#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #481 TEAM-2 (P0): подключение всех 14 отделов к командной работе.

ADR-0016 + реестр dept/team.mlog. Уровни гвардов:
1. Навыки-поставщики (A.1): 13 облегчённых функций в своих dept-файлах,
   тихие по построению (0 записей в диалог, 0 Telegram, 0 SendReport).
2. Диспетчер: TeamRunSkill проводит все навыки реестра, TeamSkillWired —
   гвард рассинхрона реестра и кода; TeamConsult на шве.
3. Карта потребностей (A.2): TeamNeedsMap детерминирована (без LLM),
   TeamAutoConsult исполняет её в HandleDeptQuery.
4. Маркер ASK (A.3): правило в промптах (TeamAskBlock) OSP/LZ/Expert и
   generic-пути; второй проход TeamSecondPass; маркеры не доходят
   владельцу (TeamStripAsks на всех путях).
5. Яна-оркестратор (A.4): TeamYanaMultiDomain (детерминированный) +
   ExecuteChain с гвардом стека от двойного вложения.
6. Реальное исполнение: нативные тесты dept/team.mlog (21).

Мутационные проверки: убрать TeamStackActive из HandleYana-ветки, убрать
TeamStripAsks из TeamSecondPass, отключить навык в реестре без отключения
в диспетчере — каждая валит минимум один тест.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAM_MLOG = open(os.path.join(REPO_ROOT, "dept", "team.mlog"), encoding="utf-8").read()
APP_MLOG = open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8").read()

DEPT_FILES = {
    "osp": open(os.path.join(REPO_ROOT, "dept", "osp.mlog"), encoding="utf-8").read(),
    "lz": open(os.path.join(REPO_ROOT, "dept", "lz.mlog"), encoding="utf-8").read(),
    "expert": open(os.path.join(REPO_ROOT, "dept", "expert.mlog"), encoding="utf-8").read(),
    "finance": open(os.path.join(REPO_ROOT, "dept", "finance.mlog"), encoding="utf-8").read(),
    "legal": open(os.path.join(REPO_ROOT, "dept", "legal.mlog"), encoding="utf-8").read(),
    "marketing": open(os.path.join(REPO_ROOT, "dept", "marketing.mlog"), encoding="utf-8").read(),
    "design": open(os.path.join(REPO_ROOT, "dept", "design.mlog"), encoding="utf-8").read(),
    "dev": open(os.path.join(REPO_ROOT, "dept", "dev.mlog"), encoding="utf-8").read(),
    "qa": open(os.path.join(REPO_ROOT, "dept", "qa.mlog"), encoding="utf-8").read(),
    "engineering": open(os.path.join(REPO_ROOT, "dept", "engineering.mlog"), encoding="utf-8").read(),
    "visual": open(os.path.join(REPO_ROOT, "dept", "visual.mlog"), encoding="utf-8").read(),
    "kavalnya": open(os.path.join(REPO_ROOT, "dept", "kavalnya.mlog"), encoding="utf-8").read(),
    "admin": open(os.path.join(REPO_ROOT, "dept", "admin.mlog"), encoding="utf-8").read(),
}

SKILL_IN_FILE = {
    ("osp", "forecast"): "OSPForecast",
    ("osp", "cross_country"): "OSPCrossCountry",
    ("lz", "tech_scan"): "LZTechScan",
    ("expert", "brief"): "ExpertBrief",
    ("finance", "calc"): "FinanceCalc",
    ("legal", "legal_check"): "LegalCheck",
    ("marketing", "audience"): "MarketingAudience",
    ("design", "ux_review"): "DesignUxReview",
    ("dev", "tech_estimate"): "DevTechEstimate",
    ("qa", "risk_review"): "QaRiskReview",
    ("engineering", "feasibility"): "EngineeringFeasibility",
    ("visual", "visualize"): "VisualDeptVisualize",
    ("kavalnya", "methodology_review"): "KavalnyaMethodologyReview",
    ("admin", "system_status"): "AdminSystemStatus",
}


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = len(source)
    return source[start:nxt]


# ── A.1: навыки-поставщики ───────────────────────────────────────────────

def test_all_skills_declared_in_dept_files():
    for (dept, skill), fname in SKILL_IN_FILE.items():
        assert f"pattern {fname}" in DEPT_FILES[dept], f"навык {dept}/{skill} отсутствует: {fname}"


def test_llm_skills_quiet_by_construction():
    # тихий режим ADR-0016: навык не пишет в диалог и не шлёт владельцу
    for (dept, skill), fname in SKILL_IN_FILE.items():
        body = _pattern_body(DEPT_FILES[dept], fname)
        for forbidden in ("RecordAssistantMessage", "SendTelegramReply", "SendReport", "LogSessionEvent"):
            assert forbidden not in body, f"{fname}: консультация не должна {forbidden}"


def test_llm_skills_honest_refusal():
    # отказ называется честно, не пустота и не маскировка под данные
    for (dept, skill), fname in SKILL_IN_FILE.items():
        if fname in ("LZTechScan", "AdminSystemStatus"):
            continue  # детерминированные — свои формы честных отказов
        body = _pattern_body(DEPT_FILES[dept], fname)
        assert "недоступен: модель не ответила" in body, f"{fname}: обязана честно называть отказ"


def test_admin_system_status_deterministic():
    body = _pattern_body(DEPT_FILES["admin"], "AdminSystemStatus")
    assert "call_llm" not in body, "system_status — детерминированный навык (реестр cost_llm: 0)"


# ── Диспетчер ────────────────────────────────────────────────────────────

def test_runskill_dispatches_all_registry_skills():
    body = _pattern_body(TEAM_MLOG, "TeamRunSkill")
    for (dept, skill), fname in SKILL_IN_FILE.items():
        assert f"{fname}(question)" in body, f"диспетчер не проводит {dept}/{skill}"
    # TEAM-1 сквозное подключение не потеряно
    assert "LZFactpack(question)" in body


def test_wired_guard_covers_all_skills():
    body = _pattern_body(TEAM_MLOG, "TeamSkillWired")
    for (dept, skill), _ in SKILL_IN_FILE.items():
        assert f'skill == "{skill}"' in body, f"TeamSkillWired не знает {dept}/{skill}"


# ── A.2: карта потребностей ──────────────────────────────────────────────

def test_needs_map_deterministic_rules():
    body = _pattern_body(TEAM_MLOG, "TeamNeedsMap")
    # примеры диспатча #483: текущий мир → ЛЗ; финансы+налоги → юристы;
    # эксперт+инвестиции → финансы; дев+архитектура → QA
    for marker in ("lz|factpack", "legal|legal_check", "finance|calc", "qa|risk_review"):
        assert marker in body, f"правило карты отсутствует: {marker}"


def test_auto_consult_wired_in_generic_path():
    body = _pattern_body(APP_MLOG, "HandleDeptQuery")
    assert "TeamAskBlock(dept)" in body, "бриф коллег и правило ASK — в промпте generic-пути"
    assert "TeamAutoConsult(dept, query)" in body, "карта потребностей исполняется до первого прохода"
    assert "TeamSecondPass(dept, query, context, reply)" in body, "второй проход в generic-пути"
    assert "TeamFooterFromBlock(auto_block)" in body, "источники консультаций — в подвале (A.5)"


# ── A.3: ASK-маркеры в прямых путях больших отделов ─────────────────────

def test_ask_second_pass_in_direct_handlers():
    # прямые пути больших отделов: второй проход и бриф в файле (точное
    # положение в хендлере фиксируют нативные тесты и мутационные прогоны)
    for dept, fname in (("osp", "HandleOSP"), ("lz", "HandleLZ"), ("expert", "HandleExpert")):
        src = DEPT_FILES[dept]
        assert f"pattern {fname}" in src
        assert "TeamSecondPass(" in src, f"{dept}: второй проход не проводён"
        assert "TeamAskBlock(" in src, f"{dept}: бриф и правило ASK не в промпте"


def test_second_pass_strips_markers_on_all_paths():
    body = _pattern_body(TEAM_MLOG, "TeamSecondPass")
    assert "TeamStripAsks(draft)" in body
    assert "TeamStripAsks(r)" in body, "финальный ответ обязан чиститься от маркеров"
    assert "TeamFooterFromBlock(consults)" in body, "источники консультаций прилагаются (A.5)"


# ── A.4: Яна-оркестратор ─────────────────────────────────────────────────

def test_yana_auto_chain_wired_with_recursion_guard():
    yana = open(os.path.join(REPO_ROOT, "dept", "yana.mlog"), encoding="utf-8").read()
    assert "TeamYanaMultiDomain(query)" in yana
    assert "TeamStackActive() == false" in yana, "гвард двойного вложения обязателен"
    assert "ExecuteChain(chain_depts, query, chat_id)" in yana, "реиспользуется существующий /chain"
    assert "team_auto_chain" in yana, "авто-цепочка видна в audit_log"


def test_yana_multi_domain_no_llm():
    body = _pattern_body(TEAM_MLOG, "TeamYanaMultiDomain")
    assert "call_llm" not in body, "детектор мультиобластности — детерминированный (без LLM)"


# ── Реальное исполнение ──────────────────────────────────────────────────

def test_mlog_native_tests_team_pass():
    proc = subprocess.run(
        [os.path.join(REPO_ROOT, "bin", "mlog"), "test", os.path.join(REPO_ROOT, "dept", "team.mlog")],
        capture_output=True, text=True, timeout=150,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "tests passed" in combined and "0/0" not in combined
    assert "❌" not in combined, combined
    for name in (
        "карта потребностей — налоги финансов ведут к юристам",
        "карта потребностей — текущий мир ведёт к ЛЗ, кроме самой ЛЗ",
        "карта потребностей — эксперт к финансам, дев к QA",
        "strip — маркеры ASK вырезаются на всех путях",
        "ASK-процессор — максимум два маркера",
        "второй проход — ответ владельцу никогда не содержит маркеров",
        "диспетчер — все навыки реестра проводятся, чужие нет",
        "Яна-детектор — мультиобластной да, однодоменный нет",
        "подвал источников из блока консультаций",
    ):
        assert name in combined, f"нативный тест обязателен: {name}"
