"""FO-008: ядро прокси — Flask app, конфиг, секреты, SQLite, аудит, трейсы.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 1; наряд #68, стоп-гейт SG-F2).
llm_proxy.py остаётся точкой сборки/entrypoint — деплой-контракт не тронут.
Этот модуль не знает о Flask-роутах и провайдерах (только они импортируют его).
"""
import os
import sys
import json
import re
import sqlite3
import threading
import time
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

from flask import Flask, request, jsonify, Response
import requests as http_requests
import secrets_crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("llm_proxy")

sys.path.insert(0, str(BASE_DIR / 'lib'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from fosved_memory import FosvedMemory
_MEMORY_DB = os.path.join(os.environ.get("DATABASE_PATH", os.path.join(str(BASE_DIR), 'data')), 'memory.db')
os.makedirs(os.path.dirname(_MEMORY_DB), exist_ok=True)
memory = FosvedMemory(_MEMORY_DB)
log_mem = logging.getLogger("fosved.memory")
log_mem.info(f"FosvedMemory loaded: {len(memory.TYPES)} types, db={_MEMORY_DB}")

from flask import Flask, request, jsonify, Response
import requests as http_requests
import secrets_crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("llm_proxy")

# ── LLM Trace (FO-004) ───────────────────────────────────────
_TRACE_DIR = os.path.join(os.environ.get("DATABASE_PATH", "./data"), "traces")
_TRACE_MAX_BYTES = int(os.environ.get("LLM_TRACE_MAX_BYTES", 10 * 1024 * 1024))  # 10 MB default
_TRACE_RETENTION = int(os.environ.get("LLM_TRACE_RETENTION", 7))  # days
_trace_lock = threading.Lock()


def _write_llm_trace(record: dict):
    """Append one JSONL trace record. File rotation by size. Write failure never raises."""
    try:
        os.makedirs(_TRACE_DIR, exist_ok=True)
        ts = record.get("ts", datetime.now(timezone.utc).isoformat())
        day = ts[:10]  # YYYY-MM-DD
        trace_file = os.path.join(_TRACE_DIR, f"llm_{day}.jsonl")
        with _trace_lock:
            # Rotate if file exceeds max size
            if os.path.exists(trace_file) and os.path.getsize(trace_file) > _TRACE_MAX_BYTES:
                seq = 1
                while os.path.exists(os.path.join(_TRACE_DIR, f"llm_{day}_{seq}.jsonl")):
                    seq += 1
                os.rename(trace_file, os.path.join(_TRACE_DIR, f"llm_{day}_{seq}.jsonl"))
            with open(trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Prune old trace files beyond retention
        _prune_old_traces()
    except Exception as e:
        log.debug(f"Trace write failed (non-fatal): {e}")


def _prune_old_traces():
    """Remove trace files older than _TRACE_RETENTION days."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_TRACE_RETENTION)).strftime("%Y-%m-%d")
        for name in os.listdir(_TRACE_DIR):
            if name.startswith("llm_") and name.endswith(".jsonl"):
                # Extract date part: llm_YYYY-MM-DD.jsonl or llm_YYYY-MM-DD_N.jsonl
                date_part = name[4:14]
                if date_part < cutoff:
                    os.remove(os.path.join(_TRACE_DIR, name))
    except Exception as e:
        log.debug(f"Trace prune failed (non-fatal): {e}")

# ──────────────────────────── APP & CONFIG ────────────────────────────
app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

# ── Auth middleware (before_request) ──────────────────────────
@app.before_request
def auth_middleware():
    path = request.path
    # Protect API, admin, memory, miniapp-action endpoints
    if any(path.startswith(p) for p in PROTECTED_PREFIXES):
        # Internal requests from mlog (localhost) are allowed to /memory/
        # without Bearer — mlog http_post() has no custom-header support.
        # External traffic is blocked by reverse_proxy (SEC-1) and firewall.
        if path.startswith("/memory/") and request.remote_addr in ("127.0.0.1", "::1"):
            return None
        if not _check_bearer():
            return jsonify({"error": "unauthorized"}), 401
    return None

PORT = int(os.environ.get("PORT_PROXY", 4000))
DB_PATH = os.environ.get("DATABASE_PATH", "./data")
Path(DB_PATH).mkdir(parents=True, exist_ok=True)
DB_FILE = os.path.join(DB_PATH, "fosved.db")

BASE_DIR = Path(__file__).parent
LIB_DIR = BASE_DIR / "library"
CFG_DIR = BASE_DIR / "config"

db_lock = threading.Lock()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ARCHIVE_CHANNEL_ID = os.environ.get("TELEGRAM_ARCHIVE_CHANNEL_ID", "")
WHISPER_API_KEY = os.environ.get("WHISPER_API_KEY", "")
WHISPER_PROVIDER = os.environ.get("WHISPER_PROVIDER", "groq")
API_SECRET = os.environ.get("API_SECRET", "")  # Bearer token for protected endpoints
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")  # X-Telegram-Bot-Api-Secret-Token

# ── Auth helpers ──────────────────────────────────────────────
PROTECTED_PREFIXES = ('/api/', '/admin-ua/', '/memory/', '/webhook/miniapp-action', '/traces')

def _check_bearer():
    """Return True if request bears valid API_SECRET, or if API_SECRET is empty (open mode)."""
    if not API_SECRET:
        return True
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {API_SECRET}'

def _verify_webhook_secret():
    """Verify Telegram webhook secret token header."""
    if not WEBHOOK_SECRET:
        return True  # no secret configured — open mode
    return request.headers.get('X-Telegram-Bot-Api-Secret-Token', '') == WEBHOOK_SECRET


def _verify_init_data(init_data, max_age_seconds=86400):
    """Validate Telegram Mini App initData signature and owner identity.

    Returns True when the signature matches the bot token, the payload is
    fresh, and the user is the owner. Disabled (returns True) when the bot
    token is not configured, so a misconfigured environment stays usable.
    """
    if not TELEGRAM_BOT_TOKEN:
        return True
    if not init_data:
        return False
    try:
        import hmac as _hmac
        from urllib.parse import parse_qsl

        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            return False

        check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = _hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = _hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, received_hash):
            return False

        auth_date = int(pairs.get("auth_date", "0"))
        if max_age_seconds and (time.time() - auth_date) > max_age_seconds:
            return False

        owner = os.environ.get("OWNER_TELEGRAM_ID", "")
        if owner:
            user = json.loads(pairs.get("user", "{}"))
            if str(user.get("id", "")) != str(owner):
                return False
        return True
    except Exception as e:
        log.warning(f"initData verification failed: {e}")
        return False


# SEC-4: Telegram delivers initData to the WebApp JS object, not to the URL.
# When the signature is absent we serve this bootstrap page: its script reads
# initData from Telegram and re-requests the same URL with the header set.
_TG_BOOTSTRAP_PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Загрузка</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
body{margin:0;padding:40px;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
background:#17212b;color:#e9edf2;text-align:center}
.msg{margin-top:24px;font-size:15px;color:#8fa3b8}
</style></head><body>
<div class="msg" id="s">Загрузка…</div>
<script>
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  var initData = tg && tg.initData ? tg.initData : "";
  if (!initData) {
    document.getElementById("s").textContent =
      "Эта страница открывается только из Telegram.";
    return;
  }
  if (tg.expand) { tg.expand(); }
  fetch(window.location.href, {
    headers: { "X-Telegram-Init-Data": initData }
  }).then(function (r) {
    if (!r.ok) { throw new Error("HTTP " + r.status); }
    return r.text();
  }).then(function (html) {
    document.open();
    document.write(html);
    document.close();
  }).catch(function (e) {
    document.getElementById("s").textContent = "Не удалось загрузить: " + e.message;
  });
})();
</script>
</body></html>"""


def require_telegram(view):
    """Allow the request only from inside Telegram (valid initData)."""
    from functools import wraps

    @wraps(view)
    def wrapper(*args, **kwargs):
        init_data = (request.args.get("tgWebAppData")
                     or request.headers.get("X-Telegram-Init-Data", ""))
        if not _verify_init_data(init_data):
            # No signature at all: browser navigation from a web_app button.
            # Serve the bootstrap page so its script can supply initData.
            if not init_data:
                return Response(_TG_BOOTSTRAP_PAGE, status=200, mimetype="text/html")
            # Signature present but invalid, stale, or from another user: refuse.
            log.warning("SEC-4: initData present but rejected")
            return Response(
                "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
                "<title>Доступ закрыт</title></head><body style='font-family:sans-serif;"
                "padding:40px;background:#17212b;color:#e9edf2'>"
                "<h2>Доступ закрыт</h2><p>Эта страница открывается только из Telegram.</p>"
                "</body></html>",
                status=403, mimetype="text/html")
        return view(*args, **kwargs)

    return wrapper

# ──────────────────────────── SEC-5/SEC-6: секреты и интеграции ────────────────────────────

def get_secret(name: str) -> str:
    """Единая точка чтения секрета: сначала БД (расшифровать), иначе env var."""
    try:
        rows = _query("SELECT encrypted_value FROM secrets_store WHERE name = ?", (name,), fetch=True)
        if rows:
            decrypted = secrets_crypto.decrypt_value(rows[0]["encrypted_value"])
            if decrypted:
                return decrypted
    except Exception as e:
        log.error(f"get_secret({name}) DB lookup failed: {e}")
    return os.environ.get(name, "")


def set_secret(name: str, plain_value: str) -> bool:
    """Сохранить секрет в БД зашифрованным. False, если SECRETS_MASTER_KEY не настроен."""
    if not secrets_crypto.is_configured():
        return False
    encrypted = secrets_crypto.encrypt_value(plain_value)
    _query(
        "INSERT INTO secrets_store (name, encrypted_value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(name) DO UPDATE SET encrypted_value = excluded.encrypted_value, updated_at = excluded.updated_at",
        (name, encrypted),
    )
    return True


def delete_secret(name: str) -> None:
    """Удалить переопределение из БД — вернуться к значению из env var."""
    _query("DELETE FROM secrets_store WHERE name = ?", (name,))


def _has_db_override(name: str) -> bool:
    rows = _query("SELECT 1 FROM secrets_store WHERE name = ?", (name,), fetch=True)
    return bool(rows)


INTEGRATIONS_REGISTRY = [
    {"env_key": "ZAI_API_KEY", "label": "Z.ai (GLM)", "kind": "model"},
    {"env_key": "DEEPSEEK_API_KEY", "label": "DeepSeek", "kind": "model"},
    {"env_key": "GROQ_API_KEY", "label": "Groq", "kind": "model"},
    {"env_key": "GROK_API_KEY", "label": "Grok (xAI)", "kind": "model"},
    {"env_key": "ANTHROPIC_API_KEY", "label": "Anthropic (Claude)", "kind": "model"},
    {"env_key": "OPENAI_API_KEY", "label": "OpenAI", "kind": "model"},
    {"env_key": "APODEX_API_KEY", "label": "Apodex", "kind": "model"},
    {"env_key": "NVIDIA_API_KEY", "label": "NVIDIA", "kind": "model"},
    {"env_key": "CEREBRAS_API_KEY", "label": "Cerebras", "kind": "model"},
    {"env_key": "SAKANA_API_KEY", "label": "Sakana Fugu", "kind": "model"},
    {"env_key": "KIMI_API_KEY", "label": "Kimi (Moonshot)", "kind": "model"},
    {"env_key": "TAVILY_API_KEY", "label": "Tavily (веб-поиск)", "kind": "service"},
    {"env_key": "GITHUB_TOKEN_METALOGOS", "label": "GitHub (трекинг репозиториев)", "kind": "service"},
]

# ──────────────────────────── DEPT COLORS & NAMES ────────────────────────────
DEPT_COLORS = {
    'yana': {'start': '#293133', 'end': '#1a2024', 'accent': '#3d4a4d'},
    'osp': {'start': '#b91c1c', 'end': '#7f1d1d', 'accent': '#dc2626'},
    'lz': {'start': '#0e7490', 'end': '#164e63', 'accent': '#0891b2'},
    'expert': {'start': '#3730a3', 'end': '#1e1b4b', 'accent': '#4f46e5'},
    'marketing': {'start': '#c2410c', 'end': '#7c2d12', 'accent': '#ea580c'},
    'finance': {'start': '#15803d', 'end': '#14532d', 'accent': '#16a34a'},
    'legal': {'start': '#475569', 'end': '#1e293b', 'accent': '#64748b'},
    'dev': {'start': '#1d4ed8', 'end': '#1e3a8a', 'accent': '#2563eb'},
    'design': {'start': '#be185d', 'end': '#831843', 'accent': '#ec4899'},
    'qa': {'start': '#4d7c0f', 'end': '#365314', 'accent': '#65a30d'},
    'visual': {'start': '#7e22ce', 'end': '#581c87', 'accent': '#a855f7'},
    'engineering': {'start': '#44403c', 'end': '#292524', 'accent': '#78716c'},
    'kavalnya': {'start': '#b45309', 'end': '#78350f', 'accent': '#d97706'},
    'admin': {'start': '#1e40af', 'end': '#1e3a5f', 'accent': '#3b82f6'},
}

DEPT_NAMES = {
    'yana': 'Yana — Шеф де кабинета', 'osp': 'ОСП · Стратегическое планирование',
    'lz': 'ЛЗ · Лаборатория знаний', 'expert': 'Эксперт · Подготовка к встрече',
    'marketing': 'Маркетинг', 'finance': 'Финансы', 'legal': 'Юрист',
    'dev': 'Dev · Разработка', 'design': 'Дизайн · UI/UX', 'qa': 'QA · Тестирование',
    'visual': 'Визуал · Инфографика', 'engineering': 'Инженерия · Расчёты',
    'kavalnya': 'Кавальня · Методология', 'admin': 'Админ · Система',
}

DEPT_HASHTAGS = {
    'osp': '#OSP #analytics #strategy',
    'lz': '#LZ #technology #politics #economics #geopolitics #research',
    'expert': '#Expert #briefing #meeting #negotiations',
    'marketing': '#Marketing #audience',
    'finance': '#Finance #cashflow',
    'legal': '#Legal #contracts',
    'dev': '#Dev #code #architecture',
    'design': '#Design #UX',
    'qa': '#QA #testing',
    'visual': '#Visual #infographic',
    'engineering': '#Engineering #calculations',
    'kavalnya': '#Kavalnya #methodology',
    'yana': '#Yana #cabinet',
    'admin': '#Admin #system',
}

# ──────────────────────────── SQLITE SETUP ────────────────────────────
def _db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with db_lock:
        c = _db()
        c.execute("""
            CREATE TABLE IF NOT EXISTS secrets_store (
                name TEXT PRIMARY KEY,
                encrypted_value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.executescript("""
        CREATE TABLE IF NOT EXISTS miniapp_responses (id TEXT PRIMARY KEY, dept TEXT, title TEXT, query TEXT, raw_text TEXT DEFAULT '', html TEXT, confidence TEXT, created_at TEXT DEFAULT (datetime('now')), archived INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS miniapp_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, note_text TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS dept_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, metric_name TEXT, metric_value TEXT, period TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS token_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, provider TEXT, model TEXT, input_tokens TEXT, output_tokens TEXT, cost_usd TEXT, request_type TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT (datetime('now')), action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT);
        -- FO-007: trace_log — отладочные чекпоинты (раньше сваливались в audit_log)
        CREATE TABLE IF NOT EXISTS trace_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT (datetime('now')), action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT);
        -- FO-007: error_log — структурированные ошибки (внешние вызовы, потери данных)
        CREATE TABLE IF NOT EXISTS error_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT DEFAULT (datetime('now')), source TEXT, dept TEXT, kind TEXT, detail TEXT);
        -- FO-006: консолидированные факты (ночная консолидация dialog_history, mem0-паттерн)
        CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, chat_id TEXT DEFAULT '0', content TEXT NOT NULL, status TEXT DEFAULT 'active', source_dialog_ids TEXT DEFAULT '[]', confidence REAL DEFAULT 0.8, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_facts_dept ON facts(dept, status);
        CREATE TABLE IF NOT EXISTS dialog_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, dept TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS adapt_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, original_query TEXT, original_response TEXT, correction TEXT, corr_type TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS error_patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, error_type TEXT, query_text TEXT, correction TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS channel_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, dept TEXT, title TEXT, channel_message_id TEXT, archived_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT, file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS knowledge_edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT, edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS admin_findings (id INTEGER PRIMARY KEY AUTOINCREMENT, severity TEXT, category TEXT, file TEXT, issue TEXT, fix TEXT, status TEXT DEFAULT 'open', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS admin_proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, status TEXT DEFAULT 'pending', narad_id TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS admin_night_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_data TEXT, review_data TEXT, health_score INTEGER, findings_count INTEGER, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS lz_monitors (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, frequency TEXT DEFAULT 'daily', created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS news_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, url TEXT, category TEXT DEFAULT 'general', language TEXT DEFAULT 'ru', published TIMESTAMP, collected TIMESTAMP DEFAULT CURRENT_TIMESTAMP, relevance_score REAL DEFAULT 0, hash TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS continuous_learning (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT NOT NULL, query TEXT, approach TEXT, score REAL DEFAULT 0.5, created_at TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_cl_dept ON continuous_learning(dept);
        CREATE INDEX IF NOT EXISTS idx_news_category ON news_cache (category, collected DESC);
        CREATE INDEX IF NOT EXISTS idx_news_hash ON news_cache (hash);
        """)
        for col_sql, col_name in [
            ("ALTER TABLE token_usage ADD COLUMN compression_saved INTEGER DEFAULT 0", "compression_saved"),
            ("ALTER TABLE token_usage ADD COLUMN combo TEXT DEFAULT ''", "combo"),
            ("ALTER TABLE miniapp_responses ADD COLUMN archived INTEGER DEFAULT 0", "archived"),
        ]:
            try:
                c.execute(col_sql)
            except Exception as e:
                # ожидаемый сбой при повторном добавлении существующей колонки
                log.debug(f"[migration] column add skipped (expected if exists): {e}")
        c.commit(); c.close()

init_db()

def _query(sql, params=(), fetch=False):
    with db_lock:
        try:
            c = _db()
            cur = c.execute(sql, params)
            if fetch:
                rows = cur.fetchall(); c.close(); return rows
            c.commit(); c.close()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return [] if fetch else None
            raise

def _get_setting(key, default=""):
    """Read a value from system_settings (shared kv with Metalogos)."""
    try:
        rows = _query("SELECT value FROM system_settings WHERE key = ?", (key,), fetch=True)
        if rows:
            return rows[0]["value"]
    except Exception as e:
        log.error(f"_get_setting({key}) failed: {e}")
    return default

def _log_audit(action, details_dict, dept="system"):
    _query("INSERT INTO audit_log (action,actor,dept,details,status) VALUES (?,'proxy',?,?,'ok')",
           (action, dept, json.dumps(details_dict, ensure_ascii=False)))

# ── FO-007: error_log и гигиена журналов (issue #67) ────────────────────
# Политика: молчаливый except запрещён (CI-проверка: scripts/check_silent_excepts.py).
# Ошибки внешних вызовов и потери данных → error_log (через _log_error);
# audit_log остаётся журналом действий; отладочные чекпоинты — в trace_log.
_LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "90"))              # audit_log, error_log
_TRACE_LOG_RETENTION_DAYS = int(os.environ.get("TRACE_LOG_RETENTION_DAYS", "14"))  # trace_log (debug)
_ERROR_DEDUP_SECONDS = 60
_error_dedup = {}
_error_dedup_lock = threading.Lock()

def _log_error(detail, source="llm_proxy", dept="system", kind="error"):
    """Единая точка фиксации ошибки: log.warning с тегом + строка в error_log.

    Дедуп 60с по (source, dept, kind, detail) — циклические сбои (typing-индикатор,
    внешние API) не заливают таблицу. Сбой самой записи в error_log не ломает
    основной поток — внутри только log.debug.
    """
    detail = str(detail)[:500]
    log.warning(f"[error:{source}/{dept}/{kind}] {detail}")
    key = (source, dept, kind, detail[:200])
    now = time.monotonic()
    with _error_dedup_lock:
        last = _error_dedup.get(key)
        if last is not None and (now - last) < _ERROR_DEDUP_SECONDS:
            return
        if len(_error_dedup) > 2000:
            _error_dedup.clear()
        _error_dedup[key] = now
    try:
        _query("INSERT INTO error_log (source, dept, kind, detail) VALUES (?,?,?,?)",
               (source, dept, kind, detail))
    except Exception as e:
        log.debug(f"error_log insert failed (non-fatal): {e}")

def _rotate_service_logs():
    """Ротация журналов: строки старше retention архивируются в JSONL и удаляются.

    audit_log/error_log — LOG_RETENTION_DAYS (90), trace_log (отладка) — 14 дней.
    Вызывается на старте и из /cron/backup (каждые 6ч).
    """
    archive_dir = Path(DB_PATH) / "archive"
    jobs = [
        ("audit_log", "timestamp", _LOG_RETENTION_DAYS),
        ("error_log", "ts", _LOG_RETENTION_DAYS),
        ("trace_log", "timestamp", _TRACE_LOG_RETENTION_DAYS),
    ]
    for table, ts_col, days in jobs:
        try:
            rows = _query(f"SELECT * FROM {table} WHERE {ts_col} < datetime('now', ?)",
                          (f"-{days} days",), fetch=True)
            if not rows:
                continue
            archive_dir.mkdir(parents=True, exist_ok=True)
            with open(archive_dir / f"{table}.jsonl", "a", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
            _query(f"DELETE FROM {table} WHERE {ts_col} < datetime('now', ?)", (f"-{days} days",))
            log.info(f"[rotation] {table}: archived+deleted {len(rows)} rows older than {days}d")
        except Exception as e:
            log.warning(f"[rotation] {table} failed (non-fatal): {e}")

_rotate_service_logs()
