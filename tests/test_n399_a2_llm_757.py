#!/usr/bin/env python3
"""Гвард наряда #399 A.2: потолок max_tokens + видимая обрезка (Metalogos-#757).

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/399
Диспатч #403 Wave 3: гейт выполнен — Metalogos- #757 выпущен (тег v0.27.1,
мерж 260a33a — предок тега) И #401 закрыт.

A.2.1 — bin/mlog = 0.30.0 (релиз-артефакт тега, sha256 зафиксирован в ADR-0018;
       прошлый-хороший 0.27.1 вендорен как bin/mlog-0271), фича #757 живёт
       в линии 0.27.1+ — проверено на 0.30.0.
A.2.2 — app.mlog: llm { max_tokens: 8192 } сразу после providers (грамматика
        0.27.1: хвост — упорядоченная цепочка; поле до providers = parse).
A.2.3 — SendReport (dept/miniapp.mlog): пометка «ОТВЕТ ОБРЕЗАН» через
        llm_last_finish_reason() на общем пути доставки владельцу.
A.2.4 — entrypoint.sh: фолбэк-патч (0.20 не знает фичу — sed-вырезание из
        serve-копии; проверено: до патча 0.20 даёт parse-ошибку, после — 0).
#505 A.3 — фолбэк-конвейер пополнен вырезанием llm { timeout: 150 } (0.20
        поле не понимает): живая проба ниже воспроизводит фактический
        конвейер entrypoint целиком (оба sed + вырезание timeout).
Запуск: python -m pytest tests/test_n399_a2_llm_757.py -v
"""
import hashlib
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
MINIAPP = (REPO_ROOT / "dept" / "miniapp.mlog").read_text(encoding="utf-8")
ENTRYPOINT = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")


# ── A.2.1: бинарь 0.30.0 ──────────────────────────────────────────────────


def _version(binary: str) -> str:
    out = subprocess.run([str(REPO_ROOT / binary), "--version"],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip().splitlines()[0]


def test_battle_binary_is_0331():
    v = _version("bin/mlog")
    assert "0.33.1" in v, f"боевой бинарь должен быть 0.33.1 (релиз v0.33.1), получено: {v}"


def test_prev_good_binary_is_0271():
    v = _version("bin/mlog-0271")
    assert "0.27.1" in v, f"прошлый-хороший должен быть 0.27.1, получено: {v}"


def test_old_binaries_are_out():
    assert not (REPO_ROOT / "bin" / "mlog-025").exists(), \
        "mlog-025 выведен из репо (ADR-0012), восстанавливается из git-истории"
    assert not (REPO_ROOT / "bin" / "mlog-027").exists(), \
        "mlog-027 выведен из репо (ADR-0015), восстанавливается из git-истории"


def test_battle_binary_sha256_matches_artifact():
    # целостность релиз-артефакта тега v0.33.1 (sha256 из SHA256SUMS релиза; наряд #571)
    expected_prefix = "bef3e1b24e10aa909eb6250b71eb7b74911f8df6e8d758f029f991bd9131de98"
    h = hashlib.sha256((REPO_ROOT / "bin" / "mlog").read_bytes()).hexdigest()
    assert h == expected_prefix, f"bin/mlog sha256={h}, ожидание SHA256SUMS v0.33.1: {expected_prefix}"


def test_prev_good_binary_sha256_matches():
    # bin/mlog-0271 — тот самый бинарь 0.27.1, что был боевым (ADR-0012/0015)
    expected_prefix = "43fb5c7ad21f8dd9630cf26c548446f29a139209df9d4ba95bd0d4736dbba9b2"
    h = hashlib.sha256((REPO_ROOT / "bin" / "mlog-0271").read_bytes()).hexdigest()
    assert h == expected_prefix, f"bin/mlog-0271 sha256={h}, ожидание ADR-0012: {expected_prefix}"


# ── A.2.2: max_tokens в llm{} ─────────────────────────────────────────────


def test_max_tokens_present_after_providers():
    # грамматика 0.27.1: max_tokens идёт сразу после providers-списка
    assert "max_tokens: 8192," in APP, "llm { max_tokens } отсутствует (#399 A.2)"
    llm_block = APP[APP.index("llm {"):APP.index("max_tokens: 8192,")]
    assert "providers: [" in llm_block, \
        "max_tokens должен идти ПОСЛЕ providers (упорядоченный хвост грамматики 0.27.1)"


def test_max_tokens_rationale_documented():
    # обоснование значения зафиксировано рядом (требование чек-листа наряда)
    assert "верхний общий знаменатель output-лимитов" in APP
    assert "METALOGOS_LLM_MAX_TOKENS" in APP


# ── A.2.3: пометка обрезки в SendReport ───────────────────────────────────


def test_sendreport_checks_finish_reason():
    assert "llm_last_finish_reason()" in MINIAPP
    assert '"length"' in MINIAPP and '"max_tokens"' in MINIAPP
    assert "ОТВЕТ ОБРЕЗАН ПО ЛИМИТУ max_tokens" in MINIAPP


def test_sendreport_note_before_dispatch():
    # пометка добавляется ДО ветвления yana/admin → все отделы покрыты
    pattern_pos = MINIAPP.index("pattern SendReport(")
    note_pos = MINIAPP.index("trunc_note")
    branch_pos = MINIAPP.index('if dept == "yana" or dept == "admin"', pattern_pos)
    assert pattern_pos < note_pos < branch_pos


# ── A.2.4: фолбэк-патч entrypoint ─────────────────────────────────────────


def test_entrypoint_fallback_patch_exists():
    assert "/max_tokens: 8192,/d" in ENTRYPOINT, \
        "фолбэк-патч #399 отсутствует — 0.20 упадёт на llm { max_tokens }"
    assert 's/llm_last_finish_reason()/""/g' in ENTRYPOINT, \
        "фолбэк-патч #399: билтин не вырезается — 0.20 упадёт на parse"
    assert 'if [ "$MLOG_BIN" = "$MLOG_LEGACY" ]' in ENTRYPOINT


# ── живая проба фолбэк-патча (реальный mlog-020, не только текст) ─────────


def test_fallback_patched_file_parses_on_020():
    """Реальный путь фолбэка: аугмент + sed-патч → 0.20 check без parse error."""
    import os
    import tempfile
    aug = "{ printf '%s\\n' \"profile legacy { egress: permissive_with_audit }\"; cat app.mlog; }"
    with tempfile.TemporaryDirectory() as td:
        srv = os.path.join(td, "serve.mlog")
        subprocess.run(["bash", "-c", f"{aug} > {srv}"], cwd=REPO_ROOT, check=True)
        subprocess.run(["sed", "-i", "/max_tokens: 8192,/d", srv], check=True)
        # #505 A.3: фактический конвейер фолбэка entrypoint вырезает и timeout
        subprocess.run(["sed", "-i", "/^  timeout: 150,$/d", srv], check=True)
        subprocess.run(["sed", "-i", "s/llm_last_finish_reason()/\"\"/g", srv], check=True)
        out = subprocess.run([str(REPO_ROOT / "bin" / "mlog-020"), "check", srv],
                             capture_output=True, text=True, timeout=120)
        assert "parse error" not in out.stdout + out.stderr, \
            f"фолбэк-копия с патчем не должна давать parse error:\n{out.stdout[-600:]}"


def test_feature_file_parses_on_battle_binary():
    """Боевая копия (с фичей) на боевом бинаре 0.28.0 — 0 parse error."""
    out = subprocess.run([str(REPO_ROOT / "bin" / "mlog"), "check", "app.mlog"],
                         capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
    assert "parse error" not in out.stdout + out.stderr, \
        f"app.mlog с фичей #757 должен парситься боевым бинарем:\n{out.stdout[-600:]}"
