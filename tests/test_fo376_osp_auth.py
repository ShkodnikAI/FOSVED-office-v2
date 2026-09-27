"""Наряд №376 (P1): runtime-гвард auth /osp/analyze — обе формы секрета.

Баг (аудит 25.09): expected строился как H(secret) и сравнивался как
H(received) vs H(expected)=H(H(secret)) — двойной хэш при неидемпотентном
redact (0.24/0.25) делал raw-форму (cron-стиль) непроходимой всегда.
Hash-form (мост LZ→ОСП №318) продолжала проходить — потому реальный мост
был жив, а все cron-стиль пробы (/osp/analyze?secret=RAW) — всегда 403.

Фикс: сравнение против ОДНОГО H(secret); принимаются обе формы:
  (а) hash-form дословно (lz.mlog: redact(env,"hash_only"));
  (б) raw: redact(received,"hash_only") == H(secret).
Предварительный redact("all") сохранён (taint-валидатор Wave 15).

Гвард гоняет scripts/fo376_probe_auth.sh — изолированный mlogserver
(scripts/probe318qp.mlog, роут /qp2 = точная реплика роута app.mlog) —
на обоих бинарях (боевой 0.27.0 + гвард 0.25.0, ADR-0009) и ассертит матрицу.

ВНИМАНИЕ: probe-скрипты — локальные инструменты (scripts/ в .gitignore,
не трекаются); на свежем клоне тест честно SKIP'ается, верификация
воспроизводится по процедуре отчёта №376/ADR.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "scripts" / "fo376_probe_auth.sh"

pytestmark = pytest.mark.skipif(
    not PROBE.exists(), reason="probe-скрипт — локальный незатреканный инструмент (gitignore scripts/)")

EXPECTED_ROWS = [
    ("raw correct", "match [HTTP 200]"),
    ("hash-form", "match [HTTP 200]"),
    ("raw wrong", "mismatch [HTTP 403]"),
    ("none", "mismatch [HTTP 403]"),
    ("selfcheck", "selfcheck-match [HTTP 200]"),
]
BINS = ["bin/mlog", "bin/mlog-025"]


def _probe_output() -> str:
    proc = subprocess.run(["bash", str(PROBE)], capture_output=True, text=True,
                          timeout=180, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, (
        f"пробник упал rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )
    assert "serve boot FAILED" not in proc.stdout, f"бут не удался:\n{proc.stdout}"
    return proc.stdout


def _blocks(out: str) -> dict:
    """Разбор вывода на блоки по '=== <bin> ==='."""
    blocks = {}
    current = None
    for line in out.splitlines():
        if line.startswith("=== "):
            current = line.strip("= ").strip()
            blocks[current] = []
        elif current is not None and ":" in line and line.startswith("  "):
            blocks[current].append(line.strip())
    return blocks


def test_auth_matrix_both_forms_both_binaries():
    """Матрица: raw=200, hash-form=200, wrong=403, none=403, selfcheck=200."""
    blocks = _blocks(_probe_output())
    for b in BINS:
        assert b in blocks, f"нет блока {b} в выводе пробника: {list(blocks)}"
        rows = {}
        for r in blocks[b]:
            if " : " in r:
                k, v = r.split(" : ", 1)
                rows[k.strip()] = v.strip()
        for label, expected in EXPECTED_ROWS:
            got = rows.get(label, "<missing>")
            assert got == expected, f"{b}: {label}: ожидалось {expected}, получено {got}"


def test_old_double_hash_pattern_gone_from_qp2_and_app():
    """Статика: /qp2 в пробнике и app.mlog несут одинарный hash-compare."""
    probe_mlog = (REPO_ROOT / "scripts" / "probe318qp.mlog").read_text(encoding="utf-8")
    app = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    fixed = 'if received != expected and redact(received, "hash_only") != expected'
    assert fixed in probe_mlog, "в probe318qp.mlog /qp2 нет фиксированного паттерна"
    assert '"/qp2"' in probe_mlog, "в probe318qp.mlog нет роута /qp2"
    assert fixed in app, "в app.mlog /osp/analyze нет фиксированного паттерна"
