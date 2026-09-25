"""Наряд №380: гварды Legal — populate knowledge-паков в KV + DDL contract_templates.

Факты до исполнения:
- populate «populated at startup from .md files» был заявлен (legal.mlog :324),
  но не существовал — все юрисдикции/формы молча деградировали в хардкод-фолбэки;
- contract_templates читался (ListTemplates SELECT), но не создавался нигде —
  свежий деплой падал SQL_ERROR на /legal-templates.
"""
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEGAL = (REPO_ROOT / "dept" / "legal.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def test_populate_exists_and_wired():
    """PopulateLegalKnowledge живёт и вызывается из обоих лоадеров."""
    assert "pattern PopulateLegalKnowledge()" in LEGAL
    assert "pattern LoadKnowledgeFile(fpath: String)" in LEGAL
    seg_jx = LEGAL[LEGAL.index("pattern LoadJurisdictionKnowledge"):]
    seg_jx = seg_jx[:seg_jx.index("\npattern ", 10)]
    assert "PopulateLegalKnowledge()" in seg_jx, "LoadJurisdictionKnowledge не населяет KV"
    seg_bf = LEGAL[LEGAL.index("pattern LoadBusinessFormKnowledge"):]
    seg_bf = seg_bf[:seg_bf.index("\npattern ", 10)]
    assert "PopulateLegalKnowledge()" in seg_bf, "LoadBusinessFormKnowledge не населяет KV"


def test_todo_stub_guard():
    """TODO-заглушки пропускаются (порог длины + маркер), реальные паки проходят."""
    seg = LEGAL[LEGAL.index("pattern LoadKnowledgeFile"):]
    seg = seg[:seg.index("\npattern ", 10)]
    assert 'let safe = redact(content, "all")' in seg, "taint-валидатор: redact ДО решений"
    assert 'if length(safe) < 400 then { return "" }' in seg
    assert 'if contains(safe, "TODO:") then { return "" }' in seg
    # критерий соответствует реальности паков
    jx = REPO_ROOT / "library" / "knowledge" / "legal" / "jurisdictions"
    by = (jx / "BY.md").read_text(encoding="utf-8")
    assert len(by) >= 400 and "TODO:" not in by, "BY.md должен быть реальным паком"
    for stub in ("RU.md", "EU.md", "US.md"):
        content = (jx / stub).read_text(encoding="utf-8")
        assert len(content) < 400 or "TODO:" in content, f"{stub} перестал быть заглушкой — обнови гвард"
    # бизнес-формы — реальный контент
    bf = REPO_ROOT / "library" / "knowledge" / "legal" / "business-forms"
    for f in ("OOO.md", "IP.md", "SELF_EMPLOYED.md"):
        content = (bf / f).read_text(encoding="utf-8")
        assert len(content) >= 400, f"{f} должен быть реальным паком"


def test_kv_keys_consistent():
    """Ключи populate совпадают с ключами чтения (legal_jx_*, legal_bf_*)."""
    # чтение в лоадере
    assert 'let key = "legal_jx_" + jurisdiction' in LEGAL
    assert 'kv_get("legal_bf_" + form)' in LEGAL
    # populate покрывает все 4 юрисдикции и 3 формы (константы BF_*)
    for jx in ("BY", "RU", "EU", "US"):
        assert f'kv_set("legal_jx_{jx}"' in LEGAL, f"нет populate для юрисдикции {jx}"
    for form in ("ooo", "ip", "selfemployed"):
        assert f'kv_set("legal_bf_{form}"' in LEGAL, f"нет populate для формы {form}"
    # version-stamp от устаревания
    assert '_ver"' in LEGAL
    assert "sha256(" in LEGAL


def test_contract_templates_ddl():
    """DDL contract_templates в InitDB — схема снята с живой БД (нулевой дрейф)."""
    m = re.search(r'db_execute\("CREATE TABLE IF NOT EXISTS contract_templates \((.*?)\)"\)', APP, re.S)
    assert m, "нет CREATE TABLE IF NOT EXISTS contract_templates в InitDB"
    ddl = f"CREATE TABLE IF NOT EXISTS contract_templates ({m.group(1)})"
    con = sqlite3.connect(":memory:")
    con.execute(ddl)
    con.execute(ddl)  # идемпотентность
    con.close()
    # дрейф vs живая БД (skip в CI-песочнице)
    db = REPO_ROOT / "data" / "fosved.db"
    if not db.exists():
        return
    live = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    live_cols = {r[1] for r in live.execute("PRAGMA table_info(contract_templates)")}
    mem = sqlite3.connect(":memory:")
    mem.execute(ddl)
    ddl_cols = {r[1] for r in mem.execute("PRAGMA table_info(contract_templates)")}
    assert ddl_cols == live_cols, f"дрейф: DDL={sorted(ddl_cols)} live={sorted(live_cols)}"


def test_list_templates_honest_degradation():
    """Seed-данных нет — ListTemplates честно деградирует, не выдумывает шаблоны."""
    seg = LEGAL[LEGAL.index("pattern ListTemplates"):]
    seg = seg[:seg.index("\npattern ", 10)] if "\npattern " in seg[10:] else seg
    assert "Шаблоны не загружены" in seg
    assert "/legal-nda" in seg and "/legal-msa" in seg
    # фолбэки юрисдикций не удалены (нужны для TODO-паков RU/EU/US)
    assert "Континентальная система. ГК РБ" in LEGAL
    assert "knowledge pack не загружен" in LEGAL
