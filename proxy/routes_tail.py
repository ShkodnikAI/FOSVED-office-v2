"""FO-008: транспорт ч.5b — memory, reminder, cron, консолидация, golden, traces.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 4e; наряд #68, стоп-гейт SG-F2).
"""

import os
import re
import json
import time
import uuid
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests as http_requests

from flask import request, jsonify, Response, send_file

from proxy.core import (
    app, log, http_requests,
    _query, _log_audit, _log_error, _write_llm_trace, _get_setting, _db, db_lock,
    get_secret, set_secret, delete_secret, _has_db_override, INTEGRATIONS_REGISTRY,
    PORT, DB_PATH, DB_FILE, BASE_DIR, LIB_DIR, CFG_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ARCHIVE_CHANNEL_ID, API_SECRET, WEBHOOK_SECRET,
    WHISPER_API_KEY, WHISPER_PROVIDER,
    memory, require_telegram, _TG_BOOTSTRAP_PAGE, _verify_init_data, _verify_webhook_secret,
    _memorize, RENDER_URL,
    detect_dept, get_dept_prompt, CONDENSED_PROMPTS, FORMAT_INSTRUCTION, COMMAND_DEPT,
    DEPT_COLORS, DEPT_NAMES, DEPT_HASHTAGS,
    _TRACE_DIR, _TRACE_MAX_BYTES, _TRACE_RETENTION,
    auto_enrich, _has_enricher,
    _collect_metrics_for_period, _format_metrics_text,
)
from proxy.providers import (
    PROVIDERS, TOKEN_COSTS, PROVIDER_MAX_TOKENS, COMBO_CHAINS,
    _breaker, _cfg_cache, call_llm, _call_single_provider,
    _generate_image, _IMG_DIR, _ALLOWED_SIZES, _zai_headers, _load_zai_config,
    _estimate_tokens, _compress_messages, _combo_for_task,
    cleanup_tool_output_files,  # FO-016: ретеншн offload-хранилища
)
from proxy.dialog import (  # FO-017: Dialog v2 — Parts + event-log
    save_message as dialog_save_message,
    add_tool_call as dialog_add_tool_call,
    add_tool_result as dialog_add_tool_result,
    get_session_events as dialog_get_session_events,
    get_session_messages as dialog_get_session_messages,
    get_part as dialog_get_part,
    migrate_dialog_history as dialog_migrate_dialog_history,
    rollback_migration as dialog_rollback_migration,
)
from proxy.owner_profile import (  # FO-019: профиль владельца static/dynamic/buckets
    get_owner_profile as profile_get_owner_profile,
    rebuild_owner_profile as profile_rebuild_owner_profile,
)
from proxy.review import (  # FO-020: review-очередь выведенного
    get_review_queue as review_get_queue,
    decide_review as review_decide,
    queue_depth as review_queue_depth,
    notify_queue_overflow_if_needed as review_notify_overflow,
    REVIEW_SOURCES, REVIEW_DECISIONS,
)
from proxy.telegram import (
    _MARKER_EMOJI, _ALL_EMOJI, _escape_mdv2, _tg_send_formatted,
    _tg_send_message, _tg_send_voice, _tg_send_report_with_button,
    _tg_get_file, _tg_download_file, _tg_send_photo, _tg_send_document,
    _safe_filename_part, _send_chat_action_loop, _tg_send_chat_action,
)
from proxy.voice import _clean_text_for_tts, tts_endpoint, stt_endpoint
from proxy.reports import (
    html_lib_escape, strip_html_for_archive, _html_base, _dept_header,
    _status_icon, _dept_kpis, _build_action_bar, ARCHIVE_MONTHS_RU,
    _browse_page, _evidence_badges_css,
)
from proxy.news import (
    RSS_FEEDS, GDELT_BASE, DEPT_QUERIES, DEPT_CATEGORIES,
    collect_tavily, collect_rss, collect_gdelt, get_fresh_news,
    get_night_news_digest, enrich_news_with_fulltext,
)
from proxy.lz_github import (
    OSINT_DISCLAIMER, OSINT_RATE_LIMIT, scan_osint,
    GITHUB_TOKEN, GITHUB_HEADERS, GITHUB_WATCH_RELEASES,
    _github_search, _github_releases,
    scheduler_lz_daily_core, scheduler_admin_daily,
)

# ══════════════════════════════════════════════════════════════════════
#  LZ DAILY REPORT — GitHub scan + LLM analysis + Admin delivery

# ══════════════════════════════════════════════════════════════════════
#  FOSVED MEMORY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.route('/memory/recall', methods=['POST'])
def memory_recall_endpoint():
    """Recall memories by query."""
    data = request.get_json(force=True) or {}
    query = data.get('query', '')
    mem_type = data.get('type')
    limit = data.get('limit', 10)
    if not query:
        return jsonify({'error': 'query required'}), 400
    results = memory.recall(query, type_filter=mem_type, limit=limit)
    return jsonify({'results': results, 'count': len(results)})


@app.route('/memory/remember', methods=['POST'])
def memory_remember_endpoint():
    """Save a new memory."""
    data = request.get_json(force=True) or {}
    if 'content' not in data:
        return jsonify({'error': 'content required'}), 400
    mem_id = memory.remember(
        content=data['content'],
        mem_type=data.get('type', 'fact'),
        confidence=float(data.get('confidence', 0.8)),
        source=data.get('source', 'manual')
    )
    return jsonify({'id': mem_id, 'status': 'remembered'})


@app.route('/memory/stats', methods=['GET'])
def memory_stats_endpoint():
    """Memory statistics."""
    return jsonify(memory.stats())


@app.route('/memory/answer', methods=['POST'])
def memory_answer_endpoint():
    """RAG answer based on memory."""
    data = request.get_json(force=True) or {}
    answer_text = memory.answer(data.get('question', ''))
    return jsonify({'answer': answer_text})


@app.route('/memory/maintenance', methods=['POST'])
def memory_maintenance_endpoint():
    """Run nightly maintenance."""
    result = memory.nightly_maintenance()
    return jsonify({'result': result})


@app.route('/memory/conflicts', methods=['GET'])
def memory_conflicts_endpoint():
    """Detect memory conflicts."""
    conflicts = memory.detect_conflicts()
    return jsonify({'conflicts': conflicts, 'count': len(conflicts)})


@app.route('/yana/auto-memorize', methods=['POST'])
def yana_auto_memorize():
    """Extract key facts from Yana exchange and store to FosvedMemory.
    Uses cheap model (groq) for extraction. Fire and forget."""
    d = request.get_json(force=True) or {}
    query = d.get('query', '')
    reply = d.get('reply', '')
    chat_id = d.get('chat_id', '')
    if len(query) < 10 or len(reply) < 20:
        return jsonify({'status': 'skipped', 'reason': 'too short'})
    try:
        prompt = [
            {"role": "system", "content": "Extract 1-3 key facts worth remembering long-term from this conversation. "
                "Only facts about the OWNER: name, location, preferences, decisions, obligations, relationships, projects, health. "
                "Ignore: greetings, meta-comments, questions about system nature. "
                "Output ONLY a JSON array of objects with keys: content (string), type (fact|preference|commitment|decision|context), confidence (0.5-1.0). "
                "When a fact is a commitment or reminder with a date/time, include a \"date\" key with the date in YYYY-MM-DD HH:MM format (or YYYY-MM-DD if no time). If the date is relative (tomorrow, next week), calculate the actual date based on today being 2026-07-06. If nothing worth remembering, output: []"},
            {"role": "user", "content": f"User: {query[:500]}\nYana: {reply[:500]}"}
        ]
        result = _call_single_provider("groq", "openai/gpt-oss-20b", prompt, dept="yana", max_tokens=300, is_internal=True)
        if result and result.get('reply'):
            import json as _json
            text = result['reply'].strip()
            if text.startswith('```'):
                text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            facts = _json.loads(text)
            saved = 0
            for f in facts[:3]:
                if isinstance(f, dict) and f.get('content'):
                    memory.remember(
                        content=f['content'][:500],
                        mem_type=f.get('type', 'fact'),
                        confidence=float(f.get('confidence', 0.8)),
                        source='yana_auto'
                    )
                    saved += 1
            log.info(f"Yana auto-memorize: extracted {saved} facts from chat {chat_id}")

            # Also check for dated reminders — store in yana_events for scheduler
            for f in facts[:3]:
                if isinstance(f, dict) and f.get('type') == 'commitment' and f.get('date'):
                    _query("INSERT OR IGNORE INTO yana_events (event_text, event_date, event_type) VALUES (?, ?, 'reminder')",
                           (f['content'][:300], f['date'][:20]))
                    log.info(f"Yana reminder stored: {f['content'][:60]} at {f.get('date', '?')}")

            return jsonify({'status': 'ok', 'saved': saved})
    except Exception as e:
        log.warning(f"Yana auto-memorize failed: {e}")
    return jsonify({'status': 'error'})


# ══════════════════════════════════════════════════════════════════════
#  REMINDER CHECK — send due reminders to owner
# ══════════════════════════════════════════════════════════════════════

@app.post("/scheduler/reminder-check")
def scheduler_reminder_check():
    """Check yana_events for due reminders and send them to owner."""
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        return jsonify({"status": "error", "message": "OWNER_TELEGRAM_ID not set"}), 400

    try:
        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        # Find events due now (event_date <= now) that haven't been reminded yet
        rows = _query("SELECT id, event_text, event_date FROM yana_events "
                       "WHERE event_date <= ? AND reminded_at IS NULL "
                       "ORDER BY event_date ASC LIMIT 5",
                       (now_iso,))

        sent = 0
        for r in rows:
            event_text = r["event_text"]
            event_date = r["event_date"]
            event_id = r["id"]

            msg = f"Напоминание: {event_text}\n({event_date})"
            _send_telegram_message(owner_id, msg)

            # Mark as reminded
            _query("UPDATE yana_events SET reminded_at = datetime('now') WHERE id = ?", (event_id,))
            sent += 1
            log.info(f"Reminder sent: [{event_date}] {event_text[:60]}")

        # Clean up old reminded events (older than 7 days)
        _query("DELETE FROM yana_events WHERE reminded_at IS NOT NULL AND reminded_at < datetime('now', '-7 days')")

        return jsonify({"status": "ok", "sent": sent, "checked": len(rows)})
    except Exception as e:
        log.error(f"reminder_check error: {e}")
        _log_audit("scheduler_reminder_check_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  IMAGE GENERATION ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.route('/generate-image', methods=['POST'])
def generate_image_endpoint():
    """Generate an image via z-ai API and send it to Telegram chat.
    Request body: {prompt, size?, chat_id, caption?}
    Returns: {status, path?, error?}"""
    d = request.get_json(force=True) or {}
    prompt = d.get('prompt', '').strip()
    chat_id = str(d.get('chat_id', ''))
    size = d.get('size', '1024x1024')
    caption = d.get('caption', '')
    if not prompt:
        return jsonify({'status': 'error', 'error': 'prompt is required'}), 400
    if not chat_id:
        return jsonify({'status': 'error', 'error': 'chat_id is required'}), 400
    # Send upload_photo action so user sees progress
    _tg_send_chat_action(chat_id, 'upload_photo')
    fpath, err = _generate_image(prompt, size)
    if err:
        _tg_send_message(chat_id, f"Не удалось сгенерировать изображение: {err}")
        return jsonify({'status': 'error', 'error': err}), 500
    # Send to Telegram
    msg_id = _tg_send_photo(chat_id, fpath, caption or None)
    _log_audit('image_generated', {'prompt': prompt[:100], 'size': size, 'path': fpath, 'chat_id': chat_id, 'tg_msg_id': msg_id}, dept='design')
    return jsonify({'status': 'ok', 'path': fpath, 'tg_msg_id': msg_id})



# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

# ──────────────────────────── PYTHON TELEGRAM WEBHOOK (DEAD CODE) ────────────────────────────
# WH-1/WH-2: route returned to Metalogos after fixing app.mlog:2251 SQL bug.
# Kept RENDER_URL below (used elsewhere); the Flask route + full handler body
# (~340 lines) removed as unreachable — reverse_proxy.py no longer sends
# /webhook/telegram here. Old implementation lives in git history if a
# rollback to the Python path is ever needed again.

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("RENDER_URL", "https://fosved-office-v2.onrender.com"))

# ── Cron endpoint ──
@app.route("/cron/collect-news", methods=["GET"])
def cron_collect_news():
    secret = request.args.get("secret", "")
    if secret != os.environ.get("CRON_SECRET", ""):
        return "Forbidden", 403
    rss_count = collect_rss()
    gdelt_count = collect_gdelt_themes()
    tavily_count = collect_tavily()
    enrich_count = enrich_news_with_fulltext(limit=5)
    _log_audit("news_collection", {"rss": rss_count, "gdelt": gdelt_count, "tavily": tavily_count, "enriched": enrich_count}, "collector")
    return jsonify({"rss": rss_count, "gdelt": gdelt_count, "tavily": tavily_count, "enriched": enrich_count, "total": rss_count + gdelt_count + tavily_count})


# ── FO-001: Nightly DB backup ──
@app.route("/cron/backup", methods=["GET"])
def cron_backup():
    """Nightly backup cron: VACUUM INTO + integrity check + retention."""
    secret = request.args.get("secret", "")
    if secret != os.environ.get("CRON_SECRET", ""):
        return "Forbidden", 403
    _rotate_service_logs()  # FO-007: ротация журналов перед бэкапом
    import subprocess
    upload = request.args.get("upload", "0") == "1"
    cmd = [sys.executable, "scripts/backup_db.py", "backup"]
    if upload:
        cmd.append("--upload")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                env={**os.environ, "DATABASE_PATH": os.environ.get("DATABASE_PATH", "./data")})
        ok = result.returncode == 0
        _log_audit("db_backup", {"ok": ok, "output": result.stdout[-500:] if result.stdout else ""}, "system")
        return jsonify({"ok": ok, "output": result.stdout[-500:] if result.stdout else result.stderr[-500:]})
    except Exception as e:
        _log_audit("db_backup_error", {"error": str(e)[:500]}, "system")
        return jsonify({"ok": False, "error": str(e)[:500]}), 500


# ── FO-016: чистка offload-хранилища tool-выводов (issue #82) ────────────
# data/tool_output/ с ретеншном 7 дней (env FOSVED_TOOL_OUTPUT_RETENTION_DAYS).
@app.route("/cron/cleanup-tool-output", methods=["GET"])
def cron_cleanup_tool_output():
    secret = request.args.get("secret", "")
    if secret != os.environ.get("CRON_SECRET", ""):
        return "Forbidden", 403
    removed = cleanup_tool_output_files()
    _log_audit("tool_output_cleanup", {"removed": removed}, "system")
    return jsonify({"ok": True, "removed": removed})


# ── FO-017: Dialog v2 — Part-модель + event-log с per-session seq ────────
# Эндпоинты для mlog/админов: запись реплик с Parts, тулз-события,
# лента/восстановление, идемпотентная миграция dialog_history (обратимая).
@app.route("/dialog/message", methods=["POST"])
def dialog_message_endpoint():
    d = request.get_json(force=True) or {}
    sid = d.get("session_id")
    if not sid:
        return jsonify({"error": "session_id required"}), 400
    try:
        res = dialog_save_message(
            str(sid), d.get("role", "user"),
            content=d.get("content", ""), dept=d.get("dept", ""),
            parts=d.get("parts"), source=d.get("source", "api"),
            source_id=d.get("source_id"), meta=d.get("meta"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if res is None:
        return jsonify({"error": "save failed"}), 500
    return jsonify(res)


@app.route("/dialog/tool-call", methods=["POST"])
def dialog_tool_call_endpoint():
    d = request.get_json(force=True) or {}
    sid = d.get("session_id")
    if not sid:
        return jsonify({"error": "session_id required"}), 400
    call_part = dialog_add_tool_call(
        str(sid), d.get("message_id"), d.get("tool", ""),
        arguments=d.get("arguments"))
    if call_part is None:
        return jsonify({"error": "tool_call part failed"}), 500
    result_part = None
    if "result" in d or d.get("error"):
        result_part = dialog_add_tool_result(
            str(sid), call_part, result=d.get("result"),
            ok=bool(d.get("ok", True)), error=d.get("error"))
    return jsonify({"tool_call_part": call_part, "tool_result_part": result_part})


@app.route("/dialog/session/<session_id>", methods=["GET"])
def dialog_session_endpoint(session_id):
    """Лента и реплики с Parts. ?events=1 — сырая лента (from_seq/limit);
    по умолчанию — messages с вложенными Parts (типы для miniapp: tool_call
    сворачивается клиентом)."""
    if request.args.get("events") == "1":
        events = dialog_get_session_events(
            session_id,
            from_seq=int(request.args.get("from_seq", 0)),
            limit=min(int(request.args.get("limit", 1000)), 10000))
        return jsonify({"session_id": session_id, "events": events,
                        "count": len(events)})
    msgs = dialog_get_session_messages(session_id,
                                       limit=min(int(request.args.get("limit", 200)), 1000))
    return jsonify({"session_id": session_id, "messages": msgs, "count": len(msgs)})


@app.route("/dialog/part/<int:part_id>", methods=["GET"])
def dialog_part_endpoint(part_id):
    p = dialog_get_part(part_id)
    if p is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(p)


@app.route("/dialog/migrate", methods=["POST"])
def dialog_migrate_endpoint():
    """Миграция dialog_history → Dialog v2. {batch, dry_run, rollback}."""
    d = request.get_json(force=True) or {}
    if d.get("rollback"):
        res = dialog_rollback_migration()
        _log_audit("dialog_v2_rollback", res, "system")
        return jsonify(res)
    res = dialog_migrate_dialog_history(batch=int(d.get("batch", 500)),
                                        dry_run=bool(d.get("dry_run")))
    _log_audit("dialog_v2_migration", res, "system")
    return jsonify(res)


# ── FO-019: профиль владельца — static/dynamic/buckets одним вызовом ─────
@app.route("/profile/owner", methods=["GET", "POST"])
def profile_owner_endpoint():
    """Один вызов для всех департаментов. Метафильтры: dept/topic/section.
    mlog: POST {"dept": "finance"}; браузер/миниапп: GET ?dept=…&topic=…"""
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
    else:
        d = request.args
    res = profile_get_owner_profile(
        dept=d.get("dept"), topic=d.get("topic"),
        section=d.get("section"),
        max_chars=int(d.get("max_chars", 4000) or 4000))
    return jsonify(res)


@app.route("/profile/rebuild", methods=["POST"])
def profile_rebuild_endpoint():
    """Пересборка профиля из активных фактов (после консолидации — вручную
    или из крона). {dept?: "…"}"""
    d = request.get_json(silent=True) or {}
    res = profile_rebuild_owner_profile(dept_filter=d.get("dept"), source="api")
    _log_audit("owner_profile_rebuild", res, "memory")
    return jsonify(res)


# ── FO-020: review-очередь выведенного (inference review, issue #86) ──────
@app.route("/review/queue", methods=["GET", "POST"])
def review_queue_endpoint():
    """Очередь невыверенного: parent_count DESC (сильнейший сигнал сверху).
    mlog: POST {} → карточки для /review."""
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
    else:
        d = request.args
    src = d.get("source") or None
    if src and src not in REVIEW_SOURCES:
        return jsonify({"error": f"unknown source: {src}"}), 400
    items = review_get_queue(limit=int(d.get("limit", 50) or 50), source=src)
    return jsonify({"items": items, "count": len(items), "depth": review_queue_depth()})


@app.route("/review/decide", methods=["POST"])
def review_decide_endpoint():
    """Решение ревью: approve | decline (+reason) | undo."""
    d = request.get_json(force=True) or {}
    try:
        res = review_decide(d.get("item_id"), d.get("source"),
                            d.get("decision"), reason=d.get("reason"),
                            actor=d.get("actor", "owner"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(res)


# ── FO-006: ночная консолидация памяти (mem0-паттерн, issue #66) ─────────
# dialog_history остаётся append-only журналом; факты живут в facts и
# становятся первичным источником утреннего контекста.

_FACTS_MAX_OPS = 20          # максимум операций за один LLM-вызов
_FACTS_DIALOG_ROWS = 120     # максимум реплик дня на входе консолидации
_FACTS_BACKFILL_DAYS = 90    # безопасный предел backfill

def _extract_json_block(text):
    """Достаёт первый JSON-объект из ответа LLM (терпим к ```-заборам и мусору)."""
    text = str(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception as e:
        log.debug(f"consolidation: direct json parse failed: {e}")
    if isinstance(parsed, dict):
        return parsed
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
        except Exception as e:
            log.debug(f"consolidation: regex json parse failed: {e}")
    return parsed if isinstance(parsed, dict) else None

def _consolidate_dept_day(dept, day):
    """Консолидация одного дня одного департамента: диалог → ops → facts.

    Возвращает словарь счётчиков. Любой сбой (LLM, парсинг, БД) не роняет
    процесс: ошибка фиксируется через _log_error и возвращается в статусе.
    """
    day_start, day_end = f"{day} 00:00:00", f"{day} 23:59:59"
    try:
        rows = _query(
            "SELECT id, role, content FROM dialog_history "
            "WHERE dept=? AND role IN ('user','assistant') AND created_at BETWEEN ? AND ? "
            "ORDER BY id ASC LIMIT ?",
            (dept, day_start, day_end, _FACTS_DIALOG_ROWS), fetch=True)
    except Exception as e:
        _log_error(f"consolidation: dialog read failed {dept}/{day}: {e}",
                   source="memory_consolidation", dept=dept, kind="db_read")
        return {"dept": dept, "day": day, "error": "dialog_read_failed"}
    if not rows:
        return {"dept": dept, "day": day, "skipped": "no_dialogs"}

    dialog_text = "\n".join(f"[{r['id']}] {r['role']}: {str(r['content'])[:400]}" for r in rows)
    try:
        existing = _query(
            "SELECT id, content FROM facts WHERE dept=? AND status='active' "
            "ORDER BY updated_at DESC LIMIT 60", (dept,), fetch=True)
    except Exception as e:
        _log_error(f"consolidation: facts read failed {dept}: {e}",
                   source="memory_consolidation", dept=dept, kind="db_read")
        return {"dept": dept, "day": day, "error": "facts_read_failed"}
    facts_text = "\n".join(f"[{r['id']}] {r['content']}" for r in existing) or "(пусто)"

    prompt = (
        "Ты — модуль консолидации памяти офиса FOSVED (паттерн mem0).\n"
        f"Ниже — диалоги департамента «{dept}» за {day} и текущие консолидированные факты.\n\n"
        "Задача: извлечь из диалогов атомарные факты (одно предложение — один проверяемый факт) "
        "и синхронизировать их со списком текущих фактов.\n\n"
        "Операции:\n"
        "- ADD — новый факт, которого нет в списке\n"
        "- UPDATE — уточнение/изменение существующего факта (укажи target_id и новую формулировку)\n"
        "- DELETE — факт больше не верен (укажи target_id)\n\n"
        "Правила:\n"
        "- Только конкретные проверяемые утверждения: решения, настройки, события, предпочтения, результаты. Не выдумывай.\n"
        "- Близкие дубликаты существующего факта — не ADD, а NOOP (просто не включай в ответ).\n"
        f"- Максимум {_FACTS_MAX_OPS} операций за вызов.\n"
        "- Ответ — ТОЛЬКО JSON без пояснений:\n"
        '{"ops":[{"op":"ADD","content":"...","confidence":0.9},'
        '{"op":"UPDATE","target_id":123,"content":"новая формулировка","confidence":0.9},'
        '{"op":"DELETE","target_id":123,"reason":"..."}]}\n\n'
        f"=== ТЕКУЩИЕ ФАКТЫ ===\n{facts_text}\n\n"
        f"=== ДИАЛОГИ ЗА {day} ===\n{dialog_text}"
    )

    try:
        result = call_llm("admin", [{"role": "user", "content": prompt}])
    except Exception as e:
        _log_error(f"consolidation: LLM call failed {dept}/{day}: {e}",
                   source="memory_consolidation", dept=dept, kind="external")
        return {"dept": dept, "day": day, "error": "llm_failed"}
    reply = result.get("reply", "")
    if reply.startswith("[Oshibka]"):
        _log_error(f"consolidation: LLM unavailable {dept}/{day}: {reply[:150]}",
                   source="memory_consolidation", dept=dept, kind="external")
        return {"dept": dept, "day": day, "error": "llm_unavailable"}

    parsed = _extract_json_block(reply)
    if parsed is None or not isinstance(parsed.get("ops"), list):
        _log_error(f"consolidation: unparseable LLM reply {dept}/{day}: {str(reply)[:200]}",
                   source="memory_consolidation", dept=dept, kind="parse")
        return {"dept": dept, "day": day, "error": "unparseable_reply"}

    created = updated = deleted = noop = 0
    source_ids = json.dumps([r["id"] for r in rows])
    now = datetime.utcnow().isoformat()
    # FO-020: консолидация — выведенное знание: inference, pending,
    # parent_count = число диалогов-источников
    parent_count = len(json.loads(source_ids))

    def _insert_fact(content, confidence):
        _query(
            "INSERT INTO facts (dept, chat_id, content, status, source_dialog_ids, confidence, created_at, updated_at, inference, review_status, parent_count) "
            "VALUES (?, '0', ?, 'active', ?, ?, ?, ?, 1, 'pending', ?)",
            (dept, str(content)[:500], source_ids, max(0.0, min(1.0, float(confidence))), now, now, parent_count))

    for op in parsed["ops"][:_FACTS_MAX_OPS]:
        if not isinstance(op, dict):
            noop += 1
            continue
        action = str(op.get("op", "NOOP")).upper()
        try:
            if action == "ADD" and op.get("content"):
                _insert_fact(op["content"], op.get("confidence", 0.8))
                created += 1
            elif action == "UPDATE" and op.get("content") and op.get("target_id"):
                _query("UPDATE facts SET status='superseded', updated_at=? WHERE id=? AND dept=?",
                       (now, int(op["target_id"]), dept))
                _insert_fact(op["content"], op.get("confidence", 0.8))
                updated += 1
            elif action == "DELETE" and op.get("target_id"):
                _query("UPDATE facts SET status='deleted', updated_at=? WHERE id=? AND dept=?",
                       (now, int(op["target_id"]), dept))
                deleted += 1
            else:
                noop += 1
        except Exception as e:
            _log_error(f"consolidation: fact op apply failed {dept}/{day}: {str(op)[:120]}: {e}",
                       source="memory_consolidation", dept=dept, kind="db_write")

    counters = {
        "dept": dept, "day": day, "source_rows": len(rows),
        "created": created, "updated": updated, "deleted": deleted, "noop": noop,
    }
    # FO-004: счётчик консолидации в трейсах (отдельный trace_type)
    try:
        _write_llm_trace({
            "trace_id": uuid.uuid4().hex[:16],
            "trace_type": "memory_consolidation",
            "time": now,
            "dept": dept, "date": day,
            "facts_created": created, "facts_updated": updated,
            "facts_deleted": deleted, "facts_noop": noop,
            "source_rows": len(rows),
            "provider": result.get("provider"), "model": result.get("model"),
            "tokens_in": result.get("tokens_in"), "tokens_out": result.get("tokens_out"),
        })
    except Exception as e:
        log.debug(f"consolidation trace write failed (non-fatal): {e}")
    return counters

def _consolidate_memory(days=1, dept_filter=None, backfill=False):
    """Прогон консолидации: последний день (по умолчанию) или backfill N дней.

    Возвращает список счётчиков по (департамент, день). Порядок дней — от старых
    к свежим (обновления фактов доносятся в хронологическом порядке).
    """
    days = max(1, min(int(days), _FACTS_BACKFILL_DAYS))
    if backfill:
        day_list = [(datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(days, 0, -1)]
    else:
        day_list = [(datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")]

    results = []
    for day in day_list:
        if dept_filter:
            depts = [dept_filter]
        else:
            day_start, day_end = f"{day} 00:00:00", f"{day} 23:59:59"
            rows = _query("SELECT DISTINCT dept FROM dialog_history WHERE created_at BETWEEN ? AND ?",
                          (day_start, day_end), fetch=True)
            depts = [r["dept"] for r in rows if r["dept"]]
        for dept in depts:
            counters = _consolidate_dept_day(dept, day)
            results.append(counters)
    return results

@app.post("/cron/consolidate-memory")
def cron_consolidate_memory():
    """FO-006: ночная консолидация dialog_history → facts.

    Query: ?secret=CRON_SECRET
    JSON body (всё опционально): {"days": 1, "dept": "osp", "backfill": false, "backup": false}
    - default: вчерашний день, все департаменты с активностью
    - backfill=true + days=N: одноразовый прогон последних N дней (порциями день×департамент)
    - backup=true: сначала scripts/backup_db.py (бэкап FO-001) — обязателен для backfill
    """
    secret = request.args.get("secret", "")
    if secret != os.environ.get("CRON_SECRET", ""):
        return "Forbidden", 403
    d = request.get_json(silent=True) or {}
    days = int(d.get("days", 1))
    dept_filter = d.get("dept")
    backfill = bool(d.get("backfill", False))
    do_backup = bool(d.get("backup", False))

    backup_status = None
    if do_backup:
        try:
            import subprocess
            result = subprocess.run([sys.executable, "scripts/backup_db.py", "backup"],
                                    capture_output=True, text=True, timeout=120,
                                    env={**os.environ, "DATABASE_PATH": os.environ.get("DATABASE_PATH", "./data")})
            backup_status = {"ok": result.returncode == 0,
                             "output": (result.stdout or result.stderr)[-300:]}
        except Exception as e:
            backup_status = {"ok": False, "error": str(e)[:300]}
            _log_error(f"consolidation pre-backup failed: {e}", source="memory_consolidation", kind="backup")
            return jsonify({"status": "aborted", "reason": "backup_failed", "backup": backup_status}), 500

    try:
        results = _consolidate_memory(days=days, dept_filter=dept_filter, backfill=backfill)
    except Exception as e:
        _log_error(f"consolidation run failed: {e}", source="memory_consolidation", kind="run")
        return jsonify({"status": "error", "message": str(e)[:300]}), 500

    totals = {
        "created": sum(r.get("created", 0) for r in results),
        "updated": sum(r.get("updated", 0) for r in results),
        "deleted": sum(r.get("deleted", 0) for r in results),
        "noop": sum(r.get("noop", 0) for r in results),
        "errors": sum(1 for r in results if r.get("error")),
    }
    _log_audit("memory_consolidation", {"totals": totals, "days": days, "backfill": backfill, "dept": dept_filter}, "memory")

    # FO-019: после консолидации обновляем профиль владельца (генератор).
    # Сбой профиля не роняет консолидацию — фиксируется в ответе и error_log.
    profile_status = None
    if not backfill:  # backfill — разовая операция, профиль rebuild'ится один раз в конце обычного прогона
        try:
            profile_status = profile_rebuild_owner_profile(source="nightly")
        except Exception as e:
            _log_error(f"owner_profile nightly rebuild failed: {e}",
                       source="owner_profile", kind="run")
            profile_status = {"status": "error", "error": str(e)[:200]}
    # FO-020: очередь ревью выросла? — уведомление владельцу (после консолидации)
    review_overflow = None
    try:
        review_overflow = review_notify_overflow()
    except Exception as e:
        _log_error(f"review overflow notify failed: {e}", source="review", kind="run")
    return jsonify({"status": "ok", "totals": totals, "backup": backup_status,
                    "results": results, "owner_profile": profile_status,
                    "review_overflow": review_overflow})


# ── FO-005: golden-set eval-регрессий по департаментам (issue #65) ───────
# Ночной прогон: каждый департамент на golden-наборе, скор = формат-правила
# + llm_verifier; тренд — в dept_metrics и трейсах FO-004; падение — алерт.

_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
_GOLDEN_MIN_SCORE = float(os.environ.get("GOLDEN_MIN_SCORE", "0.6"))       # абсолютный порог
_GOLDEN_REGRESSION_DROP = float(os.environ.get("GOLDEN_REGRESSION_DROP", "0.15"))  # падение vs предыдущий прогон

def _golden_load(dept):
    """Загрузить golden-набор департамента (tests/golden/<dept>.json)."""
    path = _GOLDEN_DIR / f"{dept}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("tasks", [])

def _golden_format_score(task, reply):
    """Доля выполненных формат-правил из expect (0.0-1.0)."""
    rules = task.get("expect") or {}
    reply_low = str(reply).lower()
    total = passed = 0
    exp = rules.get("contains_any")
    if exp:
        total += 1
        if any(str(x).lower() in reply_low for x in exp):
            passed += 1
    rx = rules.get("contains_regex")
    if rx:
        total += 1
        if re.search(rx, str(reply), re.I | re.S):
            passed += 1
    ban = rules.get("not_contains")
    if ban:
        total += 1
        if not any(str(x).lower() in reply_low for x in ban):
            passed += 1
    mn, mx = rules.get("min_chars"), rules.get("max_chars")
    if mn or mx:
        total += 1
        n = len(str(reply))
        if (not mn or n >= int(mn)) and (not mx or n <= int(mx)):
            passed += 1
    return (passed / total) if total else 1.0

def _golden_run_dept(dept, tasks):
    """Прогнать golden-набор одного департамента. Возвращает сводку."""
    results = []
    for task in tasks:
        tid, q = task.get("id", "?"), task.get("input", "")
        llm_failed = False
        t0 = time.monotonic()
        try:
            result = call_llm(dept, [{"role": "user", "content": q}])
            reply = result.get("reply", "")
            provider, model = result.get("provider"), result.get("model")
        except Exception as e:
            _log_error(f"golden: llm call failed {dept}/{tid}: {e}",
                       source="golden_evals", dept=dept, kind="external")
            reply, provider, model, llm_failed = "", None, None, True
        latency_ms = round((time.monotonic() - t0) * 1000)

        if llm_failed or reply.startswith("[Oshibka]"):
            fmt_score, ver_score = 0.0, None
        else:
            fmt_score = _golden_format_score(task, reply)
            ver_score = None
            try:
                import llm_verifier
                ver_score = float(llm_verifier.score(
                    q, reply, task.get("verifier_criteria",
                                       "Correctness: Does the response solve the problem accurately?")))
            except Exception as e:
                _log_error(f"golden: verifier failed {dept}/{tid}: {e}",
                           source="golden_evals", dept=dept, kind="verifier")

        score = round(fmt_score if ver_score is None else (0.5 * fmt_score + 0.5 * ver_score), 3)
        results.append({
            "task": tid, "score": score, "format_score": round(fmt_score, 3),
            "verifier_score": round(ver_score, 3) if ver_score is not None else None,
            "latency_ms": latency_ms, "llm_failed": llm_failed,
        })
        # FO-004: скор задачи в трейсах (тренд виден в /traces)
        try:
            _write_llm_trace({
                "trace_id": uuid.uuid4().hex[:16],
                "trace_type": "golden_eval",
                "time": datetime.utcnow().isoformat(),
                "dept": dept, "task": tid,
                "score": score, "format_score": round(fmt_score, 3),
                "verifier_score": round(ver_score, 3) if ver_score is not None else None,
                "latency_ms": latency_ms,
                "provider": provider, "model": model,
            })
        except Exception as e:
            log.debug(f"golden trace write failed (non-fatal): {e}")

    scores = [r["score"] for r in results] or [0.0]
    return {
        "dept": dept,
        "avg_score": round(sum(scores) / len(scores), 3),
        "min_score": min(scores),
        "tasks_total": len(results),
        "failed": sum(1 for r in results if r["llm_failed"]),
        "results": results,
    }

def _golden_previous_avg(dept):
    """Предыдущая средняя оценка департамента (dept_metrics, до сегодня)."""
    today = datetime.utcnow().isoformat()[:10]
    rows = _query(
        "SELECT metric_value FROM dept_metrics WHERE dept=? AND metric_name='golden_eval_avg' "
        "AND created_at < ? ORDER BY id DESC LIMIT 1", (dept, today), fetch=True)
    if rows:
        try:
            return float(rows[0]["metric_value"])
        except (ValueError, TypeError):
            return None
    return None

@app.post("/scheduler/golden-evals")
def scheduler_golden_evals():
    """FO-005: ночной прогон golden-наборов + детекция регрессий.

    Query: ?secret=CRON_SECRET
    JSON body (опционально): {"depts": ["osp", "lz"]} — по умолчанию все наборы в tests/golden/
    Регрессия = avg < GOLDEN_MIN_SCORE (0.6) или падение >= 0.15 против предыдущего прогона.
    Регрессия → audit_log + мгновенный алерт владельцу в Telegram.
    """
    secret = request.args.get("secret", "")
    if secret != os.environ.get("CRON_SECRET", ""):
        return "Forbidden", 403
    d = request.get_json(silent=True) or {}
    dept_list = d.get("depts") or sorted(p.stem for p in _GOLDEN_DIR.glob("*.json"))
    if not dept_list:
        return jsonify({"status": "ok", "message": "no golden sets found", "results": []})

    alerts = []
    results = []
    for dept in dept_list:
        tasks = _golden_load(dept)
        if not tasks:
            results.append({"dept": dept, "skipped": "no_golden_set"})
            continue
        summary = _golden_run_dept(dept, tasks)
        prev = _golden_previous_avg(dept)
        summary["previous_avg"] = prev
        summary["regression"] = bool(
            summary["avg_score"] < _GOLDEN_MIN_SCORE
            or (prev is not None and (prev - summary["avg_score"]) >= _GOLDEN_REGRESSION_DROP))
        # Тренд: dept_metrics (screen FO-011, morning brief)
        try:
            _query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES (?,?,?,?,?)",
                   (dept, "golden_eval_avg", str(summary["avg_score"]),
                    datetime.utcnow().isoformat()[:10], datetime.utcnow().isoformat()))
        except Exception as e:
            _log_error(f"golden: dept_metrics insert failed {dept}: {e}",
                       source="golden_evals", dept=dept, kind="metrics_loss")
        if summary["regression"]:
            alerts.append(summary)
        results.append(summary)

    # Сигнал владельцу: мгновенный алерт по регрессии
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if alerts and owner_id:
        lines = ["❌ Регрессия качества департаментов (golden evals):"]
        for s in alerts:
            prev_txt = f" (было {s['previous_avg']:.2f})" if s.get("previous_avg") is not None else ""
            lines.append(f"• {s['dept']}: {s['avg_score']:.2f}{prev_txt}, проваленных задач: {s['failed']}")
            worst = min(s["results"], key=lambda r: r["score"]) if s["results"] else None
            if worst:
                lines.append(f"  худшая: {worst['task']} = {worst['score']:.2f}")
        try:
            _tg_send_message(owner_id, "\n".join(lines))
        except Exception as e:
            _log_error(f"golden: owner alert send failed: {e}", source="golden_evals", kind="external")

    totals = {
        "depts": len(results),
        "regressions": len(alerts),
        "avg_all": round(sum(r["avg_score"] for r in results if "avg_score" in r) /
                         max(1, sum(1 for r in results if "avg_score" in r)), 3),
    }
    _log_audit("golden_evals", {"totals": totals, "alerts": [s["dept"] for s in alerts]}, "quality")
    return jsonify({"status": "ok", "totals": totals, "thresholds": {
        "min_score": _GOLDEN_MIN_SCORE, "regression_drop": _GOLDEN_REGRESSION_DROP}, "results": results})




# ── LLM Traces (FO-004) ──────────────────────────────────────
@app.route("/traces", methods=["GET"])
def traces_endpoint():
    """Query LLM trace JSONL files. Params: dept, from, to, limit, ok."""
    dept = request.args.get("dept", "")
    from_ts = request.args.get("from", "")
    to_ts = request.args.get("to", "")
    limit = min(int(request.args.get("limit", 100)), 1000)
    ok_filter = request.args.get("ok", "")  # "true" / "false" / "" (all)

    results = []
    try:
        if not os.path.isdir(_TRACE_DIR):
            return jsonify({"traces": [], "count": 0})

        files = sorted(
            [f for f in os.listdir(_TRACE_DIR) if f.startswith("llm_") and f.endswith(".jsonl")],
            reverse=True  # newest first
        )
        for fname in files:
            if len(results) >= limit:
                break
            date_part = fname[4:14]  # llm_YYYY-MM-DD...
            if from_ts and date_part < from_ts:
                continue
            if to_ts and date_part > to_ts:
                continue
            with open(os.path.join(_TRACE_DIR, fname), "r", encoding="utf-8") as f:
                for line in f:
                    if len(results) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if dept and rec.get("dept") != dept:
                        continue
                    if ok_filter == "true" and not rec.get("ok"):
                        continue
                    if ok_filter == "false" and rec.get("ok"):
                        continue
                    results.append(rec)
    except Exception as e:
        log.warning(f"Traces query failed: {e}")

    return jsonify({"traces": results, "count": len(results)})


@app.route("/traces-stats", methods=["GET"])
def trace_stats_endpoint():
    """Aggregate stats from traces: calls per provider, avg latency, error rate."""
    from_ts = request.args.get("from", (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()[:10])
    to_ts = request.args.get("to", "")
    try:
        if not os.path.isdir(_TRACE_DIR):
            return jsonify({"error": "no traces directory"})

        stats = {"by_provider": {}, "by_dept": {}, "total_calls": 0, "total_errors": 0, "avg_latency_ms": 0}
        latencies = []
        files = sorted([f for f in os.listdir(_TRACE_DIR) if f.startswith("llm_") and f.endswith(".jsonl")])
        for fname in files:
            date_part = fname[4:14]
            if date_part < from_ts:
                continue
            if to_ts and date_part > to_ts:
                continue
            with open(os.path.join(_TRACE_DIR, fname), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    prov = rec.get("gen_ai.system", "unknown")
                    dept = rec.get("dept", "unknown")
                    lat = rec.get("latency_ms", 0)
                    is_ok = rec.get("ok", True)

                    stats["by_provider"].setdefault(prov, {"calls": 0, "errors": 0, "latency_ms": 0})
                    stats["by_provider"][prov]["calls"] += 1
                    if not is_ok:
                        stats["by_provider"][prov]["errors"] += 1
                        stats["total_errors"] += 1
                    else:
                        stats["by_provider"][prov]["latency_ms"] += lat
                        latencies.append(lat)

                    stats["by_dept"].setdefault(dept, {"calls": 0, "errors": 0})
                    stats["by_dept"][dept]["calls"] += 1
                    if not is_ok:
                        stats["by_dept"][dept]["errors"] += 1

                    stats["total_calls"] += 1

        if latencies:
            stats["avg_latency_ms"] = round(sum(latencies) / len(latencies))
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)})



# ── FO-008 шаг 4b: коллекторы новостей в пакете proxy/ ───────────────────────
from proxy.news import (
    RSS_FEEDS as RSS_FEEDS, GDELT_BASE as GDELT_BASE,
    DEPT_QUERIES as DEPT_QUERIES, DEPT_CATEGORIES as DEPT_CATEGORIES,
    collect_tavily as collect_tavily, enrich_news_with_fulltext as enrich_news_with_fulltext,
    collect_rss as collect_rss, collect_gdelt as collect_gdelt,
    collect_gdelt_themes as collect_gdelt_themes, _extract_keywords as _extract_keywords,
    get_fresh_news as get_fresh_news, get_night_news_digest as get_night_news_digest,
)



# ══════════════════════════════════════════════════════════════════════
#  WATCH SWEEP — daily sweep of WatchlistItem table
#  Checks all active items, updates lastCheckAt/nextCheckAt, detects deltas
#  Called by Render cron at 06:00 UTC = 09:00 MSK
# ══════════════════════════════════════════════════════════════════════

@app.post("/scheduler/watch-sweep")
def scheduler_watch_sweep():
    """Sweep all active WatchlistItems, check for deltas, update timestamps.
    For each item:
      1. Query news/LLM for recent changes on the topic
      2. Compare with lastDelta — if new information, increment deltaCount
      3. Update lastCheckAt, compute nextCheckAt from frequency
      4. If delta detected, send brief notification to owner
    """
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        return jsonify({"status": "error", "message": "OWNER_TELEGRAM_ID not set"}), 400

    try:
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Get all active watchlist items
        items = _query("""
            SELECT w.id, w.analysis_id, w.topic, w.frequency, w.last_delta, w.delta_count,
                   a.topic AS analysis_topic
            FROM watchlist_item w
            LEFT JOIN analysis a ON a.id = w.analysis_id
            WHERE w.active = 1
            ORDER BY w.next_check_at ASC
        """, fetch=True)

        if not items:
            return jsonify({"status": "ok", "swept": 0, "message": "no active watchlist items"})

        swept = 0
        deltas = 0
        notifications = []

        for item in items:
            wid, analysis_id, topic, frequency, last_delta, delta_count, analysis_topic = item

            # Query LLM for recent developments on this topic
            sweep_prompt = f"""Ты мониторинг-аналитик ОСП. Проверь тему на предмет новых событий за последние 24 часа.

Тема: {topic}
Контекст анализа: {analysis_topic or 'N/A'}
Предыдущий дельта: {last_delta or 'нет'}

Если есть новые существенные изменения (не шум, не повтор), опиши кратко (1-2 предложения).
Если изменений нет — ответь ровно одним словом: NO_DELTA"""

            llm_result = _call_llm_with_failover(sweep_prompt, 'osp')
            reply = llm_result.get('reply', '') if isinstance(llm_result, dict) else str(llm_result)
            new_delta = None if 'NO_DELTA' in reply.upper()[:50] else reply.strip()

            # Compute nextCheckAt based on frequency
            freq_days = {'DAILY': 1, 'WEEKLY': 7, 'BIWEEKLY': 14}.get(frequency, 1)
            next_check = (datetime.utcnow() + timedelta(days=freq_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

            if new_delta:
                # Delta detected
                new_count = (delta_count or 0) + 1
                _query("UPDATE watchlist_item SET last_check_at=?, next_check_at=?, last_delta=?, delta_count=? WHERE id=?",
                       (now_iso, next_check, new_delta[:500], new_count, wid))
                deltas += 1
                notifications.append(f"▸ {topic}: {new_delta[:150]}")
            else:
                # No delta — just update timestamps
                _query("UPDATE watchlist_item SET last_check_at=?, next_check_at=? WHERE id=?",
                       (now_iso, next_check, wid))

            swept += 1

        # Send consolidated notification if any deltas found
        if notifications:
            msg = "🔍 Watch Sweep — обнаружены дельты:\n\n" + "\n".join(notifications[:10])
            if len(notifications) > 10:
                msg += f"\n\n...и ещё {len(notifications) - 10}"
            _send_telegram_message(owner_id, msg)

        _log_audit('watch_sweep', {'swept': swept, 'deltas': deltas}, 'osp')
        log.info(f"Watch sweep: {swept} items, {deltas} deltas")
        return jsonify({"status": "ok", "swept": swept, "deltas": deltas})

    except Exception as e:
        log.error(f"watch_sweep error: {e}")
        _log_audit("watch_sweep_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  INDICATOR PRE-REMINDERS — 7-day pre-verification reminders
#  Finds indicators with verifyDate within N days, sends reminder to owner
#  Called by Render cron at 03:00 UTC = 06:00 MSK (before morning brief)
# ══════════════════════════════════════════════════════════════════════

@app.post("/scheduler/indicator-pre-reminders")
def scheduler_indicator_pre_reminders():
    """Find indicators with verifyDate within `days_ahead` days.
    Send a consolidated pre-reminder to owner with:
      - Indicator description + verifyDate
      - How many days until verification
      - What the indicator confirms
    Marks pre_verify_reminder_sent = 1 so we don't re-notify.
    """
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        return jsonify({"status": "error", "message": "OWNER_TELEGRAM_ID not set"}), 400

    d = request.get_json(force=True, silent=True) or {}
    days_ahead = int(d.get("days_ahead", 7))

    try:
        cutoff = (datetime.utcnow() + timedelta(days=days_ahead)).strftime("%Y-%m-%dT23:59:59Z")
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Find unverified indicators with verifyDate within N days that haven't been pre-reminded
        indicators = _query("""
            SELECT i.id, i.description, i.verify_date, i.is_binary, i.confirms_what,
                   i.pre_verify_reminder_sent, a.topic AS analysis_topic
            FROM indicator i
            LEFT JOIN analysis a ON a.id = i.analysis_id
            WHERE i.verified_at IS NULL
              AND i.verify_date <= ?
              AND i.verify_date >= ?
              AND i.pre_verify_reminder_sent = 0
            ORDER BY i.verify_date ASC
        """, (cutoff, now_iso), fetch=True)

        if not indicators:
            return jsonify({"status": "ok", "reminders": 0, "message": f"no indicators due within {days_ahead}d"})

        # Build reminder message
        lines = []
        for ind in indicators:
            iid, desc, vdate, is_binary, confirms, pre_sent, analysis_topic = ind
            # Compute days until verification
            try:
                verify_dt = datetime.strptime(vdate[:10], "%Y-%m-%d")
                days_left = (verify_dt - datetime.utcnow()).days
                days_str = f"{days_left}д" if days_left > 0 else "СЕГОДНЯ" if days_left == 0 else "ПРОСРОЧЕН"
            except Exception:
                days_str = "?"

            line = f"▸ {desc[:100]}\n  Верификация: {vdate[:10]} ({days_str})\n  Подтверждает: {confirms[:80]}"
            if analysis_topic:
                line += f"\n  Анализ: {analysis_topic[:60]}"
            lines.append(line)

            # Mark as pre-reminded
            _query("UPDATE indicator SET pre_verify_reminder_sent = 1 WHERE id = ?", (iid,))

        # Send consolidated message
        msg = f"⏰ I&W Пред-напоминания ({days_ahead}д до верификации):\n\n"
        msg += "\n\n".join(lines[:8])
        if len(lines) > 8:
            msg += f"\n\n...и ещё {len(lines) - 8} индикаторов"

        msg += "\n\n/osp verify <id> — верифицировать индикатор"

        _send_telegram_message(owner_id, msg)

        _log_audit('indicator_pre_reminders', {'count': len(indicators), 'days_ahead': days_ahead}, 'osp')
        log.info(f"Indicator pre-reminders: {len(indicators)} indicators within {days_ahead}d")
        return jsonify({"status": "ok", "reminders": len(indicators), "days_ahead": days_ahead})

    except Exception as e:
        log.error(f"indicator_pre_reminders error: {e}")
        _log_audit("indicator_pre_reminders_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  EXPERT CHART ENDPOINT
#  Called by mlog via http_post to generate PNG charts (residual value,
#  operation cost, TCO comparison) using scripts/expert_charts.py
# ══════════════════════════════════════════════════════════════════════

@app.post("/expert/chart")
def expert_chart():
    """Generate PNG chart for Expert automotive analysis.
    Expects JSON: {chart_type: "residual_value"|"operation_cost"|"comparison", data: {...}}
    Calls scripts/expert_charts.py to render the chart.
    """
    import subprocess
    d = request.get_json(force=True)
    chart_type = d.get("chart_type", "residual_value")
    chart_data = d.get("data", {})

    if not chart_data:
        return jsonify({"error": "data required"}), 400

    script_path = os.path.join(os.path.dirname(__file__), "scripts", "expert_charts.py")
    if not os.path.exists(script_path):
        # Fallback: try /home/z/my-project/scripts/expert_charts.py
        script_path = "/home/z/my-project/scripts/expert_charts.py"

    try:
        # Write data to temp file (avoid shell escaping issues with JSON)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
            json.dump(chart_data, tf, ensure_ascii=False)
            tmp_path = tf.name

        result = subprocess.run(
            [sys.executable, script_path, chart_type, tmp_path],
            capture_output=True, text=True, timeout=30
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            app.logger.error(f"Expert chart error: {result.stderr}")
            return jsonify({"error": "chart generation failed", "detail": result.stderr[:500]}), 500

        chart_result = json.loads(result.stdout)
        return jsonify(chart_result)

    except subprocess.TimeoutExpired:
        return jsonify({"error": "chart generation timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# call_python — universal mlog->Python bridge (Variant B)
# Whitelisted modules only. No arbitrary code execution.
# ============================================================
CALL_PYTHON_ALLOWED = {
    # LLM-as-a-Verifier
    "llm_verifier": {"select", "score", "verify", "rank"},
    # Data processing
    "json": {"dumps", "loads"},
    "statistics": {"mean", "median", "stdev", "variance"},
    "math": {"ceil", "floor", "log", "log10", "sqrt", "exp", "pow", "factorial", "gcd", "comb", "perm"},
    "datetime": {"datetime", "timedelta", "timezone"},
    # Text
    "re": {"match", "search", "findall", "sub", "split"},
    "difflib": {"SequenceMatcher", "get_close_matches"},
    # File
    "csv": {"reader", "writer", "DictReader", "DictWriter"},
    # Finance/math
    "decimal": {"Decimal"},
    "fractions": {"Fraction"},
}

@app.post("/call-python")
def call_python_endpoint():
    """Universal Python bridge for mlog. Executes module.function(args) with strict whitelist.
    Body: {"module": "statistics", "function": "mean", "args": [[1,2,3,4,5]], "kwargs": {}, "dept": "dev"}
    Returns: {"result": <value>, "type": <python type name>}
    FO-015 Guardian: второй контур — право py_<module>_<function> проверяется матрицей
    до исполнения (deny/ask гасят вызов независимо от whitelist-уровня).
    """
    d = request.get_json(force=True) or {}
    module_name = d.get('module', '')
    func_name = d.get('function', '')
    args = d.get('args', [])
    kwargs = d.get('kwargs', {})
    dept = d.get('dept', 'system')

    # FO-015: Guardian permission-matrix (второй контур)
    try:
        from proxy.guardian import enforce, GuardianDenied, shell_permission
        permission = f"py_{module_name}_{func_name}"
        if module_name == "os" and func_name == "system":
            permission = shell_permission(str(args[0]) if args else "shell_empty")
        enforce(dept, permission, chat_id=d.get('chat_id'))
    except GuardianDenied as gd:
        _log_audit("call_python_guardian_denied", {"module": module_name, "function": func_name, "dept": dept, "reason": str(gd)[:200]}, dept)
        return jsonify({"error": str(gd)}), 403
    except Exception as e:
        log.warning(f"[guardian] check failed, fail-open per default_action: {e}")

    # Security: whitelist check
    if module_name not in CALL_PYTHON_ALLOWED:
        _log_audit("call_python_blocked", {"module": module_name, "function": func_name}, "system")
        return jsonify({"error": f"Module '{module_name}' not allowed. Allowed: {list(CALL_PYTHON_ALLOWED.keys())}"}), 403

    allowed_funcs = CALL_PYTHON_ALLOWED[module_name]
    if func_name not in allowed_funcs:
        _log_audit("call_python_blocked", {"module": module_name, "function": func_name}, "system")
        return jsonify({"error": f"Function '{func_name}' not allowed in '{module_name}'. Allowed: {list(allowed_funcs)}"}), 403

    try:
        import importlib
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
        result = func(*args, **kwargs)
        _log_audit("call_python", {"module": module_name, "function": func_name}, "system")
        # Serialize result
        if isinstance(result, (list, dict, str, int, float, bool, type(None))):
            serialized = result
        elif isinstance(result, tuple):
            serialized = list(result)
        elif hasattr(result, '__dict__'):
            serialized = str(result)
        else:
            serialized = str(result)
        return jsonify({"result": serialized, "type": type(result).__name__})
    except Exception as e:
        _log_audit("call_python_error", {"module": module_name, "function": func_name, "error": str(e)[:200]}, "system")
        return jsonify({"error": str(e)[:500]}), 500


# ═══════════════════════════════════════════════════════════════════════════
# FO-025: shadow-оценка моделей — недельный отчёт из trace_log
# ═══════════════════════════════════════════════════════════════════════════
@app.get("/api/shadow/report")
def api_shadow_report():
    """Недельный отчёт shadow-канарейки: win-rate, дельта-качество,
    дельта-цена/латентность по департаментам; рекомендация владельцу
    Go/No-Go на изменение GetModelFallbackChain. Источник — парные
    trace-записи (event='shadow', одинаковый pair_id)."""
    try:
        from proxy.core import _TRACE_DIR
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        pairs = {}
        trace_dir = Path(_TRACE_DIR)
        if trace_dir.exists():
            for tf in sorted(trace_dir.glob("llm_*.jsonl")):
                try:
                    for line in tf.read_text(encoding="utf-8", errors="replace").splitlines():
                        if '"event": "shadow"' not in line and '"event":"shadow"' not in line:
                            continue
                        rec = json.loads(line)
                        if rec.get("event") != "shadow" or rec.get("ts", "") < cutoff:
                            continue
                        pid = rec.get("pair_id")
                        if pid:
                            pairs.setdefault(pid, {})[rec.get("side")] = rec
                except (json.JSONDecodeError, ValueError):
                    continue

        by_dept = {}
        for p in pairs.values():
            main = p.get("main")
            sh = p.get("shadow")
            if not main or not sh:
                continue
            d = by_dept.setdefault(main.get("dept", "?"), {
                "pairs": 0, "wins": 0, "losses": 0, "ties": 0,
                "delta_quality": 0.0, "delta_cost": 0.0, "delta_latency_ms": 0.0,
                "candidate": sh.get("gen_ai.request.model", "?"),
                "scored": 0,
            })
            d["pairs"] += 1
            ms, ss = main.get("verifier_score"), sh.get("verifier_score")
            if ms is not None and ss is not None:
                d["scored"] += 1
                delta = ss - ms
                d["delta_quality"] += delta
                if delta > 0.05:
                    d["wins"] += 1
                elif delta < -0.05:
                    d["losses"] += 1
                else:
                    d["ties"] += 1
            d["delta_cost"] += (sh.get("cost_usd", 0) or 0)
            d["delta_latency_ms"] += ((sh.get("latency_ms") or 0) - (main.get("latency_ms") or 0))

        depts = []
        for dept, d in sorted(by_dept.items()):
            scored = d["scored"]
            win_rate = round(d["wins"] / scored, 3) if scored else None
            avg_dq = round(d["delta_quality"] / scored, 4) if scored else None
            entry = {
                "dept": dept,
                "candidate_model": d["candidate"],
                "pairs": d["pairs"],
                "scored_pairs": scored,
                "win_rate": win_rate,
                "avg_delta_quality": avg_dq,
                "avg_delta_cost_usd": round(d["delta_cost"] / d["pairs"], 6) if d["pairs"] else None,
                "avg_delta_latency_ms": round(d["delta_latency_ms"] / d["pairs"]) if d["pairs"] else None,
            }
            # Рекомендация: кандидата имеет смысл ставить в цепь, если он
            # чаще выигрывает у основной модели и не дороже заметно.
            if scored and win_rate is not None and avg_dq is not None:
                if win_rate >= 0.6 and avg_dq >= 0:
                    entry["recommendation"] = "GO"
                elif win_rate <= 0.35 or avg_dq <= -0.1:
                    entry["recommendation"] = "NO-GO"
                else:
                    entry["recommendation"] = "KEEP-TESTING"
            else:
                entry["recommendation"] = "KEEP-TESTING"
            depts.append(entry)

        return jsonify({"status": "ok", "window_days": 7,
                        "total_pairs": len(pairs), "depts": depts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
