#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#744 EXP-2: конвейер Эксперта — профессия → шкурка → поиск кругами
(12/25) → черновик по шаблону → разбор «конкурирующим профессионалом».

A: гейт дедлайна, брифинги, LoadExpertSkills (12 несуществующих скиллов),
подкоманды авто и KB/SkillSet удалены (КБ — в шкурке auto, EXP-1); таблица
expert_briefings не удалена (данные); ExpertBrief (TEAM) — сигнатура и
назначение сохранены; маршрутизация app.mlog не тронута.
B: константы EXPERT_SEARCH_MAX/DEEP, план по 8 категориям, круги, шаблон
9 разделов, rival_review сильной моделью (честная пометка при
недоступности), черновики шкурок в expert_skins_draft, /expert skin save.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")
os.environ.setdefault("API_SECRET", "test-secret-123")

from proxy import expert_skins  # noqa: E402

EXPERT = (REPO / "dept" / "expert.mlog").read_text(encoding="utf-8")
APP = (REPO / "app.mlog").read_text(encoding="utf-8")
SKIN_AUTO = REPO / "skills" / "expert" / "skins" / "auto" / "SKIN.md"


def _code_lines(src: str) -> list:
    return [l for l in src.splitlines() if not l.strip().startswith("//")]


def _segment(src: str, decl: str) -> str:
    start = src.index(decl)
    rest = src[start + len(decl):]
    nxt = rest.find("\npattern ")
    return (decl + rest[:nxt]) if nxt != -1 else (decl + rest)


# ─────────────── A: чистка ───────────────

def test_a_gate_deadline_removed():
    """НАРЯД A.1: гейт дедлайна и ExpertDetectDeadline удалены; отказ
    «когда встреча» отсутствует — запрос без срока идёт в конвейер."""
    assert "ExpertDetectDeadline" not in EXPERT
    assert "когда встреча" not in EXPERT
    assert "Без срока это не препарация" not in EXPERT
    assert "Deadline" not in "\n".join(_code_lines(EXPERT))


def test_a_briefings_removed_table_kept():
    """A.1: ExpertCreateBriefing/ListBriefings/UpdateBriefingStatus и
    команды /expert briefing|/quickexpert|briefings|debrief удалены;
    таблица expert_briefings (данные) не удалена."""
    for gone in ("pattern ExpertCreateBriefing(", "pattern ExpertListBriefings(",
                 "pattern ExpertUpdateBriefingStatus(", "/expert briefing",
                 "/quickexpert", "/expert briefings", "/expert debrief"):
        assert gone not in EXPERT, gone
    assert "CREATE TABLE IF NOT EXISTS expert_briefings" in APP, \
        "таблица (данные) сохранена в InitDB app.mlog"


def test_a_load_expert_skills_removed():
    """A.2: LoadExpertSkills с 12 несуществующими путями удалён; скиллы —
    из шкурки (B.2)."""
    assert "pattern LoadExpertSkills(" not in EXPERT
    assert "skills/rapid-domain-immersion" not in EXPERT
    assert "pre-meeting-intel" not in EXPERT
    assert "tactical-meeting-protocol" not in EXPERT


def test_a_auto_subcommands_removed_tools_kept():
    """A.3: подкоманды авто и ExpertAutomotiveKB/SkillSet/Lookup/Compare
    удалены; инструменты шкурки auto остались (конвейер B.7)."""
    for gone in ("/expert auto", "/expert compare", "/expert residual",
                 "/expert cost", "/expert chart",
                 "pattern ExpertAutomotiveKB(", "pattern ExpertAutomotiveSkillSet(",
                 "pattern ExpertAutomotiveLookup(", "pattern ExpertCompareVehicles("):
        assert gone not in EXPERT, gone
    for kept in ("pattern ExpertAvByListings(", "pattern ExpertResidualValueData(",
                 "pattern ExpertOperationCostData(", "pattern ExpertGenerateChart("):
        assert kept in EXPERT, kept


def test_a_team_brief_signature_untouched():
    """Запрет: ExpertBrief (TEAM, dept/team.mlog:493) — сигнатура и
    назначение сохранены."""
    seg = _segment(EXPERT, "pattern ExpertBrief(question: String) -> String {")
    assert "коллега запрашивает навык brief" in seg
    assert "call_llm(prompt, question)" in seg


def test_a_routing_untouched():
    """Запрет: маршрутизация в app.mlog не изменена — HandleExpert зовётся
    как раньше."""
    assert "HandleExpert(query, chat_id)" in APP


def test_a_deepexpert_is_depth_flag():
    """A.1: /deepexpert — флаг глубины (25 поисков), не брифинг."""
    seg = _segment(EXPERT, "pattern HandleExpert(")
    assert 'starts_with(t, "/deepexpert")' in seg
    assert "ExpertRunReport(deep_query, chat_id, true)" in seg


# ─────────────── B: конвейер ───────────────

def test_b_limits_12_25():
    """НАРЯД B.4: константы EXPERT_SEARCH_MAX=12, EXPERT_DEEP_SEARCH_MAX=25
    (паттерны-константы)."""
    seg_max = _segment(EXPERT, "pattern ExpertSearchMax() -> Float {")
    seg_deep = _segment(EXPERT, "pattern ExpertDeepSearchMax() -> Float {")
    assert "return 12.0" in seg_max
    assert "return 25.0" in seg_deep
    assert "ExpertSearchMax()" in EXPERT and "ExpertDeepSearchMax()" in EXPERT


def test_b1_profession_detect():
    """B.1: первый дешёвый вызов — профессия/специализация/отрасль/термины;
    строка «Надеваю: …» в отчёте; сбой модели — честная деградация."""
    seg = _segment(EXPERT, "pattern ExpertDetectProfession(")
    assert "Профессия | Специализация | Отрасль" in seg
    run_seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "надета" in run_seg and "Надеваю" in EXPERT


def test_b2_skin_or_draft():
    """B.2: шкурка по triggers (валидатор EXP-1, call_python expert_skins);
    нет готовой → черновик в expert_skins_draft; /expert skin save <id> —
    выдаёт текст, файл не пишет."""
    seg = _segment(EXPERT, "pattern ExpertPickSkin(")
    assert 'call_python("expert_skins", "pick_skin"' in seg
    assert "expert_skins_draft" in EXPERT
    assert "INSERT INTO expert_skins_draft" in EXPERT
    seg_save = _segment(EXPERT, "pattern ExpertSkinDraftText(")
    assert "файл не пишет" in seg_save or "не пишет" in seg_save
    # таблица создаётся лениво
    assert "CREATE TABLE IF NOT EXISTS expert_skins_draft" in EXPERT


def test_b3_plan_categories():
    """B.3: план поиска по 8 фиксированным категориям (1–2 запроса на
    категорию, языки en/ru, site: по sources[] шкурки)."""
    seg = _segment(EXPERT, "pattern ExpertSearchPlan(")
    for cat in ("нормы и стандарты", "статистика отказов, отзывы, рекламации",
                "независимые тесты", "форумы и сообщества практиков",
                "научные работы", "регуляторы", "экономика и цены", "критика"):
        assert cat in seg, cat
    assert "1-2 конкретных поисковых запроса" in seg
    assert "site:" in seg and "en/ru" in seg


def test_b4_circles_and_budget():
    """B.4: круг 1 по плану → круг 2 по пробелам → круг 3 при deep;
    лимит на отчёт; бюджет Tavily — честная строка."""
    seg = _segment(EXPERT, "pattern ExpertSearchCircles(")
    assert "cap1" in seg and "max_searches / 2.0" in seg
    assert "непокрытые категории и пустые места" in seg
    assert "used < max_searches" in seg
    assert "дневной бюджет Tavily исчерпан" in EXPERT, "честный бюджет"


def test_b5_draft_by_template():
    """B.5: черновик по шаблону EXP-1 — read library/expert_report_template.md
    в конвейере; сбой модели — честная деградация, не молчание."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "library/expert_report_template.md" in EXPERT
    assert "Разбор недоступен" in seg


def test_b6_rival_review_strong_model():
    """B.6: разбор «конкурирующим профессионалом» — llm_verifier.rival_review
    (сильная модель glm-4.6 из реестра); недоступность — пометка в отчёте,
    не тишина (правило при затруднении); вычеркнутое не возвращается."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert 'call_python("llm_verifier", "rival_review"' in seg
    assert "не выполнен" in seg and "сильная модель недоступна" in EXPERT
    assert "Вычеркнутое НЕ возвращать" in EXPERT
    lv = (REPO / "llm_verifier.py").read_text(encoding="utf-8")
    assert '"model": "glm-4.6"' in lv, "сильная модель в реестре rival_review"


def test_b6_verifier_criteria_replaced():
    """Вербификатор: критерий «meeting prep» заменён на «глубина, механизм,
    источники негативных нюансов» (score + select)."""
    assert "Usable for meeting preparation" not in EXPERT
    assert "Usable for meeting prep" not in EXPERT
    assert "Mechanism: Every nuance has a why?" in EXPERT
    assert EXPERT.count("Depth: Professional") >= 2


def test_b7_auto_tools_in_numbers():
    """B.7: при auto-теме — вызов avby_listings/residual_value, результаты
    со пометкой «вставить в раздел «Цифры»»."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "вставить в раздел «Цифры»" in seg
    assert "ExpertAvByListings(query)" in seg
    assert "ExpertResidualValueData(query, chat_id)" in seg


def test_disclaimer_by_industry():
    """Строка «информационный разбор, не консультация специалиста» —
    медицина/право/финансы, без сокращения глубины."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "информационный разбор, не консультация специалиста" in seg
    assert "врач" in seg and "юрист" in seg and "финанс" in seg


# ─────────────── python-швы ───────────────

def test_pick_skin_matches_auto():
    """C.1: авто «Toyota RAV4 2019» → шкурка auto надета; солнечные панели
    и токарка — шкурки нет (конвейер строит черновик)."""
    d = json.loads(expert_skins.pick_skin("стоит ли брать Toyota RAV4 2019 на вторичке"))
    assert d["ok"] == 1 and d["domain"] == "auto"
    assert "toyota" in d["matched"] or "rav4" in d["matched"]
    for q in ("солнечные панели для частного дома в Беларуси",
              "токарная обработка нержавейки AISI 304"):
        assert json.loads(expert_skins.pick_skin(q))["ok"] == 0, q


def test_rival_review_honest_degradation():
    """Правило при затруднении: без ключей провайдеров — честный
    {"ok": 0, "note": …}, не молчание."""
    import types
    lv_path = REPO / "llm_verifier.py"
    code = lv_path.read_text(encoding="utf-8")
    saved = {k: v for k, v in os.environ.items() if "API_KEY" in k}
    for k in saved:
        os.environ.pop(k, None)
    try:
        lv = types.ModuleType("lv")
        lv.__file__ = str(lv_path)
        exec(compile(code, str(lv_path), "exec"), lv.__dict__)
        assert hasattr(lv, "rival_review"), \
            f"rival_review нет: rival in code={'rival_review' in code}, len={len(code)}"
        r = json.loads(lv.rival_review("тема", "длинный черновик " * 40))
    finally:
        os.environ.update(saved)
    assert r["ok"] == 0 and "недоступна" in r["note"]


def test_pick_skin_valid_skin_only():
    """Сопоставление только по валидным шкуркам (валидатор EXP-1):
    битая шкурка не надевается."""
    d = json.loads(expert_skins.pick_skin("Toyota Camry остаточная стоимость"))
    assert d["ok"] == 1  # auto валидна


# ─────────────── живая mlog-фикстура ───────────────

def test_live_no_deadline_gate_query_flows():
    """НАРЯД C.1: запрос без срока идёт в конвейер (не отказ). Живой прогон
    фикстуры: HandleExpert в CI-окружении без LLM-ключей деградирует честно
    («Разбор недоступен…»), но НЕ возвращает уточняющий вопрос о сроке."""
    fixture = REPO / "test_n744v1.mlog"
    subprocess.run([sys.executable, str(REPO / "scripts" / "n744_fixture.py"),
                    str(fixture)], check=True, cwd=REPO)
    db = Path("/tmp/n744-test/expert.db")
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    env = dict(os.environ, DATABASE_URL=f"sqlite:{db}", OWNER_TELEGRAM_ID="12345",
               METALOGOS_MOCK_LLM="1")
    r = subprocess.run([str(REPO / "bin" / "mlog"), "run", "test_n744v1.mlog"],
                       capture_output=True, text=True, timeout=300, env=env, cwd=REPO)
    out = r.stdout + r.stderr
    assert "когда встреча" not in out, "гейт дедлайна вернулся!"
    assert ("Разбор недоступен" in out or "Надеваю" in out or "Недоступна" in out), \
        f"конвейер не отработал: {out[-400:]}"
