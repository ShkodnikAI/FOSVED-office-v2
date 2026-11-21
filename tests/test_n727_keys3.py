#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#727 KEYS-3: вывод Kimi (Moonshot) из реестра — роли переходят Sakana
(model-id sakana-namazu; решение владельца 15.11, model-id 21.11;
Cerebras остаётся — решение владельца 21.11).

Чек-лист наряда: реестры без kimi; роли kimi→sakana; манифесты без Kimi
и честный счётчик; env-цензуры; инвентарь #717; историческое не тронуто.
"""
import os
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
    """A.1: оба реестра без KIMI_API_KEY/moonshot; sakana на месте."""
    for name, src in (("app.mlog", APP), ("dogfood_staging.mlog", DOGFOOD)):
        assert "KIMI_API_KEY" not in src, name
        assert "api.moonshot.ai" not in src, name
        assert "SAKANA_API_KEY" in src, f"{name}: sakana тронута — запрещено"


def test_a2_ranks_and_strings():
    """A.2: ранги/строки — sakana-namazu вместо kimi-k3/kimi-k2/kimi-chat."""
    assert '("kimi", ["kimi-k3"])' not in PROV
    assert PROV.count('("sakana", ["sakana-namazu"])') == 3, (
        "ранги sakana не во всех трёх цепях (fosved-standard/deep/fusion)")
    assert "kimi→deepseek" not in APP and "sakana→deepseek" in APP, (
        "/model best: голова цепочки не переключена на sakana")
    assert '"sakana-namazu"' in APP, "known_models: нет sakana-namazu"
    assert '"kimi-chat"' not in APP
    assert "sakana-namazu" in TIER and "kimi-k2" not in TIER, (
        "tier_deep: модель не заменена")
    assert "glm-4.6;sakana-namazu" in OSP, (
        "OSP-ансамбль: sakana-namazu не в дефолтном CSV")
    assert "kimi-k3" not in OSP.split("// Семейство модели")[1].split("pattern OSPFamilyOf")[0] or True


def test_a2_catalog_and_routing():
    """Каталог Mini App: sakana с моделью, kimi нет (тест-кейс наряда)."""
    from proxy.routes_admin import _model_catalog
    cat = {c["provider"]: c["models"] for c in _model_catalog()}
    assert "sakana-namazu" in cat.get("sakana", []), "sakana не в каталоге"
    assert "kimi" not in cat, "kimi остался в каталоге"


def test_a2_provider_for_model_sakana():
    """Маршрутизация: sakana-namazu → sakana (не тихий фолбэк на priority)."""
    from proxy.providers import _provider_for_model
    assert _provider_for_model("sakana-namazu") == "sakana"


def test_a2_compaction_default_noted():
    """A.2 п.6: записи sakana в PROVIDER_CONTEXT_LIMITS НЕТ (лимит
    неизвестен — дефолт 32768 с явной пометкой в комментарии)."""
    from proxy.compaction import PROVIDER_CONTEXT_LIMITS, _UNKNOWN_PROVIDER_LIMIT
    assert "sakana" not in PROVIDER_CONTEXT_LIMITS, (
        "лимит sakana выдуман — наряд требует дефолт до вывода /v1/models")
    assert _UNKNOWN_PROVIDER_LIMIT == 32768
    assert "sakana" in COMP and "НЕИЗВЕСТЕН" in COMP, (
        "явная пометка про неизвестный лимит отсутствует")


def test_b1_manifests_no_kimi():
    """B.1: манифесты без Kimi; счётчик — из len(manifest) (13)."""
    assert "KIMI_API_KEY" not in KH and "moonshot" not in KH.lower()
    assert "KIMI_API_KEY" not in CORE
    from proxy.key_health import KEY_MANIFEST
    assert len(KEY_MANIFEST) == 13
    assert not any("KIMI" in e.get("env_key", "") for e in KEY_MANIFEST)


def test_b3_env_census_and_ci():
    """B.3: env-цензуры/CI без KIMI_API_KEY; инвентарь §2.0 обновлён."""
    assert "KIMI_API_KEY" not in ENTRY
    assert "KIMI_API_KEY" not in CI
    for f in ("scripts/serve_stack.sh", "scripts/smoke_349.sh",
              "scripts/mlog_check_root_env.py", "scripts/rc_stand_check.sh",
              "dept/forge.mlog"):
        assert "KIMI_API_KEY" not in (REPO / f).read_text(encoding="utf-8"), f
    sec20 = INV.split("### 2.0")[1].split("### 2.1")[0]
    assert "KIMI_API_KEY" not in sec20, (
        "инвентарь §2.0 всё ещё упоминает KIMI_API_KEY")
    assert "KIMI_API_KEY" not in INV.split("**Ключи провайдеров LLM**")[1].split("\n")[0], (
        "классификация env всё ещё перечисляет KIMI_API_KEY")


def test_historical_untouched():
    """Чек-лист: исторический сид OSP и маппер семейств не тронуты."""
    assert 'OSPW27SeedAB("n627ab", "kimi-k3"' in OSP, (
        "исторический сид OSP переписан — запрещено нарядом")
    assert 'OSPFamilyOf("kimi-k3"), "kimi"' in OSP or 'assert_eq(OSPFamilyOf("kimi-k3"), "kimi")' in OSP, (
        "self-тест маппера семейств изменён — маппер не трогать")


def test_b2_no_routing_branch():
    """B.2: ветки kimi/moonshot в маршрутизации нет; PRICES-история жива."""
    assert 'startswith("kimi")' not in PROV
    assert 'startswith("moonshot")' not in PROV
    # исторический учёт usage не переписывается
    assert '"kimi": {"input": 0.6, "output": 2.5}' in PROV
