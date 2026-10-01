#!/usr/bin/env python3
"""Наряд #400: ЛЗ больше не выбрасывает свой ответ при инвестиционном сигнале.

Запуск: python3 -m pytest tests/test_n400_lz_referral.py -v

Контракт (#400):
  A.1 — ответ ЛЗ отдаётся всегда; пересылка — дополнение (строка-пометка).
  A.2 — один строгий триггер: LZGateOSPReferral (YES/NO); INVEST_REFERRAL
        из генерирующего промпта удалён; двойных пересылок нет.
  A.3 — /lz invest — явная пересылка по команде (была только в дисклеймере).
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
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n400-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

LZ_SRC = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")


def test_generating_prompt_has_no_invest_prefix():
    """A.2: префикс-инструкция снята из генерирующего промпта."""
    assert "Если это involves investment" not in LZ_SRC, (
        "генерирующий промпт всё ещё просит модель ставить INVEST_REFERRAL — "
        "модель решала без строгого критерия, «новинки GitHub» улетали в ОСП")
    assert 'if starts_with(result, "INVEST_REFERRAL")' not in LZ_SRC, (
        "префиксная ветка с выбросом ответа ЛЗ всё ещё в коде")


def test_lz_answer_is_never_replaced():
    """A.1: ответ ЛЗ возвращается всегда; при REFERRED — только дополнение."""
    assert 'return disclaimer + "\\n" + result + LZSourcesFooter(context, live) + referral_note' in LZ_SRC, (
        "главный возврат HandleLZ должен нести ответ ЛЗ + подвал источников + пометку")
    assert "🔄 Передано в ОСП для инвестиционного анализа\"" not in LZ_SRC.replace(
        "Передано в ОСП для инвестиционного анализа: «", ""), (
        "остался возврат, заменяющий ответ ЛЗ строкой пересылки")
    assert 'let mut referral_note = ""' in LZ_SRC
    assert 'if starts_with(ref, "REFERRED") then' in LZ_SRC


def test_single_referral_trigger():
    """A.2: ровно один гейт-триггер; POST /osp/analyze — ровно в двух местах
    (гейт + явная команда /lz invest), один запрос исполняет максимум один."""
    # #427: в гейт ОСП уходит чистая тема topic_query = LZStripCommand(query),
    # а не сырой текст команды (текст команды в Tavily уводил выдачу в сторону)
    assert LZ_SRC.count("LZGateOSPReferral(topic_query)") == 1, (
        "гейт должен вызываться из HandleLZ ровно один раз (аргумент topic_query, #427)")
    posts = LZ_SRC.count('http_post("http://127.0.0.1:10001/osp/analyze')
    # #446 A.2 (2026-10-02): третий легитимный отправитель — LZInflectionDetect
    # (инфлекшн-алерт, решение владельца: построить через живой /osp/analyze;
    # раньше ходил на несуществующий :4000/osp/inflection-alert)
    assert posts == 3, (
        f"POST /osp/analyze в lz.mlog должен быть ровно 3 (гейт + /lz invest + "
        f"inflection-alert #446 A.2), сейчас {posts} — дубли одного запроса недопустимы")
    assert "INVEST_REFERRAL" in LZ_SRC, (
        "упоминание INVEST_REFERRAL должно остаться только в комментарии истории #400")


def test_explicit_invest_command():
    """A.3: /lz invest существует и доступен до доменной классификации."""
    assert 'if starts_with(t, "/lz invest") then' in LZ_SRC, (
        "дисклеймер обещает /lz invest — команда должна существовать")
    invest_idx = LZ_SRC.index('if starts_with(t, "/lz invest") then')
    domain_idx = LZ_SRC.index("let domain = LZClassifyDomain(query)")
    assert invest_idx < domain_idx, (
        "/lz invest должен обрабатываться до доменной классификации (как остальные подкоманды)")
    assert 'type: "explicit_invest"' in LZ_SRC, (
        "явная пересылка помечается типом explicit_invest в audit-цепочке ОСП")


def test_gate_pattern_untouched_contract():
    """Гейт остаётся YES/NO-вызовом с fire-and-forget (№318: redact-hash)."""
    assert "pattern LZGateOSPReferral(query: String) -> String" in LZ_SRC
    gate_seg = LZ_SRC[LZ_SRC.index("pattern LZGateOSPReferral"):LZ_SRC.index("pattern LZGateCompetingCheck")]
    assert 'if result == "YES" then' in gate_seg
    assert 'redact(env("CRON_SECRET"), "hash_only")' in gate_seg, (
        "секрет в мосте №318 ходит только односторонним redact-hash")
