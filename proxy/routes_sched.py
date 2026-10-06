"""FO-008: транспорт ч.4 — архив-роуты, планировщики, learning, audit, deep-research.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 4d; наряд #68, стоп-гейт SG-F2).
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

from flask import request, jsonify, Response

from proxy.core import (
    app, log, http_requests,
    _query, _log_audit, _log_error, _write_llm_trace, _get_setting,
    get_secret, DB_PATH, DB_FILE, BASE_DIR, LIB_DIR, CFG_DIR,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ARCHIVE_CHANNEL_ID,
    memory, require_telegram,
    _memorize, RENDER_URL,
    detect_dept, get_dept_prompt, CONDENSED_PROMPTS, FORMAT_INSTRUCTION,
    DEPT_COLORS, DEPT_NAMES, DEPT_HASHTAGS,
    auto_enrich, _has_enricher,
    _collect_metrics_for_period, _format_metrics_text,
)
from proxy.providers import (
    PROVIDERS, COMBO_CHAINS, _breaker, _cfg_cache, call_llm, _call_single_provider,
    TOKEN_COSTS,
)
from proxy.telegram import (
    _MARKER_EMOJI, _ALL_EMOJI, _escape_mdv2, _tg_send_formatted,
    _tg_send_message, _tg_send_voice, _tg_send_report_with_button,
    _tg_get_file, _tg_download_file, _tg_send_photo, _tg_send_document,
    _safe_filename_part, _send_chat_action_loop, _tg_send_chat_action,
)
from proxy.reports import (
    html_lib_escape, strip_html_for_archive, _html_base, _dept_header,
    _status_icon, _dept_kpis, _build_action_bar, ARCHIVE_MONTHS_RU,
    _browse_page, _evidence_badges_css,
)
from proxy.news import get_night_news_digest, get_fresh_news
from proxy.lz_github import scheduler_lz_daily_core, _github_search, scan_osint

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

    # FO-042 (наряд #149): резервный контур FORGE — bundle-бэкап bare-репозиториев
    # + выгрузка forge_* документом. Запуск рядом с брифом — триггер BRIEF-1
    # (надёжный, подтверждён lz-daily); неудачи громкие (строка в брифе), не молчаливые.
    forge_backup_line = ""
    try:
        from proxy.forge_backup import run_forge_backup, store_backup_summary, export_forge_state
        backup_result = run_forge_backup()
        store_backup_summary(backup_result)
        forge_backup_line = backup_result.get("line", "")
        export_forge_state(owner_id)  # документ владельцу; неудача не роняет бриф
    except Exception as e:
        log.warning(f"[morning_brief] forge backup/export failed (non-fatal): {e}")
        forge_backup_line = f"бэкап FORGE: сбой контура ({str(e)[:120]})"

    # FO-043 (наряд #150): недельный срез доли first-try — только по понедельникам
    forge_edit_line = ""
    try:
        if datetime.utcnow().weekday() == 0:
            from proxy.forge_backup import forge_edit_stats_week_line
            forge_edit_line = forge_edit_stats_week_line()
    except Exception as e:
        log.warning(f"[morning_brief] forge edit stats failed (non-fatal): {e}")

    # #486 A.4: раздел «Ключи» — детерминированно (дата/цифры не искажаются
    # пересказом LLM): только проблемы + строка «остальные N — ok»;
    # при всех ok — одна строка; старше 26 ч — честное «не выполнялась»
    keys_line = ""
    try:
        from proxy.key_health import build_morning_line
        keys_line = build_morning_line()
    except Exception as e:
        log.warning(f"[morning_brief] keys line failed (non-fatal): {e}")
        keys_line = ""

    # FO-049 (диспатч #161): недельная метрика нарядной дисциплины — по понедельникам
    narad_stats_line = ""
    try:
        if datetime.utcnow().weekday() == 0:
            from proxy.narad_queue import narad_stats_week_line
            narad_stats_line = narad_stats_week_line()
    except Exception as e:
        log.warning(f"[morning_brief] narad stats failed (non-fatal): {e}")

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

        # Pending narads + FO-047: полная нарядная очередь (бриф показывает
        # жизненный цикл, а не только pending)
        narad_rows = _query("SELECT COUNT(*) as cnt FROM narads WHERE status = 'pending'", fetch=True)
        narads_pending = narad_rows[0]["cnt"] if narad_rows else 0
        try:
            from proxy.narad_queue import queue_counts as _narad_counts
            _nq = _narad_counts()
            narads_queue_line = (f"Нарядная очередь: в ожидании {_nq['pending']}, одобрено {_nq['approved']}, "
                                 f"в очереди {_nq['queued']}, в работе {_nq['in_work']}, "
                                 f"на приёмке {_nq['testing']}, заблокировано {_nq['blocked']}")
        except Exception as nq_err:  # noqa: BLE001 — бриф деградирует к счётчику pending
            log.warning(f"narad queue line failed: {nq_err}")
            narads_queue_line = f"Нарядная очередь: нерешённых {narads_pending}"

        # Recent corrections
        corr_rows = _query("SELECT COUNT(*) as cnt FROM adapt_corrections WHERE created_at > datetime('now', '-24 hours')", fetch=True)
        corrections_24h = corr_rows[0]["cnt"] if corr_rows else 0
        # FO-036 (наряд #134): задачи FORGE от агентов — только proposed,
        # владелец подтверждает пачкой по утреннему брифу (A.5)
        forge_proposed = ""
        fp_count = 0
        try:
            fp_rows = _query(
                "SELECT id, title, project_slug, priority FROM forge_tasks "
                "WHERE status = 'proposed' ORDER BY id LIMIT 8", fetch=True)
            if fp_rows:
                fp_count = len(fp_rows)
                forge_proposed = "\n".join(
                    [f"  - #{r['id']} [{r['priority']}] {r['project_slug']}: {r['title']}" for r in fp_rows])
        except Exception as e:
            log.warning(f"[morning_brief] forge proposed query failed: {e}")
        # FO-038 C.3: FORGE-гейты и замечания — «требует внимания» ежедневно
        forge_attention = ""
        fa_count = 0
        try:
            fg_rows = _query(
                "SELECT id, kind, question FROM forge_gates "
                "WHERE decision IS NULL OR decision = '' ORDER BY id LIMIT 5", fetch=True)
            fr_rows = _query(
                "SELECT COUNT(*) as c FROM forge_remarks WHERE status = 'open'", fetch=True)
            fa_count = len(fg_rows) if fg_rows else 0
            open_remarks = fr_rows[0]["c"] if fr_rows else 0
            if fg_rows or open_remarks:
                lines = [f"  - Гейт #{r['id']} [{r['kind']}]: {r['question'][:100]}" for r in fg_rows]
                if open_remarks:
                    lines.append(f"  - Открытых замечаний: {open_remarks}")
                forge_attention = "\n".join(lines)
        except Exception as e:
            log.warning(f"[morning_brief] forge attention query failed: {e}")

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
{narads_queue_line}
Коррекций за сутки: {corrections_24h}
{metrics_text}

=== FORGE: ЗАДАЧИ ОТ АГЕНТОВ, ЖДУЩИЕ ПОДТВЕРЖДЕНИЯ (proposed) ===
{forge_proposed if forge_proposed else 'Нет предложенных задач'}

=== FORGE: ТРЕБУЕТ ВНИМАНИЯ (гейты и замечания, ежедневно пока не решены) ===
{forge_attention if forge_attention else 'Нет висящих гейтов и замечаний'}

=== FORGE: РЕЗЕРВНЫЙ КОНТУР (bundle-бэкап репозиториев) ===
{forge_backup_line if forge_backup_line else 'Резерв FORGE не выполнялся — проверить контур backup_forge_repos.py'}

=== FORGE: МЕТРИКА ФОРМАТА ПРАВОК (неделя, по понедельникам) ===
{forge_edit_line if forge_edit_line else ''}

=== НАРЯДЫ: МЕТРИКА ДИСЦИПЛИНЫ (неделя, по понедельникам) ===
{narad_stats_line if narad_stats_line else ''}

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

        # FO-042: строка резерва FORGE — точно в бриф (не через LLM, чтобы
        # цифры не искажались пересказом)
        if forge_backup_line:
            brief = brief + "\n\n💾 Резерв FORGE: " + forge_backup_line
        # FO-043: недельный срез first-try — тоже дословно (по понедельникам)
        if forge_edit_line:
            brief = brief + "\n🛠 Правки FORGE: " + forge_edit_line
        # #486 A.4: раздел «Ключи» — дословно из последней проверки
        if keys_line:
            brief = brief + "\n\n" + keys_line

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
    #485 A.4: сообщение открывается детерминированным разделом «Ночная проверка» —
    итогом последнего ночного цикла из admin_night_reports (старше 26 ч —
    честное «не выполнялась с <дата>»), затем комментарий к брифу Яны.
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

        # ── 4.5 #485 A.4: итог последнего ночного цикла ──
        # Ночная проверка пишется NightSlot'ом в admin_night_reports с маркером
        # scan_data='night-slot'. Порог 26 ч: слот 05:00 МСК + запас на сбой/пробуждение.
        night_line = ""
        night_ctx = ""
        try:
            night_rows = _query(
                "SELECT created_at, review_data, health_score, findings_count FROM admin_night_reports "
                "WHERE scan_data = 'night-slot' ORDER BY id DESC LIMIT 1",
                fetch=True,
            )
            if night_rows:
                nr = night_rows[0]
                created_at = str(nr["created_at"] or "")[:16]
                try:
                    info = json.loads(nr["review_data"] or "{}")
                    if not isinstance(info, dict):
                        info = {}
                except (ValueError, TypeError):
                    info = {}
                age_h = None
                try:
                    dt = datetime.strptime(str(nr["created_at"]), "%Y-%m-%d %H:%M:%S")
                    age_h = (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).total_seconds() / 3600.0
                except (ValueError, TypeError):
                    age_h = None
                if age_h is None:
                    night_line = "🌙 Ночная проверка: итог без даты (" + created_at + ")"
                elif age_h > 26.0:
                    night_line = "🌙 Ночная проверка: НЕ выполнялась с " + created_at + " UTC (>26 ч) ⚠️"
                else:
                    status = str(info.get("status") or "?")
                    health = str(info.get("health") or "?")
                    findings = nr["findings_count"] if nr["findings_count"] is not None else "?"
                    summary = str(info.get("summary") or "").strip()
                    night_line = (
                        f"🌙 Ночная проверка ({created_at} UTC): {status}; "
                        f"здоровье: {health}/10; открытых находок: {findings}"
                    )
                    if summary:
                        night_line += "\n" + summary[:400]
                night_ctx = night_line
            else:
                night_line = "🌙 Ночная проверка: ещё не выполнялась (первый ночной цикл после деплоя)"
                night_ctx = night_line
        except Exception as e:
            _log_error(f"night report read failed: {e}", source="admin_brief", dept="admin", kind="db_read")

        # ── 5. Build admin prompt ──
        messages = [
            {"role": "system", "content": admin_prompt + "\n\nТы — Админ Фосвед Офиса. Ты прочитал утренний отчёт Яны и должен дать свой ответ. Твой ответ — это директива на день. Упомяни находки Лаборатории Знаний, если они релевантны. Форматирование: *жирный* для приоритетов и ключевых слов, __подчёркнуто__ для указаний, эмодзи только как маркеры секций. НЕ используй кавычки."},
            {"role": "user", "content": f"""Яна прислала утренний отчёт:

{yana_brief}

{f"=== НАХОДКИ ЛЗ ===\n{lz_context}" if lz_context else ""}
{f"=== СТАТУС ===\n{issues_context}" if issues_context else ""}
{f"=== НОЧНАЯ ПРОВЕРКА (уже в сообщении первым разделом, не дублируй) ===\n{night_ctx}" if night_ctx else ""}

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

        # #485 A.4: раздел «Ночная проверка» — детерминированно ПЕРЕД комментарием
        # (дата/цифры не искажаются пересказом LLM — принцип FO-042/FO-043)
        final_reply = (night_line + "\n\n" + reply) if night_line else reply

        msg_id = _tg_send_formatted(owner_id, final_reply, dept="admin")
        _log_audit("scheduler_admin_morning_reply", {"owner_id": owner_id, "provider": result["provider"], "msg_id": msg_id})

        return jsonify({"status": "ok", "reply": final_reply, "msg_id": msg_id})

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
        _query("INSERT INTO continuous_learning (dept, query, approach, score, created_at) VALUES (?,?,?,?,datetime('now'))",
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

        # #407 A.3: статус в выдаче — ok/refused виден в журнале Mini App
        rows = _query("SELECT id, action, details, timestamp, status FROM audit_log ORDER BY id DESC LIMIT ?", (limit,), fetch=True)

        entries = []
        for r in rows:
            entry = {
                "id": r["id"],
                "action": r["action"],
                "created": r["timestamp"],
                "status": r["status"],
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

