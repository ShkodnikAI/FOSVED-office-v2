"""Наряд №378: гварды Engineering — вызов объявленных гейтов, честная верификация,
переключатель нормативной базы RF|BY|EU.

Дефекты наряда (до исполнения):
- EngGateImmutable / EngGateSafetyFactor объявлены и никогда не вызывались;
- verification_agrees = true хардкод — каждый расчёт помечался self_verified;
- нормативная база Tier1 — только RF, переключателя нет.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENG = (REPO_ROOT / "dept" / "engineering.mlog").read_text(encoding="utf-8")
CONSTITUTION = (REPO_ROOT / "library" / "engineering.md").read_text(encoding="utf-8")
# #447/ADR-0013: единый источник текста отдела — library/engineering.md
# (departments/engineering.md несёт только frontmatter + @include-директиву)


def _calls(src: str, name: str) -> list:
    """Строки с вызовом pattern (объявление не считается)."""
    return [
        line for line in src.splitlines()
        if f"{name}(" in line and f"pattern {name}" not in line
        and not line.strip().startswith("//")
    ]


def test_gates_declared_and_called():
    """Оба гейта объявлены И вызываются живым кодом (не только в объявлениях)."""
    assert "pattern EngGateImmutable(file_path: String)" in ENG
    assert "pattern EngGateSafetyFactor(factor: String)" in ENG
    # EngGateImmutable вызывается из GuardMutable (обёртка immunity-гейта)
    imm_calls = _calls(ENG, "EngGateImmutable")
    assert imm_calls, "EngGateImmutable объявлен, но не вызывается"
    assert any("GuardMutable" in line or "gate = EngGateImmutable" in line for line in imm_calls)
    # EngGateSafetyFactor вызывается в FullPipeline (Step 5.5)
    sf_calls = _calls(ENG, "EngGateSafetyFactor")
    assert any("sf_gate" in line for line in sf_calls), "EngGateSafetyFactor не вызывается в треке"


def test_guard_mutable_wired_into_mutators():
    """GuardMutable стоит перед мутациями записи расчёта (4 точки)."""
    assert "pattern GuardMutable(calc_id: String)" in ENG
    calls = _calls(ENG, "GuardMutable")
    assert len(calls) >= 4, f"GuardMutable вызывается {len(calls)} раз, ожидается >= 4"
    # Каждая из четырёх мутаторов содержит вызов гейта до db_execute UPDATE
    for fn in ("SetNormBase", "SetLoadCases", "IndependentVerify", "EngineerReview"):
        seg = ENG[ENG.index(f"pattern {fn}"):]
        seg = seg[:seg.index("\npattern ", 10)] if "\npattern " in seg[10:] else seg
        assert "GuardMutable(" in seg, f"{fn} не защищён GuardMutable"


def test_immutable_zone_mapping():
    """Карта зон: engineer_approved/archived → calc_verified; system_lockdown → lockdown."""
    assert 'if kv_get("system_lockdown") == "true" then { return "lockdown" }' in ENG
    assert "STATUS_ENGINEER_APPROVED() then { return \"calc_verified\" }" in ENG
    assert "STATUS_ARCHIVED() then { return \"calc_verified\" }" in ENG


def test_verification_agrees_not_hardcoded():
    """Хардкод verification_agrees = true устранён; состояние из реального сигнала Route-2."""
    assert "let verification_agrees = true" not in ENG, "хардкод verification_agrees = true остался"
    assert 'let verification_agrees = verification_state == "agreed"' in ENG
    assert 'verification_state = "unavailable"' in ENG
    assert 'verification_state = "disagreed"' in ENG
    # недоступность верификатора — честный статус, не true
    assert "verification_unavailable" in ENG
    assert "self_verified НЕ присвоен" in ENG
    # magnitud-проверка используется для вердикта, а не выбрасывается
    assert "Порядок величины (\" + verification_state" in ENG


def test_verification_unavailable_persists_honestly():
    """DB-колонка verification_agrees хранит 'unavailable' (TEXT), а не ложный true/false."""
    assert 'if verification_state == "unavailable" then { let va_str = "unavailable" }' in ENG
    # DDL: verification_agrees TEXT — вместит three-state (DDL однострочный)
    app = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    ddl_line = next((l for l in app.splitlines()
                     if "CREATE TABLE IF NOT EXISTS engineering_calculations" in l), "")
    assert ddl_line and "verification_agrees TEXT" in ddl_line


def test_normbase_switch():
    """Переключатель RF|BY|EU: GetNormSystem читает config, дефолт RF; вызовы без хардкода."""
    assert "pattern GetNormSystem()" in ENG
    assert 'read_file("config/engineering_normbase.txt")' in ENG
    assert 'if nb == "BY"' in ENG and 'if nb == "EU"' in ENG
    # хардкод "RF" в вызовах устранён
    assert 'SetNormBase(parsed.calc_id, parsed.discipline, "RF", "")' not in ENG
    assert 'SetNormBase(parsed.calc_id, parsed.discipline, GetNormSystem(), "")' in ENG
    assert 'let norm_system = "RF"' not in ENG
    assert "let norm_system = GetNormSystem()" in ENG


def test_norm_packs_rf_by_eu():
    """Дефолт-паки для трёх систем присутствуют (RF-пак сохранён дословно)."""
    assert "pattern GetDefaultNormsFor(discipline: String, norm_system: String)" in ENG
    # RF-пак сохранён
    assert "СП 20.13330" in ENG and "ПУЭ" in ENG and "ГОСТ Р 52869" in ENG
    # BY-пак
    assert "СН 2.04.01-2020" in ENG and "ГОСТ 30331.1" in ENG
    # EU-пак
    assert "EN 1990" in ENG and "ISO 4413" in ENG and "IEC 60364" in ENG
    # GetDefaultNorms делегирует RF (обратная совместимость)
    assert 'return GetDefaultNormsFor(discipline, "RF")' in ENG
    # SetNormBase берёт дефолты под norm_system расчёта, а не RF всегда
    assert "GetDefaultNormsFor(discipline, norm_system)" in ENG


def test_safety_gate_threshold_config():
    """Порог гейта: пол 1.5 кодифицирован, config может только повышать; не-число — PASS."""
    assert 'read_file("config/engineering_min_safety_factor.txt")' in ENG
    assert "let mut min_f = 1.5" in ENG
    assert "if min_cfg > min_f then { let min_f = min_cfg }" in ENG
    assert 'if to_string(f) == "()" then { return "PASS" }' in ENG


def test_config_files_present_and_valid():
    """Config-файлы существуют с валидными дефолтами."""
    nb = (REPO_ROOT / "config" / "engineering_normbase.txt").read_text(encoding="utf-8").strip()
    assert nb in ("RF", "BY", "EU"), f"недопустимое значение normbase: {nb!r}"
    sf = (REPO_ROOT / "config" / "engineering_min_safety_factor.txt").read_text(encoding="utf-8").strip()
    assert float(sf) >= 1.5, f"config понижает пол запаса прочности: {sf}"


def test_constitution_sync():
    """Конституция отдела синхронизирована с гейтами (порог 1.5, RF|BY|EU, неизменяемость)."""
    assert "1.5" in CONSTITUTION
    assert "RF | BY | EU" in CONSTITUTION
    assert "EngGateImmutable" in CONSTITUTION


def test_disclaimer_not_weakened():
    """Граница наряда: дисклеймер «ПРЕДВАРИТЕЛЬНО» не ослаблен."""
    assert "WrapWithDisclaimer(result)" in ENG
    assert "contains(result, \"ПРЕДВАРИТЕЛЬНО\")" in ENG
