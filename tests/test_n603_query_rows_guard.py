#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #603 B.3: статический гвард — parse_json(to_string(query())) запрещён.

F2: `to_string()` результата `query()` на 0.34.x даёт `[Row {…}]` — это не
JSON, `parse_json` бросает ошибку вне `try`, обработчик webhook падает
(`Handler error: parse_json() error: expected value at line 1 column 2`).
Тело ошибки уходит HTTP-ответом в Telegram и в stdout не попадает —
молчаливый обрыв BuildContext всех отделов, кроме Яны.

Гвард: для каждой переменной, присвоенной из `query(` (в т.ч. через
`TryVal(try query(…)`), в файле не должно быть `parse_json(to_string(<имя>))`.
Поиск регуляркой по именам переменных на уровне файла (строже «в пределах
паттерна» — допустимо по тексту наряда).

Мутация: вернуть старую строку `app.mlog:1149` — гвард обязан стать красным.
"""
import glob
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LET_RE = re.compile(r"^let\s+([A-Za-z_]\w*)\s*=\s*(.+)$")
QUERY_RE = re.compile(r"\bquery\(")


def _files():
    paths = [os.path.join(REPO, "app.mlog")]
    paths += sorted(glob.glob(os.path.join(REPO, "dept", "*.mlog")))
    return [p for p in paths if os.path.exists(p)]


def _violations(src):
    """[(имя, строка)] — query-переменные, читаемые через parse_json(to_string())."""
    names = set()
    for line in src.splitlines():
        m = LET_RE.match(line.strip())
        if m and QUERY_RE.search(m.group(2)):
            names.add(m.group(1))
    out = []
    for name in sorted(names):
        m = re.search(rf"parse_json\(to_string\({re.escape(name)}\)\)", src)
        if m:
            line_no = src[:m.start()].count("\n") + 1
            out.append((name, line_no))
    return out


def test_no_parse_json_to_string_of_query_results():
    bad = []
    for path in _files():
        src = open(path, encoding="utf-8").read()
        for name, line_no in _violations(src):
            bad.append(f"{os.path.relpath(path, REPO)}:{line_no} — parse_json(to_string({name}))")
    assert not bad, (
        "F2-класс: результат query() читается строковым кругом parse_json(to_string(…)) "
        "— на 0.34.x это молчаливый обрыв обработчика: " + "; ".join(bad))


def test_mutation_reverting_1149_is_caught():
    """Мутант «вернуть строку :1149» обязан быть пойман гвардом (результат — в PR)."""
    app = os.path.join(REPO, "app.mlog")
    src = open(app, encoding="utf-8").read()
    fixed = 'let merged = to_string(json_get(get(rows, 0), "merged", ""))'
    assert fixed in src, "фикс #603 B.1 в GetInjectedContext исчез"
    mutant = src.replace(
        fixed,
        'let merged = to_string(json_get(parse_json(to_string(rows)), "[0].merged", ""))')
    assert mutant != src, "мутация :1149 не применилась"
    v = _violations(mutant)
    assert any(name == "rows" for name, _ in v), (
        "гвард НЕ поймал мутацию :1149 (parse_json(to_string(rows))) — результат "
        "мутации: НЕ пойман")
