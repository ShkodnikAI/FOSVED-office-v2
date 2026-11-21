#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#727 KEYS-3 + отмена установки Sakana (распоряжение владельца 21.11).

В силе: вывод Kimi из реестров/манифестов/env-цензур (решение 15.11,
аудит 5/5 отказов). Отменено: передача ролей kimi → sakana-namazu —
ранги убраны без замены, sakana снова пассивный провайдер реестра.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

APP = (REPO / "app.mlog").read_text(encoding="utf-8")
DOGFOOD = (REPO / "dogfood_staging.mlog").read_text(encoding="utf-8")
OSP = (REPO / "dept" / "osp.mlog").read_text(encoding="utf-8")
PROV = (REPO / "proxy" / "providers.py").read_text(encoding="utf-8")
COMP = (REPO / "proxy" / "compaction.py").read_text(encoding="utf-8")
KH = (REPO / "proxy" / "key_health.py").read_text(encoding="utf-8")
CORE = (REPO / "proxy" / "core.py").read_text(encoding="utf-8")
TIER = (REPO / "config" / "tier_deep.txt").read_text(encoding="utf-8")
ENTRY = (REPO / "entrypoint.sh").read_text(encoding="utf-8")
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
INV = (REPO / "docs" / "office" / "interproc_inventory.md").read_text(encoding="utf-8")


def test_a1_registries_no_kimi():
    """A.1 (в силе): оба реестра без KIMI_API_KEY/moonshot; sakana-строка
    пассивного провайдера на месте (отмена её не трогала)."""
    for name, src in (("app.mlog", APP), ("dogfood_staging.mlog", DOGFOOD)):
        assert "KIMI_API_KEY" not in src, name
        assert "api.moonshot.ai" not in src, name
        assert "SAKANA_API_KEY" in src, f"{name}: sakana-строка реестра пропала"


def test_a2_ranks_removed_no_replacement():
    """Отмена A.2: рангов kimi НЕТ и замены sakana НЕТ — цепи без обоих."""
    assert '("kimi", ["kimi-k3"])' not in PROV
    assert '("sakana", ["sakana-namazu"])' not in PROV
    assert '"sakana": {' not in PROV, (
        "PROVIDERS снова содержит sakana — отмена неполная")
    assert "deepseek→zai→groq→cerebras→anthropic" in APP and "sakana→" not in APP, (
        "/model best: sakana осталась головой цепочки")
    assert '"sakana-namazu"' not in APP and '"kimi-chat"' not in APP, (
        "known_models: модель удалённого/пассивного провайдера в списке")
    assert "sakana-namazu" not in TIER and "kimi-k2" not in TIER
    assert "glm-4.6;sakana-namazu" not in OSP, (
        "OSP-ансамбль: sakana-namazu осталась в дефолтном CSV")
    assert '"sakana": "Sakana"' not in (REPO / "proxy" / "routes_admin.py").read_text(encoding="utf-8"), (
        "мёртвый лейбл каталога sakana остался")


def test_a2_catalog_neither_kimi_nor_sakana():
    """Каталог Mini App: выводится из COMBO_CHAINS — ни kimi, ни sakana."""
    from proxy.routes_admin import _model_catalog
    cat = {c["provider"]: c["models"] for c in _model_catalog()}
    assert "kimi" not in cat
    assert "sakana" not in cat, "sakana без ролей не должна попадать в каталог"


def test_a2_routing_no_sakana_branch():
    """Маршрутизация: ветки sakana нет — sakana-namazu не резолвится
    в провайдера (не тихий обход; прямой вызов sakana вне реестра ролей)."""
    from proxy.providers import _provider_for_model
    assert 'startswith("sakana")' not in PROV
    assert _provider_for_model("sakana-namazu") != "sakana"


def test_a2_compaction_no_sakana_entry():
    """Compaction: sakana в таблице лимитов не участвует (ролей нет);
    дефолт _UNKNOWN_PROVIDER_LIMIT для неё — 32768."""
    from proxy.compaction import PROVIDER_CONTEXT_LIMITS, _UNKNOWN_PROVIDER_LIMIT
    assert "sakana" not in PROVIDER_CONTEXT_LIMITS
    assert "kimi" not in PROVIDER_CONTEXT_LIMITS
    assert _UNKNOWN_PROVIDER_LIMIT == 32768
    assert "отменена" in COMP, "пометка об отмене установки отсутствует"


def test_b1_manifests_no_kimi():
    """B.1 (в силе): манифесты без Kimi; 13 ключей."""
    assert "KIMI_API_KEY" not in KH and "moonshot" not in KH.lower()
    assert "KIMI_API_KEY" not in CORE
    from proxy.key_health import KEY_MANIFEST
    assert len(KEY_MANIFEST) == 13
    assert not any("KIMI" in e.get("env_key", "") for e in KEY_MANIFEST)
    # sakana остаётся пассивной записью проверки ключа (не удалялась)
    assert any(e.get("env_key") == "SAKANA_API_KEY" for e in KEY_MANIFEST)


def test_b3_env_census_and_ci():
    """B.3 (в силе): env-цензуры/CI без KIMI_API_KEY; инвентарь обновлён."""
    assert "KIMI_API_KEY" not in ENTRY
    assert "KIMI_API_KEY" not in CI
    for f in ("scripts/serve_stack.sh", "scripts/smoke_349.sh",
              "scripts/mlog_check_root_env.py", "scripts/rc_stand_check.sh",
              "dept/forge.mlog"):
        assert "KIMI_API_KEY" not in (REPO / f).read_text(encoding="utf-8"), f
    sec20 = INV.split("### 2.0")[1].split("### 2.1")[0]
    assert "KIMI_API_KEY" not in sec20
    assert "KIMI_API_KEY" not in INV.split("**Ключи провайдеров LLM**")[1].split("\n")[0]


def test_historical_untouched():
    """Чек-лист: исторический сид OSP и маппер семейств не тронуты."""
    assert 'OSPW27SeedAB("n627ab", "kimi-k3"' in OSP
    assert 'assert_eq(OSPFamilyOf("kimi-k3"), "kimi")' in OSP


def test_b2_no_routing_branch_prices_history():
    """B.2 (в силе): ветки kimi/moonshot нет; PRICES-история жива."""
    assert 'startswith("kimi")' not in PROV
    assert 'startswith("moonshot")' not in PROV
    assert '"kimi": {"input": 0.6, "output": 2.5}' in PROV
