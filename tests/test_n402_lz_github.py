#!/usr/bin/env python3
"""Наряд #402: данные LZ Daily по GitHub (lz_github_updates) читаются отделом.

Запуск: python3 -m pytest tests/test_n402_lz_github.py -v

Контракт (#402):
  A.1 — команда /lz github [дни]: выборка из lz_github_updates, группировка
        релизы/репозитории, синтез ЛЗ поверх реальных записей, ссылки из данных.
  A.2 — BuildLZContext подмешивает записи при GitHub-теме запроса.
  A.3 — подвал «Источники:» показывает «LZ Daily (GitHub)», когда данные использованы.

Реальный путь (фикстура на интерпретаторе, отчёт наряда): HandleLZ("/lz github 7")
возвращает реальные записи с ссылками, выведенными из channel_name; пустая
таблица — честное «ничего не собрал»; подвал появляется только при GitHub-теме.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n402-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

LZ_SRC = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")


def test_command_exists_before_classification():
    """A.1: /lz github обрабатывается до доменной классификации."""
    assert 'if starts_with(t, "/lz github") then' in LZ_SRC
    cmd_idx = LZ_SRC.index('if starts_with(t, "/lz github") then')
    dom_idx = LZ_SRC.index("let domain = LZClassifyDomain(query)")
    assert cmd_idx < dom_idx, "/lz github — подкоманда, не свободный запрос"


def test_reads_real_table_not_imagination():
    """A.1: выборка из lz_github_updates; честное «ничего не собрал» на пустоте."""
    assert "FROM lz_github_updates" in LZ_SRC, (
        "таблица lz_github_updates так и не читается отделом")
    assert "ничего не собрал" in LZ_SRC, (
        "пустая таблица должна давать честное сообщение, не выдумку")


def test_links_derived_from_data():
    """A.1: ссылки выводятся детерминированно из channel_name (owner/repo),
    не генерируются моделью."""
    assert 'https://github.com/" + name' in LZ_SRC


def test_context_mixing_gated_by_topic():
    """A.2: подмешивание в свободный запрос — только при GitHub-теме."""
    assert "pattern LZGithubContextIfRelevant(query: String) -> String" in LZ_SRC
    seg = LZ_SRC[LZ_SRC.index("pattern LZGithubContextIfRelevant"):LZ_SRC.index("pattern LZContainsCyrillic")]
    for kw in ('"github"', '"гитхаб"', '"репозитор"', '"релиз"'):
        assert kw in seg, f"маркер темы {kw} не проверяется"
    assert "+ LZGithubContextIfRelevant(query)" in LZ_SRC, (
        "BuildLZContext должен включать GitHub-компонент")


def test_footer_marks_usage():
    """A.3: подвал источников отражает использование LZ Daily (GitHub)."""
    assert 'if contains(context, "LZ Daily (GitHub)") then' in LZ_SRC
    assert '\\n· LZ Daily (GitHub)' in LZ_SRC


def test_days_clamped():
    """A.1: дни зажаты 1..30, дефолт 7 — SQL-параметр безопасен."""
    seg = LZ_SRC[LZ_SRC.index("pattern LZGithubUpdates"):LZ_SRC.index("pattern LZGithubContextIfRelevant")]
    assert "if d <= 0.0 then { let d = 7.0 }" in seg
    assert "if d > 30.0 then { let d = 30.0 }" in seg
    assert "?1" in seg and "days" in seg, "дни идут связанным параметром"
