"""#245: Тест-барьер — запрет повторных top-level def в одном модуле (AST).

Ловит класс shadowing-багов: повторное определение функции на уровне модуля
молча затирает первое при импорте. Методы классов не считаются top-level
(разбор через AST, не regex) — `QuotaTracker.note_rate_limited` и модульный
враппер `note_rate_limited` в resilience.py легитимно сосуществуют.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _module_files():
    """Все python-модули продукта: proxy/*.py + корневые *.py."""
    files = sorted((ROOT / "proxy").glob("*.py"))
    files += sorted(p for p in ROOT.glob("*.py") if p.is_file())
    return [p for p in files]


def _top_level_dups(source: str):
    """[(name, [lines])] повторных top-level def/async def в исходнике."""
    tree = ast.parse(source)
    seen: dict = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seen.setdefault(node.name, []).append(node.lineno)
    return {n: ls for n, ls in seen.items() if len(ls) > 1}


@pytest.mark.parametrize("path", _module_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_duplicate_top_level_defs(path):
    source = path.read_text(encoding="utf-8", errors="replace")
    dups = _top_level_dups(source)
    assert not dups, (
        f"{path.relative_to(ROOT)}: повторные top-level def "
        f"(второе молча затирает первое): "
        + ", ".join(f"{n} @ строки {ls}" for n, ls in dups.items())
    )


def test_detector_catches_artificial_dup():
    """Барьер барьера: детектор действительно ловит дубль, иначе тест бесполезен."""
    src = "def foo():\n    return 1\n\n\ndef foo():\n    return 2\n"
    assert "foo" in _top_level_dups(src)


def test_detector_ignores_class_methods():
    """Метод класса и модульная функция с одинаковым именем — не дубль (разные ns)."""
    src = (
        "class A:\n"
        "    def note(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "def note():\n"
        "    return 2\n"
    )
    assert _top_level_dups(src) == {}
