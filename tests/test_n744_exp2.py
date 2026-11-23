#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#744 EXP-2: конвейер Эксперта — профессия → шкурка → поиск кругами
(12/25) → черновик по шаблону → разбор «конкурирующим профессионалом».

A: гейт дедлайна, брифинги, LoadExpertSkills (12 несуществующих скиллов),
подкоманды авто и KB/SkillSet удалены (КБ — в шкурке auto, EXP-1); таблица
expert_briefings не удалена (данные); ExpertBrief (TEAM) — сигнатура и
назначение сохранены. Раунд 2 (ревью c5b2eff): диспетчер app.mlog передаёт
Эксперту ИСХОДНЫЙ текст команды (иначе /deepexpert и /expert skin save не
работали вовсе), ExpertStripCommand снимает префикс сам.
B: константы EXPERT_SEARCH_MAX/DEEP, план по 8 категориям, круги, шаблон
9 разделов, rival_review сильной моделью (честная пометка при
недоступности), черновики шкурок в expert_skins_draft (INSERT OR IGNORE
под TryVal — голый db_execute с SQL-ошибкой ронял весь запрос; id —
sha256-отпечаток, redact не маскирует), /expert skin save; контекст отдела
(BuildExpertContext) — в промпте черновика и во втором проходе.
Живые фикстуры: test_n744v1 (герметичная, бюджет Tavily предзаполнен) и
test_n744v2 (поведенческая, стабы швов) — генератор scripts/n744_fixture.py,
--check проверяет, что коммит не разошёлся с генератором.
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


def _block(src: str, needle: str) -> str:
    """Тело блока: от '{' после needle до парной '}' (в диспетчерном блоке
    app.mlog и гейте auto_on скобок в строках нет)."""
    start = src.index(needle)
    op = src.index("{", start)
    depth = 0
    for i in range(op, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("незакрытый блок после " + needle)


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


def test_a_dispatcher_passes_raw_command():
    """Раунд 2 (дефект c5b2eff): диспетчер app.mlog снимал первый токен
    команды → «/deepexpert» терял флаг глубины, «/expert skin save <id>»
    уходил в полный разбор. Теперь Эксперту передаётся исходный текст, а
    префикс снимает сам Эксперт (ExpertStripCommand). Остальная маршрутизация
    app.mlog не тронута."""
    pos = APP.index("HandleExpert(text, chat_id)")
    start = APP.rindex('if dept == "expert" then {', 0, pos)
    block = _block(APP[start:], 'if dept == "expert" then {')
    assert "RecordUserMessage(chat_id, \"expert\", text)" in block
    assert "HandleExpert(text, chat_id)" in block
    assert "HandleExpert(query, chat_id)" not in APP
    assert "#744 EXP-2" in block, "причина смены — в комментарии у места"


def test_a_deepexpert_is_depth_flag():
    """A.1: /deepexpert — флаг глубины (25 поисков), не брифинг; до фикса
    диспетчера флаг не доходил вовсе."""
    seg = _segment(EXPERT, "pattern HandleExpert(")
    assert 'starts_with(t, "/deepexpert")' in seg
    assert "ExpertRunReport(topic, chat_id, true)" in seg
    assert "ExpertRunReport(topic, chat_id, false)" in seg


def test_a_command_parsing_helpers():
    """Раунд 2: разбор команд устойчив к обоим видам входа — с командой
    (app.mlog после фикса) и без (chain, старый диспетчер):
    ExpertStripCommand снимает ведущий токен, ExpertSkinDraftId достаёт
    skin-<id> из любого места запроса, «skin save» работает и без слэша."""
    assert "pattern ExpertStripCommand(" in EXPERT
    assert "pattern ExpertSkinDraftId(" in EXPERT
    assert 'starts_with(t, "/expert skin save") or starts_with(t, "skin save")' in EXPERT


def test_a_expert_disclaimer_removed():
    """Раунд 2: ExpertDisclaimer удалён (с EXP-1 без вызовов, значение не
    использовалось); отраслевая строка честности — в ExpertRunReport."""
    assert "ExpertDisclaimer" not in "\n".join(_code_lines(EXPERT))


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
    выдаёт текст, файл не пишет; таблица создаётся лениво; шов недоступен —
    честная пометка, не молчание."""
    seg = _segment(EXPERT, "pattern ExpertPickSkin(")
    assert 'call_python("expert_skins", "pick_skin"' in seg
    assert "Шкурка недоступна: шов expert_skins не ответил" in seg
    assert "INSERT OR IGNORE INTO expert_skins_draft" in EXPERT
    seg_save = _segment(EXPERT, "pattern ExpertSkinDraftText(")
    assert "не пишет" in seg_save
    assert "CREATE TABLE IF NOT EXISTS expert_skins_draft" in EXPERT


def test_b2_draft_insert_honest_failure():
    """Раунд 2 (дефект c5b2eff): голый db_execute с SQL-ошибкой ронял весь
    запрос («UNIQUE constraint failed…», rc=1). Теперь INSERT OR IGNORE под
    TryVal; «1» — записано, иначе честная ветка «НЕ сохранён» + аудит."""
    seg = _segment(EXPERT, "pattern ExpertPickSkin(")
    assert "INSERT OR IGNORE INTO expert_skins_draft" in seg
    assert "TryVal(try db_execute" in seg
    assert "expert_skin_draft_not_saved" in seg
    assert "НЕ сохранён" in seg
    assert "занят или таблица недоступна" in seg


def test_b2_draft_id_survives_redact():
    """Раунд 2 (дефект c5b2eff, урок #603 A.2): время+случайное число в id
    маскировалось redact'ом как номер карты. Теперь id — «skin-» + 16-hex
    отпечаток sha256 (21 символ), redact на id не применяется (идиома
    engineering.mlog)."""
    seg = _segment(EXPERT, "pattern ExpertPickSkin(")
    line = next(l for l in seg.splitlines() if 'let draft_id = "skin-"' in l)
    assert "sha256(" in line and "0.0, 16.0" in line
    assert "redact(" not in line
    # id виден владельцу: в ответе и команда сохранения файла
    run_seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "Текст черновика: /expert skin save " in run_seg
    assert "сохранить в expert_skins_draft не удалось" in run_seg


def test_b2_draft_not_saved_branch():
    """Раунд 2: несовместимая таблица (N744_CASE=notsaved) — запрос не
    падает, черновик показан в ответе, пометка честная."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "Готовой шкурки по этой теме не было" in seg
    assert "Черновик шкурки" in seg


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


def test_b5_pipeline_uses_context_builder():
    """Раунд 2 (дефект c5b2eff): конвейер потерял BuildExpertContext —
    профиль отдела, память Яны, корректировки, факты, диалог, кросс-ссылки
    ЛЗ/ОСП (#234), TeamAsk/TeamBoard не попадали в промпт. Контекст — в
    системном промпте черновика; второй проход получает тот же промпт."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "let context = BuildExpertContext(query, chat_id)" in seg
    assert "=== КОНТЕКСТ ОТДЕЛА (профиль и корректировки обязательны) ===" in seg
    assert "let work_context = draft_sys +" in seg
    assert "TeamSecondPass(dept, query, work_context, reply)" in seg
    bc = _segment(EXPERT, "pattern BuildExpertContext(")
    for seam in ("ReadDeptProfile", "YanaRecallMemories", "YanaNowInfo",
                 "GetCorrections", "GetFacts", "GetRecentDialog",
                 "TeamAskBlock", "TeamBoardBlock"):
        assert seam + "(" in bc, seam


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
    со пометкой «вставить в раздел «Цифры»»; оба вызова — РОВНО под гейтом
    auto_on (до раунда 2 вызовы жили в BuildExpertContext без гейта, а
    условие гейта теряло «надета шкурка auto»)."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "вставить в раздел «Цифры»" in seg
    gate = _block(seg, "if auto_on then {")
    assert "ExpertAvByListings(query)" in gate
    assert "ExpertResidualValueData(query, chat_id)" in gate
    assert EXPERT.count("ExpertAvByListings(query)") == 1, "ровно один вызов — под гейтом"
    assert "НЕ живые данные" in gate, "кривые остаточной стоимости помечены"


def test_b7_auto_gate_conditions():
    """Раунд 2: гейт auto_on — шкурка надета (auto), automotive-тема (#336),
    «авто» в профессии, марки; contains регистрозависим → иглы по lower() в
    нижнем регистре (дефект c5b2eff: игла «Toyota» не совпадала никогда)."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    line = next(l for l in seg.splitlines() if "let auto_on = " in l)
    assert 'contains(skin_block, "Шкурка надета (auto)")' in line
    assert "ExpertIsAutomotiveTopic(query) == true" in line
    assert 'contains(lower(profession_line), "авто")' in line
    for m in re.finditer(r'contains\((?:lower\([a-z_]+\)|t_q), "([^"]+)"\)', line):
        assert m.group(1) == m.group(1).lower(), "игла не в нижнем регистре: " + m.group(0)
    assert "toyota" in line and "bmw" in line and "kia" in line


def test_disclaimer_by_industry():
    """Строка «информационный разбор, не консультация специалиста» —
    медицина/право/финансы, без сокращения глубины."""
    seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "информационный разбор, не консультация специалиста" in seg
    assert "врач" in seg and "юрист" in seg and "финанс" in seg


def test_b8_sources_footer_honest():
    """#468: строка источников только при реальных результатах с URL
    («•»); при пустом поиске — пометка «свежих данных живой поиск не дал»,
    без выдуманных источников."""
    seg = _segment(EXPERT, "pattern ExpertSourcesFooter(")
    assert "=== Live Search" in seg and '"•"' in seg
    assert "Живой веб-поиск (кругами)" in seg
    run_seg = _segment(EXPERT, "pattern ExpertRunReport(")
    assert "свежих данных живой поиск не дал" in run_seg


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


# ─────────────── живые mlog-фикстуры ───────────────

def test_committed_fixtures_match_generator():
    """Фикстуры в репо — вывод генератора scripts/n744_fixture.py; расхождение
    = забытый коммит (test_n744v*.mlog игнорируется .gitignore → только
    -f)."""
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "n744_fixture.py"),
                        "--check"], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout + r.stderr


def _run_fixture(name: str, case: str = "") -> str:
    tag = name.replace(".mlog", "") + (("_" + case) if case else "")
    db = Path("/tmp/n744-test") / (tag + ".db")
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    env = dict(os.environ, DATABASE_URL=f"sqlite:{db}", OWNER_TELEGRAM_ID="12345",
               METALOGOS_MOCK_LLM="1")
    if case:
        env["N744_CASE"] = case
    r = subprocess.run([str(REPO / "bin" / "mlog"), "run", name],
                       capture_output=True, text=True, timeout=300, env=env, cwd=REPO)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"rc={r.returncode}\n{out[-1500:]}"
    # фатальные ошибки рантайма — строки «error: […]»; пойманные try'ем
    # («[try] caught error: …», шум env_or/to_float в utils) — легальны
    fatal = [l for l in out.splitlines() if l.startswith("error: ")]
    assert "TYPE_MISMATCH" not in "".join(fatal) and not fatal, out[-1500:]
    return out


def test_live_v1_no_deadline_gate_hermetic():
    """НАРЯД C.1 + герметичность: запрос без срока идёт в конвейер, не в
    отказ. Дневной бюджет Tavily предзаполнен → общий шов TavilySearch
    отвечает «(budget)» ДО всякого http_post (CI без ключей и без сети);
    честная строка бюджета — в ответе; футера источников нет (источников
    не было); черновик шкурки сохранён, id виден владельцу."""
    out = _run_fixture("test_n744v1.mlog")
    assert "когда встреча" not in out, "гейт дедлайна вернулся!"
    assert "Разбор недоступен" not in out, "мок-LLM не должен деградировать"
    assert "дневной бюджет Tavily исчерпан" in out, "честная строка бюджета"
    assert "(лимит поисков: 12; шкурка: нет)" in out
    assert "Шкурка недоступна: шов expert_skins не ответил" in out, \
        "run-контекст: шов python недоступен — честная пометка"
    assert "Живой веб-поиск (кругами)" not in out, "нет результатов — нет футера источников"


@pytest.mark.parametrize("case", ["", "notsaved"])
def test_live_v2_pipeline(case):
    """Поведенческая фикстура v2: команды без темы/id, черновик шкурки +
    round-trip /expert skin save (оба вида запроса), лимиты 12/25 (deep-флаг),
    контекст отдела и шаблон в промпте, кросс-ссылки ЛЗ/ОСП, авто-инструменты
    ровно под гейтом, rival_review в обе стороны, запись аудита;
    N744_CASE=notsaved — честная ветка без падения запроса."""
    out = _run_fixture("test_n744v2.mlog", case)
    expected = {"": 75, "notsaved": 7}
    m = re.search(r"N744V2 SUMMARY pass=(\d+) fail=(\d+)", out)
    assert m, out[-1500:]
    assert m.group(2) == "0" and int(m.group(1)) == expected[case], \
        f"сводка {m.group(0)}, ожидалось pass={expected[case]} fail=0"
    assert "FAIL " not in out, out[-1500:]
