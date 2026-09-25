"""Наряд №385: гварды модель-каскадов — инвентаризация config-читателей,
dept-заявленные каскады глубины применяются к tier-роутингу, дефолт не тронут.

Факт наряда (§5.6): каскады quick/standard/deep существовали механизмом
(FOIP-003.15: ClassifyQueryTier → kv query_tier → GetModelFallbackChain →
tier_X.txt), но команды глубины из промптов отделов (/quickexpert, /deepexpert,
/quickanalyze) не мапились в tier — каскад применялся не там, где заявлен.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")

TIER_FILES = {
    "quick": (REPO_ROOT / "config" / "tier_quick.txt").read_text(encoding="utf-8"),
    "standard": (REPO_ROOT / "config" / "tier_standard.txt").read_text(encoding="utf-8"),
    "deep": (REPO_ROOT / "config" / "tier_deep.txt").read_text(encoding="utf-8"),
}


def _classify_body():
    seg = APP[APP.index("pattern ClassifyQueryTier"):]
    return seg[:seg.index("\npattern ", 10)]


def test_dept_declared_cascades_mapped():
    """Команды глубины из промптов отделов задают tier модели."""
    body = _classify_body()
    mapped_quick = [
        ("/quickexpert", "quick"),   # library/expert.md: уровень 1
        ("/quickanalyze", "quick"),  # library/osp.md: компрессионный формат
    ]
    mapped_deep = [
        ("/deepexpert", "deep"),     # library/expert.md: уровень 3
        ("/osp deep", "deep"), ("/osp full", "deep"), ("/osp wargame", "deep"),
        ("/lz deep", "deep"), ("/chain", "deep"), ("/debrief", "deep"),
    ]
    for cmd, tier in mapped_quick + mapped_deep:
        assert f'starts_with(text, "{cmd}")' in body, f"{cmd} не маплен в tier"
    # приоритет: явные команды глубины проверяются ДО ключевых слов deep
    assert body.index('"/quickexpert"') < body.index("deep_kw")


def test_tier_files_have_models():
    """Каждый tier-файл содержит хотя бы одну модель (некомментарную строку)."""
    for tier, content in TIER_FILES.items():
        lines = [l.strip() for l in content.splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        assert lines, f"config/tier_{tier}.txt пуст (одни комментарии)"
        # формат: provider/model или голое имя модели (kimi-k2)
        for l in lines:
            assert re.fullmatch(r"[\w.\-/]+", l), f"tier_{tier}: подозрительная строка {l!r}"


def test_chain_priority_order():
    """Приоритет цепочки FOIP-003.15: tier → override отдела → глобальный → дефолт."""
    seg = APP[APP.index("pattern GetModelFallbackChain"):]
    seg = seg[:seg.index("\npattern ", 10)]
    i_tier = seg.index('kv_get("query_tier")')
    i_override = seg.index('override_file = "config/override_"')
    i_global = seg.index('read_file("config/priority_model.txt")')
    assert i_tier < i_override < i_global, "порядок приоритета цепочки нарушен"
    # граница наряда: дефолт не тронут
    assert 'return "glm-4.6"' in seg


def test_tier_set_reset_lifecycle():
    """query_tier ставится на запрос (webhook) и сбрасывается после использования."""
    assert 'kv_set("query_tier", tier)' in APP
    assert 'kv_set("query_tier", "")' in APP
    assert 'kv_get("query_tier")' in APP


def test_config_inventory_complete():
    """Инвентарь: все файлы config/ имеют живого читателя (mlog или python).
    waker_windows.txt — осознанное исключение: конфиг внешнего waker'а (FO-052,
    «конфиг по месту исполнения»), кодом офиса не читается."""
    providers_py = (REPO_ROOT / "proxy" / "providers.py").read_text(encoding="utf-8")
    eng = (REPO_ROOT / "dept" / "engineering.mlog").read_text(encoding="utf-8")
    # tier-файлы читаются динамическим путём "config/tier_" + tier + ".txt"
    assert 'config/tier_' in APP
    readers = {
        "priority_model.txt": [APP, providers_py],
        "priority_provider.txt": [providers_py],
        "tier_quick.txt": ["config/tier_"], "tier_standard.txt": ["config/tier_"],
        "tier_deep.txt": ["config/tier_"],
        "engineering_normbase.txt": [eng],
        "engineering_min_safety_factor.txt": [eng],
    }
    KNOWN_EXTERNAL = {"waker_windows.txt"}
    orphans = []
    for f in (REPO_ROOT / "config").iterdir():
        if f.name in readers:
            if not any(f.name in src or src in APP for src in readers[f.name]):
                orphans.append(f.name)
        elif f.name.startswith("override_"):
            continue  # динамический путь ("config/override_" + dept) — app.mlog:676
        elif f.name in KNOWN_EXTERNAL:
            continue
        else:
            orphans.append(f"{f.name} (читатель не найден)")
    assert not orphans, f"config-файлы без читателей: {orphans}"
