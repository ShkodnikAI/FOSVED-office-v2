#!/usr/bin/env python3
"""llm_proxy.py — Fosved Office v2 LLM Proxy Server
Flask server on port 4000 with native circuit breaker, combo chains, token compression,
7-provider direct failover, dept routing, dashboards, SQLite,
TTS/STT, archive, scheduler, learning, audit, and search endpoints."""

import sys, json, os, re, sqlite3, subprocess, threading, time, logging, hashlib, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import doc_extract
import html as html_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import secrets_crypto

# ── FO-008: стренглер-фасад (шаг 1) ──────────────────────────────────────────
# Ядро и провайдеры вынесены в пакет proxy/ (вербатим, поведение 1-в-1).
# llm_proxy.py остаётся точкой сборки/entrypoint: здесь регистрируются роуты,
# отсюда tests и mlog-вызовы берут все имена (ре-экспорт ниже).
from flask import Flask, request, jsonify, Response  # noqa: F401

from proxy.core import (
    # app & auth
    app, auth_middleware, _check_bearer, _verify_webhook_secret,
    _verify_init_data, require_telegram, _TG_BOOTSTRAP_PAGE, PROTECTED_PREFIXES,
    # config & env
    PORT, DB_PATH, DB_FILE, BASE_DIR, LIB_DIR, CFG_DIR, db_lock,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ARCHIVE_CHANNEL_ID,
    WHISPER_API_KEY, WHISPER_PROVIDER, API_SECRET, WEBHOOK_SECRET,
    # secrets & integrations
    get_secret, set_secret, delete_secret, _has_db_override, INTEGRATIONS_REGISTRY,
    # sqlite & журналы (audit/error)
    _db, init_db, _query, _get_setting, _log_audit, _log_error, _rotate_service_logs,
    _LOG_RETENTION_DAYS, _TRACE_LOG_RETENTION_DAYS, _ERROR_DEDUP_SECONDS,
    # трейсы LLM (FO-004)
    _TRACE_DIR, _TRACE_MAX_BYTES, _TRACE_RETENTION, _write_llm_trace, _prune_old_traces,
    # память и логгеры
    memory, log_mem, log,
    # HTTP-клиент (единый requests)
    http_requests,
    # словарь департаментов
    DEPT_COLORS, DEPT_NAMES, DEPT_HASHTAGS,
)

from proxy.providers import (
    PROVIDERS, TOKEN_COSTS, PROVIDER_MAX_TOKENS, COMBO_CHAINS,
    _TASK_COMBO_MAP, _FREE_DEPTS, CircuitBreaker, _breaker, _combo_for_task,
    _COMPRESSION_MAX_TOKENS, _COMPRESSION_KEEP_SYSTEM,
    _estimate_tokens, _compress_messages, _call_single_provider, call_llm,
    _cfg_cache, _load_cfg,
    _ZAI_CONFIG_PATHS, _ZAI_CONFIG, _load_zai_config, _zai_headers,
    _generate_image, _IMG_DIR, _ALLOWED_SIZES,
)




# ── FO-008 шаг 3: HTML-билдеры отчётов в пакете proxy/ ───────────────────────
from proxy.reports import (
    html_lib_escape, strip_html_for_archive, _html_base, _dept_header,
    _status_icon, _dept_kpis, _build_action_bar, ARCHIVE_MONTHS_RU,
    _browse_page, _evidence_badges_css,
)



# ── FO-008 шаг 2: Telegram-адаптер и голосовые эндпоинты в пакете proxy/ ─────
from proxy.telegram import (
    _MARKER_EMOJI, _ALL_EMOJI, _escape_mdv2, _tg_send_formatted,
    _tg_send_message, _tg_send_voice, _tg_send_report_with_button,
    _tg_get_file, _tg_download_file, _tg_send_photo, _tg_send_document,
    _safe_filename_part,
)
from proxy import voice as _proxy_voice  # noqa: F401 — регистрация роутов /tts /stt
from proxy.voice import _clean_text_for_tts  # noqa: F401 — ре-экспорт



# ── FO-008 шаг 4a: транспорт ч.1 + dept-блок/обогащение в proxy/ ─────────────
from proxy.core import (
    auto_enrich as auto_enrich, _has_enricher as _has_enricher,
    _auto_enrich_fn as _auto_enrich_fn,
    detect_dept as detect_dept, get_dept_prompt as get_dept_prompt,
    CONDENSED_PROMPTS as CONDENSED_PROMPTS, FORMAT_INSTRUCTION as FORMAT_INSTRUCTION,
    COMMAND_DEPT as COMMAND_DEPT, RUSSIAN_KEYWORDS as RUSSIAN_KEYWORDS,
    KEYWORD_WEIGHTS as KEYWORD_WEIGHTS, _ANALYTICAL_DEPTS as _ANALYTICAL_DEPTS,
)
import proxy.routes_core  # noqa: F401 — регистрация роутов health..extract-document
from proxy.telegram import (
    _send_chat_action_loop as _send_chat_action_loop,
    _tg_send_chat_action as _tg_send_chat_action,
)

# ──────────────────────────── OSINT (Aliens Eye) ────────────────────────────
OSINT_DISCLAIMER = "⚠ OSINT-данные собраны из открытых источников. Результаты не гарантируют принадлежность аккаунтов конкретному лицу. Используйте для легитимных целей в рамках законодательства."
_osint_last_time = {}  # rate limiting: chat_id -> timestamp
OSINT_RATE_LIMIT = 60  # seconds between scans

def categorize_platform(site_name):
    """Категоризация платформы по типу."""
    categories = {
        'social': ['twitter', 'facebook', 'instagram', 'tiktok', 'snapchat', 'threads', 'mastodon', 'bluesky', 'x.com'],
        'professional': ['linkedin', 'xing', 'angellist', 'crunchbase'],
        'tech': ['github', 'gitlab', 'bitbucket', 'stackoverflow', 'hackernews', 'dev.to', 'codepen'],
        'media': ['youtube', 'twitch', 'vimeo', 'soundcloud', 'spotify', 'medium', 'substack'],
        'messaging': ['telegram', 'discord', 'slack', 'signal', 'whatsapp'],
        'commerce': ['amazon', 'ebay', 'etsy', 'shopify', 'aliexpress'],
        'gaming': ['steam', 'xbox', 'playstation', 'epic', 'roblox', 'minecraft'],
        'forum': ['reddit', 'quora', '4chan', 'hackforums'],
        'dating': ['tinder', 'bumble', 'okcupid'],
        'darknet': ['onion', 'tor', 'i2p'],
    }
    site_lower = site_name.lower()
    for category, platforms in categories.items():
        if any(p in site_lower for p in platforms):
            return category
    return 'other'


def scan_osint(username, level='basic', timeout=120, tor=False, sites=None):
    """Scan username across 840+ platforms via Aliens Eye."""
    cmd = ['aliens_eye', username, '--format', 'json', '--plain', '-l', level]
    if tor:
        cmd.extend(['--tor'])
    if sites:
        cmd.extend(['--site', ','.join(sites)])
    cmd.extend(['--no-nsfw'])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, 'NO_COLOR': '1'}
        )
        if result.returncode != 0:
            return {'error': f'Aliens Eye exited with code {result.returncode}', 'stderr': result.stderr[:500]}

        data = json.loads(result.stdout)
        results_list = data.get('results', [])
        found = [p for p in results_list if p.get('status') == 'Found']
        maybe = [p for p in results_list if p.get('status') == 'Maybe']

        return {
            'username': username,
            'found': len(found),
            'maybe': len(maybe),
            'total_scanned': len(results_list),
            'scan_time': data.get('elapsed', '?'),
            'platforms': [{
                'name': p.get('site', ''),
                'url': p.get('url', ''),
                'confidence': p.get('confidence', 0),
                'category': categorize_platform(p.get('site', ''))
            } for p in found],
            'uncertain': [{
                'name': p.get('site', ''),
                'url': p.get('url', ''),
                'confidence': p.get('confidence', 0)
            } for p in maybe],
        }
    except subprocess.TimeoutExpired:
        return {'error': f'Timeout after {timeout}s', 'username': username}
    except json.JSONDecodeError:
        return {'error': 'Failed to parse Aliens Eye output', 'raw': result.stdout[:500]}
    except FileNotFoundError:
        return {'error': 'aliens_eye binary not found. Install: pip3 install aliens-eye'}
    except Exception as e:
        return {'error': str(e)}





# ──────────────────────────── MEMORIZE HELPER ────────────────────────────
def _memorize(dept, topic, content):
    """Save a finding to dialog_history as a system memorization entry."""
    now = datetime.utcnow().isoformat()
    entry = f"[MEMORY] {topic}: {content}"
    _query("INSERT INTO dialog_history (dept, chat_id, role, content, created_at) VALUES (?, '0', 'system', ?, ?)",
           (dept, entry, now))




# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: ARCHIVE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.post("/archive/publish")
def archive_publish():
    """Publish a document to the Telegram archive channel."""
    d = request.get_json(force=True)
    doc_id = d.get("doc_id", "")
    dept = d.get("dept", "")
    title = d.get("title", "")
    content = d.get("content", "")

    if not content:
        return jsonify({"status": "error", "message": "content is required"}), 400
    if not TELEGRAM_ARCHIVE_CHANNEL_ID:
        return jsonify({"status": "error", "message": "TELEGRAM_ARCHIVE_CHANNEL_ID not set"}), 500

    try:
        # Compact archive record: date, dept, description, link + .html attachment
        plain = strip_html_for_archive(content)
        summary = " ".join(plain.split())[:200]
        if len(" ".join(plain.split())) > 200:
            summary = summary + "..."

        day = datetime.utcnow().strftime("%Y-%m-%d")
        hashtags = DEPT_HASHTAGS.get(dept, "")
        link = f"{RENDER_URL}/miniapp/{doc_id}" if doc_id else ""

        lines = [f"{day} | {dept}"]
        if title:
            lines.append(title[:150])
        if summary:
            lines.append("")
            lines.append(summary)
        if link:
            lines.append("")
            lines.append(f"Открыть: {link}")
        if hashtags:
            lines.append("")
            lines.append(hashtags)
        record = "\n".join(lines)[:1024]

        # Attach the stored HTML as a document (archive stays readable without our service)
        msg_id = None
        archive_format = _get_setting("archive_format") or "compact"
        html_doc = ""
        if doc_id and archive_format == "compact":
            rows = _query("SELECT html FROM miniapp_responses WHERE id = ?", (doc_id,), fetch=True)
            if rows:
                html_doc = rows[0]["html"] or ""

        if html_doc:
            fname = f"{day}_{_safe_filename_part(dept, 20)}_{_safe_filename_part(title)}.html"
            fpath = os.path.join("/tmp", fname)
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(html_doc)
                msg_id = _tg_send_document(TELEGRAM_ARCHIVE_CHANNEL_ID, fpath, record)
            finally:
                try:
                    os.remove(fpath)
                except Exception as e:
                    log.warning(f"[cleanup] temp report remove failed: {e}")

        # Fallback: no HTML stored, or document upload failed
        if not msg_id:
            msg_id = _tg_send_message(TELEGRAM_ARCHIVE_CHANNEL_ID, record)

        # Record in channel_archive table
        now = datetime.utcnow().isoformat()
        _query("INSERT INTO channel_archive (doc_id, dept, title, channel_message_id, archived_at) VALUES (?,?,?,?,?)",
               (doc_id, dept, title, str(msg_id) if msg_id else "", now))

        _log_audit("archive_publish", {"doc_id": doc_id, "dept": dept, "title": title, "msg_id": msg_id, "chars": len(record)})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"archive_publish error: {e}")
        _log_audit("archive_publish_error", {"error": str(e)[:500], "doc_id": doc_id})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/archive/daily-digest")
def archive_daily_digest():
    """Collect today's stats and send a digest to the archive channel."""
    try:
        if not TELEGRAM_ARCHIVE_CHANNEL_ID:
            return jsonify({"status": "error", "message": "TELEGRAM_ARCHIVE_CHANNEL_ID not set"}), 500

        now = datetime.utcnow()
        today = now.isoformat()[:10]
        today_start = today + "T00:00:00"

        # Collect today's stats
        tasks_rows = _query("SELECT dept, COUNT(*) as c FROM dialog_history WHERE created_at>=? AND role='user' GROUP BY dept", (today_start,), fetch=True)
        reports_rows = _query("SELECT dept, COUNT(*) as c FROM miniapp_responses WHERE created_at>=? GROUP BY dept", (today_start,), fetch=True)
        corrections_rows = _query("SELECT dept, COUNT(*) as c FROM adapt_corrections WHERE created_at>=? GROUP BY dept", (today_start,), fetch=True)

        # Build digest text
        lines = []
        lines.append(f"DAILY DIGEST - {today}")
        lines.append("=" * 40)
        lines.append("")

        # Task breakdown
        total_tasks = sum(r["c"] for r in tasks_rows)
        lines.append(f"TASKS: {total_tasks} total")
        for r in sorted(tasks_rows, key=lambda x: -x["c"]):
            dept_name = DEPT_NAMES.get(r["dept"], r["dept"])
            lines.append(f"  {dept_name}: {r['c']}")
        lines.append("")

        # Reports
        total_reports = sum(r["c"] for r in reports_rows)
        lines.append(f"REPORTS: {total_reports} total")
        for r in sorted(reports_rows, key=lambda x: -x["c"]):
            dept_name = DEPT_NAMES.get(r["dept"], r["dept"])
            lines.append(f"  {dept_name}: {r['c']}")
        lines.append("")

        # Corrections
        total_corrections = sum(r["c"] for r in corrections_rows)
        lines.append(f"CORRECTIONS: {total_corrections} total")
        for r in sorted(corrections_rows, key=lambda x: -x["c"]):
            dept_name = DEPT_NAMES.get(r["dept"], r["dept"])
            lines.append(f"  {dept_name}: {r['c']}")

        digest_text = "\n".join(lines)

        msg_id = _tg_send_message(TELEGRAM_ARCHIVE_CHANNEL_ID, digest_text)
        _log_audit("archive_daily_digest", {"date": today, "tasks": total_tasks, "reports": total_reports, "corrections": total_corrections, "msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"archive_daily_digest error: {e}")
        _log_audit("archive_daily_digest_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: SCHEDULER ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

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

@app.post("/scheduler/morning-brief")
def scheduler_morning_brief():
    """
    Generate and send a morning brief to the owner.
    Яна делает отчёт в 7:20: дата, время, прогноз погоды, как работает офис, важные мировые события.
    """
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    # BRIEF-1: dedup — избегаем двойной отправки при повторном вызове эндпоинта
    recent = _query(
        "SELECT COUNT(*) as c FROM audit_log WHERE action='scheduler_morning_brief' "
        "AND status='ok' AND timestamp > datetime('now', '-10 minutes')",
        fetch=True
    )
    if recent and recent[0]["c"] > 0:
        return jsonify({"status": "skipped", "message": "brief already sent within last 10 minutes"}), 200

    # BRIEF-1 доп.: отдельный Render Cron Job 'lz-daily' ненадёжно подхватывает
    # свежий код (подтверждено — ручной вызов на основном сервисе работает,
    # плановый cron неделями не создавал новых записей). Раз утренний бриф
    # уже надёжно срабатывает каждый день на этом же сервисе — используем
    # его как единственную точку триггера, не полагаясь на отдельный cron.
    try:
        scheduler_lz_daily_core(dry_run=False, owner_id=owner_id)
    except Exception as e:
        log.warning(f"lz-daily scan inside morning-brief failed (non-fatal): {e}")

    try:
        now = datetime.utcnow()
        # Minsk time for display (UTC+3 year-round)
        from datetime import timezone, timedelta as _td
        msk = timezone(_td(hours=3))
        now_msk = datetime.now(msk)
        date_str = now_msk.strftime("%d.%m.%Y")
        time_str = now_msk.strftime("%H:%M")
        weekday = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"][now_msk.weekday()]

        # ── 1. Weather (wttr.in — free, no API key) ──
        weather_text = ""
        try:
            weather_resp = http_requests.get("https://wttr.in/Minsk?format=%C+%t+%w+%h+%P&lang=ru", timeout=10)
            if weather_resp.ok:
                weather_text = weather_resp.text.strip()
            else:
                weather_text = "Погода недоступна"
        except Exception:
            weather_text = "Не удалось получить прогноз погоды"

        # Extended forecast
        weather_ext = ""
        try:
            weather_ext_resp = http_requests.get("https://wttr.in/Minsk?format=3&lang=ru", timeout=10)
            if weather_ext_resp.ok:
                weather_ext = weather_ext_resp.text.strip()
        except Exception as e:
            _log_error(f"weather fetch failed: {e}", source="morning_brief", dept="yana", kind="external")

        # ── 2. Office metrics ──
        yesterday = (now - timedelta(days=1)).isoformat()[:10] + "T00:00:00"
        today = now.isoformat()[:10] + "T00:00:00"
        metrics = _collect_metrics_for_period(yesterday, today)
        metrics_text = _format_metrics_text(metrics)

        # Dialog count (24h)
        dialog_rows = _query("SELECT COUNT(*) as cnt FROM dialog_history WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        dialog_24h = dialog_rows[0]["cnt"] if dialog_rows else 0

        # Active departments (24h)
        dept_rows = _query("SELECT DISTINCT dept FROM dialog_history WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        active_depts = [r["dept"] for r in dept_rows] if dept_rows else []

        # Pending narads
        narad_rows = _query("SELECT COUNT(*) as cnt FROM narads WHERE status = 'pending'", fetch=True)
        narads_pending = narad_rows[0]["cnt"] if narad_rows else 0

        # Recent corrections
        corr_rows = _query("SELECT COUNT(*) as cnt FROM adapt_corrections WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        corrections_24h = corr_rows[0]["cnt"] if corr_rows else 0

        # FO-007: повторяющиеся ошибки департаментов за сутки — в дайджест
        errors_digest = ""
        try:
            err_rows = _query(
                "SELECT dept, kind, COUNT(*) as c FROM error_log "
                "WHERE ts > datetime('now', '-1 day') AND kind != 'external' "
                "GROUP BY dept, kind HAVING c >= 3 ORDER BY c DESC LIMIT 5", fetch=True)
            ext_rows = _query(
                "SELECT COUNT(*) as c FROM error_log "
                "WHERE ts > datetime('now', '-1 day') AND kind = 'external'", fetch=True)
            if err_rows:
                errors_digest = "\n".join(
                    [f"  - {r['dept']}/{r['kind']}: {r['c']} раз(а) за сутки" for r in err_rows])
                if ext_rows and ext_rows[0]["c"]:
                    errors_digest += f"\n  - внешние сбои (api/сеть): {ext_rows[0]['c']} раз(а) за сутки"
        except Exception as e:
            log.warning(f"[morning_brief] error digest query failed: {e}")

        # ── 3. LZ daily findings (from memory) ──
        lz_findings = ""
        try:
            lz_mem = memory.recall("LZ Daily", type_filter="observation", limit=3)
            if lz_mem:
                lz_findings = "\n".join([f"  - {f['content'][:120]}" for f in lz_mem])
        except Exception as e:
            _log_error(f"LZ memory recall failed: {e}", source="morning_brief", dept="yana", kind="memory")

        # ── 4. Night news (with explicit empty marker) ──
        night_news = get_night_news_digest()
        if not night_news:
            night_news = "\n📰 Топ события за ночь: НЕТ ДАННЫХ (сборщик новостей не вернул результатов)\n"

        # ── 5. Build prompt ──
        dept_prompt = get_dept_prompt("yana")
        user_prompt = f"""Составь утренний отчёт для хозяина офиса.

Дата: {date_str} ({weekday})
Время: {time_str} (Минск)

=== ПОГОДА (Минск) ===
{weather_text}
{weather_ext}

=== КАК РАБОТАЕТ ОФИС (последние 24ч) ===
Диалогов: {dialog_24h}
Активные отделы: {', '.join(active_depts) if active_depts else 'нет активности'}
Нерешённых нарядов: {narads_pending}
Коррекций за сутки: {corrections_24h}
{metrics_text}

=== ПОВТОРЯЮЩИЕСЯ ОШИБКИ ОФИСА ЗА СУТКИ ===
{errors_digest if errors_digest else 'Нет'}

=== НАХОДКИ ЛАБОРАТОРИИ ЗНАНИЙ ===
{lz_findings if lz_findings else 'За последние сутки нет новых находок'}

{night_news}

=== ТВОЯ ЗАДАЧА ===
Напиши утренний отчёт на русском. Структура:
1. 📅 Дата, время, день недели
2. 🌤 Прогноз погоды в Минске
3. 🏢 Статус офиса — кратко, что происходит
4. 🌍 Важные мировые события — ТОЛЬКО из раздела «Топ события за ночь» ниже, если он есть. Если раздела нет или он пуст — напиши буквально «За ночь значимых событий не зафиксировано» и не добавляй ничего от себя. ЗАПРЕЩЕНО придумывать события, даже правдоподобные.
5. 🔍 Ключевые находки ЛЗ (если есть)
6. ⚡ Что требует внимания хозяина (включая повторяющиеся ошибки офиса, если раздел непуст)

ФОРМАТИРОВАНИЕ (Telegram MarkdownV2):
▸ Заголовки секций: *Жирный текст*
▸ Ключевые цифры и термины: *выделить жирным*
▸ Подчёркивания важных пунктов: __подчёркнуто__
▸ Статусы: ✅ зелёный, ⚠️ жёлтый, ❌ красный
▸ НЕ используй кавычки " " или « » — они озвучиваются TTS
▸ Эмодзи только как маркеры секций (📅🌤🏢🌍🔍⚡), не ставь эмодзи в середине предложений
▸ НЕ ставь # заголовки — Telegram их не рендерит

Будь лаконичной но информативной. 7-12 предложений максимум."""

        messages = [
            {"role": "system", "content": dept_prompt + "\n\nТы — Яна, управляющая офисом. Ты составляешь утренний отчёт для хозяина. Отчёт должен быть информативным, структурированным, на русском языке. Упоминай находки Лаборатории Знаний если они есть. Форматирование: *жирный* для заголовков и ключевых слов, __подчёркнуто__ для важных пунктов, эмодзи только как маркеры секций. НЕ используй кавычки."},
            {"role": "user", "content": user_prompt},
        ]

        result = call_llm("yana", messages)
        brief = result["reply"]

        msg_id = _tg_send_formatted(owner_id, brief, dept="yana")
        _log_audit("scheduler_morning_brief", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "brief": brief, "msg_id": msg_id})

    except Exception as e:
        log.error(f"morning_brief error: {e}")
        _log_audit("scheduler_morning_brief_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/admin-morning-reply")
def scheduler_admin_morning_reply():
    """
    Админ делает свой ответ на утренний отчёт Яны (7:25).
    Анализирует отчёт Яны, добавляет своё видение, приоритеты, замечания.
    """
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        # ── 1. Get Yana's last morning brief from dialog_history ──
        yana_rows = _query(
            "SELECT content, created_at FROM dialog_history WHERE dept='yana' AND role='assistant' "
            "AND created_at > datetime('now', '-2 hours') ORDER BY id DESC LIMIT 1",
            fetch=True
        )
        yana_brief = yana_rows[0]["content"] if yana_rows else ""

        if not yana_brief:
            # Fallback: just send a status
            msg_id = _tg_send_message(owner_id, "⏰ Утренний ответ Админа: не найден свежий отчёт Яны для комментирования.")
            return jsonify({"status": "ok", "msg_id": msg_id, "note": "no_yana_brief"})

        # ── 2. Get admin prompt ──
        admin_prompt = get_dept_prompt("admin")

        # ── 3. Get LZ daily findings for admin context ──
        lz_context = ""
        try:
            lz_mem = memory.recall("LZ Daily", type_filter="observation", limit=5)
            if lz_mem:
                lz_context = "\n".join([f"  - {f['content'][:200]}" for f in lz_mem])
        except Exception as e:
            _log_error(f"LZ memory recall failed: {e}", source="admin_brief", dept="admin", kind="memory")

        # ── 4. Get pending issues ──
        issues_context = ""
        try:
            narad_rows = _query("SELECT COUNT(*) as cnt FROM narads WHERE status = 'pending'", fetch=True)
            if narad_rows:
                issues_context = f"Нерешённых нарядов: {narad_rows[0]['cnt']}"
        except Exception as e:
            _log_error(f"narads count query failed: {e}", source="admin_brief", dept="admin", kind="db_read")

        # ── 5. Build admin prompt ──
        messages = [
            {"role": "system", "content": admin_prompt + "\n\nТы — Админ Фосвед Офиса. Ты прочитал утренний отчёт Яны и должен дать свой ответ. Твой ответ — это директива на день. Упомяни находки Лаборатории Знаний, если они релевантны. Форматирование: *жирный* для приоритетов и ключевых слов, __подчёркнуто__ для указаний, эмодзи только как маркеры секций. НЕ используй кавычки."},
            {"role": "user", "content": f"""Яна прислала утренний отчёт:

{yana_brief}

{f"=== НАХОДКИ ЛЗ ===\n{lz_context}" if lz_context else ""}
{f"=== СТАТУС ===\n{issues_context}" if issues_context else ""}

Твоя задача: напиши краткий ответ на отчёт Яны на русском. Структура:
1. 📌 Приоритеты на сегодня — 2-3 главных задачи
2. 💬 Замечания по отчёту Яны (если есть)
3. 🔧 Указания отделам
4. 🔍 Что из находок ЛЗ стоит изучить и применить

ФОРМАТИРОВАНИЕ (Telegram MarkdownV2):
▸ Заголовки: *Жирный текст*
▸ Приоритеты и указания: __подчёркнуто__
▸ Статусы: ✅ ⚠️ ❌
▸ НЕ используй кавычки — они озвучиваются TTS
▸ Эмодзи только как маркеры секций (📌💬🔧🔍), не в середине предложений

Будь кратким, по-деловому. 5-8 предложений."""},
        ]

        result = call_llm("admin", messages)
        reply = result["reply"]

        msg_id = _tg_send_formatted(owner_id, reply, dept="admin")
        _log_audit("scheduler_admin_morning_reply", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "reply": reply, "msg_id": msg_id})

    except Exception as e:
        log.error(f"admin_morning_reply error: {e}")
        _log_audit("scheduler_admin_morning_reply_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/evening-summary")
def scheduler_evening_summary():
    """Generate and send an evening summary, plus publish daily digest to archive."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10] + "T00:00:00"

        metrics = _collect_metrics_for_period(today)
        metrics_text = _format_metrics_text(metrics)

        dept_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are generating an evening summary for the office owner. Review the day's performance, highlight achievements and issues. Format in Russian."},
            {"role": "user", "content": f"Sformirui vechernii itog za segodnyashnii den'.\n\n{metrics_text}\n\nOzhidai: korotkii itog na 5-8 punktov s rekomendatsiyami."},
        ]

        result = call_llm("yana", messages)
        summary = result["reply"]

        # Send to owner
        msg_id = _tg_send_message(owner_id, summary)

        # Publish daily digest to archive channel
        if TELEGRAM_ARCHIVE_CHANNEL_ID:
            tasks_total = sum(metrics["tasks"].values())
            reports_total = sum(metrics["reports"].values())
            corrections_total = sum(metrics["corrections"].values())
            digest_lines = [
                f"DAILY DIGEST - {now.isoformat()[:10]}",
                "=" * 40,
                f"Tasks: {tasks_total}",
                f"Reports: {reports_total}",
                f"Corrections: {corrections_total}",
            ]
            digest_text = "\n".join(digest_lines)
            _tg_send_message(TELEGRAM_ARCHIVE_CHANNEL_ID, digest_text)

        _log_audit("scheduler_evening_summary", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"evening_summary error: {e}")
        _log_audit("scheduler_evening_summary_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/weekly-digest")
def scheduler_weekly_digest():
    """Generate a weekly digest per department and send via Telegram."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        metrics = _collect_metrics_for_period(week_ago)
        metrics_text = _format_metrics_text(metrics)

        dept_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are generating a weekly digest for the office owner. Summarize per-department performance, trends, and recommendations. Format in Russian."},
            {"role": "user", "content": f"Sformirui ezhenedelnyi digest za proshlou nedelyu.\n\n{metrics_text}\n\nOzhidai: detalnyi digest po departamentam s rekomendatsiyami."},
        ]

        result = call_llm("yana", messages)
        digest = result["reply"]

        # Send via SendReport (if > 800 chars, use Mini App button)
        if len(digest) > 800:
            msg_id = _tg_send_report_with_button(owner_id, digest)
        else:
            msg_id = _tg_send_message(owner_id, digest)

        _log_audit("scheduler_weekly_digest", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id, "chars": len(digest)})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"weekly_digest error: {e}")
        _log_audit("scheduler_weekly_digest_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/monthly-review")
def scheduler_monthly_review():
    """Generate a monthly review per department."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        month_ago = (now - timedelta(days=30)).isoformat()

        metrics = _collect_metrics_for_period(month_ago)
        metrics_text = _format_metrics_text(metrics)

        dept_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are generating a monthly review for the office owner. Analyze per-department performance: tasks completed, average ratings, correction frequency. Identify trends and action items. Format in Russian."},
            {"role": "user", "content": f"Sformirui ezhemesyachnyi obzor za proshlyi mesyats.\n\n{metrics_text}\n\nOzhidai: analiz po departamentam s planom deistvii."},
        ]

        result = call_llm("yana", messages)
        review = result["reply"]

        msg_id = _tg_send_report_with_button(owner_id, review)

        _log_audit("scheduler_monthly_review", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "msg_id": msg_id})

    except Exception as e:
        log.error(f"monthly_review error: {e}")
        _log_audit("scheduler_monthly_review_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/control-check")
def scheduler_control_check():
    """Check control predictions against current reality."""
    d = request.get_json(force=True)
    owner_id = d.get("owner_id", "")

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        # Get all control_* keys from system_settings
        controls = _query("SELECT key, value FROM system_settings WHERE key LIKE 'control_%'", fetch=True)

        if not controls:
            _tg_send_message(owner_id, "No control predictions found in system_settings.")
            _log_audit("scheduler_control_check", {"owner_id": owner_id, "found": 0})
            return jsonify({"status": "ok", "checked": 0})

        results = []
        osp_prompt = get_dept_prompt("osp")

        for ctrl in controls:
            key = ctrl["key"]
            value = ctrl["value"]
            try:
                ctrl_data = json.loads(value) if isinstance(value, str) else value
            except (json.JSONDecodeError, TypeError):
                ctrl_data = {"raw": value}

            frequency = ctrl_data.get("frequency", "daily")
            topic = ctrl_data.get("topic", key)
            original_prediction = ctrl_data.get("prediction", ctrl_data.get("original", str(value)))

            # For daily controls, compare prediction with current reality via LLM
            if frequency == "daily":
                messages = [
                    {"role": "system", "content": osp_prompt + "\n\nYou are performing a control check. Compare the original prediction with the current situation. Be brief, 2-3 sentences. Format in Russian."},
                    {"role": "user", "content": f"Control check: {topic}\n\nOriginal prediction: {original_prediction}\n\nAnalyze: did the prediction match reality? What changed?\n\nOzhidai: korotkii analiz 2-3 predlozheniya."},
                ]
                check_result = call_llm("osp", messages)
                analysis = check_result["reply"]
                results.append({"key": key, "topic": topic, "frequency": frequency, "analysis": analysis})

        # Format and send results
        if results:
            lines = [f"CONTROL CHECK - {datetime.utcnow().isoformat()[:10]}", "=" * 40, ""]
            for r in results:
                lines.append(f"[{r['topic']}]")
                lines.append(f"  {r['analysis']}")
                lines.append("")
            check_text = "\n".join(lines)
        else:
            check_text = "No daily control predictions to check."

        msg_id = _tg_send_message(owner_id, check_text)
        _log_audit("scheduler_control_check", {"owner_id": owner_id, "checked": len(controls), "daily": len(results), "msg_id": msg_id})

        return jsonify({"status": "ok", "checked": len(controls), "daily": len(results), "msg_id": msg_id})

    except Exception as e:
        log.error(f"control_check error: {e}")
        _log_audit("scheduler_control_check_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/scheduler/self-learn")
def scheduler_self_learn():
    """Self-learning: call LLM to identify improvement areas and memorize findings."""
    try:
        # Get recent corrections and error patterns for context
        corrs = _query("SELECT dept, original_query, correction, created_at FROM adapt_corrections ORDER BY id DESC LIMIT 20", fetch=True)
        patterns = _query("SELECT dept, error_type, query_text, created_at FROM error_patterns ORDER BY id DESC LIMIT 20", fetch=True)

        context_parts = []
        if corrs:
            context_parts.append("Recent corrections:")
            for c in corrs[-10:]:
                context_parts.append(f"  [{c['dept']}] {c['original_query'][:100]} -> {c['correction'][:100]}")
        if patterns:
            context_parts.append("\nRecent error patterns:")
            for p in patterns[-10:]:
                context_parts.append(f"  [{p['dept']}] {p['error_type']}: {p['query_text'][:100]}")

        context = "\n".join(context_parts) if context_parts else "No recent data available."

        yana_prompt = get_dept_prompt("yana")
        messages = [
            {"role": "system", "content": yana_prompt + "\n\nYou are performing self-learning analysis. Based on recent corrections and error patterns, identify ONE specific improvement topic that would reduce errors. Be practical and specific. Output format: TOPIC: <topic> | INSIGHT: <insight> | ACTION: <action>. Format in Russian."},
            {"role": "user", "content": f"Proanalizirui nedavnie oshibki i predlozhi odnu konkretnuyu temu dlya samousovershenstvovaniya.\n\n{context}\n\nFormat: TOPIC: <tema> | INSIGHT: <vyvod> | ACTION: <deistvie>"},
        ]

        result = call_llm("yana", messages)
        finding = result["reply"]

        # Memorize finding
        _memorize("yana", "self_learn", finding)

        _log_audit("scheduler_self_learn", {"provider": result["provider"], "finding": finding[:200]})

        return jsonify({"status": "ok", "finding": finding})

    except Exception as e:
        log.error(f"self_learn error: {e}")
        _log_audit("scheduler_self_learn_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: LEARNING ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.post("/learning/fix")
def learning_fix():
    """Process a user correction: classify error type and save to learning tables."""
    d = request.get_json(force=True)
    text = d.get("text", "")
    dept = d.get("dept", "yana")

    if not text:
        return jsonify({"status": "error", "message": "text is required"}), 400

    try:
        # Call LLM to classify the error type
        dept_prompt = get_dept_prompt(dept)
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are a quality control classifier. Analyze the user's correction text and classify the error type. Also suggest how to fix it going forward. Output JSON only: {\"error_type\": \"TOO_GENERAL|WRONG_FACTS|WRONG_DEPT|BAD_FORMAT|MISSING_CONTEXT|OTHER\", \"suggestion\": \"your suggestion\"}. Language: Russian."},
            {"role": "user", "content": f"Klassifitsirui etu korrektsiyu:\n\n{text}\n\nVerni tolko JSON."},
        ]

        result = call_llm(dept, messages)
        reply = result["reply"]

        # Parse JSON from LLM response
        try:
            # Try to extract JSON from the response (may be wrapped in markdown code block)
            json_match = re.search(r'\{[^}]+\}', reply, re.DOTALL)
            if json_match:
                classification = json.loads(json_match.group())
            else:
                classification = {"error_type": "OTHER", "suggestion": reply}
        except json.JSONDecodeError:
            classification = {"error_type": "OTHER", "suggestion": reply}

        error_type = classification.get("error_type", "OTHER")
        suggestion = classification.get("suggestion", "")

        now = datetime.utcnow().isoformat()

        # Save to error_patterns table
        _query("INSERT INTO error_patterns (dept, error_type, query_text, created_at) VALUES (?,?,?,?)",
               (dept, error_type, text[:2000], now))

        # Save to adapt_corrections table
        _query("INSERT INTO adapt_corrections (dept, original_query, correction, created_at, corr_type) VALUES (?,?,?,?,?)",
               (dept, text[:2000], suggestion[:2000], now, error_type))

        _log_audit("learning_fix", {"dept": dept, "error_type": error_type, "text_len": len(text)})

        return jsonify({"status": "ok", "error_type": error_type, "suggestion": suggestion})

    except Exception as e:
        log.error(f"learning_fix error: {e}")
        _log_audit("learning_fix_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/learning/good")
def learning_good():
    """Save a positive example for learning."""
    d = request.get_json(force=True)
    dept = d.get("dept", "yana")
    query = d.get("query", "")
    response = d.get("response", "")

    if not query or not response:
        return jsonify({"status": "error", "message": "query and response are required"}), 400

    now = datetime.utcnow().isoformat()
    _query("INSERT INTO adapt_corrections (dept, original_query, correction, created_at, corr_type) VALUES (?,?,?,?,?)",
           (dept, query[:2000], response[:2000], now, "positive"))

    _log_audit("learning_good", {"dept": dept, "query_len": len(query), "response_len": len(response)})

    return jsonify({"status": "ok"})

@app.post("/learning/stats")
def learning_stats():
    """Return learning statistics."""
    try:
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        # Corrections count (7d)
        corr_rows = _query("SELECT COUNT(*) as c FROM adapt_corrections WHERE created_at>=? AND corr_type != 'positive'", (week_ago,), fetch=True)
        corrections_7d = corr_rows[0]["c"] if corr_rows else 0

        # Positive examples count
        pos_rows = _query("SELECT COUNT(*) as c FROM adapt_corrections WHERE corr_type = 'positive'", fetch=True)
        positive_total = pos_rows[0]["c"] if pos_rows else 0

        # Error pattern breakdown
        pattern_rows = _query("SELECT error_type, COUNT(*) as c FROM error_patterns GROUP BY error_type ORDER BY c DESC", fetch=True)
        error_breakdown = {}
        for r in pattern_rows:
            error_breakdown[r["error_type"]] = r["c"]

        # Per-dept corrections (7d)
        dept_rows = _query("SELECT dept, COUNT(*) as c FROM adapt_corrections WHERE created_at>=? AND corr_type != 'positive' GROUP BY dept ORDER BY c DESC", (week_ago,), fetch=True)
        dept_corrections = {}
        for r in dept_rows:
            dept_corrections[r["dept"]] = r["c"]

        return jsonify({
            "status": "ok",
            "corrections_7d": corrections_7d,
            "positive_examples": positive_total,
            "error_breakdown": error_breakdown,
            "dept_corrections": dept_corrections,
        })

    except Exception as e:
        log.error(f"learning_stats error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ── IDEA-2: Continuous Learning — record & recall patterns ──

@app.post("/learning/record")
def learning_record():
    """Record a successful pattern for continuous learning.

    Stores query -> approach pairs that scored well in verification.
    Used by HandleDeptQuery in app.mlog after successful verify."""
    d = request.get_json(force=True)
    dept = d.get("dept", "")
    query = d.get("query", "")
    approach = d.get("approach", "")
    score = d.get("score", "0.5")

    if not dept or not query or not approach:
        return jsonify({"status": "error", "message": "dept, query, approach required"}), 400

    try:
        _execute("INSERT INTO continuous_learning (dept, query, approach, score, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (dept, query[:1000], approach[:2000], float(score)))
        log.info(f"learning_record: dept={dept} score={score} query={query[:60]}")
        return jsonify({"status": "ok"})

    except Exception as e:
        log.error(f"learning_record error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/learning/recall")
def learning_recall():
    """Recall past successful patterns for a dept+query.

    Searches continuous_learning table by dept + keyword matching.
    Returns the most recent high-score approaches."""
    d = request.get_json(force=True)
    dept = d.get("dept", "")
    query = d.get("query", "")
    limit = d.get("limit", 3)

    if not dept or not query:
        return jsonify({"status": "error", "count": 0, "results": []})

    try:
        # Extract keywords (words >= 4 chars) from query for LIKE matching
        keywords = [w for w in query.lower().split() if len(w) >= 4][:6]
        if not keywords:
            return jsonify({"status": "ok", "count": 0, "results": []})

        # Build LIKE conditions with OR
        conditions = []
        params = []
        for kw in keywords:
            conditions.append("LOWER(query) LIKE ?")
            params.append(f"%{kw}%")

        where_clause = " AND ".join(conditions)
        sql = f"SELECT approach, score, created_at FROM continuous_learning WHERE dept=? AND ({where_clause}) ORDER BY score DESC, id DESC LIMIT ?"
        params.extend([dept, int(limit)])

        rows = _query(sql, params, fetch=True)
        results = []
        for r in (rows or []):
            results.append({
                "approach": r.get("approach", ""),
                "score": r.get("score", "0.5"),
                "created_at": r.get("created_at", ""),
            })

        return jsonify({"status": "ok", "count": len(results), "results": results})

    except Exception as e:
        log.error(f"learning_recall error: {e}")
        return jsonify({"status": "ok", "count": 0, "results": []})  # non-blocking


@app.post("/learning/debrief")
def learning_debrief():
    """Analyze error patterns for a specific department."""
    d = request.get_json(force=True)
    dept = d.get("dept", "yana")

    try:
        # Get recent corrections for department
        corrs = _query("SELECT original_query, correction, corr_type, created_at FROM adapt_corrections WHERE dept=? AND corr_type != 'positive' ORDER BY id DESC LIMIT 20", (dept,), fetch=True)

        if not corrs:
            return jsonify({"status": "ok", "analysis": "No corrections found for this department."})

        # Format corrections for LLM analysis
        corr_text_parts = []
        for c in corrs:
            corr_text_parts.append(f"[{c['corr_type']}] {c['original_query'][:200]} -> {c['correction'][:200]} ({c['created_at'][:10]})")
        corr_text = "\n".join(corr_text_parts)

        dept_prompt = get_dept_prompt(dept)
        messages = [
            {"role": "system", "content": dept_prompt + "\n\nYou are analyzing error patterns for department quality improvement. Identify recurring themes, root causes, and propose 3 actionable improvements. Format in Russian."},
            {"role": "user", "content": f"Proanalizirui patterny oshibok departamenta {DEPT_NAMES.get(dept, dept)}:\n\n{corr_text}\n\nSformirui analiz s vyvodami i 3 konkretnymi predlozheniyami po uluchsheniyu."},
        ]

        result = call_llm(dept, messages)
        analysis = result["reply"]

        _log_audit("learning_debrief", {"dept": dept, "corrections_analyzed": len(corrs), "provider": result["provider"]})

        return jsonify({"status": "ok", "analysis": analysis})

    except Exception as e:
        log.error(f"learning_debrief error: {e}")
        _log_audit("learning_debrief_error", {"error": str(e)[:500], "dept": dept})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: AUDIT RECENT ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.get("/audit/recent")
@require_telegram
def audit_recent():
    """Return recent audit log entries."""
    try:
        limit = request.args.get("limit", 20, type=int)
        limit = min(limit, 200)

        rows = _query("SELECT id, action, details, timestamp FROM audit_log ORDER BY id DESC LIMIT ?", (limit,), fetch=True)

        entries = []
        for r in rows:
            entry = {
                "id": r["id"],
                "action": r["action"],
                "created": r["timestamp"],
            }
            try:
                entry["details"] = json.loads(r["details"]) if r["details"] else {}
            except (json.JSONDecodeError, TypeError):
                entry["details"] = {"raw": r["details"]}
            entries.append(entry)

        return jsonify({"status": "ok", "entries": entries, "count": len(entries)})

    except Exception as e:
        log.error(f"audit_recent error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-3: SEARCH ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/search")
def search_endpoint():
    """Search miniapp_responses (raw_text and title) for query text."""
    d = request.get_json(force=True)
    query = d.get("query", "")

    if not query:
        return jsonify({"status": "error", "message": "query is required"}), 400

    try:
        search_term = f"%{query}%"
        rows = _query(
            "SELECT id, dept, title, created_at FROM miniapp_responses WHERE (raw_text LIKE ? OR title LIKE ?) ORDER BY id DESC LIMIT 50",
            (search_term, search_term),
            fetch=True
        )

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "dept": r["dept"],
                "title": r["title"],
                "created": r["created_at"],
            })

        return jsonify({"status": "ok", "results": results, "count": len(results)})

    except Exception as e:
        log.error(f"search error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  MEGA-4: LZ DEEP RESEARCH (APODEX)
# ══════════════════════════════════════════════════════════════════════


@app.post("/lz/deep-research")
def lz_deep_research():
    """Apodex-powered deep research endpoint with typing indicator refresh."""
    d = request.get_json(force=True)
    query_text = d.get("query", "")
    dept = d.get("dept", "lz")
    provider = d.get("provider", "apodex")
    model = d.get("model", "apodex-1.0-mini")
    system_context = d.get("system_context", "")
    chat_id = d.get("chat_id", "")

    if not query_text:
        return jsonify({"status": "error", "message": "query is required"}), 400

    stop_typing = None
    if chat_id:
        stop_typing = _send_chat_action_loop(chat_id, "typing", 5)

    try:
        # Build LZ prompt for deep research
        lz_prompt = system_context or get_dept_prompt("lz")

        # If no specific system context, build one
        if not system_context:
            lz_prompt = f"""{lz_prompt}

You are performing DEEP RESEARCH with verification via Apodex.
Requirements:
1. Find minimum 10 independent sources
2. Verify each fact — indicate source and confidence level
3. Mark: [FACT verified], [FACT unverified], [INTERPRETATION], [SPECULATION]
4. Identify contradictions between sources
5. Build timeline if applicable
6. Rate disruption potential (1-10)
7. State what could NOT be found/verified
8. Language: Russian
9. Format: layers (like OSP), with evidence graph at end"""

        messages = [
            {"role": "system", "content": lz_prompt},
            {"role": "user", "content": query_text}
        ]

        # Call Apodex (or fallback to default provider)
        apodex_key = os.environ.get("APODEX_API_KEY", "")
        if apodex_key and provider == "apodex":
            headers = {"Authorization": f"Bearer {apodex_key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "max_tokens": 16384,
                "messages": messages
            }
            resp = http_requests.post(
                "https://platform.apodex.ai/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=300  # 5 minutes for deep research
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            used_provider = "apodex"
            used_model = model
            t_in = data.get("usage", {}).get("prompt_tokens", 0)
            t_out = data.get("usage", {}).get("completion_tokens", 0)
        else:
            # Fallback to standard LLM
            result = call_llm(dept, messages)
            answer = result.get("reply", "Deep research failed.")
            used_provider = result.get("provider", "fallback")
            used_model = result.get("model", "unknown")
            t_in = result.get("tokens_in", 0)
            t_out = result.get("tokens_out", 0)

        # Track token usage
        costs = TOKEN_COSTS.get(used_provider, {"input": 1, "output": 1})
        cost = t_in * costs["input"] / 1_000_000 + t_out * costs["output"] / 1_000_000
        now = datetime.utcnow().isoformat()
        _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
               (used_provider, used_model, t_in, t_out, round(cost, 6), dept, now))

        _log_audit("lz_deep_research", {
            "dept": dept, "provider": used_provider, "model": used_model,
            "query": query_text[:100], "tokens_in": t_in, "tokens_out": t_out,
            "verified": used_provider == "apodex"
        })

        return jsonify({
            "response": answer,
            "provider": used_provider,
            "model": used_model,
            "verified": used_provider == "apodex",
            "tokens_in": t_in,
            "tokens_out": t_out
        })

    except Exception as e:
        log.error(f"lz_deep_research error: {e}")
        _log_audit("lz_deep_research_error", {"error": str(e)[:500], "query": query_text[:100]})
        return jsonify({"response": f"Deep research error: {str(e)}", "provider": None, "verified": False}), 500
    finally:
        if stop_typing:
            stop_typing.set()

# ══════════════════════════════════════════════════════════════════════
#  MEGA-4: EVIDENCE GRAPH BADGES (added to HTML base)
# ══════════════════════════════════════════════════════════════════════

# Apodex verified/unverified/conflicting badges are handled in strip_html_for_archive
# Evidence CSS is injected via _html_base extension

# ══════════════════════════════════════════════════════════════════════
#  NARAD 29: MINI APP SPA — API ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
def api_dashboard():
    """Dashboard data: KPIs, alerts, dept cards, admin status."""
    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        r_today = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        r_week = _query("SELECT COUNT(*) as c FROM dialog_history WHERE created_at>=?", (week_ago,), fetch=True)
        r_cost_today = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        r_cost_month = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (month_ago,), fetch=True)
        r_reports_today = _query("SELECT COUNT(*) as c FROM miniapp_responses WHERE created_at>=?", (today,), fetch=True)

        tasks_today = r_today[0]["c"] if r_today else 0
        tasks_week = r_week[0]["c"] if r_week else 0
        cost_today = r_cost_today[0]["t"] if r_cost_today else 0
        cost_month = r_cost_month[0]["t"] if r_cost_month else 0
        reports_today = r_reports_today[0]["c"] if r_reports_today else 0

        # Average rating
        r_avg = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE created_at>=?", (week_ago,), fetch=True)
        avg_rating = r_avg[0]["a"] if r_avg else 0

        kpis = {
            "tasks": tasks_today, "tasks_week": tasks_week,
            "cost_today": round(cost_today, 2), "cost_month": round(cost_month, 2),
            "rating": round(avg_rating, 1), "reports": reports_today,
        }

        # Dept cards
        dept_cards = []
        for dept in [d for d in DEPT_NAMES if d != "admin"]:
            c = DEPT_COLORS.get(dept, DEPT_COLORS["admin"])
            r_d = _query("SELECT COUNT(*) as c FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
            r_m = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
            calls = r_d[0]["c"] if r_d else 0
            rating = r_m[0]["a"] if r_m else 0
            status = "active" if calls > 5 else "idle" if calls > 0 else "inactive"
            dept_cards.append({
                "slug": dept, "name": DEPT_NAMES.get(dept, dept),
                "color": c, "calls": calls, "rating": round(rating, 1),
                "status": status, "override": _cfg_cache["overrides"].get(dept) or None,
            })

        # Admin status
        kg_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph", fetch=True)
        kg_edges = _query("SELECT COUNT(*) as c FROM knowledge_edges", fetch=True)
        issues = _query("SELECT COUNT(*) as c FROM admin_findings WHERE status='open'", fetch=True)
        proposals = _query("SELECT COUNT(*) as c FROM admin_proposals WHERE status='pending'", fetch=True)

        admin_status = {
            "nodes": kg_nodes[0]["c"] if kg_nodes else 0,
            "edges": kg_edges[0]["c"] if kg_edges else 0,
            "issues": issues[0]["c"] if issues else 0,
            "proposals": proposals[0]["c"] if proposals else 0,
            "code_health": round(avg_rating, 1),
        }

        return jsonify({"status": "ok", "kpis": kpis, "depts": dept_cards, "admin": admin_status})
    except Exception as e:
        log.error(f"api_dashboard error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/dept/<slug>")
def api_dept(slug):
    """Department details: KPIs, recent tasks, skills, corrections, model config."""
    dept = slug.lower()
    if dept not in DEPT_NAMES:
        return jsonify({"status": "error", "message": "Unknown department"}), 404
    try:
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()

        r_tasks = _query("SELECT COUNT(*) as c FROM dialog_history WHERE dept=? AND created_at>=? AND role='user'", (dept, week_ago), fetch=True)
        r_rating = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        r_tokens = _query("SELECT COALESCE(SUM(input_tokens),0)+COALESCE(SUM(output_tokens),0) as t FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        r_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)

        kpis = {
            "tasks": r_tasks[0]["c"] if r_tasks else 0,
            "rating": round(r_rating[0]["a"], 1) if r_rating else 0,
            "tokens": r_tokens[0]["t"] if r_tokens else 0,
            "cost": round(r_cost[0]["t"], 2) if r_cost else 0,
        }

        # Recent tasks
        recent = _query("SELECT content, created_at FROM dialog_history WHERE dept=? AND role='user' ORDER BY id DESC LIMIT 5", (dept,), fetch=True)
        tasks = [{"text": r["content"][:100], "created": r["created_at"][:16]} for r in recent]

        # Corrections
        corrs = _query("SELECT original_query, correction, created_at FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 5", (dept,), fetch=True)
        corrections = [{"original": r["original_query"][:80], "corrected": r["correction"][:80], "created": r["created_at"][:10]} for r in corrs]

        # Skills
        skills_idx = CFG_DIR / f"../skills_index/{dept}.txt"
        skills = []
        if skills_idx.exists():
            skills = [s.strip() for s in skills_idx.read_text().strip().split("\n") if s.strip()][:15]

        # Model config
        model = _cfg_cache["overrides"].get(dept) or _cfg_cache["priority_model"] or "glm-4.6"
        provider = _cfg_cache["priority_provider"]

        return jsonify({
            "status": "ok", "slug": dept, "name": DEPT_NAMES[dept],
            "color": DEPT_COLORS.get(dept, {}),
            "kpis": kpis, "tasks": tasks, "corrections": corrections,
            "skills": skills, "model": model, "provider": provider,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/models")
def api_models():
    """Model statuses with usage stats."""
    try:
        now = datetime.utcnow()
        month_ago = (now - timedelta(days=30)).isoformat()
        models = []

        # Build model list from providers + overrides
        seen = set()
        model_info = {
            "zai": {"name": "GLM 4.6", "provider": "zai", "label": "Z.ai", "tier": "priority"},
            "deepseek": {"name": "DeepSeek Chat", "provider": "deepseek", "label": "DeepSeek", "tier": "cheap"},
            "groq": {"name": "Llama 3.3 70B", "provider": "groq", "label": "Groq", "tier": "free"},
            "grok": {"name": "Grok 3", "provider": "grok", "label": "xAI", "tier": "free_limit"},
            "anthropic": {"name": "Claude Sonnet 4", "provider": "anthropic", "label": "Anthropic", "tier": "paid"},
            "openai": {"name": "GPT-4o", "provider": "openai", "label": "OpenAI", "tier": "paid"},
            "apodex": {"name": "Apodex 1.0", "provider": "apodex", "label": "Apodex", "tier": "special"},
        }

        for prov_key, info in model_info.items():
            api_key = os.environ.get(PROVIDERS[prov_key]["env_key"])
            if prov_key in seen:
                continue
            seen.add(prov_key)

            r_calls = _query("SELECT COUNT(*) as c FROM token_usage WHERE provider=? AND created_at>=?", (prov_key, month_ago), fetch=True)
            r_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE provider=? AND created_at>=?", (prov_key, month_ago), fetch=True)
            calls = r_calls[0]["c"] if r_calls else 0
            cost = r_cost[0]["t"] if r_cost else 0

            # Check if it's the priority provider
            is_priority = prov_key == _cfg_cache["priority_provider"]

            status = "active" if api_key else "no_key"
            if prov_key == "grok":
                # Check if rate limited (mock: if calls > 500)
                status = "limited" if calls > 500 else status

            models.append({
                "key": prov_key, "name": info["name"], "label": info["label"],
                "tier": info["tier"], "status": status, "priority": is_priority,
                "calls": calls, "cost": round(cost, 2),
            })

        # Overrides per dept
        overrides = {d: v for d, v in _cfg_cache["overrides"].items() if v}

        # Today analytics
        today = now.isoformat()[:10]
        r_today = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        r_today_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (today,), fetch=True)
        active_provs = _query("SELECT DISTINCT provider FROM token_usage WHERE created_at>=?", (today,), fetch=True)

        analytics = {
            "requests_today": r_today[0]["c"] if r_today else 0,
            "cost_today": round(r_today_cost[0]["t"], 2) if r_today_cost else 0,
            "active_providers": len(active_provs),
        }

        return jsonify({"status": "ok", "models": models, "overrides": overrides, "analytics": analytics})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/economics")
def api_economics():
    """Economics data: costs by dept, by model, by period."""
    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()

        # Period costs
        periods = {}
        for label, start in [("today", today), ("week", week_ago), ("month", month_ago)]:
            r = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (start,), fetch=True)
            periods[label] = round(r[0]["t"], 2) if r else 0

        # By dept (month)
        dept_costs = _query("SELECT dept, COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=? GROUP BY dept ORDER BY t DESC", (month_ago,), fetch=True)
        by_dept = [{"dept": r["dept"], "name": DEPT_NAMES.get(r["dept"], r["dept"]), "cost": round(r["t"], 2), "color": DEPT_COLORS.get(r["dept"], {}).get("accent", "#C9A84C")} for r in dept_costs]

        # By provider (month)
        prov_costs = _query("SELECT provider, COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=? GROUP BY provider ORDER BY t DESC", (month_ago,), fetch=True)
        by_provider = [{"provider": r["provider"], "cost": round(r["t"], 2)} for r in prov_costs]

        # Budget
        budget_rows = _query("SELECT value FROM system_settings WHERE key='daily_budget'", fetch=True)
        budget = budget_rows[0]["value"] if budget_rows else "10"

        return jsonify({"status": "ok", "periods": periods, "by_dept": by_dept, "by_provider": by_provider, "budget": budget})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/narads")
def api_narads():
    """List narads."""
    try:
        rows = _query("SELECT id, title, description, risk_level, status, created_at, approved_at FROM narads ORDER BY id DESC LIMIT 20", fetch=True)
        narads = []
        for r in rows:
            narads.append({
                "id": r["id"], "title": r["title"], "description": r["description"] or "",
                "risk": r["risk_level"], "status": r["status"],
                "created": r["created_at"][:16] if r["created_at"] else "",
                "approved": r["approved_at"][:16] if r["approved_at"] else "",
            })
        return jsonify({"status": "ok", "narads": narads})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/narads/<nid>/approve")
def api_narad_approve(nid):
    try:
        _query("UPDATE narads SET status='approved', approved_at=datetime('now') WHERE id=?", (nid,))
        _log_audit("narad_approve_miniapp", {"narad_id": nid})
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/narads/<nid>/reject")
def api_narad_reject(nid):
    try:
        _query("UPDATE narads SET status='rejected' WHERE id=?", (nid,))
        _log_audit("narad_reject_miniapp", {"narad_id": nid})
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/archive")
def api_archive():
    """Search archive. Accepts ?q= query param, optional ?dept= filter."""
    try:
        q = request.args.get("q", "")
        dept_filter = request.args.get("dept", "")
        if q:
            search_term = f"%{q}%"
            if dept_filter:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE (raw_text LIKE ? OR title LIKE ?) AND dept=? ORDER BY created_at DESC LIMIT 50",
                             (search_term, search_term, dept_filter), fetch=True)
            else:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE raw_text LIKE ? OR title LIKE ? ORDER BY created_at DESC LIMIT 50",
                             (search_term, search_term), fetch=True)
        else:
            if dept_filter:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE dept=? ORDER BY created_at DESC LIMIT 50", (dept_filter,), fetch=True)
            else:
                rows = _query("SELECT id, dept, title, created_at FROM miniapp_responses ORDER BY created_at DESC LIMIT 50", fetch=True)

        results = [{"id": r["id"], "dept": r["dept"], "title": r["title"], "created": r["created_at"][:16] if r["created_at"] else ""} for r in rows]
        return jsonify({"status": "ok", "results": results, "count": len(results)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/admin/status")
def api_admin_status():
    """Admin stats: graph, issues, proposals."""
    try:
        kg_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph", fetch=True)
        kg_edges = _query("SELECT COUNT(*) as c FROM knowledge_edges", fetch=True)
        issues = _query("SELECT id, severity, file_path, issue, status FROM admin_findings WHERE status='open' ORDER BY id DESC LIMIT 10", fetch=True)
        proposals = _query("SELECT id, content, status FROM admin_proposals WHERE status='pending' ORDER BY id DESC LIMIT 10", fetch=True)
        reports = _query("SELECT COUNT(*) as c FROM admin_reports", fetch=True)

        return jsonify({
            "status": "ok",
            "graph": {"nodes": kg_nodes[0]["c"] if kg_nodes else 0, "edges": kg_edges[0]["c"] if kg_edges else 0},
            "issues": [{"id": r["id"], "severity": r["severity"], "file": r["file_path"], "issue": r["issue"]} for r in issues],
            "proposals": [{"id": r["id"], "content": r["content"][:200], "status": r["status"]} for r in proposals],
            "reports_count": reports[0]["c"] if reports else 0,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  ADMIN UA — Understand Anything (6 sub-agents)
# ══════════════════════════════════════════════════════════════════════

SKIP_DIRS = {'data', '.git', 'node_modules', '__pycache__', 'отчёты', 'tool-results', 'scripts', 'upload'}
KNOWN_BUILTINS = ['send_message', 'query', 'db_execute', 'kv_set', 'kv_get',
    'http_post', 'http_get', 'read_file', 'write_file', 'call_llm',
    'json_get', 'parse_json', 'json_encode', 'respond', 'respond_html',
    'memorize', 'recall', 'whisper_transcribe', 'tts_send', 'git_push',
    'web_search', 'env', 'now', 'len', 'replace', 'split', 'AuditLog',
    'RecordUserMessage', 'RecordAssistantMessage', 'BuildContext',
    'SendTelegramReply', 'SendReport', 'DetectDepartment', 'CallLLMProxy',
    'InitDB', 'HandleAdmin', 'HandleYana', 'HandleOSP', 'HandleLZ',
    'list_dir', 'escape_json', 'to_string', 'to_float', 'to_int',
    'index_of', 'substring', 'trim', 'lower', 'upper', 'starts_with',
    'ends_with', 'contains', 'json_body', 'query_param', 'http_get']


@app.get("/admin-ua/scan")
def admin_ua_scan():
    """Scanner: inventory of all files in /office."""
    inventory = {'files': [], 'total_lines': 0, 'total_files': 0, 'by_type': {}, 'by_dir': {}}
    office_dir = Path('/office')

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            rel = str(fpath.relative_to(office_dir))
            try:
                lines = len(fpath.read_text(errors='ignore').splitlines())
            except Exception:
                lines = 0
            ext = fpath.suffix
            dir_name = rel.split('/')[0] if '/' in rel else 'root'
            inventory['files'].append({
                'path': rel, 'lines': lines, 'ext': ext, 'dir': dir_name,
                'size_kb': round(fpath.stat().st_size / 1024, 1),
            })
            inventory['total_lines'] += lines
            inventory['total_files'] += 1
            inventory['by_type'][ext] = inventory['by_type'].get(ext, 0) + 1
            inventory['by_dir'][dir_name] = inventory['by_dir'].get(dir_name, 0) + 1

    inventory['files'].sort(key=lambda x: x['lines'], reverse=True)
    summary = (f"SCAN COMPLETE\n  Files: {inventory['total_files']} | "
               f"Lines: {inventory['total_lines']:,} | "
               f"Dirs: {len(inventory['by_dir'])}\n")
    for ext, cnt in sorted(inventory['by_type'].items(), key=lambda x: -x[1]):
        summary += f"  {ext or '(none)'}: {cnt} files\n"
    if inventory['files']:
        summary += f"  Largest: {inventory['files'][0]['path']} ({inventory['files'][0]['lines']} lines)\n"
    return jsonify({'summary': summary, 'inventory': inventory})


@app.get("/admin-ua/analyze")
def admin_ua_analyze():
    """Analyzer: extract patterns, routes, imports, builtins from each file."""
    office_dir = Path('/office')
    analysis = []

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            ext = fpath.suffix
            if ext not in ('.mlog', '.py'):
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue

            fa = {'path': rel, 'patterns': [], 'routes': [], 'imports': [],
                  'builtins_used': [], 'tables': []}

            if ext == '.mlog':
                for m in re.finditer(r'pattern\s+(\w+)\(([^)]*)\)\s*->\s*(\w+)', content):
                    fa['patterns'].append({'name': m.group(1), 'args': m.group(2), 'returns': m.group(3)})
                for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                    fa['routes'].append({'path': m.group(1), 'method': m.group(2)})
                for m in re.finditer(r'import\s+([\w/]+)', content):
                    fa['imports'].append(m.group(1))
                for b in KNOWN_BUILTINS:
                    if b + '(' in content:
                        fa['builtins_used'].append(b)
                for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?(\w+)', content):
                    fa['tables'].append(m.group(1))

            elif ext == '.py':
                for m in re.finditer(r'def\s+(\w+)\(', content):
                    fa['patterns'].append({'name': m.group(1), 'args': '', 'returns': ''})
                for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                    fa['routes'].append({'path': m.group(1), 'method': 'GET/POST'})

            analysis.append(fa)

    total_patterns = sum(len(f['patterns']) for f in analysis)
    total_routes = sum(len(f['routes']) for f in analysis)
    total_imports = sum(len(f['imports']) for f in analysis)
    summary = (f"ANALYZE COMPLETE\n  Files: {len(analysis)} | "
               f"Patterns: {total_patterns} | Routes: {total_routes} | Imports: {total_imports}")

    return jsonify({'summary': summary, 'analysis': analysis})


def _ua_analyze_internal():
    """Internal analyzer — returns list of file analysis dicts (no Flask)."""
    office_dir = Path('/office')
    analysis = []

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            ext = fpath.suffix
            if ext not in ('.mlog', '.py'):
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue

            fa = {'path': rel, 'patterns': [], 'routes': [], 'imports': [],
                  'builtins_used': [], 'tables': []}

            if ext == '.mlog':
                for m in re.finditer(r'pattern\s+(\w+)\(([^)]*)\)\s*->\s*(\w+)', content):
                    fa['patterns'].append({'name': m.group(1), 'args': m.group(2), 'returns': m.group(3)})
                for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                    fa['routes'].append({'path': m.group(1), 'method': m.group(2)})
                for m in re.finditer(r'import\s+([\w/]+)', content):
                    fa['imports'].append(m.group(1))
                for b in KNOWN_BUILTINS:
                    if b + '(' in content:
                        fa['builtins_used'].append(b)
                for m in re.finditer(r'CREATE TABLE (?:IF NOT EXISTS )?(\w+)', content):
                    fa['tables'].append(m.group(1))

            elif ext == '.py':
                for m in re.finditer(r'def\s+(\w+)\(', content):
                    fa['patterns'].append({'name': m.group(1), 'args': '', 'returns': ''})
                for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                    fa['routes'].append({'path': m.group(1), 'method': 'GET/POST'})

            analysis.append(fa)

    return analysis


def _ua_scan_internal():
    """Internal scanner — returns inventory dict (no Flask)."""
    inventory = {'files': [], 'total_lines': 0, 'total_files': 0, 'by_type': {}, 'by_dir': {}}
    office_dir = Path('/office')

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            rel = str(fpath.relative_to(office_dir))
            try:
                lines = len(fpath.read_text(errors='ignore').splitlines())
            except Exception:
                lines = 0
            ext = fpath.suffix
            dir_name = rel.split('/')[0] if '/' in rel else 'root'
            inventory['files'].append({
                'path': rel, 'lines': lines, 'ext': ext, 'dir': dir_name,
                'size_kb': round(fpath.stat().st_size / 1024, 1),
            })
            inventory['total_lines'] += lines
            inventory['total_files'] += 1
            inventory['by_type'][ext] = inventory['by_type'].get(ext, 0) + 1
            inventory['by_dir'][dir_name] = inventory['by_dir'].get(dir_name, 0) + 1

    inventory['files'].sort(key=lambda x: x['lines'], reverse=True)
    return inventory


def _ua_review_internal():
    """Internal reviewer — returns findings dict with health_score (no Flask)."""
    office_dir = Path('/office')
    findings = []
    all_mlog = {}
    all_patterns = {}
    called_patterns = set()
    imported_files = set()

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix != '.mlog':
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            all_mlog[rel] = content
            for m in re.finditer(r'pattern\s+(\w+)\(', content):
                all_patterns[m.group(1)] = rel
            for m in re.finditer(r'import\s+([\w/]+)', content):
                imported_files.add(m.group(1) + '.mlog')
            for pname in all_patterns:
                if pname + '(' in content:
                    called_patterns.add(pname)
            if rel.startswith('dept/') and 'AuditLog' not in content and rel not in ('dept/utils.mlog', 'dept/context.mlog'):
                findings.append({'severity': 'medium', 'category': 'ARCHITECTURE',
                                 'file': rel, 'issue': 'No AuditLog calls — actions not logged',
                                 'fix': 'Add AuditLog() after LLM calls'})

    for f in all_mlog:
        if f != 'app.mlog' and f not in imported_files and f not in ('file_cache.mlog', 'file_cache_skills.mlog'):
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': f, 'issue': f'File not imported — possible dead code',
                             'fix': 'Import in app.mlog or delete'})

    entry_points = {'InitDB', 'Main', 'mlogserver'}
    for pname, pfile in all_patterns.items():
        if pname not in called_patterns and pname not in entry_points:
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': pfile, 'issue': f'Pattern {pname}() defined but never called',
                             'fix': 'Call it or remove'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'route\s+"(/cron/[^"]+)"', content):
            route_block = content[m.end():m.end() + 500]
            if 'CRON_SECRET' not in route_block and 'secret' not in route_block.lower():
                findings.append({'severity': 'high', 'category': 'SECURITY',
                                 'file': f, 'issue': f'Route {m.group(1)} has no CRON_SECRET check',
                                 'fix': 'Add secret validation'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'contains\([^)]+\)\s*==\s*1\.0', content):
            findings.append({'severity': 'medium', 'category': 'BUGS',
                             'file': f, 'issue': 'contains() returns Bool, == 1.0 is type mismatch',
                             'fix': 'Use: if contains(...) then { }'})

    high = len([f for f in findings if f['severity'] == 'high'])
    medium = len([f for f in findings if f['severity'] == 'medium'])
    low = len([f for f in findings if f['severity'] == 'low'])
    score = max(1, round(10 - high * 2 - medium * 0.5 - low * 0.1, 1))

    return {'findings': findings, 'health_score': score}


@app.get("/admin-ua/graph")
def admin_ua_graph():
    """Grapher: build knowledge graph from analysis data, save to SQLite."""
    conn = sqlite3.connect(str(DB_FILE))
    c = conn.cursor()

    # Ensure tables exist (may be missing if DB predates this feature)
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge_graph
        (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT,
         file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS knowledge_edges
        (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT,
         edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')))""")

    # Clear old graph
    c.execute("DELETE FROM knowledge_graph")
    c.execute("DELETE FROM knowledge_edges")

    # Run analyzer internally (not via Flask)
    analysis = _ua_analyze_internal()

    nodes_saved = 0
    edges_saved = 0
    now_ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    for fa in analysis:
        rel = fa['path']
        # Node: file
        c.execute(
            "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
            ('file', rel, rel, f"{len(fa.get('patterns', []))} patterns, {len(fa.get('routes', []))} routes", now_ts))
        nodes_saved += 1

        # Nodes + edges: patterns
        for p in fa.get('patterns', []):
            pname = p.get('name', '')
            if not pname:
                continue
            c.execute(
                "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                ('pattern', pname, rel, f"args={p.get('args', '')} returns={p.get('returns', '')}", now_ts))
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, pname, 'defines', rel, now_ts))
            edges_saved += 1

        # Nodes + edges: routes
        for r in fa.get('routes', []):
            rname = r.get('path', '')
            if not rname:
                continue
            c.execute(
                "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                ('route', rname, rel, r.get('method', ''), now_ts))
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, rname, 'exposes', rel, now_ts))
            edges_saved += 1

        # Nodes + edges: tables
        for t in fa.get('tables', []):
            c.execute(
                "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?, ?, ?, ?, ?)",
                ('table', t, rel, 'CREATE TABLE', now_ts))
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, t, 'creates', rel, now_ts))
            edges_saved += 1

        # Edges: imports
        for imp in fa.get('imports', []):
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, imp + '.mlog', 'imports', rel, now_ts))
            edges_saved += 1

        # Edges: builtins used
        for b in fa.get('builtins_used', []):
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, b, 'calls_builtin', rel, now_ts))
            edges_saved += 1

    # Cross-file pattern calls: find which files call patterns from other files
    pattern_to_file = {}
    for fa in analysis:
        for p in fa.get('patterns', []):
            pname = p.get('name', '')
            if pname:
                pattern_to_file[pname] = fa['path']

    for fa in analysis:
        rel = fa['path']
        for pname in pattern_to_file:
            if pname == 'Main' or pname == 'InitDB' or pname == 'mlogserver':
                continue
            if pattern_to_file[pname] != rel:
                try:
                    fpath = (BASE_DIR / rel)
                    if fpath.exists():
                        content = fpath.read_text(errors='ignore')
                        if pname + '(' in content:
                            c.execute(
                                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                                (rel, pname, 'calls', rel, now_ts))
                            edges_saved += 1
                except Exception as e:
                    _log_error(f"knowledge_edges insert failed: {e}", source="kg_rebuild", dept="lz", kind="data_loss")

    conn.commit()
    conn.close()

    summary = (f"GRAPH COMPLETE\n  Nodes: {nodes_saved} | Edges: {edges_saved}\n  "
               f"Files analyzed: {len(analysis)}")
    return jsonify({'summary': summary, 'nodes': nodes_saved, 'edges': edges_saved})


@app.get("/admin-ua/review")
def admin_ua_review():
    """Reviewer: orphans, bugs, security, architecture checks."""
    office_dir = Path('/office')
    findings = []

    all_mlog = {}
    all_patterns = {}
    called_patterns = set()
    imported_files = set()

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix != '.mlog':
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            all_mlog[rel] = content

            for m in re.finditer(r'pattern\s+(\w+)\(', content):
                all_patterns[m.group(1)] = rel

            for m in re.finditer(r'import\s+([\w/]+)', content):
                imported_files.add(m.group(1) + '.mlog')

            for pname in all_patterns:
                if pname + '(' in content:
                    called_patterns.add(pname)

            if rel.startswith('dept/') and 'AuditLog' not in content and rel not in ('dept/utils.mlog', 'dept/context.mlog'):
                findings.append({'severity': 'medium', 'category': 'ARCHITECTURE',
                                 'file': rel, 'issue': 'No AuditLog calls — actions not logged',
                                 'fix': 'Add AuditLog() after LLM calls'})

    for f in all_mlog:
        if f != 'app.mlog' and f not in imported_files and f not in ('file_cache.mlog', 'file_cache_skills.mlog'):
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': f, 'issue': f'File not imported — possible dead code',
                             'fix': 'Import in app.mlog or delete'})

    entry_points = {'InitDB', 'Main', 'mlogserver'}
    for pname, pfile in all_patterns.items():
        if pname not in called_patterns and pname not in entry_points:
            findings.append({'severity': 'low', 'category': 'ORPHAN',
                             'file': pfile, 'issue': f'Pattern {pname}() defined but never called',
                             'fix': 'Call it or remove'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'route\s+"(/cron/[^"]+)"', content):
            route_block = content[m.end():m.end() + 500]
            if 'CRON_SECRET' not in route_block and 'secret' not in route_block.lower():
                findings.append({'severity': 'high', 'category': 'SECURITY',
                                 'file': f, 'issue': f'Route {m.group(1)} has no CRON_SECRET check',
                                 'fix': 'Add secret validation'})

    for f, content in all_mlog.items():
        for m in re.finditer(r'contains\([^)]+\)\s*==\s*1\.0', content):
            findings.append({'severity': 'medium', 'category': 'BUGS',
                             'file': f, 'issue': 'contains() returns Bool, == 1.0 is type mismatch',
                             'fix': 'Use: if contains(...) then { }'})

    high = len([f for f in findings if f['severity'] == 'high'])
    medium = len([f for f in findings if f['severity'] == 'medium'])
    low = len([f for f in findings if f['severity'] == 'low'])
    score = max(1, round(10 - high * 2 - medium * 0.5 - low * 0.1, 1))
    summary = f"REVIEW COMPLETE\n  Findings: {len(findings)} (high={high}, medium={medium}, low={low})\n  Health: {score}/10"

    return jsonify({'summary': summary, 'findings': findings, 'health_score': score})


@app.get("/admin-ua/impact")
def admin_ua_impact():
    """Differ: impact analysis for a file."""
    file_path = request.args.get('file', '')
    if not file_path:
        return jsonify({'error': 'Missing ?file= parameter', 'dependents': [], 'risk': 'unknown'})

    office_dir = Path('/office')
    dependents = []
    target_module = file_path.replace('.mlog', '').replace('/', '')

    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix != '.mlog':
                continue
            rel = str(fpath.relative_to(office_dir))
            if rel == file_path:
                continue
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            if f'import {target_module}' in content or f'import dept/{target_module}' in content:
                dependents.append({'file': rel, 'relation': 'imports'})

    risk = 'low'
    if len(dependents) > 5 or file_path == 'app.mlog':
        risk = 'high'
    elif len(dependents) > 2:
        risk = 'medium'

    summary = f"Impact Analysis: {file_path}\n  Risk: {risk} | Dependents: {len(dependents)}\n"
    for d in dependents:
        summary += f"  {d['file']} ({d['relation']})\n"

    return jsonify({'summary': summary, 'file': file_path, 'dependents': dependents,
                    'risk': risk, 'dependent_count': len(dependents)})


@app.get("/admin-ua/docs")
def admin_ua_docs():
    """Documenter: auto-generate project structure and API reference."""
    office_dir = Path('/office')
    files_info = []
    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix not in ('.mlog', '.py', '.txt', '.html'):
                continue
            rel = str(fpath.relative_to(office_dir))
            try:
                lines = len(fpath.read_text(errors='ignore').splitlines())
            except Exception:
                lines = 0
            files_info.append({'path': rel, 'lines': lines})
    files_info.sort(key=lambda x: x['path'])

    structure = f"# Fosved Office v2 — Структура проекта\n\n**{len(files_info)} файлов**\n\n"
    for f in files_info:
        structure += f"- `{f['path']}` — {f['lines']} строк\n"

    api = "# API Reference\n\n"
    for root, dirs, files in os.walk(office_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            fpath = Path(root) / f
            if fpath.suffix not in ('.mlog', '.py'):
                continue
            try:
                content = fpath.read_text(errors='ignore')
            except Exception:
                continue
            rel = str(fpath.relative_to(office_dir))
            if fpath.suffix == '.mlog':
                for m in re.finditer(r'route\s+"([^"]+)"\s+method=(\w+)', content):
                    api += f"### `{m.group(2).upper()} {m.group(1)}`\nFile: `{rel}`\n\n"
            elif fpath.suffix == '.py':
                for m in re.finditer(r"@\w+\.route\(['\"]([^'\"]+)", content):
                    api += f"### `{m.group(1)}`\nFile: `{rel}`\n\n"

    return jsonify({'structure': structure, 'api': api})


@app.post("/admin-ua/night-cycle")
def admin_ua_night_cycle():
    """
    Full UA night cycle: Scanner → Analyzer → Grapher → Reviewer → Differ → Documenter.
    Saves results to admin_night_reports, updates knowledge graph.
    Called from /cron/night or /admin analyze.
    """
    try:
        log.info("UA Night Cycle: Phase 1/6 — Scanner")
        inventory = _ua_scan_internal()

        log.info("UA Night Cycle: Phase 2/6 — Analyzer")
        analysis = _ua_analyze_internal()

        log.info("UA Night Cycle: Phase 3/6 — Grapher")
        # Build graph in SQLite
        conn = sqlite3.connect(str(DB_FILE))
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge_graph
            (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT,
             file_path TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')))""")
        c.execute("""CREATE TABLE IF NOT EXISTS knowledge_edges
            (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT,
             edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')))""")
        c.execute("DELETE FROM knowledge_graph")
        c.execute("DELETE FROM knowledge_edges")

        nodes_saved = 0
        edges_saved = 0
        now_ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        for fa in analysis:
            rel = fa['path']
            c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?,?,?,?,?)",
                      ('file', rel, rel, f"{len(fa.get('patterns', []))}p {len(fa.get('routes', []))}r", now_ts))
            nodes_saved += 1
            for p in fa.get('patterns', []):
                pname = p.get('name', '')
                if not pname: continue
                c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?,?,?,?,?)",
                          ('pattern', pname, rel, '', now_ts))
                nodes_saved += 1
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, pname, 'defines', rel, now_ts))
                edges_saved += 1
            for r in fa.get('routes', []):
                rname = r.get('path', '')
                if not rname: continue
                c.execute("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at) VALUES (?,?,?,?,?)",
                          ('route', rname, rel, r.get('method', ''), now_ts))
                nodes_saved += 1
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, rname, 'exposes', rel, now_ts))
                edges_saved += 1
            for imp in fa.get('imports', []):
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, imp + '.mlog', 'imports', rel, now_ts))
                edges_saved += 1

        # Cross-file pattern calls
        pattern_to_file = {}
        for fa in analysis:
            for p in fa.get('patterns', []):
                if p.get('name'): pattern_to_file[p['name']] = fa['path']
        for fa in analysis:
            rel = fa['path']
            for pname, pfile in pattern_to_file.items():
                if pname in ('Main', 'InitDB', 'mlogserver'): continue
                if pfile != rel:
                    try:
                        content = (Path('/office') / rel).read_text(errors='ignore')
                        if pname + '(' in content:
                            c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                                      (rel, pname, 'calls', rel, now_ts))
                            edges_saved += 1
                    except Exception as e:
                        _log_error(f"knowledge_edges insert failed: {e}", source="kg_rebuild", dept="lz", kind="data_loss")

        conn.commit()
        conn.close()

        log.info("UA Night Cycle: Phase 4/6 — Reviewer")
        review = _ua_review_internal()
        findings = review['findings']
        health = review['health_score']

        log.info("UA Night Cycle: Phase 5/6 — Differ (skip — needs file param)")
        # Differ is on-demand via /admin impact <file>

        log.info("UA Night Cycle: Phase 6/6 — Documenter")
        structure_lines = []
        api_lines = []
        for fa in sorted(analysis, key=lambda x: x['path']):
            structure_lines.append(f"- `{fa['path']}` — {len(fa.get('patterns', []))} patterns")
            for r in fa.get('routes', []):
                api_lines.append(f"{r.get('method', '?')} {r['path']} ({fa['path']})")

        # Save night report to DB
        import json as _json
        _query("INSERT INTO admin_night_reports (scan_data, review_data, health_score, findings_count, created_at) VALUES (?,?,?,?,?)",
               (_json.dumps({'total_files': inventory['total_files'], 'total_lines': inventory['total_lines']}),
                _json.dumps(findings[:50]),
                health, len(findings), datetime.utcnow().isoformat()))

        # Save findings to admin_findings table
        for f in findings:
            _query("INSERT INTO admin_findings (severity, category, file, issue, fix, status) VALUES (?,?,?,?,?,?)",
                   (f['severity'], f['category'], f.get('file', ''), f['issue'], f.get('fix', ''), 'open'))

        # Close open findings that are resolved
        _query("UPDATE admin_findings SET status='closed' WHERE status='open' AND created_at < datetime('now', '-7 days')")

        summary = (f"UA NIGHT CYCLE COMPLETE\n"
                   f"  Files: {inventory['total_files']} ({inventory['total_lines']:,} lines)\n"
                   f"  Patterns: {sum(len(f['patterns']) for f in analysis)}\n"
                   f"  Routes: {sum(len(f['routes']) for f in analysis)}\n"
                   f"  Graph: {nodes_saved} nodes, {edges_saved} edges\n"
                   f"  Findings: {len(findings)} (h={len([f for f in findings if f['severity']=='high'])} "
                   f"m={len([f for f in findings if f['severity']=='medium'])} "
                   f"l={len([f for f in findings if f['severity']=='low'])})\n"
                   f"  Health: {health}/10")

        _log_audit("ua_night_cycle", {"files": inventory['total_files'], "nodes": nodes_saved,
                                       "edges": edges_saved, "findings": len(findings), "health": health})

        return jsonify({'status': 'ok', 'summary': summary, 'health_score': health,
                        'findings_count': len(findings)})

    except Exception as e:
        log.error(f"ua_night_cycle error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.get("/admin-ua/tour")
def admin_ua_tour():
    """Tour: guided architecture tour using all 6 sub-agents."""
    # Use internal functions, not Flask self-calls
    scan_data = _ua_scan_internal()
    review_data = _ua_review_internal()
    g_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph", fetch=True)
    g_edges = _query("SELECT COUNT(*) as c FROM knowledge_edges", fetch=True)
    kg_nodes = g_nodes[0]['c'] if g_nodes else 0
    kg_edges = g_edges[0]['c'] if g_edges else 0

    tour = f"Guided Tour по Fosved Office v2\n\n"
    tour += f"Офис: {scan_data['total_files']} файлов ({scan_data['total_lines']:,} строк)\n"
    tour += f"Knowledge graph: {kg_nodes} nodes, {kg_edges} edges\n\n"

    top_files = sorted(scan_data['files'], key=lambda x: x['lines'], reverse=True)[:5]
    tour += "Ключевые файлы:\n"
    for f in top_files:
        tour += f"  {f['path']} — {f['lines']} строк ({f['size_kb']} KB)\n"

    # Top dirs
    by_dir = scan_data.get('by_dir', {})
    tour += f"\nСтруктура: {len(by_dir)} директорий\n"
    for d, cnt in sorted(by_dir.items(), key=lambda x: -x[1])[:6]:
        tour += f"  {d}/ — {cnt} файлов\n"

    health = review_data.get('health_score', '?')
    findings = review_data.get('findings', [])
    tour += f"\nCode health: {health}/10\n"

    high_f = [f for f in findings if f['severity'] == 'high'][:3]
    med_f = [f for f in findings if f['severity'] == 'medium'][:3]
    if high_f:
        tour += f"\nHIGH severity ({len(high_f)}):\n"
        for f in high_f:
            tour += f"  [{f['category']}] {f['file']}: {f['issue']}\n"
    if med_f:
        tour += f"\nMEDIUM ({len(med_f)}):\n"
        for f in med_f:
            tour += f"  [{f['category']}] {f['file']}: {f['issue']}\n"

    return jsonify({'tour': tour})


# ══════════════════════════════════════════════════════════════════════
#  MINI APP SPA — STATIC FILE SERVING
# ══════════════════════════════════════════════════════════════════════

MINIAPP_DIR = BASE_DIR / "miniapp"

@app.get("/miniapp")
@require_telegram
def miniapp_redirect():
    """Redirect /miniapp to /miniapp-spa."""
    from flask import redirect
    return redirect("/miniapp-spa", code=301)

@app.get("/api/integrations")
def api_integrations_list():
    """Список известных интеграций со статусом. Значение ключа никогда не отдаётся целиком."""
    out = []
    for item in INTEGRATIONS_REGISTRY:
        current = get_secret(item["env_key"])
        out.append({
            "id": item["env_key"],
            "label": item["label"],
            "kind": item["kind"],
            "connected": bool(current),
            "masked": secrets_crypto.mask_value(current) if current else None,
            "source": "db" if _has_db_override(item["env_key"]) else ("env" if current else "none"),
        })
    return jsonify({"status": "ok", "integrations": out, "master_key_configured": secrets_crypto.is_configured()})


@app.post("/api/integrations/<env_key>")
def api_integrations_set(env_key):
    """Задать или обновить секрет. Значение никогда не возвращается целиком."""
    known = {item["env_key"] for item in INTEGRATIONS_REGISTRY}
    if env_key not in known:
        return jsonify({"status": "error", "message": "неизвестная интеграция"}), 404
    d = request.get_json(force=True, silent=True) or {}
    value = (d.get("value") or "").strip()
    if not value:
        return jsonify({"status": "error", "message": "значение не может быть пустым"}), 400
    ok = set_secret(env_key, value)
    if not ok:
        return jsonify({"status": "error", "message": "SECRETS_MASTER_KEY не настроен на сервере"}), 200
    _log_audit("integration_key_set", {"env_key": env_key})
    return jsonify({"status": "ok", "masked": secrets_crypto.mask_value(value)})


@app.route("/api/integrations/<env_key>", methods=["DELETE"])
def api_integrations_delete(env_key):
    known = {item["env_key"] for item in INTEGRATIONS_REGISTRY}
    if env_key not in known:
        return jsonify({"status": "error", "message": "неизвестная интеграция"}), 404
    delete_secret(env_key)
    _log_audit("integration_key_deleted", {"env_key": env_key})
    return jsonify({"status": "ok"})


@app.get("/miniapp-spa")
@app.get("/miniapp-spa/")
@require_telegram
def miniapp_spa_index():
    """Serve the Mini App SPA index page with API_SECRET injected."""
    index_path = MINIAPP_DIR / "index.html"
    if not index_path.exists():
        return "<h1>Mini App not found</h1>", 404
    html = index_path.read_text(encoding="utf-8")
    html = html.replace('{{API_SECRET}}', API_SECRET)
    return Response(html, mimetype="text/html")

@app.get("/miniapp-spa/<path:filepath>")
def miniapp_spa_static(filepath):
    """Serve static assets for the Mini App SPA.

    No initData check here: browsers do not send custom headers when loading
    <link> and <script> resources, so requiring it would break every screen.
    These files contain no user data — the pages that do remain protected.
    """
    file_path = (MINIAPP_DIR / filepath).resolve()
    if not str(file_path).startswith(str(MINIAPP_DIR.resolve())):
        return "<h1>Not found</h1>", 404
    if not file_path.exists() or not file_path.is_file():
        return "<h1>Not found</h1>", 404
    ext = file_path.suffix
    mimes = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
             ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json"}
    return Response(file_path.read_bytes(), mimetype=mimes.get(ext, "application/octet-stream"))

# ══════════════════════════════════════════════════════════════════════
#  LZ DAILY REPORT — GitHub scan + LLM analysis + Admin delivery
# ══════════════════════════════════════════════════════════════════════

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN_METALOGOS", "")
GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    GITHUB_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# Queries for GitHub scanning — tuned to Fosved's tech stack
# Dates are dynamic: search repos updated/created in last 14 days
def _build_github_queries():
    """Build GitHub search queries for Fosved's tech stack."""
    return [
        "LLM agent framework language:python stars:>10",
        "telegram bot AI assistant python stars:>5",
        "Rust DSL parser interpreter stars:>5",
        "multi-agent LLM office automation stars:>3",
        "RAG retrieval augmented python stars:>10",
        "mcp model context protocol tool stars:>5",
        "mem0 mem0ai agent memory stars:>5",
        "Flask LLM proxy failover stars:>3",
    ]

# Repos to watch for new releases
GITHUB_WATCH_RELEASES = [
    "moorcheh-ai/memanto",
    "langchain-ai/langchain",
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
]


def _github_search(query, sort="updated", per_page=5):
    """Search GitHub repos, return list of dicts. Works without token (public API)."""
    try:
        params = {"q": query, "sort": sort, "order": "desc", "per_page": per_page}
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN and not GITHUB_TOKEN.startswith("["):
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        resp = http_requests.get(
            "https://api.github.com/search/repositories",
            headers=headers, params=params, timeout=15
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            return [{
                "name": r["full_name"],
                "desc": (r.get("description") or "")[:120],
                "stars": r.get("stargazers_count", 0),
                "lang": r.get("language", ""),
                "updated": r.get("updated_at", "")[:10],
                "url": r.get("html_url", ""),
                "created": r.get("created_at", "")[:10],
            } for r in items]
        elif resp.status_code == 403:
            log.warning(f"GitHub API rate limited: {query[:50]}")
            return []
        else:
            log.warning(f"GitHub search {resp.status_code}: {query[:50]}")
            return []
    except Exception as e:
        log.error(f"GitHub search error: {e}")
        return []


def _github_releases(repo_full_name):
    """Get latest 3 releases for a repo. Works without token."""
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN and not GITHUB_TOKEN.startswith("["):
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        resp = http_requests.get(
            f"https://api.github.com/repos/{repo_full_name}/releases?per_page=3",
            headers=headers, timeout=10
        )
        if resp.status_code == 200:
            return [{
                "repo": repo_full_name,
                "tag": r.get("tag_name", ""),
                "name": r.get("name", ""),
                "body": (r.get("body") or "")[:200],
                "date": r.get("published_at", "")[:10],
                "url": r.get("html_url", ""),
            } for r in resp.json() if not r.get("draft", False)]
        return []
    except Exception as e:
        log.error(f"GitHub releases error for {repo_full_name}: {e}")
        return []


@app.get("/scheduler/lz-daily-test")
def scheduler_lz_daily_test():
    """Безопасная проверка через обычную ссылку в браузере — GET, по умолчанию
    dry_run=True принудительно, никаких побочных эффектов. Добавь
    ?really_write=yes_i_mean_it к ссылке, чтобы один раз проверить настоящую
    запись в память — так же, как это делает реальный cron (dry_run=False),
    но с основного веб-сервиса, а не с отдельного Cron Job сервиса Render.
    Так можно отличить 'фикс не сработал' от 'cron-сервис не задеплоил новый код'."""
    really_write = request.args.get("really_write") == "yes_i_mean_it"
    return scheduler_lz_daily_core(dry_run=not really_write, owner_id=os.environ.get("OWNER_TELEGRAM_ID", ""))


@app.post("/scheduler/lz-daily")
def scheduler_lz_daily():
    """
    LZ Daily Report: scan GitHub → LLM analysis → save to memory → return report.
    Called by /cron/lz-daily or manually.
    """
    d = request.get_json(force=True) or {}
    owner_id = d.get("owner_id", os.environ.get("OWNER_TELEGRAM_ID", ""))
    dry_run = d.get("dry_run", False)
    return scheduler_lz_daily_core(dry_run=dry_run, owner_id=owner_id)


def scheduler_lz_daily_core(dry_run, owner_id):
    try:
        # ── Phase 1: GitHub Scan (direct API) ─────────────────
        log.info("LZ Daily: starting GitHub scan")
        all_repos = []
        seen = set()
        for q in _build_github_queries():
            repos = _github_search(q, per_page=3)
            time.sleep(1)
            for r in repos:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    all_repos.append(r)

        # Check watched repos for new releases
        all_releases = []
        seen_release_keys = set()  # dedup by (repo, tag) across runs
        for repo in GITHUB_WATCH_RELEASES:
            releases = _github_releases(repo)
            time.sleep(1)
            for r in releases:
                rkey = f"{r['repo']}@{r['tag']}"
                if rkey not in seen_release_keys:
                    seen_release_keys.add(rkey)
                    all_releases.append(r)

        github_ok = bool(all_repos or all_releases)
        if not github_ok:
            log.warning("LZ Daily: GitHub API returned 0 results, will use LLM fallback")

        # Also check lz_monitors table for custom topics
        monitor_topics = []
        try:
            monitors = _query("SELECT query FROM lz_monitors WHERE frequency = 'daily'", fetch=True)
            monitor_topics = [m["query"] for m in monitors] if monitors else []
        except Exception:
            pass  # Table may not exist yet (created by mlog InitDB)

        scan_summary = {
            "repos_found": len(all_repos),
            "releases_found": len(all_releases),
            "monitors_active": len(monitor_topics),
            "github_api_ok": github_ok,
        }

        # ── Phase 1.5: Collect world news from news_cache (RSS + Tavily + GDELT) ──
        world_news_text = ""
        try:
            news_rows = _query("""SELECT source, title, summary, url, category, published
                                  FROM news_cache
                                  WHERE collected > datetime('now', '-24 hours')
                                  ORDER BY published DESC LIMIT 20""", fetch=True)
            if news_rows:
                cats_order = {"tech": 0, "science": 1, "geopolitics": 2, "news_ru": 3, "news_en": 4, "finance": 5}
                news_rows.sort(key=lambda r: (cats_order.get(r[4], 9), r[5] or ""))
                world_news_text = f"=== МИРОВЫЕ НОВОСТИ И СОБЫТИЯ ({len(news_rows)} за 24ч) ===\n\n"
                for nr in news_rows:
                    src, title, summary, url, cat, pub = nr
                    entry = f"[{src}] {title}\n"
                    if url:
                        entry += f"  Ссылка: {url}\n"
                    if summary and summary != title:
                        entry += f"  {summary[:200]}\n"
                    if pub:
                        entry += f"  Дата: {pub[:10]}\n"
                    world_news_text += entry + "\n"
        except Exception as e:
            log.warning(f"LZ Daily: world news query failed: {e}")

        # Count world news items
        news_count = len(world_news_text.split("[")) - 1 if world_news_text else 0

        # Update scan_summary with news count
        scan_summary["world_news"] = news_count

        # ── Phase 2: LLM Analysis ─────────────────────────────
        lz_prompt = get_dept_prompt("lz")

        if github_ok or world_news_text:
            # Direct API worked — analyze the data we collected
            repos_text = ""
            for i, r in enumerate(all_repos[:15], 1):
                repos_text += f"{i}. {r['name']} ({r['stars']}★, {r['lang']}) — {r['desc']}\n   {r['url']}\n"
            releases_text = ""
            for r in all_releases:
                releases_text += f"- {r['repo']} {r['tag']}: {r['name']} ({r['date']})\n  {r['body']}\n  {r['url']}\n"
            monitors_text = ""
            if monitor_topics:
                monitors_text = "Custom monitors: " + ", ".join(monitor_topics)

            # Build world news section for prompt
            news_section = ""
            if world_news_text:
                news_section = f"\n{world_news_text}\n"

            analysis_messages = [
                {"role": "system", "content": lz_prompt + "\n\n"
                 "Ты — Лаборатория Загадок Фосвед Офиса. Задача: проанализировать ежедневный скан мира.\n\n"
                 "ТВОЯ КЛЮЧЕВАЯ РОЛЬ: отобрать НОВИНКИ и СОБЫТИЯ, которые Админ должен знать.\n\n"
                 "Структура отчёта:\n"
                 "1. 🔥 Тренды и находки дня (технологии, наука, геополитика) — с disrupting potential 1-10\n"
                 "2. 📦 Новые релизы и обновления — что вышло\n"
                 "3. 🌍 Ключевые мировые события — экономика, политика, breakthrough\n"
                 "4. 💡 Рекомендации — что Админу стоит изучить и почему\n"
                 "5. 📊 Статистика скана\n\n"
                 "ПРАВИЛО ССЫЛОК: для КАЖДОГО упомянутого проекта/события ОБЯЗАТЕЛЬНО включай прямую ссылку на источник в формате: https://...\n"
                 "Используй ТОЛЬКО ссылки из предоставленных данных. Не придумывай ссылки.\n\n"
                 "Фильтруй: релевантное для AI-офиса, технологий, мировых событий.\n"
                 "Язык: русский."},
                {"role": "user", "content": f"Данные скана за {datetime.utcnow().isoformat()[:10]}:\n\n"
                 f"=== НОВЫЕ РЕПОЗИТОРИИ ({len(all_repos)} найдено) ===\n"
                 f"{repos_text}\n\n"
                 f"=== НОВЫЕ РЕЛИЗЫ ({len(all_releases)}) ===\n"
                 f"{releases_text}\n\n"
                 f"{news_section}"
                 f"{monitors_text}"}
            ]
        else:
            # GitHub API failed — but we may have world news from news_cache
            log.info("LZ Daily: GitHub API failed, using available data")
            news_section = ""
            if world_news_text:
                news_section = f"\n{world_news_text}\n"
            analysis_messages = [
                {"role": "system", "content": lz_prompt + "\n\n"
                 "Ты — Лаборатория Загадок Фосвед Офиса. Проведи ежедневный обзор новинок и событий.\n\n"
                 "Структура отчёта:\n"
                 "1. 🔥 Тренды и находки дня (технологии, наука, геополитика) — с disrupting potential 1-10\n"
                 "2. 🌍 Ключевые мировые события — экономика, политика, breakthrough\n"
                 "3. 💡 Рекомендации Админу\n\n"
                 "ПРАВИЛО ССЫЛОК: для КАЖДОГО упомянутого проекта/события ОБЯЗАТЕЛЬНО включай прямую ссылку на источник.\n"
                 "Используй ТОЛЬКО ссылки из предоставленных данных. Если данных нет — укажи поисковый запрос.\n\n"
                 "Язык: русский."},
                {"role": "user", "content": f"Сделай ежедневный обзор новинок и событий за {datetime.utcnow().isoformat()[:10]}.\n\n"
                 f"{news_section}"
                 f"Фокус: AI, технологии, мировые события, breakthrough.\n\n"
                 f"Для каждого пункта укажи: название, прямую ссылку на источник, что нового, почему важно."}
            ]

        result = call_llm("lz", analysis_messages)
        analysis = result.get("reply", "Analysis failed.")

        # ── Phase 3: Save to DB + Memory (with cross-run dedup) ───────────
        if not dry_run:
            # LZ Dedup: save releases & repos to lz_telegram_posts with update_id
            # update_id format: "gh:{repo}:{tag}" for releases, "gh:repo:{name}" for repos
            # UNIQUE constraint on update_id prevents duplicate entries across scans
            for r in all_releases:
                try:
                    _query(
                        "INSERT OR IGNORE INTO lz_telegram_posts (update_id, channel_id, channel_name, text, date) VALUES (?, ?, ?, ?, ?)",
                        (f"gh:{r.get('repo','')}:{r.get('tag','')}", r.get('repo',''), r.get('repo',''), r.get('body','')[:500], r.get('date',''))
                    )
                except Exception:
                    pass  # update_id column may not exist yet (pre-ALTER TABLE state)
            for r in all_repos:
                try:
                    _query(
                        "INSERT OR IGNORE INTO lz_telegram_posts (update_id, channel_id, channel_name, text, date) VALUES (?, ?, ?, ?, datetime('now'))",
                        (f"gh:repo:{r.get('name','')}", "github", r.get('lang',''), r.get('desc','')[:300])
                    )
                except Exception as e:
                    _log_error(f"lz_telegram_posts insert failed: {e}", source="lz_github", dept="lz", kind="data_loss")

            today_key = f"LZ Daily {datetime.utcnow().isoformat()[:10]}"
            # Check if we already stored today's scan summary
            existing = memory.recall_by_source("lz_daily", limit=5)
            already_today = any(today_key in (e.get("content") or "") for e in existing)
            if not already_today:
                memory.remember(
                    f"{today_key}: {len(all_repos)} repos, {len(all_releases)} releases scanned",
                    "observation", 0.7, "lz_daily"
                )
            # Save top findings as individual memories (dedup by content prefix)
            recent_findings = memory.recall_by_source("lz_daily", limit=100)
            for line in analysis.split("\n"):
                line = line.strip()
                if line.startswith(("1.", "2.", "3.")) and len(line) > 20:
                    prefix = line[:60]
                    already_saved = any(prefix in (e.get("content") or "") for e in recent_findings)
                    if not already_saved:
                        memory.remember(
                            f"LZ находка: {line[:200]}",
                            "observation", 0.8, "lz_daily"
                        )

        # ── Phase 4: Build Report ─────────────────────────────
        report = f"🔍 LZ DAILY REPORT — {datetime.utcnow().isoformat()[:10]}\n"
        report += f"{'=' * 40}\n\n"
        report += analysis
        report += f"\n\n{'─' * 40}\n"
        report += f"Скан: {len(all_repos)} repos, {len(all_releases)} releases, {news_count} новостей, {len(monitor_topics)} monitors\n"
        report += f"Provider: {result.get('provider', '?')} | Tokens: {result.get('tokens_in', 0)}+{result.get('tokens_out', 0)}"

        # ── Phase 5: Send to Owner (Admin) ────────────────────
        msg_id = None
        if owner_id and not dry_run:
            if len(report) > 1500:
                msg_id = _tg_send_report_with_button(owner_id, report)
            else:
                msg_id = _tg_send_message(owner_id, report)

        _log_audit("lz_daily_report", {
            "repos": len(all_repos), "releases": len(all_releases),
            "world_news": news_count, "monitors": len(monitor_topics),
            "provider": result.get("provider"),
            "msg_id": msg_id, "dry_run": dry_run
        })

        return jsonify({
            "status": "ok",
            "report": report,
            "scan": scan_summary,
            "msg_id": msg_id,
            "sent_to": owner_id if not dry_run else None,
        })

    except Exception as e:
        log.error(f"lz_daily_report error: {e}")
        _log_audit("lz_daily_report_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/scheduler/admin-daily")
def scheduler_admin_daily():
    """
    Admin Daily Report: comprehensive report combining:
    - Night cycle results (from kv)
    - Memory maintenance summary
    - LZ daily findings
    - System health
    Sent to owner.
    """
    d = request.get_json(force=True) or {}
    owner_id = d.get("owner_id", os.environ.get("OWNER_TELEGRAM_ID", ""))

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        parts = []

        # 1. Night cycle summary (if available)
        night_summary = ""  # Would need to read from mlog kv — call mlog internal
        parts.append(f"📅 АДМИН ДAILY REPORT — {today}")
        parts.append("=" * 40)

        # 2. Memory stats
        mem_stats = memory.stats()
        parts.append(f"\n🧠 ПАМЯТЬ: {mem_stats['total_active']} активных записей")
        for t, info in sorted(mem_stats['by_type'].items(), key=lambda x: -x[1]['count'])[:5]:
            parts.append(f"  {t}: {info['count']} (avg conf {info['avg_confidence']})")

        # 3. Memory conflicts
        conflicts = memory.detect_conflicts()
        if conflicts:
            parts.append(f"\n⚠️ КОНФЛИКТЫ: {len(conflicts)}")
            for c in conflicts[:3]:
                parts.append(f"  [{c['type']}] {c['memory_a']['content'][:50]} vs {c['memory_b']['content'][:50]}")

        # 4. Memory maintenance
        maint = memory.nightly_maintenance()
        parts.append(f"\n🔧 MEMORY MAINTENANCE:\n{maint}")

        # 5. LZ daily findings
        lz_findings = memory.recall("LZ Daily", type_filter="observation", limit=3)
        if lz_findings:
            parts.append(f"\n🔍 LZ ПОСЛЕДНИЕ НАХОДКИ:")
            for f in lz_findings:
                ts = time.strftime('%m-%d', time.localtime(f['created_at']))
                parts.append(f"  [{ts}] {f['content'][:100]}")

        # 6. System metrics
        yesterday = (now - timedelta(days=1)).isoformat()[:10] + "T00:00:00"
        metrics = _collect_metrics_for_period(yesterday, today + "T00:00:00")
        parts.append(f"\n📊 МЕТРИКИ (вчера):")
        tasks_total = sum(metrics.get("tasks", {}).values())
        reports_total = sum(metrics.get("reports", {}).values())
        parts.append(f"  Tasks: {tasks_total} | Reports: {reports_total}")

        # 7. Open issues from night cycle
        f_cnt, p_cnt = 0, 0
        try:
            findings = _query(
                "SELECT COUNT(*) as cnt FROM admin_findings WHERE status = 'open'", fetch=True
            )
            proposals = _query(
                "SELECT COUNT(*) as cnt FROM admin_proposals WHERE status = 'pending'", fetch=True
            )
            if findings and proposals:
                f_cnt = findings[0].get("cnt", 0) if isinstance(findings[0], dict) else 0
                p_cnt = proposals[0].get("cnt", 0) if isinstance(proposals[0], dict) else 0
        except Exception:
            pass  # Tables may not exist yet (created by mlog InitDB)
        if f_cnt or p_cnt:
            parts.append(f"\n📋 АДМИН: {f_cnt} open issues, {p_cnt} pending proposals")

        report = "\n".join(parts)

        # Send to owner
        if len(report) > 2000:
            msg_id = _tg_send_report_with_button(owner_id, report)
        else:
            msg_id = _tg_send_message(owner_id, report)

        _log_audit("admin_daily_report", {"owner_id": owner_id, "msg_id": msg_id, "chars": len(report)})

        return jsonify({"status": "ok", "report": report, "msg_id": msg_id})

    except Exception as e:
        log.error(f"admin_daily_report error: {e}")
        _log_audit("admin_daily_report_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


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
#  GITHUB FILE PUSH ENDPOINT — for project pipeline
# ══════════════════════════════════════════════════════════════════════

_GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
_GITHUB_HEADERS = {'Authorization': f'token {_GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'} if _GITHUB_TOKEN else {}


def _parse_github_repo(repo_url):
    """Extract owner/repo from GitHub URL or 'owner/repo' string."""
    repo_url = repo_url.strip().rstrip('/')
    # Handle 'https://github.com/owner/repo' or 'github.com/owner/repo'
    if 'github.com/' in repo_url:
        parts = repo_url.split('github.com/')[-1].split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
    # Handle 'owner/repo' format
    parts = repo_url.split('/')
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, None


@app.route('/github/push-file', methods=['POST'])
def github_push_file():
    """Push a single file to GitHub repo via Contents API.
    Request: {repo, path, content, message?, branch?}
    Returns: {status, sha?, url?, error?}"""
    if not _GITHUB_TOKEN:
        return jsonify({'status': 'error', 'error': 'GITHUB_TOKEN not set'}), 400
    d = request.get_json(force=True) or {}
    repo = d.get('repo', '').strip()
    path = d.get('path', '').strip()
    content = d.get('content', '')
    message = d.get('message', f'Add {path}').strip()
    branch = d.get('branch', 'main').strip()
    if not repo or not path or content is None:
        return jsonify({'status': 'error', 'error': 'repo, path, content required'}), 400
    owner, repo_name = _parse_github_repo(repo)
    if not owner:
        return jsonify({'status': 'error', 'error': f'Cannot parse repo: {repo}'}), 400
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/contents/{path}'
    # Check if file exists (need SHA for update)
    sha = None
    try:
        check = http_requests.get(api_url, headers=_GITHUB_HEADERS, params={'ref': branch}, timeout=15)
        if check.status_code == 200:
            sha = check.json().get('sha')
    except Exception as e:
        _log_error(f"github pre-check for branch {branch} failed: {e}", source="lz_push", dept="lz", kind="external")
    # Create/update file
    import base64
    payload = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
        'branch': branch,
    }
    if sha:
        payload['sha'] = sha
    try:
        resp = http_requests.put(api_url, json=payload, headers=_GITHUB_HEADERS, timeout=30)
        data = resp.json()
        if resp.status_code in (200, 201):
            log.info(f'GitHub push OK: {owner}/{repo_name}/{path}')
            return jsonify({'status': 'ok', 'sha': data.get('content', {}).get('sha'), 'url': data.get('content', {}).get('html_url')})
        else:
            log.error(f'GitHub push failed: {resp.status_code} {data}')
            return jsonify({'status': 'error', 'error': data.get('message', f'HTTP {resp.status_code}')})
    except Exception as e:
        log.error(f'GitHub push error: {e}')
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  OSINT ENDPOINT — Aliens Eye 840+ platforms
# ══════════════════════════════════════════════════════════════════════

@app.route('/lz/osint', methods=['POST'])
def lz_osint():
    """OSINT scan via Aliens Eye. Owner-only, rate-limited."""
    import time as _time
    d = request.get_json(force=True) or {}
    username = d.get('username', '').strip()
    level = d.get('level', 'basic')
    tor = d.get('tor', False)
    sites = d.get('sites', None)
    chat_id = str(d.get('chat_id', ''))
    caller_id = str(d.get('caller_id', ''))

    if not username:
        return jsonify({'error': 'Username required'}), 400

    # Owner-only check
    owner_id = os.environ.get('OWNER_TELEGRAM_ID', '')
    if owner_id and caller_id and caller_id != owner_id:
        _log_audit('lz_osint_denied', {'caller_id': caller_id, 'username': username}, 'lz')
        return jsonify({'error': 'OSINT доступен только владельцу'}), 403

    # Rate limit
    now = _time.time()
    last = _osint_last_time.get(chat_id, 0)
    if now - last < OSINT_RATE_LIMIT:
        wait = int(OSINT_RATE_LIMIT - (now - last))
        return jsonify({'error': f'Rate limit: подождите {wait} сек между сканами'}), 429
    _osint_last_time[chat_id] = now

    # Typing indicator
    try:
        _tg_send_message(chat_id, f"🔍 Сканирую {username} по 840+ платформам... (30-120 сек)")
    except Exception as e:
        _log_error(f"osint notice send failed: {e}", source="osint", dept="system", kind="external")

    # Scan
    result = scan_osint(username, level=level, tor=tor, sites=sites)

    if 'error' in result:
        _log_audit('lz_osint_error', {'username': username, 'error': result['error']}, 'lz')
        return jsonify({'response': f"Ошибка OSINT: {result['error']}\n\n{OSINT_DISCLAIMER}", 'osint_data': result, 'dept': 'lz'}), 500

    # LLM analysis
    lz_profile = CONDENSED_PROMPTS.get('lz', '')
    analysis_prompt = f"""{lz_profile}

Проанализируй результаты OSINT-сканирования username "{username}":

Найдено: {result['found']} платформ
Под вопросом: {result['maybe']} платформ
Просканировано: {result['total_scanned']} платформ
Время: {result['scan_time']}

Платформы где найден:
{json.dumps(result['platforms'], indent=2, ensure_ascii=False)}

Под вопросом:
{json.dumps(result['uncertain'], indent=2, ensure_ascii=False)}

Анализируй:
1. Цифровой профиль — кто этот человек судя по платформам?
2. Категоризация активности (tech/social/professional/media)
3. Аномалии — отсутствие на ожидаемых платформах
4. Противоречия между профилями
5. Уровень цифровой гигиены (много следов = низкая, мало = высокая)
6. [ФАКТ] для подтверждённых находок, [ИНТЕРПРЕТАЦИЯ] для выводов

{OSINT_DISCLAIMER}"""

    llm_result = _call_llm_with_failover(analysis_prompt, 'lz')
    analysis = llm_result.get('reply', 'Ошибка LLM-анализа') if isinstance(llm_result, dict) else str(llm_result)

    # Token tracking
    t_in = llm_result.get('tokens_in', 0) if isinstance(llm_result, dict) else 0
    t_out = llm_result.get('tokens_out', 0) if isinstance(llm_result, dict) else 0
    prov = llm_result.get('provider', '?') if isinstance(llm_result, dict) else '?'
    now_iso = datetime.utcnow().isoformat()
    _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
           (prov, 'osint-analysis', t_in, t_out, 0, 'lz', now_iso))

    _log_audit('lz_osint', {
        'username': username, 'found': result['found'], 'maybe': result['maybe'],
        'total': result['total_scanned'], 'scan_time': result['scan_time']
    }, 'lz')

    return jsonify({
        'response': analysis,
        'osint_data': result,
        'dept': 'lz',
        'disclaimer': OSINT_DISCLAIMER
    })

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

    def _insert_fact(content, confidence):
        _query(
            "INSERT INTO facts (dept, chat_id, content, status, source_dialog_ids, confidence, created_at, updated_at) "
            "VALUES (?, '0', ?, 'active', ?, ?, ?, ?)",
            (dept, str(content)[:500], source_ids, max(0.0, min(1.0, float(confidence))), now, now))

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
    return jsonify({"status": "ok", "totals": totals, "backup": backup_status, "results": results})


# ── FO-005: golden-set eval-регрессий по департаментам (issue #65) ───────
# Ночной прогон: каждый департамент на golden-наборе, скор = формат-правила
# + llm_verifier; тренд — в dept_metrics и трейсах FO-004; падение — алерт.

_GOLDEN_DIR = Path(__file__).resolve().parent / "tests" / "golden"
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


# ── Fresh news for mlog BuildContext ──
@app.route("/news/fresh", methods=["POST"])
def news_fresh():
    d = request.get_json(force=True)
    query = d.get("query", "")
    dept = d.get("dept", "")
    limit = int(d.get("limit", 5))
    news = get_fresh_news(query, dept=dept, limit=limit)
    return jsonify({"news": news})


# ── /lz/github-scan endpoint (used by ScanGitHub in lz.mlog) ──
@app.route("/lz/github-scan", methods=["POST"])
def lz_github_scan():
    """Search GitHub repos for LZ. Thin wrapper around _github_search."""
    d = request.get_json(force=True)
    query = d.get("query", "")
    limit = int(d.get("limit", 5))
    if not query:
        return jsonify({"repos": [], "total": 0})
    repos = _github_search(query, per_page=limit)
    text = "\n".join([f"- {r['name']} ({r['stars']}★, {r['lang']}) — {r['desc']}\n  {r['url']}" for r in repos])
    return jsonify({"repos": repos, "total": len(repos), "text": text})


# ── /lz news endpoint ──
@app.route("/lz/diagnose", methods=["GET"])
def lz_diagnose():
    """Честная проверка каждого заявленного источника ЛЗ по отдельности.
    Не переиспользует mlog-паттерны — бьёт напрямую в тот же механизм,
    чтобы результат не зависел от состояния dept/lz.mlog."""
    report = []

    # 1. news_cache — что реально в основе Web/YouTube/Reddit/Science/Social/Telegram
    try:
        rows = _query("SELECT COUNT(*), MAX(collected) FROM news_cache WHERE collected > datetime('now', '-48 hours')", fetch=True)
        cnt = rows[0][0] if rows else 0
        last = rows[0][1] if rows else None
        report.append({
            "source": "news_cache (основа Web/YouTube/Reddit/Science/Social/Telegram-скана)",
            "ok": cnt > 0,
            "detail": f"{cnt} записей за 48ч, последняя: {last or 'нет'}" if cnt else "пусто — сборщик RSS/GDELT не наполнял кэш последние 48ч",
        })
    except Exception as e:
        report.append({"source": "news_cache", "ok": False, "detail": f"ошибка БД: {e}"})

    report.append({
        "source": "YouTube / Reddit / Social (Twitter, TikTok, Instagram) / Telegram-web-поиск",
        "ok": False,
        "detail": "АРХИТЕКТУРНО НЕ РАБОТАЮТ: реализованы как SQL-поиск по news_cache (см. выше), не как обращение к самим платформам. Приписка 'site:reddit.com'/'tiktok' к запросу ищется как слово в заголовках новостных статей — таких статей с этих платформ в кэше нет физически.",
    })

    # 2. GitHub — реальный API
    try:
        gh_token = os.environ.get("GITHUB_TOKEN_METALOGOS", "")
        repos = _github_search("test", per_page=1)
        report.append({
            "source": "GitHub (/lz/github-scan)",
            "ok": isinstance(repos, list),
            "detail": f"токен {'задан' if gh_token else 'НЕ задан (работает по анонимному лимиту 60/час)'}, тестовый запрос вернул {len(repos)} результатов" if isinstance(repos, list) else "функция вернула не список",
        })
    except Exception as e:
        report.append({"source": "GitHub", "ok": False, "detail": f"ошибка: {e}"})

    # 3. Tavily — реальный внешний веб-поиск
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        report.append({"source": "Tavily (живой веб-поиск)", "ok": False, "detail": "TAVILY_API_KEY не задан в окружении"})
    else:
        try:
            r = http_requests.post("https://api.tavily.com/search", json={"api_key": tavily_key, "query": "test", "max_results": 1}, timeout=15)
            report.append({"source": "Tavily (живой веб-поиск)", "ok": r.status_code == 200, "detail": f"HTTP {r.status_code}"})
        except Exception as e:
            report.append({"source": "Tavily (живой веб-поиск)", "ok": False, "detail": f"сеть недоступна или таймаут: {e}"})
        report.append({
            "source": "Tavily — ВАЖНО про LZTavilySearch в dept/lz.mlog",
            "ok": False,
            "detail": "текущая реализация в mlog зовёт api.tavily.com НАПРЯМУЮ, в обход внутреннего прокси 127.0.0.1:4000, которым пользуется весь остальной код — это может быть заблокировано сетевой политикой окружения независимо от валидности ключа. Плюс вызов без try — при любом сбое падает целиком, не отвечает мягко.",
        })

    # 4. Telegram-мониторинг каналов
    try:
        rows = _query("SELECT COUNT(*) FROM lz_channels WHERE status='active'", fetch=True)
        cnt = rows[0][0] if rows else 0
        report.append({"source": "lz_channels (список отслеживаемых Telegram-каналов)", "ok": cnt > 0, "detail": f"{cnt} активных каналов" if cnt else "таблица пуста или не существует — каналов не добавлено ни одного"})
    except Exception as e:
        report.append({"source": "lz_channels", "ok": False, "detail": f"таблица недоступна: {e}"})
    report.append({
        "source": "LZTelegramSearch — ВАЖНО",
        "ok": False,
        "detail": "гарантированно падает при каждом вызове: использует db_execute() для SELECT-запроса вместо query(), без try — 'Execute returned results, did you mean to call query?'. Даже после починки — нет реального механизма чтения постов из Telegram-каналов, модель получит пустой список и будет придумывать анализ несуществующих постов.",
    })

    # 5. scan_logs — используется LZTavilySearch для логирования
    try:
        _query("SELECT COUNT(*) FROM scan_logs", fetch=True)
        report.append({"source": "scan_logs", "ok": True, "detail": "таблица существует"})
    except Exception as e:
        report.append({"source": "scan_logs", "ok": False, "detail": f"таблица не создана нигде в app.mlog — INSERT в LZTavilySearch падает: {e}"})

    # 6. Darknet — честно заявлен недоступным в самом коде
    report.append({"source": "Darknet", "ok": None, "detail": "код сам честно возвращает '[unavailable — no anonymous access infrastructure]', не пытается притворяться рабочим"})

    # 7. Свежесть памяти LZ Daily — та самая, что попадает в утренний бриф
    try:
        recent = memory.recall_by_source("lz_daily", limit=5)
        if recent:
            dates = [e.get("content", "")[:40] for e in recent]
            report.append({"source": "lz_daily память (последние 5 записей)", "ok": True, "detail": " | ".join(dates)})
        else:
            report.append({"source": "lz_daily память", "ok": False, "detail": "записей нет вообще"})
    except Exception as e:
        report.append({"source": "lz_daily память", "ok": False, "detail": f"ошибка чтения: {e}"})

    ok_count = sum(1 for r in report if r["ok"] is True)
    fail_count = sum(1 for r in report if r["ok"] is False)
    return jsonify({"status": "ok", "working": ok_count, "broken": fail_count, "report": report})


@app.route("/lz/news", methods=["POST"])
def lz_news():
    d = request.get_json(force=True)
    query = d.get("query", "")
    category = d.get("category", None)
    limit = int(d.get("limit", 15))
    if query:
        news = get_fresh_news(query, dept="lz", limit=limit)
    elif category:
        rows = _query("""SELECT source, title, summary, url, published FROM news_cache
                         WHERE category = ? ORDER BY published DESC LIMIT ?""", (category, limit), fetch=True)
        news = "\n".join(f"[{r[0]}] {r[1]}\n  {r[2] or ''}\n  {r[3] or ''}" for r in rows) if rows else "Нет событий"
    else:
        rows = _query("""SELECT source, title, summary, url, published FROM news_cache
                         ORDER BY published DESC LIMIT ?""", (limit,), fetch=True)
        news = "\n".join(f"[{r[0]}] {r[1]}\n  {r[2] or ''}\n  {r[3] or ''}" for r in rows) if rows else "Нет событий"

    lz_prompt = get_dept_prompt("lz")
    analysis_prompt = lz_prompt + "\n\nПроанализируй свежие события. Выдели тренды, аномалии, сигналы. Маркируй [ФАКТ], [ИНТЕРПРЕТАЦИЯ], [СПЕКУЛЯЦИЯ].\n\nПРАВИЛО ССЫЛОК: для КАЖДОГО упомянутого события/факта ОБЯЗАТЕЛЬНО включай прямую ссылку на источник в формате: Ссылка: https://...\nИспользуй ТОЛЬКО ссылки из предоставленных данных (строка Ссылка: ...). Если ссылка отсутствует в данных — не придумывай, просто укажи источник в квадратных скобках.\n\n" + news
    try:
        result = call_llm("lz", [{"role": "user", "content": analysis_prompt}])
        analysis = result.get("reply", "Ошибка анализа")
    except Exception as e:
        analysis = f"Ошибка: {e}"
    return jsonify({"response": analysis, "news_count": news.count("\n")})


# ── News stats ──
@app.route("/news/stats", methods=["GET"])
@require_telegram
def news_stats():
    total = _query("SELECT COUNT(*) FROM news_cache", fetch=True)[0][0]
    last_24h = _query("SELECT COUNT(*) FROM news_cache WHERE collected > datetime('now', '-24 hours')", fetch=True)[0][0]
    by_source = _query("SELECT source, COUNT(*) as c FROM news_cache GROUP BY source ORDER BY c DESC LIMIT 10", fetch=True)
    by_category = _query("SELECT category, COUNT(*) as c FROM news_cache GROUP BY category ORDER BY c DESC", fetch=True)
    return jsonify({"total": total, "last_24h": last_24h,
                    "by_source": {r[0]: r[1] for r in by_source},
                    "by_category": {r[0]: r[1] for r in by_category}})


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


# ══════════════════════════════════════════════════════════════════════
#  NEWS MONITORING: RSS + GDELT + Telegram channels
# ══════════════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "ria": {"url": "https://ria.ru/export/rss2/archive/index.xml", "category": "news_ru", "language": "ru", "name": "РИА Новости"},
    "tass": {"url": "https://tass.ru/rss/v2.xml", "category": "news_ru", "language": "ru", "name": "ТАСС"},
    "rbk": {"url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "category": "news_ru", "language": "ru", "name": "РБК"},
    "interfax": {"url": "https://www.interfax.ru/rss.asp", "category": "news_ru", "language": "ru", "name": "Интерфакс"},
    "kommersant": {"url": "https://www.kommersant.ru/RSS/news.xml", "category": "news_ru", "language": "ru", "name": "Коммерсантъ"},
    "reuters": {"url": "https://feeds.reuters.com/reuters/topNews", "category": "news_en", "language": "en", "name": "Reuters"},
    "bbc": {"url": "http://feeds.bbci.co.uk/news/world/rss.xml", "category": "news_en", "language": "en", "name": "BBC World"},
    "techcrunch": {"url": "https://techcrunch.com/feed/", "category": "tech", "language": "en", "name": "TechCrunch"},
    "theverge": {"url": "https://www.theverge.com/rss/index.xml", "category": "tech", "language": "en", "name": "The Verge"},
    "hackernews": {"url": "https://hnrss.org/frontpage", "category": "tech", "language": "en", "name": "Hacker News"},
    "arxiv_ai": {"url": "https://rss.arxiv.org/rss/cs.AI", "category": "science", "language": "en", "name": "arXiv AI"},
    "arxiv_cl": {"url": "https://rss.arxiv.org/rss/cs.CL", "category": "science", "language": "en", "name": "arXiv NLP"},
    "investing_ru": {"url": "https://ru.investing.com/rss/news.rss", "category": "finance", "language": "ru", "name": "Investing.com RU"},
    "foreignaffairs": {"url": "https://www.foreignaffairs.com/rss.xml", "category": "geopolitics", "language": "en", "name": "Foreign Affairs"},
}

GDELT_BASE = "https://api.gdeltproject.org/api/v2"

DEPT_QUERIES = {
    "osp": "geopolitics OR sanctions OR regulation OR war OR election",
    "lz": "artificial intelligence OR quantum computing OR disruption OR breakthrough",
    "finance": "economy OR inflation OR GDP OR stock market OR cryptocurrency",
    "legal": "legislation OR court OR GDPR OR compliance OR lawsuit",
    "marketing": "consumer trends OR advertising OR social media OR brand",
    "engineering": "infrastructure OR energy OR construction OR nuclear OR solar",
}

DEPT_CATEGORIES = {
    "osp": ("news_ru", "geopolitics", "news_en"),
    "lz": ("tech", "science"),
    "finance": ("finance",),
    "legal": ("geopolitics", "news_ru"),
    "marketing": ("tech", "news_en"),
}


# ── Tavily collection (merged into cron_collect_news, no extra cron slot needed) ──
def collect_tavily():
    """Collect real-time web results via Tavily API. Uses same DEPT_QUERIES as GDELT."""
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        return 0
    collected = 0
    for dept, query in DEPT_QUERIES.items():
        try:
            resp = http_requests.post("https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query,
                      "search_depth": "basic", "max_results": 5,
                      "days": 1}, timeout=15)
            if resp.status_code != 200:
                continue
            for r in resp.json().get("results", []):
                title = r.get("title", "").strip()
                url = r.get("url", "").strip()
                summary = re.sub(r"<[^>]+>", "", r.get("content", ""))[:500]
                if not title:
                    continue
                content_hash = hashlib.md5((title + url).encode()).hexdigest()
                cat = DEPT_CATEGORIES.get(dept, ("tech",))[0]
                try:
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (f"Tavily", title, summary, url, cat, "en", None, content_hash))
                    collected += 1
                except Exception as e:
                    _log_error(f"tavily news insert failed: {e}", source="collector", dept="news", kind="data_loss")
        except Exception as e:
            _log_audit("tavily_error", {"dept": dept, "error": str(e)[:100]}, "collector")
    if collected:
        _log_audit("tavily_collected", {"collected": collected}, "collector")
    return collected


def enrich_news_with_fulltext(limit=5):
    """Extract full text from top news URLs missing body content.
    Merges into existing collect cycle — no extra cron needed."""
    rows = _query("""SELECT id, url FROM news_cache
                      WHERE (summary IS NULL OR length(summary) < 100)
                      AND url IS NOT NULL AND url != ''
                      AND collected > datetime('now', '-6 hours')
                      ORDER BY published DESC LIMIT ?""", (limit,), fetch=True)
    enriched = 0
    for row_id, url in (rows or []):
        try:
            resp = http_requests.get(url, timeout=10, headers={"User-Agent": "FosvedBot/1.0"})
            if resp.status_code == 200 and len(resp.text) > 200:
                tmp = f"/tmp/news_enrich_{row_id}.html"
                with open(tmp, "w", encoding="utf-8", errors="replace") as f:
                    f.write(resp.text)
                text = doc_extract.extract_text(tmp, url)
                try: os.remove(tmp)
                except Exception as e: log.warning(f"[cleanup] news tmp remove failed: {e}")
                if text and len(text) > 50:
                    summary = text[:800]
                    _query("UPDATE news_cache SET summary = ? WHERE id = ?", (summary, row_id))
                    enriched += 1
        except Exception as e:
            _log_error(f"news enrich failed: {e}", source="collector", dept="news", kind="external")
    if enriched:
        _log_audit("news_enriched", {"enriched": enriched}, "collector")
    return enriched


def collect_rss():
    """Collect from all RSS feeds. Dedup by hash(title+url). TTL 7 days."""
    import feedparser as _fp
    collected, errors = 0, 0
    for feed_id, fc in RSS_FEEDS.items():
        try:
            feed = _fp.parse(fc["url"])
            for entry in feed.entries[:20]:
                title = entry.get("title", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", ""))).strip()
                url = entry.get("link", "").strip()
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if not title:
                    continue
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                content_hash = hashlib.md5((title + url).encode()).hexdigest()
                pub_date = None
                if published:
                    try:
                        pub_date = datetime(*published[:6]).isoformat()
                    except Exception as e:
                        log.warning(f"[collector] bad published date {published}: {e}")
                try:
                    _query("""INSERT OR IGNORE INTO news_cache
                        (source,title,summary,url,category,language,published,hash)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (fc["name"], title, summary, url, fc["category"], fc["language"], pub_date, content_hash))
                    collected += 1
                except Exception as e2:
                    _log_error(f"feedparser news insert failed: {e2}", source="collector", dept="news", kind="data_loss")
        except Exception as e:
            errors += 1
            _log_audit("rss_error", {"feed": feed_id, "error": str(e)[:100]}, "collector")
    _query("DELETE FROM news_cache WHERE collected < datetime('now', '-7 days')")
    _log_audit("rss_collected", {"collected": collected, "errors": errors}, "collector")
    return collected


def collect_gdelt(query=None, language="russian", max_items=25):
    """GDELT DOC API — free, no key."""
    params = {
        "query": query or "Russia OR technology OR AI",
        "mode": "artlist",
        "maxrecords": str(max_items),
        "format": "json",
        "sort": "DateDesc",
        "sourcelang": language,
    }
    try:
        resp = http_requests.get(f"{GDELT_BASE}/doc/doc", params=params, timeout=15)
        if resp.status_code != 200:
            return 0
        data = resp.json()
        articles = data.get("articles", [])
        collected = 0
        for a in articles:
            title = a.get("title", "").strip()
            url = a.get("url", "").strip()
            source = a.get("domain", a.get("sourcecountry", "GDELT"))
            seendate = a.get("seendate", "")
            tone = a.get("tone", 0)
            if not title:
                continue
            content_hash = hashlib.md5((title + url).encode()).hexdigest()
            cat = "geopolitics"
            tl = title.lower()
            if any(w in tl for w in ["technology", "ai", "artificial", "технолог", "искусствен"]):
                cat = "tech"
            elif any(w in tl for w in ["economy", "экономик", "market", "рынок", "billion", "млрд"]):
                cat = "finance"
            elif any(w in tl for w in ["science", "наук", "research", "исследован"]):
                cat = "science"
            try:
                _query("""INSERT OR IGNORE INTO news_cache
                    (source,title,summary,url,category,language,published,relevance_score,hash)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (f"GDELT/{source}", title, f"Tone: {float(tone):.1f}", url, cat,
                     language[:2], seendate, abs(float(tone)), content_hash))
                collected += 1
            except Exception as e:
                _log_error(f"gdelt news insert failed: {e}", source="collector", dept="news", kind="data_loss")
        _log_audit("gdelt_collected", {"collected": collected}, "collector")
        return collected
    except Exception as e:
        _log_audit("gdelt_error", {"error": str(e)[:200]}, "collector")
        return 0


def collect_gdelt_themes():
    total = 0
    for dept, query in DEPT_QUERIES.items():
        total += collect_gdelt(query=query, language="russian", max_items=10)
        total += collect_gdelt(query=query, language="english", max_items=10)
    return total


def _extract_keywords(text):
    stop = {"и", "в", "на", "с", "по", "для", "от", "что", "как", "не", "это", "the", "a", "an", "in", "on", "for", "of", "and", "to", "is", "it"}
    words = re.findall(r"[а-яёa-z]{3,}", text.lower())
    return [w for w in words if w not in stop][:10]


def get_fresh_news(query, dept=None, limit=5, max_chars=1500):
    """Get recent news relevant to query. Used by BuildContext in mlog."""
    keywords = _extract_keywords(query)
    conditions, params = [], []
    for kw in keywords[:5]:
        conditions.append("(title LIKE ? OR summary LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%"])
    where = " OR ".join(conditions) if conditions else "1=1"

    cats = DEPT_CATEGORIES.get(dept, ("news_ru", "tech", "geopolitics"))
    cat_filter = " OR ".join(["category = ?" for _ in cats])
    params.extend(cats)

    sql = f"""SELECT source, title, summary, url, published, relevance_score
             FROM news_cache WHERE ({where}) AND ({cat_filter})
             AND collected > datetime('now', '-48 hours')
             ORDER BY published DESC LIMIT ?"""
    params.append(limit)
    rows = _query(sql, params, fetch=True)

    if not rows:
        sql2 = f"""SELECT source, title, summary, url, published, relevance_score
                  FROM news_cache WHERE ({cat_filter})
                  AND collected > datetime('now', '-24 hours')
                  ORDER BY published DESC LIMIT ?"""
        rows = _query(sql2, list(cats) + [limit], fetch=True)

    if not rows:
        return ""

    news_text = "=== СВЕЖИЕ СОБЫТИЯ (последние 48ч) ===\n\n"
    current_len = 0
    for r in rows:
        entry = f"[{r[0]}] {r[1]}\n"
        if r[3]:
            entry += f"  Ссылка: {r[3]}\n"
        if r[2] and r[2] != r[1]:
            entry += f"  {r[2][:150]}\n"
        if r[4]:
            entry += f"  Дата: {r[4]}\n"
        entry += "\n"
        if current_len + len(entry) > max_chars:
            break
        news_text += entry
        current_len += len(entry)

    news_text += "=== КОНЕЦ СОБЫТИЙ ===\n"
    return news_text


def get_night_news_digest():
    """Top-5 events over last 12 hours for morning brief."""
    rows = _query("""SELECT source, title, category FROM news_cache
                     WHERE collected > datetime('now', '-12 hours')
                     ORDER BY relevance_score DESC, published DESC LIMIT 5""", fetch=True)
    if not rows:
        return ""
    emoji = {"tech": "🔬", "finance": "💰", "geopolitics": "🌍", "science": "🧪", "news_ru": "📌", "news_en": "📌"}
    digest = "\n📰 Топ события за ночь:\n"
    for r in rows:
        digest += f"  {emoji.get(r[2], '📄')} [{r[0]}] {r[1][:80]}\n"
    return digest


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
    Body: {"module": "statistics", "function": "mean", "args": [[1,2,3,4,5]], "kwargs": {}}
    Returns: {"result": <value>, "type": <python type name>}
    """
    d = request.get_json(force=True) or {}
    module_name = d.get('module', '')
    func_name = d.get('function', '')
    args = d.get('args', [])
    kwargs = d.get('kwargs', {})

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


if __name__ == "__main__":
    log.info(f"Starting LLM Proxy on port {PORT}, DB={DB_FILE}")
    log.info(f"Endpoints: health, detect-dept, ask, rate_cmd, context_cmd, voice-set, "
             f"archive/digest, archive/publish, archive/daily-digest, miniapp, enrich, tg-send, dept-dashboard, office-dashboard, "
             f"expert/chart, tts, stt, scheduler/*, learning/*, audit/recent, search, generate-image, lz/deep-research, lz/osint, memory/*, "
             f"scheduler/watch-sweep, scheduler/indicator-pre-reminders, call-python")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


