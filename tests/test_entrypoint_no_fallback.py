#!/usr/bin/env python3
"""Гвард наряда #645: запасной путь Metalogos 0.20 (mlog-020) удалён.

Решение владельца 03.11: в офисе нет запасного бинарника 0.20.0 и логики
отката на него. Если кандидат не прошёл Category A пробу аудита
(MLOG_PROBE_RC не в {0, 2}) и MLOG_BIN_FORCE не задан — старт прерывается
громко (exit 1), Render оставляет предыдущий рабочий деплой.

Мутационный контракт (проверен, см. PR #645): заменить `exit 1` в ветке
провала пробы на `MLOG_BIN="$MLOG_LEGACY"` — тест обязан покраснеть.
Запуск: python -m pytest tests/test_entrypoint_no_fallback.py -v
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")


def test_no_legacy_fallback_tokens():
    """В entrypoint.sh не осталось ни переменных, ни строк отката на 0.20."""
    for token in ("MLOG_LEGACY", "mlog-020", "GRADUAL CUTOVER"):
        assert token not in ENTRYPOINT, (
            f"entrypoint.sh содержит {token!r} — запасной путь 0.20 "
            "должен быть удалён (решение владельца, #645)"
        )


def test_failed_probe_branch_is_loud_abort():
    """Провал пробы: FORCE-оверарайд сохранён, без него — exit 1."""
    # (а) сообщение громкого отказа присутствует
    assert "FAILED the Category A audit probe" in ENTRYPOINT
    assert "boot aborted; Render keeps the previous live deploy" in ENTRYPOINT
    # (б) FORCE-ветка сохранена без изменений (серв на проваленном кандидате)
    assert 'if [ -n "${MLOG_BIN_FORCE:-}" ]; then' in ENTRYPOINT
    assert 'MLOG_BIN="$MLOG_CANDIDATE"' in ENTRYPOINT
    assert "serving on the FAILED candidate anyway (operator override)" in ENTRYPOINT
    # (в) без FORCE ветка кончается exit 1, а не откатом на legacy-бинарь
    m = re.search(
        r'serving on the FAILED candidate anyway \(operator override\)"\n'
        r'\s*else\n\s*exit 1\n\s*fi',
        ENTRYPOINT,
    )
    assert m, (
        "после FORCE-ветки должен идти else -> exit 1 (громкий отказ, #645); "
        "появился откат на legacy — мутация или регресс"
    )


def test_missing_candidate_branch_is_loud_abort():
    """Кандидат не найден → бут прерывается, никаких замен бинаря."""
    m = re.search(
        r'candidate \$MLOG_CANDIDATE not found — boot aborted"\n\s*exit 1',
        ENTRYPOINT,
    )
    assert m, "отсутствующий кандидат должен прерывать бут (exit 1, #645)"
