"""Наряд #669 (B3.1): замер хвостов и включение шва по отделам.

Структурные проверки: файлы вопросов (по 20 на отдел), новый по-отдельному
контракт шва (CardSeamEnabled(dept)), замер (CardSeamCount/CardSeamProbe/
seam_probe_runs), команды владельца /seam* и слот разового задания.
Поведенческие проверки — mlog-тесты dept/card.mlog (запускаются в CI).
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CARD = (REPO_ROOT / "dept" / "card.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")

SEAM_DEPTS = [
    "osp", "lz", "expert", "marketing", "finance", "legal",
    "dev", "design", "qa", "visual", "engineering", "kavalnya",
]


def _block(src: str, start_marker: str) -> str:
    """Текст от start_marker до следующего объявления pattern/test."""
    start = src.index(start_marker)
    nxt = src.find("\npattern ", start + 10)
    nxt2 = src.find("\ntest ", start + 10)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return src[start:min(ends)] if ends else src[start:]


def test_question_files_20_each():
    """A.2: файл <dept>.txt на каждый отдел замера, ровно 20 вопросов (без # и пустых)."""
    for dept in SEAM_DEPTS:
        p = REPO_ROOT / "config" / "seam_probe" / f"{dept}.txt"
        assert p.exists(), f"нет файла вопросов {p}"
        lines = [
            l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        assert len(lines) == 20, f"{dept}: {len(lines)} вопросов, нужно ровно 20"
        header = p.read_text(encoding="utf-8").splitlines()[0]
        assert "владелец может заменить" in header, f"{dept}: нет шапки-черновика"


def test_question_files_demand_verifiable_claims():
    """A.2: вопросы требуют проверяемого утверждения (число/дата/да-нет/чек-лист)."""
    markers = ("числ", "дата", "дату", "да/нет", "чек-лист", "сумм", "процент",
               "одним числом", "вероятност", "порог", "срок", "сколько", "ровно",
               "признак", "формулировку", "какой тип", "стоп-фактор")
    for dept in SEAM_DEPTS:
        p = REPO_ROOT / "config" / "seam_probe" / f"{dept}.txt"
        body = "\n".join(
            l for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")
        )
        hits = sum(1 for l in body.splitlines() if any(m in l.lower() for m in markers))
        assert hits >= 18, f"{dept}: только {hits}/20 вопросов содержат проверяемое требование"


def test_seam_enabled_per_dept():
    """A.1: CardSeamEnabled(dept) — двойной ключ: глобальный + card_seam_enabled:<dept>."""
    assert "pattern CardSeamEnabled(dept: String) -> Bool" in CARD
    fn = _block(CARD, "pattern CardSeamEnabled(")
    assert "'card_seam_enabled'" in fn, "нет глобального ключа"
    assert '"card_seam_enabled:" + dept' in fn, "нет департаментского ключа"
    # CardSeamVerdict передаёт отдел
    verdict = _block(CARD, "pattern CardSeamVerdict(")
    assert "CardSeamEnabled(dept)" in verdict


def test_seam_probe_table_and_counter():
    """A.3: таблица seam_probe_runs с колонками наряда; счётчик CardSeamCount."""
    assert "CREATE TABLE IF NOT EXISTS seam_probe_runs" in CARD
    ddl_m = re.search(r'CREATE TABLE IF NOT EXISTS seam_probe_runs \((.+?)\)"', CARD, re.S)
    ddl = ddl_m.group(1)
    for col in ("dept", "ts", "n", "ok", "fail", "bare", "reasons_json", "models_json"):
        assert re.search(rf"\b{col}\b", ddl), f"нет колонки {col} в seam_probe_runs"
    assert "pattern CardSeamCount(replies_json: String) -> String" in CARD
    # писатель единственный
    writers = re.findall(r"INSERT INTO seam_probe_runs", CARD)
    assert len(writers) == 1, "INSERT в seam_probe_runs должен быть ровно один (CardSeamRecord)"


def test_seam_probe_uses_battle_context_builders():
    """A.3: замер строит контекст тем же сборщиком, что боевой путь отдела."""
    one = _block(CARD, "pattern CardSeamProbeOne(")
    assert "BuildFinanceContext(" in one, "finance: боевой сборщик не подключён"
    assert "BuildOSPContext(" in one and "OSPAutoEscalate(" in one, "osp: боевой сборщик не подключён"
    assert "BuildContext(dept, question" in one, "HandleDeptQuery-отделы: боевой сборщик не подключён"
    assert "CallLLMResilient(" in one and "call_llm(" in one, "боевые вызовы LLM не подключены"


def test_seam_probe_writes_only_its_table():
    """Запрет прохода: замер не пишет в dept_archive/dialog_history/trace_log/сессии."""
    start = CARD.index("#669 A.3 — ЗАМЕР ХВОСТОВ")
    probe_zone = CARD[start:CARD.index("// ТЕСТЫ")]
    for banned in ("INSERT INTO dept_archive", "INSERT INTO dialog_history",
                   "INSERT INTO trace_log", "LogSessionEvent", "RecordAssistantMessage"):
        # ищем только в коде замера (не в комментариях-запретах)
        code = "\n".join(l for l in probe_zone.splitlines() if not l.strip().startswith("//"))
        assert banned not in code, f"замер пишет в {banned} — нарушение запрета прохода"


def test_owner_commands_in_app():
    """A.4: команды владельца /seam* в app.mlog, рядом с /score."""
    idx_score = APP.index('starts_with(text, "/score ")')
    idx_seam = APP.index('starts_with(text, "/seam-probe")')
    idx_seam2 = APP.index('starts_with(text, "/seam ")')
    assert idx_score < idx_seam < idx_seam2, "команды /seam* должны идти рядом с /score"
    assert "SeamProbeQueuePush(dept)" in APP
    assert "SeamEnable(arg)" in APP and "SeamDisable(arg)" in APP
    assert "SeamStatusTable()" in APP


def test_seam_on_threshold_gate():
    """/seam on проверяет программно: свежесть 7 дней и порог 0.80, отказ с причиной."""
    enable = _block(APP, "pattern SeamEnable(")
    assert "замера нет" in enable
    assert "старше 7 дней" in enable
    assert "ниже 80%" in enable
    assert "CardSeamLastRunFresh(dept)" in enable
    assert "ok / n < 0.80" in enable


def test_one_off_scheduler_slot():
    """A.4: разовое задание — самоснимающийся слот нативного cron."""
    slot = _block(APP, "pattern SeamProbeSlot()")
    assert "cron_remove(" in slot, "слот обязан снимать себя при пустой очереди"
    ensure = _block(APP, "pattern SeamProbeCronEnsure()")
    assert '"SeamProbeSlot"' in ensure and "cron_add(" in ensure
    # вебхук не ждёт: ответ сразу, результат отдельным сообщением
    assert "результат придёт отдельным сообщением" in APP
    assert "SendTelegramReply(OwnerTelegramId()" in slot


def test_seam_off_all_global_switch():
    """/seam off all — глобальный выключатель, /seam off <dept> — отдел."""
    disable = _block(APP, "pattern SeamDisable(")
    assert '"all"' in disable and "'card_seam_enabled'" in disable
    assert '"card_seam_enabled:" + arg' in disable


def test_dept_list_single_source():
    """Отделы замера — один источник (CardSeamDepts), app.mlog его использует."""
    m = re.search(r"pattern CardSeamDepts\(\) -> List \{\n  return \[([^\]]*)\]", CARD)
    assert m, "нет списка отделов CardSeamDepts"
    listed = re.findall(r'"([a-z\-]+)"', m.group(1))
    assert sorted(listed) == sorted(SEAM_DEPTS), f"список отделов разошёлся: {listed}"


def test_help_mentions_seam():
    """/help перечисляет команды шва."""
    assert "/seam-probe <dept>" in APP and "/seam on|off <dept>" in APP
