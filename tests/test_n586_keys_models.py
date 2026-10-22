#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #586: ключи и модели отделов работают по-настоящему.

Гварды:
- A.1: Qwen в PROVIDERS / INTEGRATIONS_REGISTRY / KEY_MANIFEST / TOKEN_COSTS /
  PROVIDER_CONTEXT_LIMITS; URL из QWEN_BASE_URL (международный по умолчанию);
- A.2: _provider_for_model — явная форма «провайдер:модель», порядок gpt-oss
  РАНЬШЕ gpt, qwen/kimi-moonshot распознаются (табличный тест 14 имён);
- B.1: POST /api/integrations/<env_key>/check — 200 → ok + models_sample,
  401 → invalid; значения ключа в ответе НЕТ; без Bearer → 401;
- C.1: назначение override_<dept>.txt вызывается ПЕРВЫМ (до model_for и combo);
- C.2: only-флаг — честная ошибка без фолбэка в combo;
- C.4.2: первая модель упала → вторая отвечает;
- C.4.4: без назначения — прежний маршрут (combo);
- C.4.5: hard-бюджет — эконом-модель важнее назначения;
- C.4.6/C.3: запись файла в обход Python → перечитка по mtime (≤5 с);
- API: only-флаг пишется/снимается, сброс назначения снимает флаг.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n586-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, DEPT_NAMES, INTEGRATIONS_REGISTRY  # noqa: E402
from proxy import providers, key_health, routes_admin  # noqa: E402
from proxy.compaction import PROVIDER_CONTEXT_LIMITS  # noqa: E402

API_AUTH = {'Authorization': 'Bearer test-secret-123'}
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def cfg_dir(tmp_path, monkeypatch):
    """CFG_DIR → tmp; кэш providers чист; mtime-снап сброшен."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    for d in DEPT_NAMES:
        (cfg / f"override_{d}.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(routes_admin, "CFG_DIR", cfg)
    monkeypatch.setattr(providers, "CFG_DIR", cfg)
    providers._cfg_cache["overrides"] = {}
    providers._cfg_cache["_mtimes"] = {}
    providers._cfg_cache["_last_check"] = 0.0
    yield cfg
    providers._cfg_cache["overrides"] = {}
    providers._cfg_cache.pop("_mtimes", None)


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Бюджет ok, компакция — no-op, shadow-хук не зовётся (тесты зовут impl напрямую)."""
    from proxy import budget as budget_mod
    monkeypatch.setattr(budget_mod, "enforce", lambda dept, command='': {"state": "ok"})
    monkeypatch.setattr(providers, "compact_context",
                        lambda messages, dept, chain=None, summarize_fn=None, chat_id=None:
                        (messages, {"tokens_before": 0, "tokens_after": 0, "pruned": 0}))
    yield


# ──────────────────────────── A.1 Qwen ────────────────────────────

def test_a1_qwen_in_all_registries():
    assert "qwen" in providers.PROVIDERS
    assert providers.PROVIDERS["qwen"]["env_key"] == "QWEN_API_KEY"
    assert providers.PROVIDERS["qwen"]["format"] == "openai"
    assert providers.PROVIDERS["qwen"]["url"].endswith("/chat/completions")
    assert providers.PROVIDERS["qwen"]["url"].startswith("https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    assert "qwen" in providers.TOKEN_COSTS
    assert any(i["env_key"] == "QWEN_API_KEY" and i["label"] == "Qwen (Alibaba)" for i in INTEGRATIONS_REGISTRY)
    entry = next(e for e in key_health.KEY_MANIFEST if e["env_key"] == "QWEN_API_KEY")
    assert entry["label"] == "Qwen (Alibaba)"
    assert entry["check"]["type"] == "openai_models"
    assert entry["check"]["url"].endswith("/models")
    assert PROVIDER_CONTEXT_LIMITS["qwen"] == 128000


def test_a1_qwen_url_honors_env(monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert providers._qwen_base_url() == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert key_health._qwen_models_url() == "https://dashscope.aliyuncs.com/compatible-mode/v1/models"
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    assert providers._qwen_base_url() == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


# ──────────────────────────── A.2 табличный тест ────────────────────────────

@pytest.mark.parametrize("model,expected", [
    ("gpt-oss-120b", "cerebras"),
    ("openai/gpt-oss-20b", "groq"),
    ("gpt-4o", "openai"),
    ("gpt", "openai"),
    ("qwen-plus", "qwen"),
    ("qwen:qwen3-max", "qwen"),
    ("qwen:qwen-plus-latest", "qwen"),
    ("kimi-k3", "kimi"),
    ("moonshot-v1-8k", "kimi"),
    ("glm-4.6", "zai"),
    ("claude-sonnet-4-20250514", "anthropic"),
    ("deepseek-chat", "deepseek"),
    ("grok-2", "grok"),
    ("llama-3.3-70b-versatile", "groq"),
    ("nvidia/llama-3.3-nemotron-super-49b-v1.5", "nvidia"),
    ("zai-glm-4", "cerebras"),
])
def test_a2_provider_for_model_table(model, expected):
    assert providers._provider_for_model(model) == expected


def test_a2_split_explicit_model():
    assert providers._split_explicit_model("qwen:qwen-plus") == ("qwen", "qwen-plus")
    assert providers._split_explicit_model("deepseek:deepseek-chat") == ("deepseek", "deepseek-chat")
    # неизвестный провайдер / пустой хвост — форма не признаётся
    assert providers._split_explicit_model("nosuch:m") == (None, "nosuch:m")
    assert providers._split_explicit_model("qwen:") == (None, "qwen:")
    assert providers._split_explicit_model("qwen-plus") == (None, "qwen-plus")


def test_a2_explicit_model_passes_without_prefix(monkeypatch):
    """Явная форма уходит провайдеру без префикса «провайдер:»."""
    calls = []
    monkeypatch.setattr(providers, "_call_single_provider",
                        lambda p, m, msgs, **kw: calls.append((p, m)) or {"reply": "ok", "provider": p, "model": m})
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "t"}], model_override="qwen:qwen3-max")
    assert res["reply"] == "ok"
    assert calls == [("qwen", "qwen3-max")]


# ──────────────────────────── B.1 проверка ключа ────────────────────────────

class _FakeResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"data": [{"id": "qwen-plus"}, {"id": "qwen-max"}]}
    def json(self):
        return self._body


def test_b1_check_endpoint_ok(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-qwen-SECRETVALUE")
    seen = {}
    def fake_get(url, headers=None, timeout=None):
        seen["url"], seen["headers"], seen["timeout"] = url, headers, timeout
        return _FakeResp(200)
    monkeypatch.setattr(key_health.http_requests, "get", fake_get)
    r = _client().post("/api/integrations/QWEN_API_KEY/check", headers=API_AUTH)
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok"
    assert d["http_code"] == 200
    assert d["models_sample"] == ["qwen-plus", "qwen-max"]
    assert d["checked_at"]
    assert seen["timeout"] == 20.0  # таймаут по заданию
    assert seen["headers"]["Authorization"] == "Bearer sk-test-qwen-SECRETVALUE"
    # значение ключа НИКОГДА не возвращается
    assert "SECRETVALUE" not in r.get_data(as_text=True)
    # результат сохранён в key_health_status
    rows = routes_admin._query("SELECT status FROM key_health_status WHERE env_key='QWEN_API_KEY'", fetch=True)
    assert rows and rows[0]["status"] == "ok"


def test_b1_check_endpoint_401(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "sk-bad")
    monkeypatch.setattr(key_health.http_requests, "get",
                        lambda url, headers=None, timeout=None: _FakeResp(401))
    r = _client().post("/api/integrations/QWEN_API_KEY/check", headers=API_AUTH)
    d = r.get_json()
    assert d["status"] == "invalid"
    assert d["http_code"] == 401
    assert "sk-bad" not in r.get_data(as_text=True)


def test_b1_check_endpoint_guards(monkeypatch):
    # неизвестная интеграция
    r = _client().post("/api/integrations/NOT_A_KEY/check", headers=API_AUTH)
    assert r.status_code == 404
    # без Bearer — как у остальных /api/
    r2 = _client().post("/api/integrations/QWEN_API_KEY/check")
    assert r2.status_code == 401


# ──────────────────────────── C.1–C.4 маршрут вызова ────────────────────────────

def _write_override(cfg, dept, models):
    (cfg / f"override_{dept}.txt").write_text("\n".join(models) + "\n", encoding="utf-8")


def _reload_cfg_into_cache(cfg):
    providers._cfg_cache["_mtimes"] = {}
    providers._cfg_cache["_last_check"] = 0.0
    providers._maybe_reload_cfg()


def test_c1_override_called_first(monkeypatch, cfg_dir):
    """C.4.1: назначение [qwen-plus] → первый вызов в qwen/qwen-plus, combo не трогается."""
    _write_override(cfg_dir, "lz", ["qwen-plus"])
    _reload_cfg_into_cache(cfg_dir)
    calls = []
    def fake_single(p, m, msgs, **kw):
        calls.append((p, m))
        return {"reply": "ответ qwen", "provider": p, "model": m}
    monkeypatch.setattr(providers, "_call_single_provider", fake_single)
    monkeypatch.setattr("proxy.departments.model_for", lambda dept: None)
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}])
    assert res["reply"] == "ответ qwen"
    # combo-цепь НЕ исполняется: единственный вызов — назначенная модель
    # (_combo_for_task вызывается раньше легитимно — для цепи компакции)
    assert calls == [("qwen", "qwen-plus")]


def test_c4_2_first_fails_second_answers(monkeypatch, cfg_dir):
    """C.4.2: [qwen-plus, deepseek-chat], qwen падает → ответ от deepseek."""
    _write_override(cfg_dir, "lz", ["qwen-plus", "deepseek-chat"])
    _reload_cfg_into_cache(cfg_dir)
    calls = []
    def fake_single(p, m, msgs, **kw):
        calls.append((p, m))
        if m == "qwen-plus":
            return None
        return {"reply": "ответ deepseek", "provider": p, "model": m}
    monkeypatch.setattr(providers, "_call_single_provider", fake_single)
    monkeypatch.setattr("proxy.departments.model_for", lambda dept: None)
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}])
    assert res["reply"] == "ответ deepseek"
    assert calls == [("qwen", "qwen-plus"), ("deepseek", "deepseek-chat")]


def test_c2_only_mode_no_fallback(monkeypatch, cfg_dir):
    """C.4.3: only=true, все назначенные падают → честная ошибка, combo не вызывается."""
    _write_override(cfg_dir, "lz", ["qwen-plus", "deepseek-chat"])
    (cfg_dir / "override_lz.only").write_text("1", encoding="utf-8")
    _reload_cfg_into_cache(cfg_dir)
    calls = []
    def fake_single(p, m, msgs, **kw):
        calls.append((p, m))
        return None
    monkeypatch.setattr(providers, "_call_single_provider", fake_single)
    monkeypatch.setattr("proxy.departments.model_for", lambda dept: None)
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}])
    assert res.get("override_only") is True
    assert "qwen/qwen-plus" in res["reply"] and "deepseek/deepseek-chat" in res["reply"]
    # combo-цепь не исполнялась: ровно два вызова — обе назначенные модели
    assert len(calls) == 2


def test_c4_4_no_override_combo_route(monkeypatch, cfg_dir):
    """C.4.4: без назначения — прежний маршрут (combo)."""
    _reload_cfg_into_cache(cfg_dir)
    calls = []
    def fake_single(p, m, msgs, **kw):
        calls.append(("combo", p, m))
        return {"reply": "ответ combo", "provider": p, "model": m}
    monkeypatch.setattr(providers, "_call_single_provider", fake_single)
    monkeypatch.setattr("proxy.departments.model_for", lambda dept: None)
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}])
    assert res["reply"] == "ответ combo"
    assert calls and calls[0][0] == "combo"


def test_c4_5_hard_budget_econom_wins(monkeypatch, cfg_dir):
    """C.4.5: hard ≥100% — эконом-модель важнее назначения."""
    from proxy import budget as budget_mod
    _write_override(cfg_dir, "lz", ["qwen-plus"])
    (cfg_dir / "override_lz.only").write_text("1", encoding="utf-8")
    _reload_cfg_into_cache(cfg_dir)
    calls = []
    def fake_single(p, m, msgs, **kw):
        calls.append((p, m))
        return {"reply": "эконом", "provider": p, "model": m}
    monkeypatch.setattr(providers, "_call_single_provider", fake_single)
    monkeypatch.setattr(budget_mod, "enforce",
                        lambda dept, command='': {"state": "hard", "econom_model": "glm-4.5-air"})
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}])
    assert res["reply"] == "эконом"
    assert calls == [("zai", "glm-4.5-air")]


def test_c4_6_mtime_reload_no_restart(monkeypatch, cfg_dir):
    """C.4.6/C.3: запись файла в обход Python (как mlog /model) → действует без рестарта."""
    providers._cfg_cache["_last_check"] = 0.0
    providers._maybe_reload_cfg()
    assert providers._cfg_cache["overrides"].get("lz") in (None, "")
    # «бот» пишет файл напрямую
    (cfg_dir / "override_lz.txt").write_text("qwen-plus\n", encoding="utf-8")
    providers._cfg_cache["_last_check"] = 0.0
    providers._maybe_reload_cfg()
    assert providers._cfg_cache["overrides"]["lz"] == "qwen-plus"
    # троттлинг: без сброса _last_check повторная проверка ничего не перечитывает
    (cfg_dir / "override_lz.txt").write_text("deepseek-chat\n", encoding="utf-8")
    providers._maybe_reload_cfg()  # _last_check свежий → скип
    assert providers._cfg_cache["overrides"]["lz"] == "qwen-plus"


# ──────────────────────────── B.2/C.2 UI-гварды разметки ────────────────────────────

def test_b2_ui_markup():
    with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as f:
        idx = f.read()
    # кнопка «Проверить сейчас» + строка результата в листе интеграции
    assert 'id="intSheetCheck"' in idx and "Проверить сейчас" in idx
    assert 'id="intSheetCheckState"' in idx
    # автозапуск проверки после сохранения (checkIntKey вызывается из intSheetSave)
    assert "checkIntKey(key)" in idx
    # переключатель «только эти модели» в листе моделей отдела
    assert 'id="deptModelOnly"' in idx and "Только эти модели (без запасных)" in idx
    # сохранение отправляет only
    assert "only:only" in idx


# ──────────────────────────── API only-флага ────────────────────────────

def test_api_only_flag_write_and_reset(cfg_dir):
    c = _client()
    r = c.post("/api/model/depts", headers=API_AUTH,
               json={"dept": "lz", "models": ["qwen-plus"], "only": True})
    assert r.status_code == 200 and r.get_json()["only"] is True
    assert (cfg_dir / "override_lz.only").exists()
    g = c.get("/api/model/depts", headers=API_AUTH).get_json()
    lz = next(d for d in g["depts"] if d["dept"] == "lz")
    assert lz["only"] is True
    # сброс назначения снимает флаг
    r2 = c.post("/api/model/depts", headers=API_AUTH, json={"dept": "lz", "models": []})
    assert r2.get_json()["only"] is False
    assert not (cfg_dir / "override_lz.only").exists()
    # явное снятие без сброса назначения
    c.post("/api/model/depts", headers=API_AUTH, json={"dept": "lz", "models": ["glm-4.6"], "only": True})
    r3 = c.post("/api/model/depts", headers=API_AUTH, json={"dept": "lz", "models": ["glm-4.6"], "only": False})
    assert r3.get_json()["only"] is False
    assert not (cfg_dir / "override_lz.only").exists()
