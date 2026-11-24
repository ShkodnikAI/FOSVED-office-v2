#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #603 D.1 (мутации): обе мутации обязаны ловиться кейсами D.1.

Отдельный файл от test_delegation_serve.py: фикстура `office` того модуля —
module-scoped и держит порт боя, пока идут кейсы; мутантам нужен свободный
порт. Результаты мутаций фиксируются в PR (форма волны).

- revert_1149 (parse_json(to_string(rows)) в GetInjectedContext) + сеянная
  инъекция владельца → BuildContext рвётся, /ask dept=design не происходит;
- drop_default_dispatch (убрать вызов DispatchYanaDelegation в ветке по
  умолчанию) → голый slug "design" уходит владельцу в /tg-send (F3).
"""
import pathlib
import re
import shutil
import sqlite3
import tempfile

import pytest

from tests.test_delegation_serve import (  # noqa: E402
    ROOT,
    _OfficeServe,
    _Stub,
    _port_busy,
    _seed_owner_injection,
    PROXY_PORT,
)


def _mutant_office(tmp: pathlib.Path, kind: str):
    """Сервер на мутантной копии app.mlog."""
    src = (ROOT / "app.mlog").read_text(encoding="utf-8")
    if kind == "revert_1149":
        fixed = 'let merged = to_string(json_get(get(rows, 0), "merged", ""))'
        mutant = src.replace(
            fixed,
            'let merged = to_string(json_get(parse_json(to_string(rows)), "[0].merged", ""))')
    elif kind == "drop_default_dispatch":
        # #771 E: делегирование в ветке по умолчанию под гвардом — мутант
        # снимает вызов, оставляя del пустым: голый slug уходит в /tg-send
        block = ('        let del = TryVal(try DispatchYanaDelegation(reply, text, chat_id))\n'
                 '        if to_string(del) == "()" then {')
        mutant = src.replace(block, '        let del = ""\n        if to_string(del) == "XX" then {')
    else:
        raise AssertionError(kind)
    assert mutant != src, f"мутация {kind} не применилась"
    out = tmp / f"app_mutant_{kind}.mlog"
    out.write_text(("profile legacy { egress: permissive_with_audit }\n"
                    if not re.search(r"^profile legacy", src, re.M) else "") + mutant,
                   encoding="utf-8")
    return _OfficeServe(out, tmp)


@pytest.fixture(scope="module")
def stub():
    if _port_busy(PROXY_PORT):
        pytest.skip(f"порт {PROXY_PORT} занят — прокси уже запущен в этом окружении")
    s = _Stub()
    yield s
    s.stop()


def _with_version():
    version = ROOT / "VERSION"
    created = not version.exists()
    if created:
        version.write_text("n603-mutant-test\n", encoding="utf-8")
    return created, version


def test_mutation_revert_1149_is_killed_by_case1(stub):
    """Мутант :1149 + НЕпустые строки query() (сеянная инъекция) — кейс ловит.

    Результат мутации: ПОЙМАНА — parse_json(to_string(Row)) рвёт BuildContext,
    /ask dept=design не происходит; #771 E: маршрут деградирует честно
    (гвард → честный отказ владельцу), Handler error больше не обязателен."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="n603-mutA-"))
    created, version = _with_version()
    serve = None
    try:
        serve = _mutant_office(tmp, "revert_1149")
        # #728 B.1: /health больше не поднимает схему — таблицу инъекции
        # создаём сами (до первого вебхука), как Flask на проде.
        con = sqlite3.connect(tmp / "office.db")
        try:
            con.execute("CREATE TABLE IF NOT EXISTS team_board (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "from_dept TEXT NOT NULL, kind TEXT NOT NULL, topic TEXT NOT NULL, "
                        "tags TEXT DEFAULT '[]', payload TEXT DEFAULT '', sources TEXT DEFAULT '', "
                        "severity TEXT DEFAULT '', delivered INTEGER DEFAULT 0, "
                        "created_at TEXT DEFAULT (datetime('now')), expires_at TEXT)")
            con.commit()
        finally:
            con.close()
        _seed_owner_injection(tmp / "office.db")  # НЕпустые rows — иначе парс не достигается
        stub.reset_calls()
        stub.detect = "yana"
        r = serve.webhook(9100004)
        depts = [d for d, _ in stub.asks()]
        assert "design" not in depts, (
            "мутант :1149 неотличим от оригинала — кейс 1 НЕ поймал мутацию; "
            f"asks={depts}")
        # результат мутации: ПОЙМАНА — сеянная инъекция теряется, делегирования
        # к design нет (выше). #771 E: маршрут теперь деградирует ЧЕСТНО — бросок
        # отдела внутри DispatchYanaDelegation ловится гвардом маршрута: честный
        # отказ владельцу и маркер вместо Handler error 500, rc=200 корректен.
        assert "Handler error" in r.text or r.status_code == 200, (
            f"мутант проявился иначе ожидаемого: rc={r.status_code}, asks={depts}, "
            f"body={r.text[:200]}")
    finally:
        if serve is not None:
            serve.stop()
        if created:
            version.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)


def test_mutation_drop_default_dispatch_is_killed_by_case2(stub):
    """Мутант «убрать DispatchYanaDelegation из ветки по умолчанию» — кейс ловит.

    Результат мутации: ПОЙМАНА — голый slug "design" уходит владельцу в /tg-send (F3)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="n603-mutB-"))
    created, version = _with_version()
    serve = None
    try:
        serve = _mutant_office(tmp, "drop_default_dispatch")
        stub.reset_calls()
        stub.detect = ""
        r = serve.webhook(9100005)
        leaked = [b for b in stub.tg_sends() if str(b.get("text", "")) == "design"]
        assert leaked, (
            "мутант «убрать DispatchYanaDelegation из ветки по умолчанию» "
            "неотличим от оригинала — кейс 2 НЕ поймал мутацию; "
            f"tg_sends={[str(b.get('text',''))[:60] for b in stub.tg_sends()][:5]}")
    finally:
        if serve is not None:
            serve.stop()
        if created:
            version.unlink(missing_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
