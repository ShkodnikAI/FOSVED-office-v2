#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MINIAPP-5 tests (#292): назначение модели отделу из Mini App.

Гварды:
- GET /api/model/depts отдаёт ВСЕ отделы DEPT_NAMES + каталог моделей из COMBO_CHAINS;
- POST пишет override_<dept>.txt в формате потребителей — ТОЛЬКО имена моделей,
  построчно (GetModelFallbackChain app.mlog:508 → CallLLMResilient; legacy fallback
  providers.py; budget.econom_model_for). Провайдер выводится из префикса модели;
- сброс (models: []) очищает файл-плейсхолдер и СНИМАЕТ кэш providers (_load_cfg) без рестарта;
- валидация: неизвестный отдел / models не список / >5 моделей / мусор в имени — 400, файл не тронут;
- audit: model_override_set / model_override_reset с source=miniapp;
- guard: /api/* без Bearer — 401;
- UI: muted-пункт снят, sheet и кнопка «Настроить» на месте;
- app.mlog: TG /model <dept> пишет тот же формат (только модель) + AuditLog.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-miniapp5-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, DEPT_NAMES  # noqa: E402
from proxy import routes_admin, providers  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

with open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8") as _f:
    APP_MLOG = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def cfg_dir(tmp_path, monkeypatch):
    """CFG_DIR → tmp; плейсхолдеры override_<dept>.txt как в репо (пустые)."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    for d in DEPT_NAMES:
        (cfg / f"override_{d}.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(routes_admin, "CFG_DIR", cfg)
    monkeypatch.setattr(providers, "CFG_DIR", cfg)
    providers._cfg_cache["overrides"] = {}
    _query = routes_admin._query
    _query("DELETE FROM audit_log WHERE action LIKE 'model_override%'")
    yield cfg
    _query("DELETE FROM audit_log WHERE action LIKE 'model_override%'")
    providers._cfg_cache["overrides"] = {}


def _audit_rows():
    rows = routes_admin._query(
        "SELECT action, details FROM audit_log WHERE action LIKE 'model_override%'", fetch=True)
    return [(r["action"], str(r["details"])) for r in rows]


# ── GET ──────────────────────────────────────────────────────────────────

def test_get_lists_all_depts_empty():
    r = _client().get("/api/model/depts", headers=API_AUTH)
    assert r.status_code == 200
    j = r.get_json()
    assert j["status"] == "ok"
    got = {d["dept"] for d in j["depts"]}
    assert got == set(DEPT_NAMES)
    assert all(d["override"] == [] for d in j["depts"])
    assert all(d["label"] for d in j["depts"])


def test_get_catalog_derived_from_combo_chains():
    """Каталог выводится из COMBO_CHAINS: zai с glm-4.6, kimi с kimi-k3, и т.д."""
    r = _client().get("/api/model/depts", headers=API_AUTH)
    cat = {c["provider"]: c["models"] for c in r.get_json()["catalog"]}
    assert "glm-4.6" in cat["zai"]
    assert "kimi-k3" in cat["kimi"]
    assert "deepseek-chat" in cat["deepseek"]
    assert "claude-sonnet-4-20250514" in cat["anthropic"]
    assert all(c["label"] for c in r.get_json()["catalog"])


# ── POST: назначение ─────────────────────────────────────────────────────

def test_post_writes_model_only_file():
    """Формат потребителей: только модели, одна на строку (порядок = цепь fallback)."""
    r = _client().post("/api/model/depts", headers=API_AUTH,
                       json={"dept": "lz", "models": ["glm-4.6", "deepseek-chat"]})
    assert r.status_code == 200
    # №586: в ответ добавлен only-флаг режима «только эти модели» (False по умолчанию)
    assert r.get_json() == {"status": "ok", "dept": "lz", "override": ["glm-4.6", "deepseek-chat"], "only": False}
    content = (routes_admin.CFG_DIR / "override_lz.txt").read_text(encoding="utf-8")
    assert content == "glm-4.6\ndeepseek-chat\n"
    # GET видит назначенное
    r = _client().get("/api/model/depts", headers=API_AUTH)
    lz = [d for d in r.get_json()["depts"] if d["dept"] == "lz"][0]
    assert lz["override"] == ["glm-4.6", "deepseek-chat"]


def test_post_updates_providers_cache_immediately():
    """_load_cfg вызван после записи: legacy fallback видит override без рестарта."""
    _client().post("/api/model/depts", headers=API_AUTH,
                   json={"dept": "finance", "models": ["claude-sonnet-4-20250514"]})
    assert providers._cfg_cache["overrides"].get("finance") == "claude-sonnet-4-20250514"


def test_post_reset_clears_file_and_cache():
    """models: [] → файл-плейсхолдер пуст, кэш снят, GET отдаёт []."""
    _client().post("/api/model/depts", headers=API_AUTH, json={"dept": "qa", "models": ["glm-4.6"]})
    r = _client().post("/api/model/depts", headers=API_AUTH, json={"dept": "qa", "models": []})
    assert r.status_code == 200
    assert r.get_json()["override"] == []
    assert (routes_admin.CFG_DIR / "override_qa.txt").read_text(encoding="utf-8") == ""
    assert "qa" not in providers._cfg_cache["overrides"]
    r = _client().get("/api/model/depts", headers=API_AUTH)
    qa = [d for d in r.get_json()["depts"] if d["dept"] == "qa"][0]
    assert qa["override"] == []


# ── POST: валидация ──────────────────────────────────────────────────────

def test_post_unknown_dept_400():
    r = _client().post("/api/model/depts", headers=API_AUTH,
                       json={"dept": "nosuchdept", "models": ["glm-4.6"]})
    assert r.status_code == 400


def test_post_models_not_list_400():
    r = _client().post("/api/model/depts", headers=API_AUTH,
                       json={"dept": "lz", "models": "glm-4.6"})
    assert r.status_code == 400


def test_post_too_many_models_400():
    r = _client().post("/api/model/depts", headers=API_AUTH,
                       json={"dept": "lz", "models": ["m1", "m2", "m3", "m4", "m5", "m6"]})
    assert r.status_code == 400


def test_post_bad_model_name_400_file_untouched():
    """Имя модели с пробелом (формат 'provider model') — 400; файл не тронут."""
    r = _client().post("/api/model/depts", headers=API_AUTH,
                       json={"dept": "lz", "models": ["zai glm-4.6"]})
    assert r.status_code == 400
    assert (routes_admin.CFG_DIR / "override_lz.txt").read_text(encoding="utf-8") == ""


def test_post_audit_logged():
    _client().post("/api/model/depts", headers=API_AUTH, json={"dept": "lz", "models": ["glm-4.6"]})
    _client().post("/api/model/depts", headers=API_AUTH, json={"dept": "lz", "models": []})
    actions = [a for a, _ in _audit_rows()]
    assert "model_override_set" in actions and "model_override_reset" in actions
    assert any("miniapp" in det for _, det in _audit_rows())


def test_api_guard_401_without_bearer():
    c = _client()
    assert c.get("/api/model/depts").status_code == 401
    assert c.post("/api/model/depts", json={"dept": "lz", "models": ["glm-4.6"]}).status_code == 401


# ── UI + app.mlog ────────────────────────────────────────────────────────

def test_ui_control_replaces_muted_item():
    """UI: оба muted-пункта сняты (#292 sheet + #293 raw-просмотр)."""
    assert 'id="deptModelBtn"' in INDEX
    assert 'id="deptModelSheet"' in INDEX
    assert 'id="deptModelSave"' in INDEX and 'id="deptModelReset"' in INDEX
    assert 'id="deptModelRaw"' in INDEX  # #293: read-only просмотр файла
    assert 'Назначение модели отделу (/model dept provider model)</span><span class="need-narad"' not in INDEX
    assert 'Чтение текущих config/override_*.txt</span><span class="need-narad"' not in INDEX


def test_app_mlog_tg_writes_model_only():
    """TG /model <dept> пишет тот же формат (только модель) + AuditLog."""
    assert 'write_file("config/override_" + dept_slug + ".txt", trim(m))' in APP_MLOG
    assert 'trim(p) + " " + trim(m))' not in APP_MLOG  # старый нечитаемый формат убран
    assert 'AuditLog("model_override_set", "system"' in APP_MLOG


def test_load_cfg_clears_stale_overrides():
    """Сброс override-файла снимает кэш при следующем _load_cfg (без рестарта)."""
    cfg = routes_admin.CFG_DIR
    (cfg / "override_legal.txt").write_text("glm-4.6\n", encoding="utf-8")
    providers._load_cfg()
    assert "legal" in providers._cfg_cache["overrides"]
    (cfg / "override_legal.txt").write_text("", encoding="utf-8")
    providers._load_cfg()
    assert "legal" not in providers._cfg_cache["overrides"]


# ── MINIAPP-6 (#293): read-only просмотр override-файлов ──────────────

def test_get_raw_matches_server_file():
    """raw в GET = фактическое содержимое файла (сверено с сервером)."""
    cfg = routes_admin.CFG_DIR
    (cfg / "override_lz.txt").write_text("# комментарий\nglm-4.6\n", encoding="utf-8")
    r = _client().get("/api/model/depts", headers=API_AUTH)
    lz = [d for d in r.get_json()["depts"] if d["dept"] == "lz"][0]
    assert lz["raw"] == "# комментарий\nglm-4.6\n"
    # пустой плейсхолдер → raw пустая строка, override []
    qa = [d for d in r.get_json()["depts"] if d["dept"] == "qa"][0]
    assert qa["raw"] == "" and qa["override"] == []


def test_get_raw_none_when_file_missing():
    cfg = routes_admin.CFG_DIR
    (cfg / "override_dev.txt").unlink()
    r = _client().get("/api/model/depts", headers=API_AUTH)
    dev = [d for d in r.get_json()["depts"] if d["dept"] == "dev"][0]
    assert dev["raw"] is None and dev["override"] == []
