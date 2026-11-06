"""Наряд #679 (D-qa): QA на карточке — шов в ответах HandleQA,
завершение прогона с программным вердиктом, /qa-release → ReleaseGate,
время устранения дефектов.

Структурные гвардии; поведенческие проверки — mlog-тесты dept/qa.mlog
(n679). Мутация «убрать вызов шва» красит test_seam_on_all_qa_answer_sites;
мутации «считать MTTR от updated_at» и «убрать coverage-цель из вердикта»
красят mlog-тесты n679 A.4/A.2 (см. отчёт наряда).
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QA = (REPO_ROOT / "dept" / "qa.mlog").read_text(encoding="utf-8")
CARD = (REPO_ROOT / "dept" / "card.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def _block(src: str, start_marker: str) -> str:
    start = src.index(start_marker)
    nxt = src.find("\npattern ", start + 10)
    nxt2 = src.find("\ntest ", start + 10)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return src[start:min(ends)] if ends else src[start:]


def test_seam_on_all_qa_answer_sites():
    """A.1: шов подключён ко ВСЕМ 8 точкам ответов ИИ владельцу.

    CmdQAStrategy, CmdQATest, CmdQADefect (LLM-ветка), CmdQAEval,
    CmdQASecurityAudit, CmdQACoverage, CmdQAMonitor, FullQAPipeline.
    Без шва остаются: CmdQADefects/CmdQARuns (данные БД), ShowQAHelp
    (статика), CmdQARunDone/CmdQARelease (программные ответы — по наряду
    шов только на ответах ИИ), QaRiskReview — ответ КОЛЛЕГЕ (team-навык).
    """
    prod = QA[: QA.index("pattern N679InsertTestRunStarted")]
    sites = prod.count('CardSeamVerdict("qa", reply, 0.0)')
    assert sites == 8, f"шов должен стоять на всех 8 точках ответа ИИ владельцу, найдено {sites}"
    # каждый вызов сопровождается strip-веткой (портируемой: strip под try)
    strips = prod.count("let stripped = TryVal(try CardTailStrip(reply))")
    assert strips == 8
    # QaRiskReview — не шов (ответ коллеге, как FinanceCalc в #670)
    risk = _block(QA, "pattern QaRiskReview(")
    assert "CardSeamVerdict" not in risk
    # программные команды — не шов
    rd = _block(QA, "pattern CmdQARunDone(")
    rel = _block(QA, "pattern CmdQARelease(")
    assert "CardSeamVerdict" not in rd
    assert "CardSeamVerdict" not in rel
    # ветки create/close CmdQADefect — системные строки без ИИ: ровно один
    # вызов шва на весь обработчик
    defect = _block(QA, "pattern CmdQADefect(")
    assert defect.count('CardSeamVerdict("qa", reply, 0.0)') == 1


def test_run_done_program_verdict():
    """A.2: программный вердикт, переход только из started, отказ повтору."""
    rd = _block(QA, "pattern CmdQARunDone(")
    # апдейт прогона: completed + счётчики + вердикт + timestamps
    assert "UPDATE test_runs SET status = 'completed'" in rd
    assert "verdict = ?" in rd and "completed_at = datetime('now')" in rd
    # вердикт считает программа: pass — failed=0 И coverage ≥ QA_COV_OVERALL
    assert "QA_COV_OVERALL()" in rd
    assert 'let mut verdict = "pass"' in rd and 'let verdict = "fail"' in rd
    assert "ниже цели" in rd
    # переход только из started; повтор/неизвестный id — отказ с причиной
    assert "только из started" in rd
    assert "не найден" in rd
    # регистрация команды
    parse = _block(QA, "pattern ParseQAQuery(")
    assert 'contains(q, "/qa-run-done")' in parse
    handle = _block(QA, "pattern HandleQA(")
    assert "cmd:qa-run-done" in handle


def test_release_cmd_calls_gate():
    """A.3: /qa-release → ReleaseGate; гейт судит по данным test_runs и defect_records."""
    rel = _block(QA, "pattern CmdQARelease(")
    assert "ReleaseGate(project, environment, isAISystem, projectFeatures, chat_id)" in rel
    parse = _block(QA, "pattern ParseQAQuery(")
    assert 'contains(q, "/qa-release")' in parse
    handle = _block(QA, "pattern HandleQA(")
    assert "cmd:qa-release" in handle

    gate = _block(QA, "pattern ReleaseGate(")
    # вердикт pass нового формата (qa-run-done) признаётся наравне с passed
    assert 'trVerdict == "passed" or trVerdict == "pass"' in gate
    # открытые critical/high дефекты блокируют
    assert "severity IN ('critical', 'high')" in gate
    assert "status NOT IN ('verified', 'wontfix', 'duplicate')" in gate


def test_mttr_block():
    """A.4: QAMttrBlock — медиана created_at → verified_at, MTTD честно не считается."""
    assert "pattern QAMttrBlock() -> String" in QA
    mttr = _block(QA, "pattern QAMttrBlock(")
    # источник — verified_at и created_at (НЕ updated_at: мутация «считать от
    # updated_at» красит mlog-тест n679 A.4 — updated_at фикстуры ≠ расчётной базе)
    assert "julianday(verified_at) - julianday(created_at)" in mttr
    # обе severity из наряда
    assert "severity = 'critical'" in mttr and "severity = 'high'" in mttr
    # честное нет данных + честный MTTD
    assert "время устранения: нет данных" in mttr
    assert "MTTD: не считается — нет момента внесения дефекта" in mttr
    # цель правил QA: critical ≤4ч; округление round(x*100)/100
    assert "цель ≤4ч" in mttr
    assert "round(" in mttr
    # вывод в /qa-monitor
    mon = _block(QA, "pattern CmdQAMonitor(")
    assert "QAMttrBlock()" in mon


def test_new_commands_do_not_break_existing_routing():
    """Новые команды не перекрывают существующие: /qa-runs не ловит /qa-release и др."""
    parse = _block(QA, "pattern ParseQAQuery(")
    # порядок проверок: /qa-run-done и /qa-release добавлены после /qa-monitor
    runs_idx = parse.index('contains(q, "/qa-runs")')
    rundone_idx = parse.index('contains(q, "/qa-run-done")')
    release_idx = parse.index('contains(q, "/qa-release")')
    assert runs_idx < rundone_idx < release_idx


def test_app_mlog_untouched():
    """Шаг 0.3: правка app.mlog в этом наряде не делается (маркер #679 не появляется)."""
    assert "#679" not in APP
    assert "qa-run-done" not in APP
    assert "qa-release" not in APP
