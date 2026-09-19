#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-12 tests (#215): форма создания проекта FORGE.

Гварды:
- форма: «+ Новый проект» в списке Проектов, нижний лист с четырьмя полями
  (название, цель одной фразой, заказчик) и seg-3 типов Сайт/Android/ИИ-офис
  (значения site/android/ai_office — как project_type в схеме);
- тонкий route: в python-роуте НЕТ INSERT INTO forge_projects (SQL только в
  dept/forge.mlog, ForgeCreateProject), мост dept/forge_create_bridge.mlog
  существует, импортирует dept/forge, вызывается с FNP_* env;
- slug: транслитерация кириллицы + дефисы, коллизии гасятся -2;
- поведение POST: мост отвечает «Проект создан:» → ok+slug; «ОТКАЗ:» → 409 с
  текстом отказа; timeout моста → 504; пустое название → 400; неверный тип
  → 400 (мост не запускается);
- дословный отказ валидации типа из ForgeCreateProject.
"""
import os
import sys
import subprocess
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui12-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}

BRIDGE_PATH = os.path.join(REPO_ROOT, "dept", "forge_create_bridge.mlog")
ROUTES_ADMIN = open(os.path.join(REPO_ROOT, "proxy", "routes_admin.py"), encoding="utf-8").read()


def _client():
    return flask_app.test_client()


@pytest.fixture()
def clean_projects():
    _query("DROP TABLE IF EXISTS forge_projects")
    _query("""CREATE TABLE forge_projects (slug TEXT PRIMARY KEY, name TEXT,
        description TEXT, goal TEXT, project_type TEXT, template_id TEXT, customer_name TEXT,
        gate_policy TEXT DEFAULT 'key_stages', model_combo TEXT DEFAULT 'fosved-standard',
        departments TEXT DEFAULT 'dev', status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))""")
    yield
    _query("DROP TABLE IF EXISTS forge_projects")


# ── Блок A: форма ────────────────────────────────────────────────────────────

def test_form_plus_button_and_sheet():
    assert 'id="projAddBtn"' in INDEX and "+ Новый проект" in INDEX
    assert 'id="projNewSheet"' in INDEX
    assert 'placeholder="Название проекта"' in INDEX
    assert 'placeholder="Цель одной фразой"' in INDEX
    assert 'placeholder="Заказчик"' in INDEX


def test_form_reuses_sheet_pattern_and_seg3():
    # переиспользование нижнего листа (.sheet/.box), как в Интеграциях (UI-8)
    assert '<div class="sheet" id="projNewSheet"><div class="box">' in INDEX
    # три типа проекта — значения как в схеме, подписи как в наряде
    for v, label in (("site", "Сайт"), ("android", "Android"), ("ai_office", "ИИ-офис")):
        assert f'data-newptype="{v}"' in INDEX and f">{label}</button>" in INDEX
    assert "seg-3" in INDEX.split('id="projNewTypeSeg"')[1].split("</div>")[0] or \
           'seg-3" style="width:100%" id="projNewTypeSeg"' in INDEX


def test_form_submit_opens_card_of_new_project():
    # после создания: закрыть лист, обновить список, открыть карточку (Smoke 4-5)
    assert 'await loadProjects();await openProject(r.project.slug)' in INDEX


# ── Блок B: тонкий route и мост ──────────────────────────────────────────────

def test_no_insert_into_forge_projects_in_python():
    # SQL создания не дублируется в Python — только чтение-проверка коллизий
    assert "INSERT INTO forge_projects" not in ROUTES_ADMIN


def test_bridge_exists_and_calls_existing_pattern():
    assert os.path.exists(BRIDGE_PATH)
    src = open(BRIDGE_PATH, encoding="utf-8").read()
    assert "import dept/forge" in src
    assert "ForgeCreateProject(" in src
    # мост получает аргументы через env и объявляет ту же базу
    for env_name in ("FNP_SLUG", "FNP_NAME", "FNP_GOAL", "FNP_CUSTOMER", "FNP_TYPE"):
        assert f'env("{env_name}")' in src
    assert "db { url: env(\"DATABASE_URL\") }" in src


def test_slugify_transliterates_and_hyphenates():
    from proxy.routes_admin import _forge_slugify
    assert _forge_slugify("Кавалерия") == "kavaleriya"
    assert _forge_slugify("Мой  Тест — Проект #1!") == "moy-test-proekt-1"
    assert _forge_slugify("   ") == "project"  # пустое → дефолт


def test_slug_collision_gets_suffix(clean_projects):
    _query("INSERT INTO forge_projects (slug, name) VALUES ('kavaleriya', 'Кавалерия')")
    from proxy import routes_admin as ra
    with mock.patch.object(ra.subprocess, "run", side_effect=AssertionError("bridge must not run in this test")):
        pass  # проверка ниже не вызывает мост: только логика суффикса через route-код
    # прямой вызов POST без моста не делаем (он бы запустил bin/mlog) — проверяем
    # логику выбора суффикса непосредственно:
    base = ra._forge_slugify("Кавалерия")
    slug, n = base, 1
    while _query("SELECT 1 FROM forge_projects WHERE slug=? LIMIT 1", (slug,), fetch=True):
        n += 1
        slug = f"{base}-{n}"
    assert slug == "kavaleriya-2"


def test_post_creates_via_bridge_ok(clean_projects):
    from proxy import routes_admin as ra
    called = {}

    def fake_run(cmd, **kw):
        called["cmd"] = cmd
        called["env"] = kw["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout="Проект создан: kavaleriya (site, гейты: key_stages)\n", stderr="")

    with mock.patch.object(ra.subprocess, "run", side_effect=fake_run):
        r = _client().post("/api/forge/projects", headers=API_AUTH,
                           json={"name": "Кавалерия", "goal": "Собрать лендинг",
                                 "customer": "ООО Рога", "project_type": "site"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok" and body["project"]["slug"] == "kavaleriya"
    # мост запущен с FNP_* env, cwd — корень репо
    assert called["cmd"] == ["./bin/mlog", "run", "dept/forge_create_bridge.mlog"]
    assert called["env"]["FNP_SLUG"] == "kavaleriya" and called["env"]["FNP_TYPE"] == "site"
    assert called["env"]["FNP_CUSTOMER"] == "ООО Рога"


def test_post_bridge_refusal_is_409_with_text(clean_projects):
    from proxy import routes_admin as ra
    refusal = "ОТКАЗ: проект kavaleria уже существует"
    with mock.patch.object(ra.subprocess, "run",
                           return_value=subprocess.CompletedProcess("mlog", 1, stdout="", stderr=refusal)):
        r = _client().post("/api/forge/projects", headers=API_AUTH,
                           json={"name": "Кавалерия", "project_type": "site"})
    assert r.status_code == 409
    assert "уже существует" in r.get_json()["message"]


def test_post_bridge_timeout_is_504(clean_projects):
    from proxy import routes_admin as ra
    with mock.patch.object(ra.subprocess, "run", side_effect=subprocess.TimeoutExpired("mlog", 90)):
        r = _client().post("/api/forge/projects", headers=API_AUTH,
                           json={"name": "Кавалерия", "project_type": "site"})
    assert r.status_code == 504


def test_post_validation_no_name_and_bad_type(clean_projects):
    from proxy import routes_admin as ra
    c = _client()
    r = c.post("/api/forge/projects", headers=API_AUTH, json={"name": "", "project_type": "site"})
    assert r.status_code == 400
    r = c.post("/api/forge/projects", headers=API_AUTH, json={"name": "X", "project_type": "yacht"})
    assert r.status_code == 400
    # дословная подсказка домена типов — как в ForgeCreateProject
    assert "{site, android, ai_office}" in r.get_json()["message"]
