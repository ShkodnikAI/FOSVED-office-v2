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
        block = ('      let del = DispatchYanaDelegation(reply, text, chat_id)\n'
                 '      if del != "1" then {')
        mutant = src.replace(block, '      if 1.0 > 0.0 then {')
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
    /ask dept=design не происходит (Handler error или обрыв делегирования)."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="n603-mutA-"))
    created, version = _with_version()
    serve = None
    try:
        serve = _mutant_office(tmp, "revert_1149")
        _seed_owner_injection(tmp / "office.db")  # НЕпустые rows — иначе парс не достигается
        stub.reset_calls()
        stub.detect = "yana"
        r = serve.webhook(9100004)
        depts = [d for d, _ in stub.asks()]
        assert "design" not in depts, (
            "мутант :1149 неотличим от оригинала — кейс 1 НЕ поймал мутацию; "
            f"asks={depts}")
        # результат мутации: поймана — Handler error или делегирование оборвалось
        assert ("Handler error" in r.text) or ("yana" not in depts), (
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
