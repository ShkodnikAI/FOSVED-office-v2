#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""№424: гвард env-allowlist в entrypoint.sh.

Политика: ценз env( по app.mlog/dept — НИЖНЯЯ ГРАНИЦА списка
METALOGOS_ENV_ALLOWLIST. Оверрайд из дашборда Render может только
ДОБАВЛЯТЬ имена. Находка №424: оверрайд затирал дефолт целиком — в проде
env("CRON_SECRET") читался, а env("INTERNAL_API_TOKEN") давал 500
ENV_NOT_PERMITTED, /version лежала (живая проба 2026-09-22).

Тест извлекает guard-блок прямо из entrypoint.sh между маркерами
BEGIN/END (защита от copy-drift) и исполняет его в bash с разными входами.
"""
import os
import shlex
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRYPOINT = os.path.join(REPO_ROOT, "entrypoint.sh")

BEGIN = "# BEGIN №424 env-allowlist guard"
END = "# END №424 env-allowlist guard"


def _extract_block() -> str:
    src = open(ENTRYPOINT, encoding="utf-8").read()
    assert BEGIN in src, f"нет начального маркера guard-блока в {ENTRYPOINT}"
    assert END in src, "нет конечного маркера guard-блока"
    start = src.index(BEGIN)
    end = src.index(END)
    assert start < end, "маркеры guard-блока перепутаны местами"
    return src[start:end]


def _run_guard(census: str, override: str | None) -> list[str]:
    """Исполняет guard-блок и возвращает итоговый список имён."""
    block = _extract_block()
    script = (
        f"METALOGOS_ENV_ALLOWLIST_CENSUS={shlex.quote(census)}\n"
        + (
            f"export METALOGOS_ENV_ALLOWLIST={shlex.quote(override)}\n"
            if override is not None
            else "unset METALOGOS_ENV_ALLOWLIST\n"
        )
        + block
        + "\nprintf '%s' \"$METALOGOS_ENV_ALLOWLIST\"\n"
    )
    out = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, f"bash упал: {out.stderr}"
    raw = out.stdout.strip()
    return [n for n in raw.split(",") if n]


def _census_from_entrypoint() -> str:
    """Ценз берём из той же строки METALOGOS_ENV_ALLOWLIST_CENSUS=… в entrypoint."""
    for line in open(ENTRYPOINT, encoding="utf-8"):
        if line.strip().startswith('METALOGOS_ENV_ALLOWLIST_CENSUS="'):
            return line.split('"')[1]
    raise AssertionError("строка METALOGOS_ENV_ALLOWLIST_CENSUS не найдена в entrypoint.sh")


def test_entrypoint_has_guard_block():
    block = _extract_block()
    assert "METALOGOS_ENV_ALLOWLIST_CENSUS" in block
    assert "case" in block  # цикл долива имён присутствует


def test_no_override_full_census():
    census = _census_from_entrypoint()
    assert _run_guard(census, None) == census.split(",")
    # пустая строка-оверрайд = unset (bash ${VAR:-default})
    assert _run_guard(census, "") == census.split(",")


def test_partial_override_restores_missing_names():
    # находка №424: дашборд задал только CRON_SECRET — INTERNAL_API_TOKEN
    # и остальные имена обязаны вернуться
    census = _census_from_entrypoint()
    got = _run_guard(census, "CRON_SECRET")
    assert "CRON_SECRET" in got
    assert "INTERNAL_API_TOKEN" in got
    assert "OWNER_TELEGRAM_ID" in got
    assert "TELEGRAM_BOT_TOKEN" in got
    assert set(got) == set(census.split(","))


def test_override_can_only_add_names():
    census = _census_from_entrypoint()
    got = _run_guard(census, "CRON_SECRET,MY_CUSTOM_VAR,INTERNAL_API_TOKEN")
    assert "MY_CUSTOM_VAR" in got  # кастомное имя сохранено
    assert set(census.split(",")) <= set(got)  # весь ценз присутствует
    assert got.count("CRON_SECRET") == 1  # без дублей
    assert got.count("INTERNAL_API_TOKEN") == 1


def test_guard_is_idempotent():
    census = _census_from_entrypoint()
    once = ",".join(_run_guard(census, "CRON_SECRET,EXTRA_ONE"))
    twice = ",".join(_run_guard(census, once))
    assert once == twice


def test_census_covers_auth_and_cron_names():
    """Критичные имена auth/кронов обязаны быть в цензе entrypoint."""
    census = _census_from_entrypoint()
    for name in (
        "CRON_SECRET",
        "INTERNAL_API_TOKEN",
        "LOCKDOWN_PASSWORD",
        "OWNER_TELEGRAM_ID",
        "TELEGRAM_BOT_TOKEN",
        "DATABASE_URL",
    ):
        assert name in census.split(","), f"{name} отсутствует в цензе entrypoint"
