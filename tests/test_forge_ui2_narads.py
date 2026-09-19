#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-2 tests (#195): экран «Наряды» — список + открытие со стоп-гейтом.

Гварды чек-листа (статические по миниаппу + поведенческие по Flask):
- фильтры 4 групп с РЕАЛЬНЫМИ счётчиками (считаются из /api/narads, не захардкожены);
- три статус-бейджа (.badge.progress/.done/.wait) осмысленными цветами через токены UI-0;
- полоса прогресса только у in_work, процент из реальных меток жизненного цикла;
- этапы: stage-dot done/active/pending, подписи под кружками;
- стоп-гейт: рамка var(--red), у каждого варианта заголовок И последствия;
  гейт НЕ рендерится, если решения не требуется (только pending);
  решение уходит на СУЩЕСТВУЮЩИЕ эндпоинты /api/narads/<id>/approve|reject;
- журнал строится из реальных данных (метки narads + шаги narad_steps), не выдуманный;
- backend: /api/narads отдаёт dept/priority/in_work; /api/narads/<id> — деталь
  с планом/критериями и шагами журнала; только чтение существующих таблиц,
  миграций и новых механизмов записи нет (прямое требование наряда).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui2-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

NARADS_SQL = (
    "CREATE TABLE IF NOT EXISTS narads (id TEXT PRIMARY KEY, title TEXT, description TEXT, "
    "requested_by TEXT, changed_files TEXT, risk_level TEXT, status TEXT, "
    "created_at TEXT DEFAULT (datetime('now')), approved_at TEXT, executed_at TEXT, result TEXT, "
    "dept TEXT, priority TEXT DEFAULT 'normal', plan TEXT, acceptance TEXT, "
    "test_status TEXT DEFAULT 'none', test_log TEXT, report TEXT, dispatch_id TEXT, "
    "rework_count INTEGER DEFAULT 0, in_work_at TEXT, testing_at TEXT)"
)

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def narads_schema():
    _query(NARADS_SQL)
    _query("DELETE FROM narads")
    from proxy.narad_queue import ensure_schema
    ensure_schema()
    _query("DELETE FROM narad_steps")
    yield
    _query("DELETE FROM narads")
    _query("DELETE FROM narad_steps")


# ── A.1 Фильтры ──────────────────────────────────────────────────────────

def test_filters_four_groups_real_counters():
    assert '<div class="filters" id="naradFilters"' in INDEX
    for label in ("Все", "В работе", "Ждёт меня", "Готово"):
        assert f'"{label}"' in INDEX
    # счётчики считаются, а не вписаны руками (макетный «Все · 4» запрещаем)
    assert 'Все · 4' not in INDEX
    assert 'c[naradGroup(x.status)]++' in INDEX
    assert '{all:naradCache.length,work:0,wait:0,done:0}' in INDEX


def test_active_filter_red_fill():
    assert '.filter.on{background:var(--red);color:var(--surface);border-color:var(--red);font-weight:600}' in INDEX
    assert '.filters{display:flex;gap:8px;overflow-x:auto' in INDEX  # горизонтальная прокрутка


# ── A.2 Карточка наряда ──────────────────────────────────────────────────

def test_badges_three_meaningful_colors():
    assert '.badge.progress{color:var(--yellow)}' in INDEX
    assert '.badge.done{color:var(--green)}' in INDEX
    assert '.badge.wait{color:var(--red-light)}' in INDEX
    # статусы реально мапятся в три класса
    assert 'if(st==="in_work")return ["progress","в работе"]' in INDEX
    assert 'if(st==="pending")return ["wait","новый"]' in INDEX
    assert 'if(st==="done")return ["done","сдан"]' in INDEX


def test_progress_bar_only_in_work_from_real_lifecycle():
    # полоса и её ширина живут строго внутри ветки in_work
    assert 'if(x.status==="in_work"){' in INDEX
    assert '["created","approved","in_work"].filter' in INDEX
    assert 'Math.round(doneN/5*100)' in INDEX
    assert 'background:var(--yellow)' in INDEX
    # у готовых/ждущих полосы нет: вне ветки in_work progress-bar не конкатенируется
    after = INDEX.split('function naradCard(')[1].split('function renderNaradFilters')[0]
    assert after.count('progress-bar') == 1  # только в in_work-ветке
    # meta — из реальных меток времени
    assert 'Начато "+relTime(x.in_work)' in INDEX


def test_task_card_clickable_to_detail():
    assert 'data-narad="\'+esc(x.id)+\'"' in INDEX
    assert 'if(t.hasAttribute("data-narad")){openNarad(t.getAttribute("data-narad"))' in INDEX


# ── B.1 Прогресс по этапам ───────────────────────────────────────────────

def test_stage_dots_colors_and_labels():
    assert '.stage-dot.done{background:var(--green);border:1.5px solid var(--green);color:var(--bg);font-weight:700}' in INDEX
    assert '.stage-dot.active{background:var(--red);border:1.5px solid var(--red);color:#fff;font-weight:700}' in INDEX
    assert '.stage-dot.pending{background:var(--surface);border:1.5px solid var(--line-strong);color:var(--muted)}' in INDEX
    # подписи ПОД кружками, по центру
    assert '.stage-item{display:flex;flex-direction:column;align-items:center' in INDEX
    assert '.stage-lbl{font-size:9.5px;color:var(--muted);margin-top:6px;text-align:center' in INDEX
    # пять реальных этапов жизненного цикла
    for stage in ("создан", "одобрен", "в работе", "приёмка", "сдан"):
        assert f'"{stage}"' in INDEX


# ── B.2 Задание и журнал ─────────────────────────────────────────────────

def test_brief_from_real_fields():
    # план/критерии/описание — реальные поля наряда, без выдуманного брифа
    assert 'if(n.plan)spec' in INDEX
    assert 'if(n.acceptance)spec' in INDEX
    assert 'if(n.description)spec' in INDEX


def test_journal_built_from_real_data():
    # строки журнала — из меток narads и шагов narad_steps
    for src in ('[n.created,"Наряд создан"]', '[n.approved,"Одобрен владельцем"]',
                '[n.in_work,"Взят в работу"', '"Отчёт отдела получен"', '"Передан на приёмку"'):
        assert src in INDEX
    # нет захардкоженного «выдуманного» журнала в статичном HTML
    body_html = INDEX.split("<body>")[1].split("<script>")[0]
    assert "Наряд создан" not in body_html


# ── B.3 Стоп-гейт ────────────────────────────────────────────────────────

def test_gate_frame_and_options_with_consequences():
    assert '.gate{border:1.5px solid var(--red);border-radius:4px;padding:14px;margin:16px 0;background:var(--surface)}' in INDEX
    assert 'Ждёт твоего решения' in INDEX
    assert '.gate-opt-title{font-weight:600' in INDEX
    assert '.gate-opt-cons{color:var(--muted)' in INDEX
    # у каждого варианта есть заголовок И последствия
    assert 'gate-opt-title">Одобрить</div><div class="gate-opt-cons">' in INDEX
    assert 'gate-opt-title">Отклонить</div><div class="gate-opt-cons">' in INDEX


def test_gate_not_rendered_without_decision():
    # гейт — только для pending; остальные статусы дают "" (блока нет вообще)
    fn = INDEX.split('function naradGateHtml(')[1].split('function renderNaradDetail')[0]
    assert fn.index('if(n.status==="pending")') < fn.index('if(n.status==="testing")')
    assert 'return ""}' in fn
    # testing/blocked — честная заметка, а не фейковый гейт с кнопками
    assert 'gate-note' in fn
    assert 'data-nact' in fn.split('if(n.status==="pending")')[1].split('if(n.status==="testing")')[0]


def test_decision_sent_to_existing_endpoints_only():
    # решение уходит ровно на существующие approve/reject, других путей записи нет
    assert 'api("/api/narads/"+encodeURIComponent(id)+"/"+act,{method:"POST",body:{}})' in INDEX
    body_html = INDEX.split("<body>")[1].split("<script>")[0]
    assert "/decide" not in INDEX  # самодельного гейт-эндпоинта нет
    # forge_gates на этом экране не рисуются (отдельный контур Проектов) — задокументировано
    assert "forge_gates" in INDEX  # комментарий-документация в JS


# ── Backend: подключение к существующим таблицам (только чтение) ─────────

def _insert(nid, status, **kw):
    cols = {"id": nid, "status": status}
    cols.update(kw)
    keys = ",".join(cols)
    qs = ",".join("?" for _ in cols)
    _query(f"INSERT INTO narads ({keys}) VALUES ({qs})", tuple(cols.values()))


def test_api_narads_list_exposes_dept_priority_in_work():
    _insert("N1", "in_work", dept="dev", priority="high",
            title="починить крон", description="описание",
            created_at="2026-09-19 08:00:00", in_work_at="2026-09-19 08:30:00")
    with _client() as c:
        resp = c.get("/api/narads", headers=API_AUTH)
    assert resp.status_code == 200
    body = resp.get_json()
    n = [x for x in body["narads"] if x["id"] == "N1"][0]
    assert n["dept"] == "dev" and n["priority"] == "high"
    assert n["in_work"] == "2026-09-19 08:30"[:16]
    assert n["status"] == "in_work"


def test_api_narad_detail_full_lifecycle_and_steps():
    _insert("N2", "testing", dept="qa", priority="normal",
            title="сводка", plan="шаги плана", acceptance="критерии",
            created_at="2026-09-19 08:00:00", approved_at="2026-09-19 09:00:00",
            in_work_at="2026-09-19 09:05:00", testing_at="2026-09-19 10:00:00")
    _query("INSERT INTO narad_steps (narad_id, dept, status, reply) VALUES ('N2','qa','ok','отчёт отдела')")
    with _client() as c:
        resp = c.get("/api/narads/N2", headers=API_AUTH)
    assert resp.status_code == 200
    body = resp.get_json()
    n = body["narad"]
    assert n["plan"] == "шаги плана" and n["acceptance"] == "критерии"
    assert n["in_work"] == "2026-09-19 09:05:00"
    steps = body["steps"]
    assert len(steps) == 1 and steps[0]["status"] == "ok" and "отчёт" in steps[0]["reply"]


def test_api_narad_detail_404_and_degraded_journal():
    _insert("N3", "pending", title="без шагов")
    with _client() as c:
        missing = c.get("/api/narads/NOPE", headers=API_AUTH)
        empty_steps = c.get("/api/narads/N3", headers=API_AUTH)
    assert missing.status_code == 404
    assert empty_steps.status_code == 200
    assert empty_steps.get_json()["steps"] == []


def test_decision_endpoints_really_write_smoke5():
    """Smoke-5 наряда: нажатие варианта — решение реально отправляется (в базе)."""
    _insert("N4", "pending", title="гейт-наряд")
    with _client() as c:
        ok = c.post("/api/narads/N4/approve", headers=API_AUTH)
        assert ok.status_code == 200 and ok.get_json()["status"] == "ok"
        rows = _query("SELECT status FROM narads WHERE id='N4'", fetch=True)
        assert rows[0]["status"] == "approved"
        rej = c.post("/api/narads/N4/reject", headers=API_AUTH)
        assert rej.status_code == 200 and rej.get_json()["status"] == "ok"
        rows = _query("SELECT status FROM narads WHERE id='N4'", fetch=True)
        assert rows[0]["status"] == "rejected"
