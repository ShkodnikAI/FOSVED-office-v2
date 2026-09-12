"""FO-019: Профиль владельца — static/dynamic/buckets одним вызовом.

Наряд #85 (пакет G, волна G2). Эталон: supermemory user-profiles —
static (долгие факты) + dynamic (текущий контекст) + buckets (именованные
топики) одним чтением; метафильтр влияет и на выдачу, и на состав.

Хранилище: таблица owner_profile с версионированием в стиле FO-009
(valid_to/superseded_by; NULL valid_to = актуально). Генератор — ночная
консолидация FO-006 (после /cron/consolidate-memory) + ручной POST
/profile/rebuild. Чтение — get_owner_profile(): один вызов, кэш с
инвалидацией по версии профиля (stale-профиль не выдаётся).

Приватность: каждая строка несёт taint-метку ('personal'); содержимое с
признаками секретов (API-ключи, токены, PEM) не попадает в профиль по
построению — фильтрация на входе (факты) и на выходе LLM (двойной контур,
семантика taint Metalogos №274/#310).
"""
import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

from proxy.core import log, _query, _get_setting, _write_llm_trace, _log_error

# ────────────────────────── схема ──────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT NOT NULL,
    bucket TEXT DEFAULT '',
    content TEXT NOT NULL,
    taint TEXT DEFAULT 'personal',
    source_facts TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.8,
    valid_from TEXT DEFAULT (datetime('now')),
    valid_to TEXT,
    superseded_by INTEGER
);
CREATE INDEX IF NOT EXISTS idx_oprofile_active ON owner_profile(section, valid_to);
"""

SECTIONS = ("static", "dynamic", "bucket")
_VERSION_KEY = "owner_profile_version"

# dept → приоритетные buckets (мягкий метафильтр; static всегда входит)
_DEPT_BUCKET_MAP = {
    "finance": ["обязательства", "проекты"],
    "legal": ["обязательства", "проекты"],
    "engineering": ["проекты", "предпочтения"],
    "dev": ["проекты", "предпочтения"],
    "design": ["предпочтения", "проекты"],
    "marketing": ["предпочтения", "проекты"],
    "osp": ["проекты", "обязательства"],
    "lz": ["проекты", "обязательства"],
    "qa": ["обязательства", "проекты"],
    "admin": ["обязательства", "проекты", "предпочтения"],
}

# ────────────────────────── приватность: отсечение секретов ──────────────────────────

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),                # openai-like (вкл. sk-proj-…)
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),                # github PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),        # github fine-grained
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),        # slack
    re.compile(r"AKIA[0-9A-Z]{16}"),                    # aws
    re.compile(r"AIZA[A-Za-z0-9]{10,}"),                # z-ai
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|пароль|токен)\b\s*[:=]\s*\S{8,}"),
]


def _contains_secret(text):
    """True, если текст выглядит как содержащий секрет — по построению
    не допускается в профиль (taint-контур №274/#310)."""
    t = str(text or "")
    return any(p.search(t) for p in _SECRET_PATTERNS)


def ensure_profile_schema():
    """Публичный алиас создания схемы (для init_db/тестов)."""
    _ensure_schema()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _version_stamp() -> str:
    """Штамп версии с микросекундами: два rebuild'а в одну секунду
    обязаны давать разные версии — иначе кэш отдаёт stale-профиль."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _ensure_schema():
    """Создать таблицу профиля, если нет (безопасно вызывать многократно)."""
    from proxy.core import _db, db_lock
    with db_lock:
        c = _db()
        try:
            c.executescript(_SCHEMA)
            c.commit()
        finally:
            c.close()


def _bump_version(ts=None):
    v = ts or _now()
    _query("INSERT INTO system_settings (key, value) VALUES (?, ?) "
           "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
           (_VERSION_KEY, v))
    return v


def current_version():
    return _get_setting(_VERSION_KEY, "") or ""


# ────────────────────────── генерация ──────────────────────────

_PROFILE_FACTS_LIMIT = 200
_PROFILE_FTS_LEN = 400      # обрезка факта на входе LLM

_SYNTH_SYSTEM = ("Ты собираешь профиль владельца офиса по фактам из памяти. "
                 "Верни ТОЛЬКО JSON вида: "
                 '{"static": ["долгий факт", ...], "dynamic": ["актуальный факт", ...], '
                 '"buckets": {"проекты": ["..."], "предпочтения": ["..."], "обязательства": ["..."]}}. '
                 "static — устойчивые факты (имя, семья, город, роль, долгие цели); "
                 "dynamic — текущий контекст (чем занят сейчас, последние решения); "
                 "buckets — сгруппированные по темам факты. Сжимай, не выдумывай, "
                 "без секретов и ключей. Максимум 25 элементов суммарно.")
_BUCKETS_FALLBACK = ("проекты", "предпочтения", "обязательства")
_DEPT_TO_BUCKET = {
    "finance": "обязательства", "legal": "обязательства", "qa": "обязательства",
    "engineering": "проекты", "dev": "проекты", "osp": "проекты", "lz": "проекты",
    "design": "предпочтения", "marketing": "предпочтения",
}


def _load_active_facts(limit=_PROFILE_FACTS_LIMIT):
    rows = _query(
        "SELECT id, dept, content, confidence, updated_at FROM facts "
        "WHERE status = 'active' ORDER BY updated_at DESC, id DESC LIMIT ?",
        (limit,), fetch=True) or []
    return [dict(r) for r in rows]


def _filter_secrets(items):
    """Двойной контур приватности: делим на чистые и заблокированные."""
    clean, blocked = [], 0
    for it in items:
        if _contains_secret(it):
            blocked += 1
        else:
            clean.append(it)
    return clean, blocked


def _deterministic_profile(facts):
    """Профиль без LLM: факты вербатим по деку (dept → bucket).
    Резерв при недоступности суммаризатора — профиль не остаётся пустым."""
    static, dynamic, buckets = [], [], {b: [] for b in _BUCKETS_FALLBACK}
    clean, blocked = _filter_secrets([f["content"] for f in facts])
    for f in facts:
        content = str(f["content"] or "")
        if _contains_secret(content):
            continue
        item = f"[{f['dept']}] {content[:300]}"
        b = _DEPT_TO_BUCKET.get(f["dept"] or "")
        if b:
            buckets[b].append(item)
        else:
            dynamic.append(item)
    # первые факты (по updated_at DESC) — кандидат в static
    static = dynamic[:5]
    dynamic = dynamic[5:]
    return {"static": static, "dynamic": dynamic, "buckets": buckets}, blocked


def _synth_profile(facts):
    """Суммаризация фактов в профиль LLM'ом (dept='memory', дешёвый путь
    консолидации). Возврат: (profile_dict, blocked_secrets, ok)."""
    lines = []
    fact_ids = []
    for f in facts:
        c = str(f["content"] or "")
        if _contains_secret(c):
            continue
        fact_ids.append(f["id"])
        lines.append(f"[{f['id']}|{f['dept']}] {c[:_PROFILE_FTS_LEN]}")
    if not lines:
        return None, 0, False
    prompt = ("=== ФАКТЫ (id|dept: текст) ===\n" + "\n".join(lines)
              + "\n\nСобери профиль владельца по инструкции системы.")
    try:
        from proxy.providers import call_llm
        result = call_llm("memory", [
            {"role": "system", "content": _SYNTH_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        text = (result or {}).get("reply") or ""
        parsed = _extract_json(text)
        if not isinstance(parsed, dict):
            return None, 0, False
        profile = _normalize_profile(parsed)
        if profile is None:
            return None, 0, False
        # выходной контур: LLM мог протянуть секрет — режем
        flat = (profile.get("static", []) + profile.get("dynamic", [])
                + [x for v in profile.get("buckets", {}).values() for x in v])
        clean_flat, blocked = _filter_secrets(flat)
        if blocked:
            log.warning(f"owner_profile: {blocked} secret-like items dropped after LLM")
            return _deterministic_profile(facts)[0], blocked, True
        return profile, 0, True
    except Exception as e:
        log.warning(f"owner_profile: synthesis failed, deterministic fallback: {e}")
        return None, 0, False


def _extract_json(text):
    """Первый JSON-объект из ответа LLM (терпим к ```-заборам и мусору).
    Локальная копия парсера консолидации — без импорта routes_tail (цикл)."""
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception as e:
        log.debug(f"owner_profile: direct json parse failed: {e}")
    if isinstance(parsed, dict):
        return parsed
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
        except Exception as e:
            log.debug(f"owner_profile: regex json parse failed: {e}")
    return parsed if isinstance(parsed, dict) else None


def _normalize_profile(parsed):
    """Приведение ответа LLM к строгой форме; None — если форма неверна."""
    out = {"static": [], "dynamic": [], "buckets": {}}
    st = parsed.get("static")
    dy = parsed.get("dynamic")
    bk = parsed.get("buckets")
    if not isinstance(st, list) or not isinstance(dy, list):
        return None
    out["static"] = [str(x)[:400] for x in st if str(x or "").strip()][:10]
    out["dynamic"] = [str(x)[:400] for x in dy if str(x or "").strip()][:10]
    if isinstance(bk, dict):
        for k, v in list(bk.items())[:6]:
            if isinstance(v, list) and str(k).strip():
                out["buckets"][str(k)[:40]] = [str(x)[:400] for x in v if str(x or "").strip()][:10]
    if not (out["static"] or out["dynamic"] or out["buckets"]):
        return None
    return out


def rebuild_owner_profile(dept_filter=None, source="manual"):
    """Пересборка профиля из активных фактов (после ночной консолидации
    или вручную). Версионирование FO-009-стиля: старые строки закрываются
    (valid_to + superseded_by), новые становятся актуальными.
    Возврат: dict со счётчиками и версией."""
    _ensure_schema()
    facts = _load_active_facts()
    if dept_filter:
        facts = [f for f in facts if f["dept"] == dept_filter]
    if not facts:
        return {"status": "no_facts", "version": current_version()}

    profile, blocked, ok = _synth_profile(facts)
    if profile is None:
        profile, blocked2 = _deterministic_profile(facts)
        blocked += blocked2
        mode = "deterministic"
    else:
        mode = "llm"

    ts = _now()
    used_ids = sorted({f["id"] for f in facts})
    inserted = 0
    from proxy.core import _db, db_lock
    first_new = None
    with db_lock:
        c = _db()
        try:
            active = c.execute("SELECT id FROM owner_profile WHERE valid_to IS NULL").fetchall()
            rows = []
            for item in profile["static"]:
                rows.append(("static", "", item))
            for item in profile["dynamic"]:
                rows.append(("dynamic", "", item))
            for bname, items in profile["buckets"].items():
                for item in items:
                    rows.append(("bucket", bname, item))
            # порядок критичен: СНАЧАЛА закрыть старые версии, ПОТОМ вставлять
            # новые (иначе новые закроются тем же UPDATE'ом)
            old_ids = [r["id"] for r in active]
            if old_ids:
                c.execute("UPDATE owner_profile SET valid_to = ? WHERE valid_to IS NULL", (ts,))
            for section, bucket, content in rows:
                cur = c.execute(
                    "INSERT INTO owner_profile (section, bucket, content, taint, source_facts, confidence, valid_from) "
                    "VALUES (?, ?, ?, 'personal', ?, 0.85, ?)",
                    (section, bucket, content, json.dumps(used_ids), ts))
                if first_new is None:
                    first_new = cur.lastrowid
                inserted += 1
            if old_ids and first_new is not None:
                ph = ",".join("?" * len(old_ids))
                c.execute(f"UPDATE owner_profile SET superseded_by = ? WHERE id IN ({ph})",
                          [first_new] + old_ids)
            c.commit()
        except sqlite3.Error as e:
            c.rollback()
            _log_error(f"owner_profile rebuild failed: {e}", source="owner_profile", kind="db_write")
            return {"status": "error", "error": str(e)[:200]}
        finally:
            c.close()
    version = _bump_version(_version_stamp())
    _write_llm_trace({
        "event": "owner_profile_rebuild", "ts": ts, "mode": mode,
        "facts_used": len(used_ids), "items": inserted, "secrets_blocked": blocked,
        "source": source, "version": version,
    })
    log.info(f"owner_profile: rebuilt mode={mode} items={inserted} "
             f"facts={len(used_ids)} blocked={blocked} v={version}")
    return {"status": "ok", "mode": mode, "items": inserted,
            "facts_used": len(used_ids), "secrets_blocked": blocked, "version": version}


# ────────────────────────── чтение (один вызов) ──────────────────────────

_cache = {"version": None, "key": (), "payload": None}
_cache_lock = threading.Lock()


def get_owner_profile(dept=None, topic=None, section=None, max_chars=4000):
    """Единственная точка чтения профиля для департаментов: один вызов
    вместо N ad-hoc запросов к памяти. Кэш инвалидируется версией профиля
    (бампнется ночной консолидацией/rebuild) — stale-профиль не выдаётся.

    Метафильтры (supermemory-семантика):
      dept   — приоритетные buckets по интересам департамента;
      topic  — подстрока по bucket/контенту;
      section— 'static' | 'dynamic' | 'bucket'.
    Возврат: {"profile": text, "version": v, "sections": [...], "chars": n,
              "cached": bool}.
    """
    t0 = time.monotonic()
    _ensure_schema()
    version = current_version()
    key = (dept or "", topic or "", section or "", int(max_chars))
    cacheable = version != ""
    if cacheable:
        with _cache_lock:
            if _cache["version"] == version and _cache["key"] == key and _cache["payload"]:
                payload = _cache["payload"]
                _trace_get(dept, topic, section, payload["chars"], version, True,
                           (time.monotonic() - t0) * 1000)
                return {**payload, "cached": True}

    where, params = ["valid_to IS NULL"], []
    if section:
        if section not in SECTIONS:
            raise ValueError(f"unknown section: {section!r} (v1: {SECTIONS})")
        where.append("section = ?")
        params.append(section)
    if topic:
        where.append("(bucket LIKE ? OR content LIKE ?)")
        params.extend([f"%{topic}%", f"%{topic}%"])
    rows = _query(
        f"SELECT id, section, bucket, content, taint, confidence FROM owner_profile "
        f"WHERE {' AND '.join(where)} ORDER BY id ASC LIMIT 120",
        tuple(params), fetch=True) or []

    static_rows = [r for r in rows if r["section"] == "static"]
    dynamic_rows = [r for r in rows if r["section"] == "dynamic"]
    bucket_rows = [r for r in rows if r["section"] == "bucket"]

    # dept-метафильтр: приоритетные buckets вперёд (стабильно)
    prio = _DEPT_BUCKET_MAP.get(dept or "", [])
    bucket_rows.sort(key=lambda r: (prio.index(r["bucket"]) if r["bucket"] in prio
                                    else len(prio), r["id"]))

    parts = []
    included = []
    if static_rows:
        body = "\n".join(f"- {r['content']}" for r in static_rows)
        parts.append("=== Профиль владельца: постоянные факты ===\n" + body)
        included.append("static")
    if bucket_rows:
        by_bucket = {}
        for r in bucket_rows:
            by_bucket.setdefault(r["bucket"] or "тема", []).append(r["content"])
        for bname in list(by_bucket):
            body = "\n".join(f"- {x}" for x in by_bucket[bname])
            parts.append(f"=== {bname} ===\n" + body)
            included.append(f"bucket:{bname}")
    if dynamic_rows:
        body = "\n".join(f"- {r['content']}" for r in dynamic_rows)
        parts.append("=== Текущий контекст владельца ===\n" + body)
        included.append("dynamic")

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[…профиль усечён]"
    payload = {"profile": text, "version": version,
               "sections": included, "chars": len(text)}
    if cacheable and text:
        with _cache_lock:
            _cache.update({"version": version, "key": key, "payload": payload})
    _trace_get(dept, topic, section, len(text), version, False,
               (time.monotonic() - t0) * 1000)
    return {**payload, "cached": False}


def _trace_get(dept, topic, section, chars, version, cached, elapsed_ms):
    try:
        _write_llm_trace({
            "event": "owner_profile", "ts": _now(),
            "dept": dept or "", "topic": topic or "", "section": section or "",
            "chars": chars, "version": version, "cached": cached,
            "latency_ms": round(elapsed_ms),
        })
    except Exception as e:
        log.debug(f"owner_profile trace failed (non-fatal): {e}")


def invalidate_owner_profile():
    """Принудительная инвалидация кэша (например, после правки фактов)."""
    _cache.update({"version": None, "key": (), "payload": None})
    return _bump_version()
