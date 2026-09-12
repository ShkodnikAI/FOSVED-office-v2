#!/usr/bin/env python3
"""proxy/departments.py — FO-018: декларативные департаменты (agent-as-markdown).

Эталон: sst/opencode config/agent.ts. Департамент = departments/<name>.md:
  ---
  model: glm-4.5            # опционально; иначе combo-логика как раньше
  temperature: 0.7          # опционально; иначе 0.7 (прежний хардкод)
  tools: [db_query, send_message]
  permission:               # FO-015: overlay в Guardian (pattern: action)
    http_*: deny
  mode: primary             # primary | subagent | all
  ---
  Тело файла = системный промпт департамента.

Иерархия (последний wins): код/конфиг → override_<dept>.txt → departments/<name>.md.
Подстановка {env:VAR} в скалярах. Неизвестное поле/тулза/действие → громкая ошибка
при старте (офис не поднимается). Permission мержится в Guardian как per-dept overlay.
"""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEPARTMENTS_DIR = BASE_DIR / "departments"

ALLOWED_FIELDS = {"model", "temperature", "tools", "permission", "mode"}
ALLOWED_MODES = {"primary", "subagent", "all"}
ALLOWED_ACTIONS = {"allow", "ask", "deny"}
DEFAULT_TEMPERATURE = 0.7  # прежний хардкод _call_single_provider

_ENV_RE = re.compile(r"\{env:([A-Z0-9_]+)\}")


class DepartmentsConfigError(Exception):
    """Громкая ошибка конфигурации: офис не поднимается."""


def _substitute_env(value):
    def repl(m):
        var = m.group(1)
        if var not in os.environ:
            raise DepartmentsConfigError(f"departments: {{env:{var}}} — переменная окружения не задана")
        return os.environ[var]
    return _ENV_RE.sub(repl, value)


def _parse_scalar(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [v.strip().strip("'\"") for v in inner.split(",")] if inner else []
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw.strip("'\"")


def parse_frontmatter(text, source="<decl>"):
    """Строгий парсер YAML-подмножества: скаляры, списки (- item), dict на 1 уровень."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        raise DepartmentsConfigError(f"{source}: frontmatter не закрыт (--- ... ---)")
    fm_text = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    fm, current_key = {}, None
    for lineno, line in enumerate(fm_text.split("\n"), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.strip().startswith("-"):
            continue  # элемент блочного списка — обрабатывается после цикла
        indented = line.startswith((" ", "\t"))
        if indented and current_key is None:
            raise DepartmentsConfigError(f"{source}:{lineno}: вложенность без родительского ключа")
        m = re.match(r"^(\s+)([A-Za-z0-9_.\-*]+):\s*(.*)$", line)
        if indented and m:
            key, val = m.group(2), m.group(3).strip()
            if not isinstance(fm[current_key], dict):
                if fm[current_key] is not None:
                    raise DepartmentsConfigError(f"{source}:{lineno}: '{current_key}' — смешение списка и dict")
                fm[current_key] = {}
            if not val:
                raise DepartmentsConfigError(f"{source}:{lineno}: пустое значение в dict '{current_key}'")
            fm[current_key][key] = _substitute_env(val)
            continue
        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if not m:
            raise DepartmentsConfigError(f"{source}:{lineno}: не понял строку: {line!r}")
        key, val = m.group(1), m.group(2).strip()
        current_key = key
        if val == "":
            fm[key] = None  # список строками ниже или dict
            continue
        parsed = _parse_scalar(val)
        fm[key] = _substitute_env(parsed) if isinstance(parsed, str) else parsed
        if key == "tools" and isinstance(parsed, list):
            fm[key] = parsed
    # список "- item" под ключом
    if fm_text and re.search(r"^\s+-\s", fm_text, re.M) and not isinstance(fm.get(current_key), dict):
        items = [re.sub(r"^\s+-\s*", "", l).strip().strip("'\"") for l in fm_text.split("\n") if re.match(r"^\s+-\s", l)]
        if items:
            fm[current_key] = [_substitute_env(i) for i in items]
    return fm, body


def validate_declaration(dept, fm, body, source):
    """Неизвестное поле/тулза-класс/действие/режим → громкая ошибка (старт роняется)."""
    unknown = set(fm) - ALLOWED_FIELDS
    if unknown:
        raise DepartmentsConfigError(f"{source}: неизвестные поля frontmatter: {sorted(unknown)} (разрешены: {sorted(ALLOWED_FIELDS)})")
    if "mode" in fm and fm["mode"] not in ALLOWED_MODES:
        raise DepartmentsConfigError(f"{source}: mode={fm['mode']!r} — разрешены {sorted(ALLOWED_MODES)}")
    if "temperature" in fm and not isinstance(fm["temperature"], (int, float)):
        raise DepartmentsConfigError(f"{source}: temperature должна быть числом")
    if "tools" in fm and not isinstance(fm["tools"], list):
        raise DepartmentsConfigError(f"{source}: tools должен быть списком")
    if "permission" in fm:
        if not isinstance(fm["permission"], dict):
            raise DepartmentsConfigError(f"{source}: permission должен быть dict (pattern: action)")
        for pattern, action in fm["permission"].items():
            if action not in ALLOWED_ACTIONS:
                raise DepartmentsConfigError(f"{source}: permission[{pattern!r}]={action!r} — действие должно быть allow|ask|deny")
    if not body.strip():
        raise DepartmentsConfigError(f"{source}: тело файла (системный промпт) пусто")


def load_declaration(dept):
    """Читает departments/<dept>.md. Возвращает dict или None, если файла нет."""
    path = DEPARTMENTS_DIR / f"{dept}.md"
    if not path.exists():
        return None
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"), source=str(path))
    validate_declaration(dept, fm, body, source=str(path))
    return {"dept": dept, "model": fm.get("model"), "temperature": fm.get("temperature"),
            "tools": fm.get("tools") or [], "permission": fm.get("permission") or {},
            "mode": fm.get("mode", "primary"), "prompt": body, "path": str(path)}


def load_all():
    """Все валидные декларации. Любая ошибка — DepartmentsConfigError наверх (старт падает)."""
    if not DEPARTMENTS_DIR.exists():
        return {}
    decls = {}
    for p in sorted(DEPARTMENTS_DIR.glob("*.md")):
        dept = p.stem
        decl = load_declaration(dept)
        if decl:
            decls[dept] = decl
    return decls


# ── Доступники для llm_proxy (иерархия: код → override_*.txt → декларация) ──
_cache = {"version": 0}

def _decls():
    if _cache["version"] != _mtime_version():
        _cache["data"] = load_all()
        _cache["version"] = _mtime_version()
    return _cache.get("data", {})


def _mtime_version():
    if not DEPARTMENTS_DIR.exists():
        return 0
    return tuple(sorted((p.name, int(p.stat().st_mtime)) for p in DEPARTMENTS_DIR.glob("*.md")))


def get_declaration(dept):
    return _decls().get(dept)


def prompt_for(dept):
    """Системный промпт из декларации или None (тогда старая цепочка)."""
    d = get_declaration(dept)
    return d["prompt"] if d else None


def temperature_for(dept):
    d = get_declaration(dept)
    return float(d["temperature"]) if d and d.get("temperature") is not None else DEFAULT_TEMPERATURE


def model_for(dept):
    d = get_declaration(dept)
    return d.get("model") if d else None


def mode_for(dept):
    d = get_declaration(dept)
    return d.get("mode", "primary") if d else None


def apply_guardian_overlays():
    """Permission из frontmatter → Guardian (per-dept overlay). Идемпотентно, аудируемо."""
    applied = 0
    for dept, d in _decls().items():
        for pattern, action in (d.get("permission") or {}).items():
            from proxy.guardian import add_rule
            existing = _existing_frontmatter_rule(dept, pattern)
            if existing and existing["action"] == action:
                continue
            if existing:
                from proxy.core import _db
                with _db() as conn:
                    conn.execute("UPDATE guardian_rules SET action=?, updated_at=datetime('now') WHERE id=?",
                                 [action, existing["id"]])
            else:
                add_rule(dept, pattern, action, source="frontmatter")
            applied += 1
    return applied


def _existing_frontmatter_rule(dept, pattern):
    from proxy.core import _query
    rows = _query("SELECT id, action FROM guardian_rules WHERE dept=? AND permission=? AND source='frontmatter'",
                  [dept, pattern], fetch=True)
    return rows[0] if rows else None
