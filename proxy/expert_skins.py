#!/usr/bin/env python3
"""#743 EXP-1 A.3: валидатор «шкурок» Эксперта.

Формат — skills/expert/skins/README.md: SKIN.md с обязательными полями
frontmatter (domain, professions, triggers, standards, sources, tools),
тело с Failure catalog и Insider glossary, домен == имя каталога.
EXP-2 использует этот валидатор при подгрузке шкурок; here — проверка
формата и белого списка tools (только реально существующие функции).
"""
import re
from pathlib import Path

import yaml

# tools EXP-2, реально существующие в коде (dept/expert.mlog):
# avby_listings -> ExpertAvByListings; residual_value -> ExpertResidualValueData;
# operation_cost -> база шкурки + chart cost; chart -> ExpertGenerateChart.
ALLOWED_TOOLS = {"avby_listings", "residual_value", "operation_cost", "chart"}
REQUIRED_FIELDS = ("domain", "professions", "triggers", "standards", "sources", "tools")
REQUIRED_BODY_SECTIONS = ("Failure catalog", "Insider glossary")


def parse_skin(path):
    """Разбор SKIN.md: возвращает (meta: dict, body: str)."""
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("нет YAML-фронтматтера --- … ---")
    meta = yaml.safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise ValueError("frontmatter не является словарём")
    return meta, m.group(2)


def validate_skin(path):
    """Валидация шкурки. Возврат (ok, errors: list[str]).
    Пустой errors — шкурка принята (EXP-2 подгружает)."""
    path = Path(path)
    errors = []
    if path.name != "SKIN.md":
        errors.append("файл должен называться SKIN.md")
        return False, errors
    try:
        meta, body = parse_skin(path)
    except (ValueError, yaml.YAMLError) as e:
        return False, [f"разбор файла: {e}"]
    for f in REQUIRED_FIELDS:
        if f not in meta or meta[f] in (None, [], ""):
            errors.append(f"поле {f!r} отсутствует или пусто")
    if errors:
        return False, errors
    if meta["domain"] != path.parent.name:
        errors.append(f"domain={meta['domain']!r} не совпадает с каталогом {path.parent.name!r}")
    for f in ("professions", "triggers", "standards", "sources", "tools"):
        if not isinstance(meta[f], list):
            errors.append(f"поле {f!r} должно быть списком")
    tools = meta.get("tools") or []
    if isinstance(tools, list):
        bad = [t for t in tools if t not in ALLOWED_TOOLS]
        if bad:
            errors.append(f"tools вне белого списка {sorted(ALLOWED_TOOLS)}: {bad}")
    for sec in REQUIRED_BODY_SECTIONS:
        if sec not in body:
            errors.append(f"в теле нет раздела {sec!r}")
    return (len(errors) == 0), errors


def pick_skin(query):
    """#744 EXP-2 B.2: сопоставление запроса с triggers[] шкурок.
    Возврат JSON-строки: {"ok": 1, "domain", "skin"} при совпадении
    (триггеры по подстрокам, lowercase), иначе {"ok": 0} — конвейер
    строит черновик (expert_skins_draft). Вызывается из mlog
    (call_python("expert_skins", "pick_skin", [query]))."""
    import json as _json
    q = (query or "").lower()
    root = Path(__file__).resolve().parent.parent / "skills" / "expert" / "skins"
    best = None
    for skin in sorted(root.glob("*/SKIN.md")):
        ok, errors = validate_skin(skin)
        if not ok:
            continue
        try:
            meta, _body = parse_skin(skin)
        except (ValueError, yaml.YAMLError):
            continue
        triggers = [str(t).lower() for t in (meta.get("triggers") or [])]
        hits = [t for t in triggers if t and t in q]
        if hits and (best is None or len(hits) > best[0]):
            best = (len(hits), skin.parent.name, skin.read_text(encoding="utf-8"), hits)
    if best is None:
        return _json.dumps({"ok": 0}, ensure_ascii=False)
    return _json.dumps({"ok": 1, "domain": best[1], "skin": best[2],
                        "matched": best[3][:5]}, ensure_ascii=False)


def list_skins(skins_dir):
    """Каталог надетых шкурок: [(domain, path)] для валидных; битые —
    ('<domain>', path, errors). Используется EXP-2 при выборе шкурки."""
    out = []
    root = Path(skins_dir)
    if not root.exists():
        return out
    for skin in sorted(root.glob("*/SKIN.md")):
        ok, errors = validate_skin(skin)
        if ok:
            out.append((skin.parent.name, str(skin)))
        else:
            out.append((skin.parent.name, {"path": str(skin), "errors": errors}))
    return out
