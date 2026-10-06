"""Барьер: каждая переменная окружения, которую читает mlog (env/env_or),
разрешена переписью ALLOWLIST_CENSUS в entrypoint.sh.

Инцидент 2026-10-06: #474 и #467 ввели OSP_TAVILY_DAILY_BUDGET,
OSP_TAVILY_CACHE_MIN, ALPHAVANTAGE_API_KEY, но не добавили их в перепись.
С 0.26 чтение неразрешённой переменной в обработчике — ENV_NOT_PERMITTED
(env_or не спасает), ОСП падал на любом вопросе («не удалось получить ответ»).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _census():
    s = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    m = re.search(r'ALLOWLIST_CENSUS="([^"]+)"', s)
    assert m, "в entrypoint.sh нет ALLOWLIST_CENSUS"
    return set(n for n in re.split(r"[,\s]+", m.group(1).strip()) if n)


def _read_names():
    names = {}
    files = [ROOT / "app.mlog"] + sorted((ROOT / "dept").glob("*.mlog"))
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            for m in re.finditer(r'(?<![A-Za-z_])env(?:_or)?\("([A-Z0-9_]+)"', line):
                names.setdefault(m.group(1), f"{f.relative_to(ROOT)}:{i}")
    return names


def test_every_env_read_is_in_census():
    census = _census()
    missing = {n: loc for n, loc in _read_names().items() if n not in census}
    assert not missing, (
        "mlog читает переменные, не разрешённые переписью ALLOWLIST_CENSUS в entrypoint.sh "
        "(на проде — ENV_NOT_PERMITTED): " + ", ".join(f"{n} ({loc})" for n, loc in sorted(missing.items()))
    )
