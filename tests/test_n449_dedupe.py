#!/usr/bin/env python3
"""#449 волна D: гварды архивации DEAD-паттернов и дедуп-инвариантов.

Решения владельца 2026-10-02: DEAD — в архив (не удаление), STRING_ONLY/
TEST_ONLY/DOC_ONLY не трогать, дубли — охранная грамота ADR-0014.
"""
import importlib.util
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ARCHIVE = REPO_ROOT / "archive" / "dead-mlog"


def registry():
    spec = importlib.util.spec_from_file_location(
        "dead_pattern_registry", REPO_ROOT / "scripts" / "dead_pattern_registry.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.collect()


def test_prod_dead_is_zero():
    """После архивации в прод-замыкании нет ни одного DEAD-паттерна.
    Возвращение вырезанного — только осознанным переносом из архива."""
    data = registry()
    prod_dead = [
        name for name, info in data["patterns"].items()
        if info["status"] == "DEAD" and any(d["class"] == "prod" for d in info["definitions"])
    ]
    assert not prod_dead, f"DEAD-паттерны вернулись в прод-замыкание: {prod_dead}"


def test_archive_dir_exists_with_content():
    files = list(ARCHIVE.glob("*.mlog"))
    assert len(files) >= 20, f"archive/dead-mlog/ пуст или неполон: {len(files)} файлов"
    # у каждого архивного файла — шапка с происхождением (A.1 вырезка / A.3 перенос)
    for f in files:
        head = f.read_text(encoding="utf-8")[:400]
        assert any(t in head for t in ("#449 A.1", "АРХИВ DEAD", "АРХИВ неимпортируемого")), (
            f"{f.name}: нет шапки-происхождения"
        )


def test_archived_patterns_not_in_prod_files():
    """Вырезанные DEAD-паттерны физически отсутствуют в прод-файлах
    (выборочный контроль по одному из каждого исходного файла)."""
    probes = {
        "dept/design.mlog": "pattern GateDesignSystemDocs",
        "dept/qa.mlog": "pattern GateResearchForNewDomain",
        "dept/finance.mlog": "pattern FinanceOpBudget",
        "app.mlog": "pattern SaveToGenericArchive",
    }
    for rel, marker in probes.items():
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert marker not in src, f"{marker} должен остаться в архиве, не в {rel}"


def test_unimported_files_moved_to_archive():
    """2 неимпортируемых файла перенесены из dept/ в archive/ (решение владельца).
    Третий из аудита, forge_create_bridge.mlog, ВЕРНУТ в dept/: он не мёртв —
    Python-слой запускает его как standalone entry-point (`mlog run`,
    routes_admin /api/forge/projects, гвард test_forge_ui12)."""
    for name in ("forge_model.mlog", "handlers_fallback.mlog"):
        assert not (REPO_ROOT / "dept" / name).exists(), f"{name} должен быть в archive/"
        assert (ARCHIVE / name).exists(), f"{name} не найден в archive/dead-mlog/"
    # живой мост остаётся в dept/
    assert (REPO_ROOT / "dept" / "forge_create_bridge.mlog").exists()


def test_dept_md_documents_moved_to_docs():
    """Прозаические документы не живут в каталоге кода dept/ (аудит #449)."""
    assert (REPO_ROOT / "docs" / "naryad-mlg2.md").exists()
    assert (REPO_ROOT / "docs" / "report-mlg2.md").exists()
    assert not (REPO_ROOT / "dept" / "naryad-mlg2.md").exists()
    assert not (REPO_ROOT / "dept" / "report-mlg2.md").exists()


def test_duplicates_baseline_matches_adr():
    """Дубли определений — ровно 7 (было 8; EnforceHardRules ушёл из дублей
    при переходе 0.28.0: QA-вариант переименован в QaEnforceHardRules —
    гейт №523 запрещает дубли с РАЗНОЙ арностью; ADR-0014, дополнение).
    Каждый дубликат упомянут в ADR-0014.
    Появление нового дубликата — сигнал к дедуп-решению (ADR-0014, следствие 2)."""
    adr = (REPO_ROOT / "docs" / "adr" / "0014-duplicate-patterns-departmental-voice.md").read_text(encoding="utf-8")
    data = registry()
    dupes = sorted(name for name, info in data["patterns"].items() if info["duplicate"])
    # наряд #514 (2026-10-16): недетерминированный бут — все дубли разведены
    # переименованием с dept-контекстом, список 7 → 0 (ADR-0014, дополнение 2).
    assert len(dupes) == 0, f"дубли паттернов вернулись: {dupes} — голоса отделов разводить по ADR-0014 (дополнение 2)"
    assert "Дополнение 2026-10-16" in adr, "ADR-0014 не фиксирует разводку #514"


def test_string_only_slot_patterns_intact():
    """Slot-паттерны планировщика не архивированы — они живы через
    строковый диспетчер dept/schedules.mlog (решение владельца: не трогать)."""
    src = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
    for name in ("MorningSlot", "NightTickSlot", "WeeklySlot", "EveningSlot",
                 "LzDailySlot", "OnlinerWarmSlot"):
        assert f"pattern {name}" in src, f"{name} потерян — STRING_ONLY не подлежит архивации"
