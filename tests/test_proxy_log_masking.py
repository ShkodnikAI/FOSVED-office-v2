#!/usr/bin/env python3
"""№423: маскирование секретов в access-логах reverse_proxy.

Контекст (инцидент 2026-09-22): CRON_SECRET ходит в query string внешних
кронов (cron-job.org), werkzeug пишет строку запроса целиком — секрет попал
в лог Render. Владелец решил секрет НЕ ротировать; компенсация — маскирование
secret=/token=/password= значений в лог-записях werkzeug.

Гвард держит два инварианта:
  1. LogRecord с чувствительным query уходит хендлерам уже замаскированным.
  2. Обычные записи (без секретов) не трогаются, битые не роняют логирование.
"""
import logging
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-mask-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from reverse_proxy import QuerySecretMasker, SENSITIVE_QUERY_RE  # noqa: E402


def _record(message: str, args: tuple = ()) -> logging.LogRecord:
    return logging.LogRecord(
        name="werkzeug",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )


class TestQuerySecretMasking:
    """QuerySecretMasker вырезает значения чувствительных query-параметров."""

    @pytest.mark.parametrize(
        "line,hidden,kept",
        [
            # инцидент 2026-09-22 — точная форма строки из лога Render
            ('"GET /cron/morning?secret=SuperSecret42 HTTP/1.1" 403',
             "SuperSecret42", "secret=<redacted>"),
            ('"GET /schedules/list?secret=SuperSecret42 HTTP/1.1" 200',
             "SuperSecret42", "secret=<redacted>"),
            # token (INTERNAL_API_TOKEN тоже ходит в query — /version?token=)
            ('"GET /version?token=InternalTok99 HTTP/1.1" 200',
             "InternalTok99", "token=<redacted>"),
            ('"GET /lockdown?password=Pass123 HTTP/1.1" 200',
             "Pass123", "password=<redacted>"),
            ('"GET /ask?api_key=KeyAbc HTTP/1.1" 200',
             "KeyAbc", "api_key=<redacted>"),
            # несколько чувствительных параметров в одной строке
            ('"GET /cron/night-tick?secret=S1&token=T2 HTTP/1.1" 200',
             "S1", "secret=<redacted>&token=<redacted>"),
            # замечание 3 аудита (#451): t= — статичный токен гварда /repos (#442)
            ('"GET /repos/task/decide?t=ReposTok77 HTTP/1.1" 403',
             "ReposTok77", "t=<redacted>"),
            # и HMAC-токен досье SHOP-5 (соседний q=2 не задет)
            ('"GET /shop/dossier/x?t=abc&q=2 HTTP/1.1" 200',
             "abc", "t=<redacted>&q=2"),
            # версия werkzeug с полным URL в сообщении об ошибке
            ("Proxy error: 404 on http://127.0.0.1:10001/cron/x?secret=Zz9",
             "Zz9", "secret=<redacted>"),
        ],
    )
    def test_masks_sensitive_values(self, line, hidden, kept):
        record = _record(line)
        masker = QuerySecretMasker()
        assert masker.filter(record) is True
        rendered = record.getMessage()
        assert hidden not in rendered, f"секрет утёк в лог: {rendered}"
        assert kept in rendered

    @pytest.mark.parametrize(
        "line",
        [
            # без секретов — не трогаем
            '"GET /health HTTP/1.1" 200',
            '"GET /miniapp/ HTTP/1.1" 200',
            "Waiting for LLM proxy... (1)",
            # нечувствительные параметры остаются как есть
            # (t= теперь чувствительный — проверяем соседние, не начинающиеся с t=)
            '"GET /shop/dossier/x?q=2 HTTP/1.1" 200',
            '"GET /shop/list?limit=10&format=json HTTP/1.1" 200',
        ],
    )
    def test_passes_normal_lines_through(self, line):
        record = _record(line)
        assert QuerySecretMasker().filter(record) is True
        assert record.getMessage() == line

    def test_sensitive_names_case_insensitive(self):
        record = _record('"GET /x?SECRET=Up HTTP/1.1" 403')
        QuerySecretMasker().filter(record)
        assert "Up" not in record.getMessage()
        assert "SECRET=<redacted>" in record.getMessage()

    def test_broken_record_does_not_raise(self):
        # args mismatch → getMessage() падает; фильтр обязан пропустить запись
        record = logging.LogRecord(
            name="werkzeug", level=logging.INFO, pathname=__file__, lineno=1,
            msg="broken %s %s", args=("only-one",), exc_info=None,
        )
        assert QuerySecretMasker().filter(record) is True

    def test_filter_installed_on_werkzeug_logger(self):
        # reverse_proxy импортирован → фильтр уже на логгере werkzeug
        werkzeug_filters = logging.getLogger("werkzeug").filters
        assert any(isinstance(f, QuerySecretMasker) for f in werkzeug_filters)

    def test_regex_covers_registered_param_names(self):
        for name in ("secret", "token", "password", "api_key", "apikey", "t"):
            assert SENSITIVE_QUERY_RE.search(f"?{name}=v"), name
            assert SENSITIVE_QUERY_RE.search(f"&{name}=v"), name
