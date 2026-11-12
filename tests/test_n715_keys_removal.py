#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #715 KEYS-2 (решение владельца 12.11 по #708): Grok, NVIDIA и
Яндекс.Маркет удалены — манифест ключей, цепочка провайдеров, площадка
магазина.

Гварды:
- A.1: манифест — 14 ключей, трёх удалённых имён нет (key_health.KEY_MANIFEST
  и дубль INTEGRATIONS_REGISTRY); оставшиеся (Qwen/FRED/Alpha Vantage и
  рабочие) на месте;
- A.2: PROVIDERS/TOKEN_COSTS/PROVIDER_CONTEXT_LIMITS/COMBO_CHAINS/
  _MODEL_LABELS без grok и nvidia; детекция префиксов сохранена
  (не тихий фолбэк), запрос модели grok-*/nvidia/* — ГРОМКИЙ отказ
  «провайдер удалён решением владельца 12.11» без сетевого вызова;
  назначение отдела на удалённого провайдера — пропуск с записью, не вызов;
- A.3: сборщика ym и площадки нет (COLLECTORS/PLATFORMS_MVP/статусы/
  /api/shop/sources); /api/models без grok;
- A.4-прогноз: QWEN_API_KEY остаётся в манифесте (ключ внесён владельцем
  в Render), FRED/ALPHAVANTAGE на месте (MCP-сервер читает из окружения).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n715-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, INTEGRATIONS_REGISTRY  # noqa: E402
from proxy import providers, key_health, routes_admin  # noqa: E402
from proxy.compaction import PROVIDER_CONTEXT_LIMITS  # noqa: E402
from proxy import shop_collectors as sc  # noqa: E402
from proxy import shop_watch as sw  # noqa: E402

REMOVED_ENV_KEYS = ("GROK_API_KEY", "NVIDIA_API_KEY", "YANDEX_MARKET_API_KEY")
REMOVED_PROVIDERS = ("grok", "nvidia")
REMOVAL_TEXT = "провайдер удалён решением владельца 12.11"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _client():
    return flask_app.test_client()


API_AUTH = {"Authorization": "Bearer test-secret-123"}


# ─────────────────────────── A.1: манифест ───────────────────────────

def test_a1_manifest_14_keys():
    env_keys = [e["env_key"] for e in key_health.KEY_MANIFEST]
    assert len(env_keys) == 14
    for gone in REMOVED_ENV_KEYS:
        assert gone not in env_keys, gone
    for keep in ("QWEN_API_KEY", "FRED_API_KEY", "ALPHAVANTAGE_API_KEY",
                 "TAVILY_API_KEY", "TELEGRAM_BOT_TOKEN", "ZAI_API_KEY",
                 "GROQ_API_KEY", "GITHUB_TOKEN_METALOGOS"):
        assert keep in env_keys, keep


def test_a1_registry_duplicate_clean():
    env_keys = [e["env_key"] for e in INTEGRATIONS_REGISTRY]
    for gone in REMOVED_ENV_KEYS:
        assert gone not in env_keys, gone
    # порядок оставшихся не менялся: первые и последние на месте
    assert env_keys[0] == "ZAI_API_KEY"
    assert env_keys[-1] == "GITHUB_TOKEN_METALOGOS"


# ─────────────────────── A.2: цепочка провайдеров ───────────────────────

def test_a2_no_removed_providers_in_chain():
    for name in REMOVED_PROVIDERS:
        assert name not in providers.PROVIDERS, name
        assert name not in providers.TOKEN_COSTS, name
        assert name not in PROVIDER_CONTEXT_LIMITS, name
        assert name not in routes_admin._MODEL_LABELS, name
        assert name not in routes_admin._MODEL_CATALOG_EXTRA, name
        for chain in providers.COMBO_CHAINS.values():
            provs = [p for p, _ in chain]
            assert name not in provs, f"{name} в цепочке {provs}"
    # REMOVED_PROVIDERS — громкий отказ для обоих
    for name in REMOVED_PROVIDERS:
        assert name in providers.REMOVED_PROVIDERS
        assert "12.11" in providers.REMOVED_PROVIDERS[name]


def test_a2_detection_kept_no_silent_fallback():
    """Префиксы grok/nvidia/ продолжают детектироваться (не уходят в
    приоритетного провайдера) — чтобы отказ был громким и осмысленным."""
    assert providers._provider_for_model("grok-3") == "grok"
    assert providers._provider_for_model("nvidia/llama-3.3-nemotron-super-49b-v1.5") == "nvidia"


@pytest.mark.parametrize("model", [
    "grok-3",
    "grok-2",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "grok:grok-3",  # явная форма после удаления не признаётся → префикс
])
def test_a2_direct_request_loud_refusal(model, monkeypatch):
    """Запрос модели удалённого провайдера — громкий отказ, НЕ тихий
    переход: ни одного вызова _call_single_provider."""

    def no_network(*a, **kw):
        raise AssertionError(f"сетевой вызов при удалённом провайдере: {a[:2]}")

    monkeypatch.setattr(providers, "_call_single_provider", no_network)
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}],
                                   model_override=model)
    assert res["reply"], model
    assert REMOVAL_TEXT in res["reply"], res["reply"]
    assert res.get("removed_provider") in REMOVED_PROVIDERS
    assert res["tokens_in"] == 0 and res["tokens_out"] == 0


def test_a2_override_on_removed_provider_skipped(tmp_path, monkeypatch):
    """Назначение отдела (override_<dept>.txt) на grok-модель — модель
    пропускается с громкой записью, вторая (живая) модель отвечает."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "override_lz.txt").write_text("grok-3\nglm-4.6\n", encoding="utf-8")
    monkeypatch.setattr(providers, "CFG_DIR", cfg)
    monkeypatch.setattr(routes_admin, "CFG_DIR", cfg)
    providers._cfg_cache["overrides"] = {"lz": "grok-3\nglm-4.6\n"}
    providers._cfg_cache["_mtimes"] = {}
    providers._cfg_cache["_last_check"] = 0.0

    calls = []

    def stub(provider_name, model, *a, **kw):
        calls.append((provider_name, model))
        assert provider_name not in REMOVED_PROVIDERS, calls
        return {"reply": "живой ответ", "provider": provider_name,
                "model": model, "tokens_in": 1, "tokens_out": 1}

    monkeypatch.setattr(providers, "_call_single_provider", stub)
    res = providers._call_llm_impl("lz", [{"role": "user", "content": "привет"}])
    assert res["reply"] == "живой ответ"
    assert ("zai", "glm-4.6") in calls, calls
    assert all(p not in REMOVED_PROVIDERS for p, _ in calls)
    providers._cfg_cache["overrides"] = {}
    providers._cfg_cache.pop("_mtimes", None)


def test_a2_no_removed_urls_in_source():
    """Мутационный гвард: URL удалённых провайдеров не возвращаются в код."""
    src = open(os.path.join(REPO_ROOT, "proxy", "providers.py"),
               encoding="utf-8").read()
    assert "api.x.ai" not in src
    assert "integrate.api.nvidia.com" not in src


# ─────────────────────── A.3: площадка магазина ───────────────────────

def test_a3_ym_collector_removed():
    assert "ym" not in sc.COLLECTORS
    assert not hasattr(sc, "collect_yandexmarket")
    assert not hasattr(sc, "_ym_offers_from")
    assert "ym" not in sw.PLATFORMS_MVP
    assert "ym" not in routes_admin._SHOP_SOURCE_STATUS
    # прямой collect('ym') — честный отказ «нет сборщика», не падение
    r = sc.collect("ym", "смартфон")
    assert r["ok"] is False and r["kind"] == "no_collector"


def test_a3_api_shop_sources_no_ym():
    resp = _client().get("/api/shop/sources", headers=API_AUTH)
    assert resp.status_code == 200
    data = resp.get_json()
    ids = [s["id"] for s in data["sources"]]
    labels = " ".join(s["label"] for s in data["sources"])
    assert "ym" not in ids
    assert "Яндекс.Маркет" not in labels
    # известные площадки на месте (порядок оставшихся не менялся)
    assert ids[:2] == ["wb", "ozon"]


def test_a3_api_models_no_grok():
    resp = _client().get("/api/models", headers=API_AUTH)
    assert resp.status_code == 200
    keys = [m["key"] for m in resp.get_json()["models"]]
    assert "grok" not in keys
    assert "zai" in keys  # приоритетный на месте


# ─────────── греп-гвард наряда: запрещённых паттернов в коде нет ───────────

def test_grep_no_removed_patterns_outside_tests_docs():
    """Проверка из наряда A.2: GROK_API_KEY|NVIDIA_API_KEY|api.x.ai|
    integrate.api.nvidia.com (+YANDEX_MARKET_API_KEY) в *.py/*.mlog/*.txt
    вне tests/, docs/, uploads/, archive/ → пусто."""
    import glob
    patterns = ("GROK_API_KEY", "NVIDIA_API_KEY", "YANDEX_MARKET_API_KEY",
                "api.x.ai", "integrate.api.nvidia.com")
    skip_dirs = ("tests/", "docs/", "uploads/", "archive/", "node_modules",
                 ".git/", "report_forge_ui", "reports/", "skills/", "library/",
                 "memories/", "skills_index/", "data/")
    hits = []
    for path in glob.glob(os.path.join(REPO_ROOT, "**"), recursive=True):
        rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        if not os.path.isfile(path) or os.path.islink(path):
            continue
        if not rel.endswith((".py", ".mlog", ".txt")):
            continue
        if any(rel.startswith(s) or rel.startswith("./" + s) for s in skip_dirs):
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for pat in patterns:
            if pat in text:
                hits.append(f"{rel}: {pat}")
    assert not hits, "остались вхождения: " + "; ".join(hits)
