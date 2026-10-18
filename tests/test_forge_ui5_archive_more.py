#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-5 tests (#198): экраны «Ещё» и «Архив отчётов».

Гварды чек-листа:
- «Ещё»: три группы (Материалы / Система / Опасно), экстренная блокировка —
  отдельная красная группа физически внизу; «Требует решения» с реальным
  числовым бейджем (/api/attention: forge_gates + admin_findings);
  FORGE/Репозитории — пункт с честным объяснением (/repos во внутреннем
  контуре); версия и хеш коммита — из реальных данных сборки;
- «Архив»: поиск по названию/отделу; три прокручиваемые строки даты
  (год/месяц/день), выбор фильтрует список БЕЗ перезагрузки (клиентский
  фильтр по реальным датам); пометка «на контроле» — только у отчётов с
  реальной kv-записью control_<doc_id> (system_settings, HandleMiniAppAction);
  «изменить» — честно сообщает об отсутствии write-эндпоинта;
  клик по строке — открывает отчёт (data-report sheet).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui5-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def ui5_schema():
    _query("CREATE TABLE IF NOT EXISTS forge_gates (id INTEGER PRIMARY KEY AUTOINCREMENT, "
           "task_id INTEGER, stage_id TEXT, kind TEXT, question TEXT, context TEXT, "
           "options_json TEXT, decision TEXT, decided_by TEXT, decided_at TEXT, "
           "telegram_message_id TEXT, created_at TEXT DEFAULT (datetime('now')))")
    _query("CREATE TABLE IF NOT EXISTS admin_findings (id INTEGER PRIMARY KEY AUTOINCREMENT, "
           "severity TEXT, category TEXT, file TEXT, issue TEXT, fix TEXT, "
           "status TEXT DEFAULT 'open', created_at TEXT DEFAULT (datetime('now')))")
    _query("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM forge_gates")
    _query("DELETE FROM admin_findings")
    _query("DELETE FROM system_settings WHERE key LIKE 'control|_%' ESCAPE '|' OR key = 'other_key'")
    yield
    _query("DELETE FROM forge_gates")
    _query("DELETE FROM admin_findings")
    _query("DELETE FROM system_settings WHERE key LIKE 'control|_%' ESCAPE '|' OR key = 'other_key'")


# ── Блок A. Экран «Ещё» ──────────────────────────────────────────────────

def test_more_three_groups_danger_bottom():
    more = INDEX.split('<section class="screen" data-tab="more">')[1].split('</section>')[0]
    assert "<h2>Материалы</h2>" in more and "<h2>Система</h2>" in more and "<h2>Опасно</h2>" in more
    # «Опасно» физически ниже остальных групп
    assert more.index("<h2>Опасно</h2>") > more.index("<h2>Система</h2>") > more.index("<h2>Материалы</h2>")
    assert 'class="group danger-group"' in more
    assert 'id="lockdownRow"' in more


def test_more_menu_items_present():
    more = INDEX.split('<section class="screen" data-tab="more">')[1].split('</section>')[0]
    for label in ("Архив отчётов", "FORGE · Репозитории", "Интеграции и ключи",
                  "Журнал аудита", "Требует решения", "Экстренная блокировка"):
        assert f'<div class="mrow-label">{label}</div>' in more


def test_attention_badge_real_count():
    assert 'id="attentionBadge"' in INDEX
    assert 'api("/api/attention")' in INDEX
    assert 'at.total>0' in INDEX  # бейдж только при реальных открытых вопросах
    assert 'b.textContent=at.total' in INDEX
    assert '.mbadge{min-width:20px;height:20px;border-radius:10px;background:var(--red)' in INDEX


def test_version_commit_real_build_data():
    assert 'at.commit||"local"' in INDEX
    assert '"офис build "+(at.commit||"local")+(at.version?" · mlog "+at.version:"")' in INDEX
    # вертикальная линия внизу экрана
    more = INDEX.split('<section class="screen" data-tab="more">')[1].split('</section>')[0]
    assert '<div class="verline" id="verLine"></div>' in more


def test_repos_row_honest():
    assert 'id="reposRow"' in INDEX
    assert 'Экран /repos живёт во внутреннем контуре (mlog serve)' in INDEX


# ── Блок B. Экран «Архив» ────────────────────────────────────────────────

def test_archive_search_and_three_date_rows():
    assert 'id="archSearch"' in INDEX and 'placeholder="Найти по названию или отделу"' in INDEX
    for row_id in ("yearRow", "monthRow", "dayRow"):
        assert f'<div class="daterow" id="{row_id}"></div>' in INDEX
    # выбор чипа фильтрует клиентски, без перезагрузки
    assert 'renderArchList();return}' in INDEX
    assert 'archYear==="all"||d.slice(0,4)===archYear' in INDEX


def test_archive_rows_watch_only_real_control():
    assert 'api("/api/archive-watches")' in INDEX
    assert 'archWatch[String(r.id)]' in INDEX  # пометка только при реальной kv-записи
    assert 'на контроле: ' in INDEX
    # «изменить» — честное сообщение, реального write-эндпоинта нет
    assert 'Изменение периода контроля — нужен отдельный наряд (write-эндпоинта нет)' in INDEX
    # клик по строке открывает отчёт; «изменить» перехватывается раньше.
    # #552: раньше строка открывала sheet-заглушку (data-report/data-body),
    # теперь — полную страницу отчёта /miniapp/<id> (data-doc).
    assert 'data-doc="\'+esc(r.id)+\'"' in INDEX
    idx_aredit = INDEX.index('hasAttribute("data-aredit")')
    idx_doc = INDEX.index('hasAttribute("data-doc")')
    assert idx_aredit < idx_doc


# ── Backend: /api/attention, /api/audit, /api/archive-watches ────────────

def test_api_attention_counts_real_entities():
    _query("INSERT INTO forge_gates (kind, question) VALUES ('plan','Куда двигаемся?')")
    _query("INSERT INTO forge_gates (kind, question, decision) VALUES ('plan','решён','Да')")
    _query("INSERT INTO admin_findings (issue, status) VALUES ('найдено','open')")
    with _client() as c:
        resp = c.get("/api/attention", headers=API_AUTH)
    body = resp.get_json()
    assert body["gates_total"] == 1        # решённый гейт не считается
    assert body["findings"] == 1
    assert body["total"] == 2              # сводный пункт по всем сущностям разом
    assert body["lockdown"] is False
    assert isinstance(body["commit"], str)


def test_api_audit_reads_existing_table():
    _query("INSERT INTO audit_log (action, actor, dept, details, status) VALUES "
           "('test_action','proxy','admin','{\"x\":1}','ok')")
    with _client() as c:
        resp = c.get("/api/audit", headers=API_AUTH)
    items = resp.get_json()["items"]
    assert any(i["action"] == "test_action" for i in items)


def test_api_archive_watches_from_shared_kv():
    _query("INSERT INTO system_settings (key, value) VALUES "
           "('control_42','daily|Курс USD/RUB'),('other_key','не контроль')")
    with _client() as c:
        resp = c.get("/api/archive-watches", headers=API_AUTH)
    ws = resp.get_json()["watches"]
    assert len(ws) == 1
    assert ws[0]["doc_id"] == "42" and ws[0]["freq"] == "daily"
    assert "USD" in ws[0]["title"]
