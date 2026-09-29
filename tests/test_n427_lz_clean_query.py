"""Гвард наряда #427: чистый запрос ЛЗ + честный подвал источников.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/427
A.1 — паттерн LZStripCommand; запрос без префикса команды уходит во внешний
      поиск (LZTavilySearch), в извлечение темы (LZExtractTopic), в гейт ОСП
      и в промпт синтеза общего пути.
A.2 — подвал источников показывает Tavily/APIscan только при реальных данных,
      маркеры-отказы не считаются источниками.
Запуск: python -m pytest tests/test_n427_lz_clean_query.py -v
Живой тест: test_n427v1.mlog (в корне, конвенция репо) (16 проверок, mlog run).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")


def test_strip_command_pattern_exists():
    assert "pattern LZStripCommand(text: String) -> String" in LZ
    # оба префикса (латиница и кириллица) и идемпотентность задокументированы
    assert '"/lz"' in LZ and '"/лз"' in LZ


def test_general_path_uses_clean_topic():
    # в общем пути HandleLZ тема чистится один раз и используется везде
    assert "let topic_query = LZStripCommand(query)" in LZ
    assert "LZClassifyDomain(topic_query)" in LZ, "классификатор домена получает команду"
    assert "BuildLZContext(topic_query" in LZ, "контекст собирается по команде"
    assert "LZGateOSPReferral(topic_query)" in LZ, "гейт ОСП решает по команде"
    assert "LZTavilySearch(topic_query, chat_id)" in LZ, "в Tavily уходит команда"
    assert "topic_query + \"\\nContext: \"" in LZ, "промпт синтеза получает команду"
    # пустая тема не уходит в полный путь
    assert "if topic_query == \"\"" in LZ


def test_tavily_and_topic_extractor_strip_internally():
    # LZTavilySearch и LZExtractTopic вызываются и из домен-веток — чистка
    # внутри, идемпотентная
    assert "let q = LZStripCommand(query)" in LZ
    assert "TavilySearch(q, \"lz\")" in LZ, "TavilySearch получает неочищенный запрос"
    assert '"Запрос: " + q + ' in LZ, "синтез Tavily по команде, не по теме"


def test_footer_hides_failure_markers():
    # маркеры-отказы Tavily — не источники
    assert 'starts_with(live_trim, "[tavily:") == false' in LZ
    assert 'starts_with(live_trim, "[оценка недоступна") == false' in LZ


def test_footer_recognizes_successful_apiscan():
    # предсуществующий дефект: при находке контекст "APIscan (тема: …):"
    # не содержал подстроки "APIscan:" — источник не показывался вовсе
    assert 'contains(context, "APIscan (тема:")' in LZ


def test_empty_tavily_results_are_marker_string():
    # пустая выдача и нерелевантные результаты возвращаются маркером-строкой,
    # который подвал не считает источником
    assert '"[tavily: релевантных результатов нет]"' in LZ
    assert "не по теме запроса]" in LZ, "модель не имеет строгого маркера нерелевантности"


def test_no_regression_subcommand_branches():
    # домен-ветки диспетчера не тронуты: их substring-вырезания на месте
    for head in ('"/lz politics"', '"/lz github"', '"/lz watch add"', '"/lz deep"'):
        assert f"starts_with(t, {head})" in LZ, f"ветка {head} исчезла"
