"""Наряд №382: гварды Kavalnya — KKRoute* удалены (класс №1), lifecycle цел,
скиллы кавальни — факт отсутствия фантомных чтений, v4.1-циклы — слоты после гейта.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KK = (REPO_ROOT / "dept" / "kavalnya.mlog").read_text(encoding="utf-8")
GUARD381 = (REPO_ROOT / "tests" / "test_n381_admin_bridges.py").read_text(encoding="utf-8")


def test_kk_routes_removed():
    """KKRouteToYana/KKRouteToOSP удалены; мосты :4000/dept/* в кавальне = 0."""
    assert "pattern KKRouteToYana" not in KK
    assert "pattern KKRouteToOSP" not in KK
    code = [l for l in KK.splitlines() if not l.strip().startswith("//")]
    assert "\n".join(code).count("4000/dept/") == 0, "мёртвые мосты остались в коде кавальни"
    # намерение зафиксировано в комментарии для истории
    assert "Наряд #382: KKRouteToYana/KKRouteToOSP удалены честно" in KK


def test_allowlist_381_updated():
    """TEMP_ALLOW #381: kavalnya выведена (мостов 0), osp осталась (4, нек вызываемые)."""
    assert "#382 (KKRoute* вычищены)" in GUARD381 or "удалён из allowlist нарядом #382" in GUARD381
    assert '"kavalnya.mlog": 2' not in GUARD381
    assert '"osp.mlog": 4' in GUARD381


def test_lifecycle_intact():
    """Границы наряда: lifecycle кавальни не тронут — V2-паттерны и команды на месте."""
    for pat in ("pattern KKArsenalReview", "pattern KKGetSkillStats"):
        assert pat in KK, f"{pat} потерян"
    for cmd in ("/recruit", "/train", "/polygon", "/debrief", "/assess",
                "/recalibrate-dept", "/arsenal-review", "/paradigm-review"):
        assert f'starts_with(t, "{cmd}")' in KK or f'"{cmd}"' in KK, f"команда {cmd} потеряна"


def test_no_phantom_skill_reads():
    """Факт: кавальня не читает skills/* (фантомов нет — пункт 2 наряда не требует переноса)."""
    assert 'read_file("skills/' not in KK
    assert "skills/" not in [l for l in KK.splitlines() if "read_file" in l and not l.strip().startswith("//")]


def test_skill_stats_via_db():
    """Скилл-статистика живёт в БД (arsenal_reviews), а не в фантомных файлах."""
    assert "pattern KKGetSkillStats" in KK
    assert "arsenal_reviews" in KK
