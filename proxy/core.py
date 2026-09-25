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
sys.path.insert(0, str(BASE_DIR))

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
        # and /dialog/ without Bearer — mlog http_post() has no custom-header
        # support. External traffic is blocked by reverse_proxy (SEC-1) and
        # firewall.
        if (path.startswith("/memory/") or path.startswith("/dialog/")
                or path.startswith("/profile/")) and \
                request.remote_addr in ("127.0.0.1", "::1"):
            return None
        if not _check_bearer():
            return jsonify({"error": "unauthorized"}), 401
    return None

PORT = int(os.environ.get("PORT_PROXY", 4000))
DB_PATH = os.environ.get("DATABASE_PATH", "./data")
Path(DB_PATH).mkdir(parents=True, exist_ok=True)
DB_FILE = os.path.join(DB_PATH, "fosved.db")

LIB_DIR = BASE_DIR / "library"
CFG_DIR = BASE_DIR / "config"

# FO-017: RLock вместо Lock — init_db() вызывает ensure_dialog_schema()
# под уже взятым лоном (реентерабельность того же потока).
db_lock = threading.RLock()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ARCHIVE_CHANNEL_ID = os.environ.get("TELEGRAM_ARCHIVE_CHANNEL_ID", "")
WHISPER_API_KEY = os.environ.get("WHISPER_API_KEY", "")
WHISPER_PROVIDER = os.environ.get("WHISPER_PROVIDER", "groq")
API_SECRET = os.environ.get("API_SECRET", "")  # Bearer token for protected endpoints
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")  # X-Telegram-Bot-Api-Secret-Token

# ── Auth helpers ──────────────────────────────────────────────
PROTECTED_PREFIXES = ('/api/', '/admin-ua/', '/memory/', '/dialog/', '/profile/', '/webhook/miniapp-action', '/traces', '/repos/', '/preview', '/preview-live/')  # FO-035 D.5, FO-037 C.2, FO-039 B.1

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
    {"env_key": "NVIDIA_API_KEY", "label": "NVIDIA", "kind": "model"},
    {"env_key": "CEREBRAS_API_KEY", "label": "Cerebras", "kind": "model"},
    {"env_key": "SAKANA_API_KEY", "label": "Sakana Fugu", "kind": "model"},
    {"env_key": "KIMI_API_KEY", "label": "Kimi (Moonshot)", "kind": "model"},
    {"env_key": "TAVILY_API_KEY", "label": "Tavily (веб-поиск)", "kind": "service"},
    {"env_key": "YANDEX_MARKET_API_KEY", "label": "Яндекс.Маркет (контентный API)", "kind": "service"},
    {"env_key": "GITHUB_TOKEN_METALOGOS", "label": "GitHub (трекинг репозиториев)", "kind": "service"},
]

# ──────────────────────────── DEPT COLORS & NAMES ────────────────────────────
DEPT_COLORS = {
    # ИСПРАВЛЕНО ПОСЛЕ ОШИБКИ: вчера этот словарь свели к одному акценту
    # на все 14 отделов, ошибочно приняв разноцветность за пережиток
    # дорефакторинговой эпохи (по аналогии с тем, что сама SPA не красит
    # навигацию по отделам). NARAD_RICH_POSTPROCESSOR — исходный наряд,
    # создавший всю систему обогащения — прямо предполагает свой цвет
    # каждому отделу как осознанную часть замысла, не случайность.
    # Разные UI-поверхности могут жить по разным правилам: нейтральная
    # навигация в SPA — и цветная печать отдела на заголовке отчёта.
    #
    # Новая палитра — не возврат к прежним ядовитым индиго/розовому/
    # фиолетовому (те были до «Диспетчерской» и с ней не сочетались),
    # а 14 приглушённых, согласованных по тону цветов в духе самой темы:
    # каждый отдел — свой оттиск печати, как в старой канцелярии.
    'yana': {'start': '#A8321E', 'end': '#7A2415', 'accent': '#A8321E'},
    'osp': {'start': '#1F5C8B', 'end': '#163F5F', 'accent': '#1F5C8B'},
    'lz': {'start': '#3D6B2C', 'end': '#2B4D20', 'accent': '#3D6B2C'},
    'expert': {'start': '#6B3FA0', 'end': '#4B2C73', 'accent': '#6B3FA0'},
    'marketing': {'start': '#9C6B0B', 'end': '#6F4C08', 'accent': '#9C6B0B'},
    'finance': {'start': '#1C7C74', 'end': '#145651', 'accent': '#1C7C74'},
    'legal': {'start': '#4A4A68', 'end': '#33334A', 'accent': '#4A4A68'},
    'dev': {'start': '#B5541F', 'end': '#7F3B16', 'accent': '#B5541F'},
    'design': {'start': '#A83E7A', 'end': '#762B57', 'accent': '#A83E7A'},
    'qa': {'start': '#5C7A29', 'end': '#41571D', 'accent': '#5C7A29'},
    'visual': {'start': '#B0472E', 'end': '#7C3220', 'accent': '#B0472E'},
    'engineering': {'start': '#565045', 'end': '#3D3931', 'accent': '#565045'},
    'kavalnya': {'start': '#8A5A1E', 'end': '#634015', 'accent': '#8A5A1E'},
    'admin': {'start': '#2E4C6B', 'end': '#20364C', 'accent': '#2E4C6B'},
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
        -- FO-009: темпоральный KG — valid_to NULL = актуально; superseded_by → новая версия
        CREATE TABLE IF NOT EXISTS knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT, file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')), valid_from TEXT, valid_to TEXT, superseded_by INTEGER);
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
            # FO-009: темпоральные колонки knowledge_graph
            ("ALTER TABLE knowledge_graph ADD COLUMN valid_from TEXT", "valid_from"),
            ("ALTER TABLE knowledge_graph ADD COLUMN valid_to TEXT", "valid_to"),
            ("ALTER TABLE knowledge_graph ADD COLUMN superseded_by INTEGER", "superseded_by"),
            # FO-017: связь узла графа с Part-репликой (прослеживаемость факта)
            ("ALTER TABLE knowledge_graph ADD COLUMN source_part_id TEXT", "source_part_id"),
            # FO-020: inference-review — выведенное понижено в весе до ревью
            ("ALTER TABLE facts ADD COLUMN inference INTEGER DEFAULT 0", "inference"),
            ("ALTER TABLE facts ADD COLUMN review_status TEXT DEFAULT 'approved'", "review_status"),
            ("ALTER TABLE facts ADD COLUMN parent_count INTEGER DEFAULT 1", "parent_count"),
            ("ALTER TABLE facts ADD COLUMN decline_reason TEXT", "decline_reason"),
            ("ALTER TABLE knowledge_graph ADD COLUMN inference INTEGER DEFAULT 0", "inference"),
            ("ALTER TABLE knowledge_graph ADD COLUMN review_status TEXT DEFAULT 'approved'", "review_status"),
            ("ALTER TABLE knowledge_graph ADD COLUMN parent_count INTEGER DEFAULT 1", "parent_count"),
            ("ALTER TABLE token_usage ADD COLUMN compression_saved INTEGER DEFAULT 0", "compression_saved"),
            ("ALTER TABLE token_usage ADD COLUMN combo TEXT DEFAULT ''", "combo"),
            ("ALTER TABLE miniapp_responses ADD COLUMN archived INTEGER DEFAULT 0", "archived"),
        ]:
            try:
                c.execute(col_sql)
            except Exception as e:
                # ожидаемый сбой при повторном добавлении существующей колонки
                log.debug(f"[migration] column add skipped (expected if exists): {e}")
        # FO-009: миграция существующих узлов — valid_from = updated_at
        # (created_at в legacy-схеме нет; updated_at — момент фиксации узла)
        c.execute("UPDATE knowledge_graph SET valid_from = updated_at WHERE valid_from IS NULL")
        c.commit(); c.close()
        # FO-017: схема Dialog v2 (dialog_message/dialog_part/session_message).
        # Ленивый импорт внутри функции — чтобы не зациклить core ↔ dialog.
        try:
            from proxy.dialog import ensure_dialog_schema
            ensure_dialog_schema()
        except Exception as e:
            log.warning(f"[init] dialog v2 schema skipped (non-fatal): {e}")
        # FO-019: таблица профиля владельца (static/dynamic/buckets)
        try:
            from proxy.owner_profile import ensure_profile_schema
            ensure_profile_schema()
        except Exception as e:
            log.warning(f"[init] owner profile schema skipped (non-fatal): {e}")


def _query(sql, params=(), fetch=False):
    with db_lock:
        c = None
        try:
            c = _db()
            cur = c.execute(sql, params)
            if fetch:
                rows = cur.fetchall(); c.close(); return rows
            c.commit(); c.close()
        except sqlite3.Error as e:
            # LEAK-FIX (кейс 2026-09-19): при ошибке execute/commit соединение
            # раньше не закрывалось. Питоновский traceback (pytest хранит его
            # для отчёта) держит фрейм живым → открытое соединение с
            # незакрытой транзакцией держало WRITE-лок навсегда, и одна
            # транзитная блокировка каскадом валила всю сессию тестов.
            # Теперь соединение закрывается на ЛЮБОЙ ошибке до raise.
            if c is not None:
                try:
                    c.close()
                except Exception:  # noqa: BLE001 — соединение уже мертво
                    pass
            if isinstance(e, sqlite3.OperationalError) and "no such table" in str(e):
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


# ═══ FO-008 шаг 4a: dept-детекция/промпты и авто-обогащение (из фасада) ═══
try:
    from auto_enricher import auto_enrich as _auto_enrich_fn
    _has_enricher = True
except Exception as _e:
    log.warning(f"auto_enricher import failed, rich post-processor disabled: {_e}")
    _auto_enrich_fn = None
    _has_enricher = False


def auto_enrich(text, dept='yana', accent_color='#A8321E'):
    """Safe wrapper — returns raw text if enricher unavailable."""
    if _auto_enrich_fn is None:
        return text or ''
    try:
        return _auto_enrich_fn(text, dept=dept, accent_color=accent_color)
    except Exception as e:
        log.warning(f"auto_enrich error: {e}")
        return text or ''

# ──────────────────────────── DEPT DETECTION ────────────────────────────
COMMAND_DEPT = {
    '/yana': 'yana', '/osp': 'osp', '/lz': 'lz', '/expert': 'expert',
    '/marketing': 'marketing', '/finance': 'finance', '/legal': 'legal',
    '/dev': 'dev', '/design': 'design', '/design-image': 'design-image', '/qa': 'qa', '/visual': 'visual', '/visual-image': 'visual-image',
    '/engineering': 'engineering', '/forge': 'kavalnya',
    '/analyze': 'osp', '/scan': 'lz', '/deep': 'osp',
    '/quickanalyze': 'osp', '/wargame': 'osp',
    '/market-research': 'marketing', '/segment': 'marketing',
    '/competitors': 'marketing', '/campaign': 'marketing',
    '/calc': 'engineering', '/simulate': 'engineering',
    '/admin': 'admin',
    '/project': 'project',
}

RUSSIAN_KEYWORDS = {
    'osp': ['проанализируй', 'прогноз', 'стратегия', 'анализ', 'сценари', 'вероятност', 'деconstruct', 'деконстру', 'тополог', 'силовой потенциал', 'препарирован'],
    'lz': ['технолог', 'монитор', 'тренд', 'прорыв', 'наука', 'исследован', 'обзор', 'что такое', 'как работает', 'лаборатори',
           'политик', 'экономик', 'геополитик', 'санкци', 'макро', 'режим', 'нарратив', 'событие', 'кризис',
           'конфликт', 'выбор', 'инфляци', 'рецесси', 'ставк', 'ценн', 'войн', 'мирн', 'дипломат',
           'cantillon', 'нарратив vs', 'narrative', 'регим', 'цикл', 'kondratieff', 'хайп', 'инфлекци',
           'осинт', 'osint', 'разведк', 'мониторинг', 'свеж', 'новост', 'событи', 'в мире', 'в рф'],
    'expert': ['встреч', 'брифинг', 'подготов к', 'эксперт', 'подготовь', 'вопросы для', 'комбат-вопрос', 'подготов',
              'переговор', 'byd', 'geely', 'chery', 'zeekr', 'lixiang', 'nio', 'xpeng', 'vinfast',
              'авто', 'автомобиль', 'автопром', 'конкурент', 'соперник',
              'toyota', 'bmw', 'mercedes', 'vw ', 'volkswagen', 'honda', 'hyundai', 'kia',
              'платформ', 'ev ', 'электромобиль', 'завод', 'производств', 'сборк', 'локализац',
              'cto', 'ceo', 'cfo', 'директор', 'руководств', 'встреча с', 'митинг', 'переговоры'],
    'marketing': ['реклам', 'аудитори', 'конверси', 'маркетинг', 'позицио', 'воронк', 'smm', 'бренд', 'контент', 'сегмент'],
    'finance': ['бюджет', 'cashflow', 'налог', 'финанс', 'расход', 'доход', 'инвестиц', 'кредит', 'курс валют', 'кассовый разрыв'],
    'legal': ['договор', 'иск', 'gdpr', 'юридическ', 'nda', 'право', 'суд', 'комплаенс', 'контракт', 'закон'],
    'dev': ['код', 'архитектур', 'api', 'программ', 'деплой', 'сервер', 'git', 'баг', 'рефактор', 'бэкенд', 'фронтенд'],
    'design': ['дизайн', 'wireframe', 'макет', 'ui', 'ux', 'интерфейс', 'прототип', 'фиго', 'компонент'],
    'qa': ['тест', 'баг', 'качеств', 'проверк', 'регресси', 'автотест', 'e2e', 'покрыти'],
    'visual': ['инфографик', 'визуализац', 'график', 'презентац', 'диаграмм', 'иллюстрац', 'дашборд'],
    'engineering': ['расчёт', 'нагрузк', 'конструкц', 'инженер', 'снип', 'гидравлик', 'прочност', 'сварк', 'фундамент'],
    'kavalnya': ['новый отдел', 'полигон', 'методолог', 'создать отдел', 'наряд', 'дефектив', 'assess', 'debrief'],
    'admin': ['оптимизир', 'почини', 'рефакторинг', 'deploy', 'админ', 'инфраструктур', 'здравствуй', 'перезагруз', 'конфиг'],
}

# ── Keyword weights for scoring: higher = more specific/less generic ──
# 'анализ' is generic (weight 1) while 'встреч' is specific (weight 4), 'byd' is very specific (weight 5)
KEYWORD_WEIGHTS = {
    'osp': {'проанализируй': 3, 'прогноз': 2, 'стратегия': 2, 'анализ': 1, 'сценари': 2, 'вероятност': 2, 'деconstruct': 3, 'деконстру': 3, 'тополог': 3, 'силовой потенциал': 3, 'препарирован': 2},
    'lz': {'политик': 3, 'экономик': 3, 'геополитик': 4, 'санкци': 4, 'макро': 3, 'режим': 3, 'нарратив': 3, 'событие': 2, 'кризис': 3,
           'конфликт': 3, 'инфляци': 3, 'рецесси': 3, 'ставк': 2, 'войн': 3, 'дипломат': 3,
           'cantillon': 4, 'осинт': 3, 'osint': 3, 'разведк': 3, 'мониторинг': 2, 'свеж': 2, 'новост': 2, 'в мире': 2, 'в рф': 3},
    'expert': {'встреч': 4, 'встреча с': 5, 'брифинг': 4, 'подготов к': 3, 'эксперт': 3, 'подготовь': 3, 'вопросы для': 3, 'комбат-вопрос': 4, 'подготов': 2,
              'переговор': 4, 'переговоры': 4, 'byd': 5, 'geely': 5, 'chery': 5, 'zeekr': 5, 'lixiang': 5, 'nio': 5, 'xpeng': 5, 'vinfast': 5,
              'cto': 4, 'ceo': 4, 'cfo': 4, 'директор': 3, 'авто': 3, 'автомобиль': 3, 'автопром': 4, 'конкурент': 3, 'платформ': 3, 'ev ': 4,
              'электромобиль': 4, 'завод': 2, 'производств': 2, 'сборк': 2, 'локализац': 3},
}

def detect_dept(text):
    text_lower = text.lower().strip()
    # Phase 1: Explicit command prefix (exact match, no scoring needed)
    for cmd, dept in sorted(COMMAND_DEPT.items(), key=lambda x: -len(x[0])):
        if text_lower.startswith(cmd) and (len(text_lower) == len(cmd) or text_lower[len(cmd)] in ' \n/'):
            return dept

    # Phase 2: Weighted keyword scoring across ALL departments
    # Each dept scores points for matching keywords; highest score wins.
    # This fixes the OSP-before-Expert ordering bug where 'анализ' (weight 1)
    # hijacked queries containing 'встреч' (weight 4) or 'byd' (weight 5).
    scores = {}
    for dept, kws in RUSSIAN_KEYWORDS.items():
        score = 0
        matched = []
        weights = KEYWORD_WEIGHTS.get(dept, {})
        for kw in kws:
            if kw in text_lower:
                w = weights.get(kw, 1)  # default weight = 1 for unweighted keywords
                score += w
                matched.append(kw)
        if score > 0:
            scores[dept] = (score, matched)

    if scores:
        # Sort by score descending; on tie, prefer expert > osp > others
        _PRIORITY = {'expert': 0, 'osp': 1, 'lz': 2, 'finance': 3, 'marketing': 4, 'legal': 5,
                     'dev': 6, 'engineering': 7, 'design': 8, 'qa': 9, 'visual': 10, 'kavalnya': 11, 'admin': 12}
        best = sorted(scores.items(), key=lambda x: (-x[1][0], _PRIORITY.get(x[0], 99)))[0]
        best_dept = best[0]
        best_score = best[1][0]
        best_keywords = best[1][1]
        log.info(f"[detect_dept] scored: { {d: s[0] for d, s in scores.items()} } → {best_dept} (score={best_score}, kw={best_keywords})")
        return best_dept

    return 'yana'

# ──────────────────────────── CONDENSED PROMPTS ────────────────────────────
CONDENSED_PROMPTS = {
    'yana': "You are Yana, Chief of Cabinet. Route tasks to departments. Be empathetic, concise. Default language: Russian.",
    'osp': "You are OSP, Strategic Analysis Dept. Use 5-level topology (Leaves/Branches/Stem/Roots/Fruits). Mark claims [FACT]/[INTERPRETATION]/[SPECULATION]. Sherman Kent scale. Language: Russian.",
    'lz': "You are LZ, World Intelligence Lab. Monitor tech + politics + economics + geopolitics + events. Structure: Signal->Impact->Opportunity. Cantillon, narrative-vs-flows, macro regime. Cite sources. Language: Russian.",
    'expert': "You are Expert, Meeting & Negotiation Preparator. Prepare briefings for meetings/interviews/negotiations. Profile counterparty, combat questions, leverage points, BATNA, red flags, decision points. Mark: [ФАКТ] confirmed, [ОЦЕНКА] expert assessment, [РИСК] potential problem. Language: Russian.",
    'marketing': "You are Marketing. Audience analysis, positioning, campaigns, conversion. Segment personas, A/B logic. ROI-focused. Language: Russian.",
    'finance': "You are Finance. Budgets, cashflow, taxes, P&L. Precise numbers, scenarios, risk buffers. Tables preferred. Language: Russian.",
    'legal': "You are Legal. Contracts, compliance, GDPR, NDA, IP. Flag risks, cite articles. Practical actionable advice. Language: Russian.",
    'dev': "You are Dev. Architecture, APIs, deployment, code review. Modern stack, clean code principles. Code blocks with explanations. Language: Russian.",
    'design': "You are Design. UI/UX, wireframes, design systems, user flows. Accessibility, mobile-first, consistency. Language: Russian.",
    'qa': "You are QA. Testing strategies, bug triage, quality metrics. Test cases, regression plans, coverage. Language: Russian.",
    'visual': "You are Visual. Infographics, data visualization, charts, presentations. Color theory, layout, clarity. Language: Russian.",
    'engineering': "You are Engineering. Structural calculations, load analysis, SNiP compliance. Safety factors, materials, drawings. Language: Russian.\n\nМинимальный коэффициент запаса: 1.5 (hard gate; config/engineering_min_safety_factor.txt может только повышать порог). Нормативные базы: RF | BY | EU — выбор в config/engineering_normbase.txt (по умолчанию RF). Утверждённые инженером расчёты неизменяемы (гейт EngGateImmutable).",
    'kavalnya': "You are Kavalnya. Methodology, department creation, polygon exercises. Frameworks, KPIs, org design. Language: Russian.",
    'admin': "You are Admin, System Agent. Health checks, config management, system diagnostics. Technical, precise, actionable. Language: Russian.",
}

FORMAT_INSTRUCTION = """

## ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО)

Отвечай РАЗВЁРНУТО (минимум 1000 символов). Структура:

1. Используй секции: "Слой 1 — ...", "Слой 2 — ..." и т.д. (минимум 3 слоя)
2. Маркируй каждое утверждение значками:
   - ✓ — подтверждённые данные, цифры, даты (факты)
   - ◈ — твой анализ и интерпретация на основе фактов
   - ⚡ — гипотезы, предположения, спекуляция
3. Завершай секцией "Вердикт" с ключевыми выводами
4. Если применимо — добавь "Индикаторы для наблюдения"
5. Язык: русский
6. Не будь кратким. Препарируй тему глубоко.
"""

# FORMAT_INSTRUCTION (layered analysis with ✓/◈/⚡) only for expert dept
# OSP format now comes from deconstruct skill (always loaded via LoadOspSkills in app.mlog)
_ANALYTICAL_DEPTS = {"expert"}

def get_dept_prompt(dept, combo=None):
    fmt = FORMAT_INSTRUCTION if dept in _ANALYTICAL_DEPTS else ""
    # FO-018: декларация departments/<dept>.md — высший приоритет (последний wins)
    try:
        from proxy.departments import prompt_for
        decl_prompt = prompt_for(dept)
        if decl_prompt is not None:
            return decl_prompt + fmt
    except Exception as e:
        log.warning(f"[config] dept declaration read failed for {dept}: {e}")
    if combo and 'free' in combo:
        return CONDENSED_PROMPTS.get(dept, CONDENSED_PROMPTS['yana']) + fmt
    try:
        f = LIB_DIR / f"{dept}.md"
        if f.exists():
            return f.read_text(encoding="utf-8") + fmt
    except Exception as e:
        log.warning(f"[config] dept prompt file read failed for {dept}: {e}")
    return CONDENSED_PROMPTS.get(dept, CONDENSED_PROMPTS['yana']) + fmt


# ═══ FO-008 шаг 4c: метрики периодов (из фасада; нужны scheduler-модулям) ═══
def _collect_metrics_for_period(start_iso, end_iso=None):
    """Collect metrics for a given time period."""
    conditions = "created_at >= ?"
    params = [start_iso]
    if end_iso:
        conditions += " AND created_at < ?"
        params.append(end_iso)

    tasks = _query(f"SELECT dept, COUNT(*) as c FROM dialog_history WHERE {conditions} AND role='user' GROUP BY dept", params, fetch=True)
    reports = _query(f"SELECT dept, COUNT(*) as c FROM miniapp_responses WHERE {conditions} GROUP BY dept", params, fetch=True)
    corrections = _query(f"SELECT dept, COUNT(*) as c FROM adapt_corrections WHERE {conditions} GROUP BY dept", params, fetch=True)
    ratings = _query(f"SELECT dept, COALESCE(AVG(CAST(metric_value AS REAL)),0) as avg_r, COUNT(*) as c FROM dept_metrics WHERE {conditions} GROUP BY dept", params, fetch=True)
    tokens = _query(f"SELECT dept, COALESCE(SUM(input_tokens),0) as ti, COALESCE(SUM(output_tokens),0) as to2, COALESCE(SUM(cost_usd),0) as cost FROM token_usage WHERE {conditions} GROUP BY dept", params, fetch=True)

    return {
        "tasks": {r["dept"]: r["c"] for r in tasks},
        "reports": {r["dept"]: r["c"] for r in reports},
        "corrections": {r["dept"]: r["c"] for r in corrections},
        "ratings": {r["dept"]: {"avg": r["avg_r"], "count": r["c"]} for r in ratings},
        "tokens": {r["dept"]: {"in": r["ti"], "out": r["to2"], "cost": r["cost"]} for r in tokens},
    }

def _format_metrics_text(metrics):
    """Format metrics dict as readable text for LLM prompt."""
    lines = []
    lines.append("METRICS:")
    all_depts = set(list(metrics["tasks"].keys()) + list(metrics["reports"].keys()) + list(metrics["corrections"].keys()) + list(metrics["ratings"].keys()))
    for dept in sorted(all_depts):
        name = DEPT_NAMES.get(dept, dept)
        parts = [f"{name}:"]
        if dept in metrics["tasks"]:
            parts.append(f"tasks={metrics['tasks'][dept]}")
        if dept in metrics["reports"]:
            parts.append(f"reports={metrics['reports'][dept]}")
        if dept in metrics["corrections"]:
            parts.append(f"corrections={metrics['corrections'][dept]}")
        if dept in metrics["ratings"]:
            r = metrics["ratings"][dept]
            parts.append(f"avg_rating={r['avg']:.1f} (n={r['count']})")
        if dept in metrics["tokens"]:
            t = metrics["tokens"][dept]
            parts.append(f"tokens={t['in']+t['out']} cost=${t['cost']:.2f}")
        lines.append("  " + " ".join(parts))
    return "\n".join(lines)


# ═══ FO-008 шаг 4d: _memorize и RENDER_URL (из фасада) ═══
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("RENDER_URL", "https://fosved-office-v2.onrender.com"))

def _memorize(dept, topic, content):
    """Save a finding to dialog_history as a system memorization entry."""
    now = datetime.utcnow().isoformat()
    entry = f"[MEMORY] {topic}: {content}"
    _query("INSERT INTO dialog_history (dept, chat_id, role, content, created_at) VALUES (?, '0', 'system', ?, ?)",
           (dept, entry, now))


# Вызов init_db в КОНЦЕ модуля: все имена (включая _query) уже определены,
# поэтому ленивые импорты схем FO-017/FO-019 не падают на частичной
# инициализации core (см. комментарий в proxy/owner_profile.py).
init_db()
