#!/usr/bin/env python3
"""Наряд #366: квест-модуль нативно — ноль мёртвых вызовов /api/quest/*.

Было: QuestCreate/QuestList/QuestStatus (dept/quest.mlog) звали пять
несуществующих Flask-роутов /api/quest/* — /quest list, new, status были
мертвы, /quest send докладывал «Paket otpravlen» при упавшем вызове.

Стало: create/list/status работают нативно из БД (each + рекурсивный CTE);
send/generate — честный отказ (почтового контура в офисе нет).

Проверка: статические гварды + детектор мёртвых вызовов; живой прогон
паттернов — test_naryad366.mlog (8 проверок, запускается в CI mlog-работе
локально: DATABASE_URL=sqlite:/tmp/n366/t.db ./bin/mlog run test_naryad366.mlog).
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEST_RAW = (REPO_ROOT / "dept" / "quest.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def _code(text):
    """mlog-комментарии (//) вырезаются — гварды смотрят только код."""
    return "\n".join(line.split("//")[0] for line in text.splitlines())


QUEST = _code(QUEST_RAW)


def test_zero_api_quest_calls():
    """Чек-лист наряда: grep 'api/quest' dept/quest.mlog → ноль."""
    assert "api/quest" not in QUEST, "в quest.mlog остались мёртвые вызовы /api/quest/*"


def test_native_patterns_use_each_and_sql():
    """list/status/create формируются из БД без HTTP."""
    assert "each r in rows" in QUEST, "QuestList потерял нативное форматирование"
    assert "each c in crows" in QUEST, "QuestStatus потерял чтение чекпоинтов"
    assert "WITH RECURSIVE seq(n)" in QUEST, "QuestCreate потерял CTE-создание чекпоинтов"


def test_honest_refusal_no_false_send():
    """send/generate — честный отказ; ложное «Paket otpravlen» удалено."""
    assert "Paket otpravlen" not in QUEST
    assert "quest_send_unavailable" in QUEST
    assert "quest_generate_unavailable" in QUEST
    assert "ne realizovana" in QUEST


def test_help_marks_send_honestly():
    """/quest help помечает send как не реализованный."""
    assert "ne realizovano" in APP, "в /quest help нет честной пометки про send"


def test_no_template_param_collision():
    """Лексер mlog 0.23: латинское t-word (template) в сигнатурах/литералах
    dept/quest.mlog ломает компиляцию (__TEMPLATE_BODY_N) — не вернуть."""
    for line in QUEST.splitlines():
        body = line.strip()
        if body.startswith("//"):
            continue
        assert "template" not in body.lower(), f"слово 'template' в коде quest.mlog: {line}"


def test_detector_quest_clean():
    """Детектор мёртвых вызовов: ни одного /api/quest в мёртвых."""
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "deadcall_detector.py")],
                          capture_output=True, text=True, timeout=60)
    out = proc.stdout + proc.stderr
    assert "Flask-роутов" in out, f"детектор не запустился: {out[:300]}"
    for line in out.splitlines():
        assert "api/quest" not in line or "МЁРТВЫЕ" not in line, \
            f"/api/quest числится мёртвым: {line}"
