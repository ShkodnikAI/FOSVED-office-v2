"""Наряд №383: гварды скилл-слоя — каждый read_file("skills/…") в dept/*.mlog
адресует СУЩЕСТВУЮЩИЙ скилл: либо в манифесте (снапшот прода), либо имеет
честный инлайн-фолбэк (SkillNote) в том же модуле.

Факты до исполнения: 56 скилл-чтений в dept/*.mlog; 36 — в манифесте (реальные,
восстанавливаются bootstrap'ом на проде; в песочнице отсутствуют — скиллы вне
git, FO-012), 20 — фантомы skills/fosved/{finance ×9, marketing ×11} — их нет
даже в снапшоте: чтения были молча пустыми на проде.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPT = {f.name: f.read_text(encoding="utf-8") for f in (REPO_ROOT / "dept").glob("*.mlog")}
MANIFEST = json.loads((REPO_ROOT / "skills-manifest.json").read_text(encoding="utf-8"))
MANIFEST_KEYS = set(MANIFEST["skills"].keys())

FALLBACK_FN = {"finance.mlog": "FinanceSkillNote", "marketing.mlog": "MarketingSkillNote"}
PHANTOMS = {
    "finance.mlog": [
        "cashflow-forecasting", "invoice-lifecycle-management", "unit-economics-calculation",
        "revenue-recognition-discipline", "forecast-verification-protocol",
        "tax-compliance-multi-jurisdiction", "multi-currency-handling",
        "mrr-arr-reporting", "runway-and-burn-analysis",
    ],
    "marketing.mlog": [
        "audience-segmentation", "forecast-before-launch", "campaign-verification",
        "honest-claims-discipline", "market-research-methods", "competitive-analysis",
        "unit-economics-and-cac", "positioning-and-messaging", "channel-strategy",
        "ab-testing-protocol", "launch-orchestration",
    ],
}


def _claimed_skills(src: str) -> list:
    return [
        m.group(1) for m in re.finditer(r'read_file\("(skills/[^"]+)"\)', src)
        if m.group(1) != "skills/" + m.group(1)  # защита от пустых
    ]


def test_every_skill_read_resolvable():
    """Каждое чтение скилла: имя в манифесте ИЛИ инлайн-фолбэк в том же модуле."""
    problems = []
    for fname, src in DEPT.items():
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))
        for path in _claimed_skills(code):
            name = path[len("skills/"):-len("/SKILL.md")] if path.endswith("/SKILL.md") else path[len("skills/"):]
            if name in MANIFEST_KEYS:
                continue
            fn = FALLBACK_FN.get(fname)
            # фолбэк вызывается с basename (последний сегмент пути)
            if fn and f'{fn}("{name.split("/")[-1]}")' in code:
                continue
            problems.append(f"{fname}: {path} — нет ни в манифесте, ни фолбэка")
    assert not problems, "фантомные скилл-чтения:\n" + "\n".join(problems)


def test_fallback_functions_cover_phantoms():
    """Оба фолбэк-паттерна покрывают все 20 фантомов и не пусты."""
    for fname, fn in FALLBACK_FN.items():
        src = DEPT[fname]
        assert f"pattern {fn}(name: String)" in src
        for name in PHANTOMS[fname]:
            assert f'if name == "{name}" then {{ return "' in src, f"{fn}: нет ветки {name}"
    # честность: не выдумывать экспертные знания — заметки ссылаются на СВОЮ схему/дисциплины
    fin = DEPT["finance.mlog"]
    assert "invoices" in fin and "exchange_rates" in fin  # таблицы из живой БД
    mkt = DEPT["marketing.mlog"]
    assert "honest-claims" in mkt.lower() and "marketing_campaigns" in mkt


def test_marketing_accumulation_bug_fixed():
    """Попутный дефект: result без mut — LoadMarketingSkills всегда возвращал пустоту."""
    seg = DEPT["marketing.mlog"][DEPT["marketing.mlog"].index("pattern LoadMarketingSkills"):]
    seg = seg[:seg.index("\npattern ", 10)]
    assert "let mut result = \"\"" in seg, "накопление result всё ещё сломано"


def test_manifest_backed_reads_untouched():
    """36 чтений из манифеста не тронуты (контент не дублируется в код)."""
    ctx = DEPT.get("context.mlog", "")
    assert 'read_file("skills/deconstruct/SKILL.md")' in ctx
    assert "deconstruct" in MANIFEST_KEYS
    # в манифесте по-прежнему 248 скиллов (манифест не расширялся — граница наряда)
    assert MANIFEST["skills_count"] == 248


def test_snapshot_path_primary():
    """read_file остаётся ПЕРВИЧНЫМ источником: фолбэк только при пустом чтении."""
    fin = DEPT["finance.mlog"]
    seg = fin[fin.index("pattern LoadFinanceSkills"):]
    seg = seg[:seg.index("\npattern ", 10)]
    # порядок: read_file → if s == "" → SkillNote → if s != ""
    i_read = seg.index('read_file("skills/fosved/finance/cashflow-forecasting')
    i_fb = seg.index('FinanceSkillNote("cashflow-forecasting")')
    assert i_read < i_fb
