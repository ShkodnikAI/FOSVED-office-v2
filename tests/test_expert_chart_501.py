#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#267: POST /expert/chart — честный 501 вместо необъяснимого 500.

Аудит #244: маршрут вызывал несуществующий scripts/expert_charts.py
(+ мусорный fallback на путь с чужой машины /home/z/...) — любой вызов
гарантированно падал 500 без объяснения.

Гварды:
- POST /expert/chart отвечает 501 с человеческим объяснением (и с
  данными, и без);
- в исходниках репозитория нет пути с чужой машины (/home/z/my-project);
- мёртвая ссылка на expert_charts.py из python-кода убрана.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n267-chart-test")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402


def _client():
    return flask_app.test_client()


def test_chart_with_data_returns_501():
    r = _client().post("/expert/chart", json={
        "chart_type": "residual_value",
        "data": {"vehicle": "BMW X5", "years": [1, 2, 3], "values": [80, 65, 50]},
    })
    assert r.status_code == 501, f"ожидался честный 501, получено {r.status_code}"
    assert "error" in r.get_json(), "ответ должен содержать объяснение"


def test_chart_without_data_still_501():
    r = _client().post("/expert/chart", json={})
    assert r.status_code == 501, "маршрут обязан отвечать 501 немедленно, без theater 400/500"


def test_no_alien_machine_paths_in_sources():
    sources = (sorted((ROOT / "proxy").glob("*.py"))
               + [ROOT / "app.mlog", ROOT / "dogfood_staging.mlog"]
               + sorted((ROOT / "dept").glob("*.mlog")))
    needle = "/home/z/" + "my-project"
    bad = [p.name for p in sources if needle in p.read_text(encoding="utf-8")]
    assert not bad, f"путь с чужой машины в исходниках: {bad}"


def test_no_dead_script_reference():
    tail_lines = (ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8").splitlines()
    live = [ln for ln in tail_lines
            if ln.strip() and not ln.strip().startswith("#")]
    bad = [ln.strip()[:120] for ln in live if "expert_charts.py" in ln]
    assert not bad, (
        f"routes_tail.py всё ещё ссылается на несуществующий expert_charts.py: {bad}")
