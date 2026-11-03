#!/usr/bin/env python3
"""Наряд #505: нативный call_llm — таймаут 30 с и бесполезный резерв провайдеров.

Барьер по тексту файлов (A.1–A.3). Критерии наряда:
(1) в блоке llm {} app.mlog есть timeout со значением 120–280 с включительно;
(2) первый провайдер — alias: deepseek, пока default_model — deepseek-chat
    (единственная модель, которую обслуживает deepseek; остальные провайдеры
    её не принимают — без этого порядка резерва фактически нет);
(3) запасной путь 0.20 (вырезавший timeout из serve-копии) удалён 03.11
    (решение владельца, наряд #645) — гвард снят вместе с веткой;
(4) timeout стоит после max_tokens (грамматика 0.27.1: упорядоченный хвост).
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(REPO, "app.mlog")
ENTRY = os.path.join(REPO, "entrypoint.sh")


def _app_text() -> str:
    with open(APP, encoding="utf-8") as f:
        return f.read()


def _entry_text() -> str:
    with open(ENTRY, encoding="utf-8") as f:
        return f.read()


def _llm_block(text: str) -> str:
    """Текст блока llm { ... } верхнего уровня (до закрывающей скобки колонки 0)."""
    m = re.search(r"^llm \{\n(.*?)^\}", text, re.M | re.S)
    assert m, "app.mlog: не найден блок llm {}"
    return m.group(1)


def test_a1_timeout_in_range():
    """(1) В llm {} есть timeout: значение 120–280 включительно."""
    block = _llm_block(_app_text())
    m = re.search(r"^  timeout: (\d+),$", block, re.M)
    assert m, "в блоке llm {} нет строки '  timeout: N,'"
    value = int(m.group(1))
    assert 120 <= value <= 280, f"timeout {value} вне диапазона 120..280"


def test_a2_deepseek_first():
    """(2) Первый провайдер deepseek, пока default_model — deepseek-chat."""
    block = _llm_block(_app_text())
    first = re.search(r"^    \{ alias: (\w+),", block, re.M)
    assert first, "не найден первый провайдер в providers"
    assert first.group(1) == "deepseek", (
        f"первый провайдер {first.group(1)}, ожидался deepseek "
        "(default_model deepseek-chat обслуживает только deepseek)"
    )
    order = re.findall(r"alias: (\w+)", block)
    rest = [a for a in order if a != "deepseek"]
    assert rest == ["kimi", "zai", "groq", "cerebras", "sakana"], (
        f"относительный порядок остальных провайдеров нарушен: {rest}"
    )
    assert 'default_model: "deepseek-chat"' in block, (
        "default_model сменился — порядок deepseek-первым пересмотреть"
    )


def test_a4_timeout_after_max_tokens():
    """(4) timeout идёт после max_tokens (грамматика 0.27.1)."""
    block = _llm_block(_app_text())
    mt = re.search(r"^  max_tokens: \d+,$", block, re.M)
    to = re.search(r"^  timeout: \d+,$", block, re.M)
    assert mt and to, "нет max_tokens или timeout в llm {}"
    assert mt.start() < to.start(), (
        "timeout должен стоять ПОСЛЕ max_tokens (грамматика 0.27.1: "
        "упорядоченный хвост блока llm)"
    )
