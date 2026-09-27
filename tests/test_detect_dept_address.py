#!/usr/bin/env python3
"""Наряд #404: обращение к отделу в начале сообщения определяет отдел раньше
подсчёта ключевых слов; «здравствуй» убран из слов Админа.

Запуск: python3 -m pytest tests/test_detect_dept_address.py -v
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
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n404-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import proxy.core as core  # noqa: E402 — атрибуты берём на момент вызова


def test_yana_address_wins_over_admin_keyword_inside():
    """«Яна, попроси Админа проверить логи» → yana (обращение раньше слов)."""
    assert core.detect_dept("Яна, попроси Админа проверить, есть ли ошибки в логах офиса за сегодня") == "yana"


def test_admin_address():
    assert core.detect_dept("Админ, проверь логи") == "admin"


def test_lz_colon_address():
    assert core.detect_dept("ЛЗ: новинки GitHub") == "lz"


def test_greeting_not_admin():
    """«Здравствуй» — приветствие, а не слово Админа (A.2)."""
    assert core.detect_dept("Здравствуй") == "yana"
    assert "здравствуй" not in core.RUSSIAN_KEYWORDS["admin"]


def test_no_address_keeps_phase2():
    """Без обращения поведение как раньше: слово «админ» внутри фразы работает."""
    assert core.detect_dept("попроси админа проверить логи") == "admin"


def test_slash_commands_unchanged():
    assert core.detect_dept("/lz новинки") == "lz"
    assert core.detect_dept("/admin") == "admin"


def test_address_requires_separator_or_end():
    """Слово внутри другого слова обращением не считается."""
    # «административный» — rest[0]='и' не разделитель → Phase 2 решает (юридические слова)
    assert core.detect_dept("административный иск к фонду") == "legal"
    # «dev» внутри «devops» — не обращение; отдел выбирает Phase 2 (слово «деплой»)
    assert core.detect_dept("devops практика: код и деплой") == "dev"
