"""Гвард exec-бит вендоренных бинарей (инцидент 2026-09-25, хвост наряда №372).

Бинарь заменялся через GitHub API (CI-артефакт) — моды в git стали 100644,
docker build падал на chmod удалённого mlog-023, деплой не проходил, прод
остался без Metalogos. Контракт (Dockerfile, №419/№349): exec-бит должен
жить в самом git (100755). Этот тест ловит регресс мод ДО деплоя.
"""
from pathlib import Path
import stat

REPO_ROOT = Path(__file__).resolve().parent.parent

# Все вендоренные бинари, которые entrypoint/Dockerfile обязаны уметь запустить.
VENDORED_BINARIES = [
    "bin/mlog",       # боевой (ADR-0009: 0.27.0)
    "bin/mlog-020",   # аварийный фолбэк guard-пробы
    "bin/mlog-025",   # прошлый-хороший / тест-гвард (ADR-0009)
]


def _mode(path: Path) -> int:
    # мода из git-индекса, а не из рабочей копии: локальный chmod без
    # коммита не должен давать зелёный тест
    out = []
    import subprocess
    r = subprocess.run(
        ["git", "ls-files", "-s", str(path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    out = r.stdout.split()
    # git ls-files -s отдаёт моду восьмеричной строкой ("100755") — парсить с базой 8
    return int(out[0], 8) if out else 0


def test_vendored_binaries_have_exec_bit_in_git():
    missing = []
    for rel in VENDORED_BINARIES:
        p = REPO_ROOT / rel
        assert p.exists(), f"{rel} отсутствует в репо"
        git_mode = _mode(p) & 0o777
        if not git_mode & stat.S_IXUSR:
            missing.append(f"{rel}: git-mode {oct(git_mode)}, ожидается 100755")
    assert not missing, (
        "exec-бит потерян в git (класс инцидента 2026-09-25): " + "; ".join(missing)
    )


def test_dockerfile_does_not_chmod_removed_binaries():
    # регресс №372: chmod ссылался на выведенный mlog-023 → build breaker
    df = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    for removed in ("mlog-022", "mlog-023"):
        assert f"/office/bin/{removed}" not in df, (
            f"Dockerfile ссылается на выведенный из репо {removed} "
            "(build breaker, инцидент 2026-09-25)"
        )
