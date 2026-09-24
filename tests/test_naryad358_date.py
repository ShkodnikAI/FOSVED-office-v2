#!/usr/bin/env python3
"""naryad-358: дата в промпте /yana/auto-memorize динамическая (Europe/Minsk).

Было: «...based on today being 2026-07-06» — зашитая июльская дата; любое
«напомни завтра» сохранялось от 2026-07-06, напоминания уходили не в тот
день или никогда.

Проверка (реальный прогон эндпоинта, LLM-провайдер замокан):
- в системном промпте нет зашитой 2026-07-06;
- в промпте реальная сегодняшняя дата (Europe/Minsk — конвенция /now-time);
- факт-напоминание «завтра в 10» попадает в yana_events датой завтра
  относительно РЕАЛЬНОГО сегодня.
"""
import json as _json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-naryad358-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query, app  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app
import proxy.routes_tail as rt  # noqa: E402


def test_auto_memorize_uses_real_today(monkeypatch):
    tz = ZoneInfo("Europe/Minsk")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")

    captured = {}

    def fake_provider(_prov, _model, prompt, **kw):
        captured['prompt'] = prompt
        # модель честно считает «завтра» от даты из промпта
        return {"reply": _json.dumps([
            {"content": "позвонить в автосервис по гарантии", "type": "commitment",
             "date": f"{tomorrow} 10:00", "confidence": 0.9}
        ])}

    monkeypatch.setattr(rt, '_call_single_provider', fake_provider)

    # yana_events (стор напоминаний планировщика) — минимальная схема
    _query("CREATE TABLE IF NOT EXISTS yana_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_text TEXT, event_date TEXT, event_type TEXT)")

    client = app.test_client()
    resp = client.post('/yana/auto-memorize', json={
        'query': 'Напомни завтра в 10 позвонить в автосервис по гарантии',
        'reply': 'Хорошо, напоминание поставлено: завтра в 10:00 позвонить в автосервис.',
        'chat_id': '555000',
    })
    body = resp.get_json() or {}
    assert resp.status_code == 200 and body.get('status') == 'ok', body

    sys_prompt = captured['prompt'][0]['content']
    assert '2026-07-06' not in sys_prompt, 'зашитая июльская дата осталась в промпте'
    assert f'today being {today}' in sys_prompt, 'в промпте не реальная сегодняшняя дата'

    # напоминание реально в yana_events датой завтра от реального сегодня
    rows = _query("SELECT event_date FROM yana_events WHERE event_text LIKE ? ORDER BY rowid DESC LIMIT 1",
                  ('%автосервис%',), fetch=True)
    assert rows, 'напоминание не сохранилось в yana_events'
    assert rows[0][0] == f"{tomorrow} 10:00", f"дата в памяти {rows[0][0]} != завтра {tomorrow}"
