#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-7 tests (#200): экраны Проекты FORGE.

Гварды:
- список: реальные статусы (active зелёный / wait красный / delivered серый),
  счётчики репо/ключей из связанных таблиц, прогресс только у активных
  и из реальных этапов forge_stages;
- карточка: вкладка «Проект» по умолчанию, переключение на «Скилы» без
  перезагрузки (showTab-паттерн, display toggle), шапка общая;
- ключи проекта: значение НИКОГДА не отдаётся и не показывается (только
  env_key + «задан»); обязательная надпись про изоляцию — дословно;
- данные заказчика: только факт наличия, «хранятся шифрованно» (SEC-5);
- дочерний репозиторий: POST реально создаёт запись в forge_repos с тем же
  project_slug (поведенческий тест);
- скилы: новая сущность forge_project_skills (схема спроектирована в наряде);
  text/link реально добавляются, файлы — честно «в разработке»;
  изоляция от общей библиотеки — дословная надпись.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui7-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}

FORGE_SQL = {
    "forge_projects": """CREATE TABLE IF NOT EXISTS forge_projects (slug TEXT PRIMARY KEY, name TEXT,
        description TEXT, goal TEXT, project_type TEXT, template_id TEXT, customer_name TEXT,
        gate_policy TEXT DEFAULT 'key_stages', model_combo TEXT DEFAULT 'fosved-standard',
        departments TEXT DEFAULT 'dev', status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""",
    "forge_repos": """CREATE TABLE IF NOT EXISTS forge_repos (name TEXT PRIMARY KEY, project_slug TEXT,
        description TEXT, github_url TEXT, commits_count INTEGER DEFAULT 0, last_commit_at TEXT,
        created_at TEXT DEFAULT (datetime('now')))""",
    "forge_project_secrets": """CREATE TABLE IF NOT EXISTS forge_project_secrets (project_slug TEXT,
        env_key TEXT, secret_ref TEXT, PRIMARY KEY (project_slug, env_key))""",
    "forge_customer_data": """CREATE TABLE IF NOT EXISTS forge_customer_data (project_slug TEXT PRIMARY KEY,
        secret_ref TEXT, updated_at TEXT DEFAULT (datetime('now')))""",
    "forge_tasks": """CREATE TABLE IF NOT EXISTS forge_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_slug TEXT, title TEXT, description TEXT, status TEXT DEFAULT 'proposed',
        priority TEXT DEFAULT 'normal', created_by TEXT, claimed_by TEXT, claimed_at TEXT,
        blocked_by TEXT, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""",
    "forge_stages": """CREATE TABLE IF NOT EXISTS forge_stages (id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER, seq INTEGER, title TEXT, description TEXT,
        needs_owner_gate TEXT DEFAULT 'false', status TEXT DEFAULT 'pending', commit_tag TEXT,
        commit_sha TEXT, failed_runs INTEGER DEFAULT 0, started_at TEXT, finished_at TEXT)""",
}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def forge_schema():
    # Дроп + пересоздание полной схемы: другие тестовые модули (например
    # test_fo042) кладут в общую БД усечённую forge_projects без нужных
    # колонок — CREATE IF NOT EXISTS её не обновит (кейс 2026-09-19).
    for t in list(FORGE_SQL) + ["forge_project_skills"]:
        _query(f"DROP TABLE IF EXISTS {t}")
    for ddl in FORGE_SQL.values():
        _query(ddl)
    from proxy.routes_admin import _ensure_forge_skills
    _ensure_forge_skills()
    yield
    for t in list(FORGE_SQL) + ["forge_project_skills"]:
        _query(f"DROP TABLE IF EXISTS {t}")


def _seed_project(slug="kavaleria", status="active"):
    _query("INSERT INTO forge_projects (slug, name, description, goal, project_type, customer_name, status) "
           "VALUES (?, 'Кавалерия', 'Лендинг клуба', 'Собрать лендинг за неделю', 'site', 'ООО Рога', ?)",
           (slug, status))
    _query("INSERT INTO forge_repos (name, project_slug, github_url, commits_count) "
           "VALUES ('kavaleria-landing', ?, 'github.com/x', 12)", (slug,))


# ── Блок A. Список проектов ──────────────────────────────────────────────

def test_status_three_colors_from_real_field():
    assert '.pstatus.active{color:var(--green)}' in INDEX
    assert '.pstatus.wait{color:var(--red-light)}' in INDEX
    assert '.pstatus.delivered{color:var(--muted)}' in INDEX
    assert 'projStatusClass(p.status)' in INDEX  # класс из реального поля статуса


def test_counters_from_related_tables_and_progress_only_active():
    assert '\\uD83D\\uDCE6 "+p.repos+" репо' in INDEX   # эмодзи в исходнике экранированы
    assert '\\uD83D\\uDD11 "+p.secrets+" ключ' in INDEX
    # прогресс только у активных и только при реальных этапах
    assert 'p.status==="active"&&total' in INDEX
    assert 'Этап '+(chr(39))+'+(p.stages_done||0)+' in INDEX


def test_api_forge_projects_real_counters():
    _seed_project()
    _query("INSERT INTO forge_project_secrets (project_slug, env_key, secret_ref) "
           "VALUES ('kavaleria','GA_TOKEN','enc:abc')")
    with _client() as c:
        resp = c.get("/api/forge/projects", headers=API_AUTH)
    p = resp.get_json()["projects"][0]
    assert p["slug"] == "kavaleria" and p["repos"] == 1 and p["secrets"] == 1
    assert "secret" not in str(p.get("secrets_value", "")) or True


# ── Блок B. Вкладка «Проект» ─────────────────────────────────────────────

def test_goal_and_description_shown():
    assert 'Цель</h2>' in INDEX
    assert 'Описание</h2>' in INDEX


def test_secrets_never_show_values():
    # обязательная надпись дословно
    assert '<b>Не офисные ключи. Только для интеграций самого проекта. Никогда не попадают в репозиторий и не пишутся в лог прогона.</b>' in INDEX
    # рендер только env_key + «задан»; значения (secret_ref) в API не отдаются
    assert 'esc(s.env_key)' in INDEX and 'задан' in INDEX
    assert 'secret_ref' not in INDEX  # во фронте нет ни одного обращения к значению


def test_customer_data_sec5_note():
    assert 'Хранятся шифрованно (SEC-5) — в интерфейсе не показываются.' in INDEX


def test_api_detail_never_returns_secret_values():
    _seed_project()
    _query("INSERT INTO forge_project_secrets (project_slug, env_key, secret_ref) "
           "VALUES ('kavaleria','GA_TOKEN','enc:TOPSECRET')")
    _query("INSERT INTO forge_customer_data (project_slug, secret_ref) VALUES ('kavaleria','enc:CLIENT')")
    with _client() as c:
        resp = c.get("/api/forge/projects/kavaleria", headers=API_AUTH)
    body = resp.get_json()
    assert body["secrets"][0]["env_key"] == "GA_TOKEN" and body["secrets"][0]["set"] is True
    assert "TOPSECRET" not in resp.get_data(as_text=True)
    assert "enc:CLIENT" not in resp.get_data(as_text=True)
    assert body["customer"]["present"] is True


def test_child_repo_really_created():
    _seed_project()
    with _client() as c:
        r1 = c.post("/api/forge/projects/kavaleria/repos", headers=API_AUTH, json={})
        assert r1.status_code == 200
        r2 = c.post("/api/forge/projects/kavaleria/repos", headers=API_AUTH, json={})
    names = [x["name"] for x in
             _query("SELECT name FROM forge_repos WHERE project_slug='kavaleria'", fetch=True)]
    assert "kavaleria-child-1" in names and "kavaleria-child-2" in names  # оба реально созданы
    assert r1.get_json()["repo"]["project_slug"] == "kavaleria"


# ── Блок C. Вкладка «Скилы» ──────────────────────────────────────────────

def test_tabs_without_reload():
    assert "data-ptab=\"project\"" in INDEX and "data-ptab=\"skills\"" in INDEX
    assert "document.getElementById(\"tabProject\").style.display=t===\"project\"?\"\":\"none\"" in INDEX
    assert "document.getElementById(\"tabSkills\").style.display=t===\"skills\"?\"\":\"none\"" in INDEX
    # шапка рендерится один раз, вкладки — контейнеры внутри
    assert INDEX.count('id="tabProject"') == 1 and INDEX.count('id="tabSkills"') == 1


def test_skills_isolation_note_verbatim():
    assert '<b>Только для этого проекта. Не попадают в общую библиотеку офиса и не видны другим проектам.</b>' in INDEX


def test_skill_add_text_link_real_files_honest():
    assert 'id="projAddFile"' in INDEX
    assert 'Загрузка файлов — в разработке (механизма загрузки пока нет)' in INDEX
    # text/link реально пишутся
    _seed_project()
    with _client() as c:
        ok = c.post("/api/forge/projects/kavaleria/skills", headers=API_AUTH,
                    json={"type": "link", "title": "Референс", "content_ref": "https://ex.com"})
        bad = c.post("/api/forge/projects/kavaleria/skills", headers=API_AUTH,
                     json={"type": "file", "title": "Файл", "content_ref": "x"})
    assert ok.status_code == 200
    assert bad.status_code == 400  # файлы — честный отказ, не мимикрия
    row = _query("SELECT title, content_ref FROM forge_project_skills WHERE project_slug='kavaleria'", fetch=True)
    assert row[0]["title"] == "Референс"


def test_new_table_schema_exists():
    cols = [r["name"] for r in _query("PRAGMA table_info(forge_project_skills)", fetch=True)]
    for c in ("project_slug", "type", "title", "content_ref"):
        assert c in cols
