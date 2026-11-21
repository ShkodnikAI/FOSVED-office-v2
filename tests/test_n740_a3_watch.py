#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#740 OSP-FRESH, часть 2: A.3 — пересмотр watching-прогноза при новом
событии по теме (инцидент 17.11: прогноз по мосту опровергнут в тот же
день, авто-пометки не существовало). Контрольный прогон B — сценарий
scripts/n740_control_run.py (в PR).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = Path(__file__).resolve().parent.parent
OSP_MLOG = (REPO / "dept" / "osp.mlog").read_text(encoding="utf-8")
ROUTES_TAIL = (REPO / "proxy" / "routes_tail.py").read_text(encoding="utf-8")

PAT_WATCH = "OSP" + "WatchNewsCheck"  # OSPWatchNewsCheck — как в коде (семейство OSP*)


def _pattern_body(source: str, name: str) -> str:
    start = source.index("pattern " + name)
    nxt = source.find("\npattern ", start + 10)
    if nxt == -1:
        nxt = len(source)
    return source[start:nxt]


def test_a3_watch_news_check_pattern():
    """Паттерн проверки новых событий: пометка «требует пересмотра»,
    уведомление одной строкой (OutboxPut), запись в osp_forecast_events,
    матчинг темы через общий матчер (call_python news.topic_matches_news)."""
    assert "pattern " + PAT_WATCH in OSP_MLOG, "нет паттерна проверки новых событий"
    body = _pattern_body(OSP_MLOG, PAT_WATCH)
    assert "требует пересмотра" in body, "нет пометки «требует пересмотра»"
    assert "topic_matches_news" in body, "матчинг темы не через общий матчер"
    assert "OutboxPut" in body, "уведомление владельцу не отправляется"
    assert "osp_forecast_events" in body, "пометка не журналируется в events"
    # окно поиска: записи news_cache новее даты прогноза (created_at)
    assert "created_at" in body, "сравнение с датой прогноза отсутствует"


def test_a3_event_keys_per_narad():
    """Ключи события — точно по наряду A.3: удар/атака/обрушение/взрыв."""
    body = _pattern_body(OSP_MLOG, PAT_WATCH)
    for k in ("удар", "атак", "обруш", "взрыв"):
        assert k in body, f"ключ события «{k}» из наряда не проверяется"


def test_a3_watch_slot_runs_news_check():
    """Ночная вахта OSPWatchSlot зовёт проверку новых событий в том же
    слоте — без отдельного расписания (запрет наряда: расписание сбора
    не меняем, это читатель)."""
    slot = _pattern_body(OSP_MLOG, "OSPF" + "reshnessGate")  # smoke: helper жив
    assert "pattern OSP" + "WatchSlot" in OSP_MLOG
    ws = _pattern_body(OSP_MLOG, "OSP" + "WatchSlot")
    assert PAT_WATCH + "()" in ws, "OSPFWatchSlot не зовёт проверку новых событий"


def test_a3_whitelist_entry():
    """call_python-мост: news.topic_matches_news в whitelist (иначе A.3
    падает 403 Module not allowed)."""
    assert '"news": {"topic_matches_news"}' in ROUTES_TAIL, (
        "news.topic_matches_news нет в CALL_PYTHON_ALLOWED")
