"""Наряд #384: гварды Яны — синхронность списка делегирования (промпт ↔ гейт-2 ↔
диспетчер), живая проба (обоими бинарями), честный статус даты-якоря экстрактора.

Факты при исполнении:
- v1 «гейт 2 пропускает [DELEGATE: admin]» устарела: office#359 свёл гейт-2 и
  диспетчер YanaCheckDelegate к ЕДИНОМУ списку YanaDelegateListJson (12 slug'ов);
  admin исключён сознательно (AGENTS.md §3) и блокируется в обоих местах;
- дата-якорь «today being 2026-07-06» в экстракторе памяти починен нарядом-358
  (routes_tail.py: динамическая дата Europe/Minsk);
- «закрытие петель» (delegation ≥85%) — цель в промпте, автоматического трекера
  нет — честное ограничение зафиксировано в самом промпте (library/yana.md).
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
YANA = (REPO_ROOT / "dept" / "yana.mlog").read_text(encoding="utf-8")
PROMPT = (REPO_ROOT / "library" / "yana.md").read_text(encoding="utf-8")
TAIL = (REPO_ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")
SCENARIO = REPO_ROOT / "test_n384_delegation.mlog"

DELEGATE_SLUGS = [
    "osp", "lz", "expert", "marketing", "finance", "legal",
    "dev", "design", "qa", "visual", "engineering", "kavalnya",
]

MARKS = [
    *[f"g{i:02d}_{s}_gate_pass" for i, s in enumerate(DELEGATE_SLUGS, 1)],
    *[f"d{i:02d}_{s}_dispatcher" for i, s in enumerate(DELEGATE_SLUGS, 1)],
    "ga_admin_gate_denies", "da_admin_dispatcher_empty",
    "gn_ghost_gate_denies", "dn_ghost_dispatcher_empty",
    "s01_single_source_by_construction",
]


def _run(binary: str):
    return subprocess.run(
        [str(REPO_ROOT / binary), "run", str(SCENARIO)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
    )


def test_delegation_probe_both_binaries():
    """Живая проба: таблица slug → гейт → диспетчер на бою и гварде (0.27+0.25)."""
    for binary in ("bin/mlog", "bin/mlog-025"):
        proc = _run(binary)
        assert proc.returncode == 0, f"{binary}: rc={proc.returncode}\n{proc.stderr[-1500:]}"
        for mark in MARKS:
            assert f"PASS {mark}" in proc.stdout, f"{binary}: нет PASS {mark}\n{proc.stdout[-1500:]}"
        assert "FAILED" not in proc.stdout, f"{binary}: есть FAILED:\n{proc.stdout}"


def test_prompt_gate_list_sync():
    """Промпт-список отделов ↔ YanaDelegateListJson: 12 slug'ов синхронны, admin — вне."""
    m = re.search(r"YanaDelegateListJson\(\) -> String \{\s*return json_encode\(\[([^\]]+)\]\)", YANA)
    assert m, "YanaDelegateListJson не найден"
    json_slugs = re.findall(r'"(\w+)"', m.group(1))
    assert json_slugs == DELEGATE_SLUGS, f"список в коде изменился: {json_slugs}"
    # промпт описывает все 12 (список «- slug — ...» в library/yana.md)
    prompt_slugs = set(re.findall(r"^- (\w+) — ", PROMPT, re.M))
    for s in DELEGATE_SLUGS:
        assert s in prompt_slugs, f"{s} описан в коде, но отсутствует в промпте Яны"
    # admin: в промпте ЕСТЬ (отдел существует), в делегировании НЕТ (AGENTS.md §3)
    assert "admin" in prompt_slugs
    assert "admin" not in json_slugs


def test_dispatcher_single_source():
    """YanaCheckDelegate читает тот же единый список, что и гейт-2 (office#359)."""
    seg = YANA[YANA.index("pattern YanaCheckDelegate"):]
    seg = seg[:seg.index("\npattern ", 10)]
    assert "return YanaDelegateTarget(reply)" in seg


def test_memory_extractor_date_dynamic():
    """Дата-якорь устранён нарядом-358: экстрактор (routes_tail.py) берёт дату динамически."""
    code = "\n".join(l for l in TAIL.splitlines() if not l.strip().startswith("#"))
    assert "today being 2026" not in code, "зашитая дата вернулась в код (упоминание в комментарии #358 — допустимо)"
    assert "today_str = datetime.now(_tz)" in code
    assert "naryad-358" in TAIL
    # «закрытие петель»: честное ограничение осталось зафиксированным в промпте
    assert "не может видеть что происходит после делегирования" in PROMPT
