"""FO-008: транспорт ч.5a — /api/*, admin-ua, integrations, miniapp-spa.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 4e; наряд #68, стоп-гейт SG-F2).
"""

import os
import re
import json
import time
import uuid
import subprocess
import threading
import sqlite3
import secrets_crypto
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests as http_requests

from flask import request, jsonify, Response, send_file

from proxy.kg import kg_scan_rebuild, kg_active
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
        kg_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph WHERE valid_to IS NULL", fetch=True)
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
        by_dept = [{"dept": r["dept"], "name": DEPT_NAMES.get(r["dept"], r["dept"]), "cost": round(r["t"], 2), "color": DEPT_COLORS.get(r["dept"], {}).get("accent", "#A8321E")} for r in dept_costs]

        # By provider (month)
        prov_costs = _query("SELECT provider, COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=? GROUP BY provider ORDER BY t DESC", (month_ago,), fetch=True)
        by_provider = [{"provider": r["provider"], "cost": round(r["t"], 2)} for r in prov_costs]

        # FO-025: by_model — срез по моделям с меткой shadow (канарейка видна отдельно)
        model_rows = _query("SELECT model, request_type, COUNT(*) as n, COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=? GROUP BY model, request_type ORDER BY t DESC LIMIT 30", (month_ago,), fetch=True)
        by_model = [{"model": r["model"], "requests": r["n"],
                     "cost": round(r["t"], 4),
                     "shadow": str(r["request_type"] or "").startswith("shadow")} for r in model_rows]

        # Budget
        budget_rows = _query("SELECT value FROM system_settings WHERE key='daily_budget'", fetch=True)
        budget = budget_rows[0]["value"] if budget_rows else "10"

        return jsonify({"status": "ok", "periods": periods, "by_dept": by_dept, "by_provider": by_provider, "by_model": by_model, "budget": budget})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/budget/status")
def api_budget_status():
    """FO-024: срез бюджетов для /budget — spent/limit по департаментам,
    кто в эконом-режиме. Читающий эндпоинт: без алертов и side-effects."""
    try:
        from proxy.budget import status_snapshot
        return jsonify({"status": "ok", **status_snapshot()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/narads")
def api_narads():
    """List narads.

    FORGE-UI-2 (#195): SELECT дополнен dept/priority/in_work_at (колонки схемы FO-046
    уже существуют — миграции нет, только чтение существующей таблицы).
    """
    try:
        rows = _query("SELECT id, title, description, risk_level, status, created_at, approved_at, dept, priority, in_work_at FROM narads ORDER BY id DESC LIMIT 20", fetch=True)
        narads = []
        for r in rows:
            narads.append({
                "id": r["id"], "title": r["title"], "description": r["description"] or "",
                "risk": r["risk_level"], "status": r["status"],
                "created": r["created_at"][:16] if r["created_at"] else "",
                "approved": r["approved_at"][:16] if r["approved_at"] else "",
                "dept": r["dept"] or "", "priority": r["priority"] or "normal",
                "in_work": r["in_work_at"][:16] if r["in_work_at"] else "",
            })
        return jsonify({"status": "ok", "narads": narads})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/narads/<nid>")
def api_narad_detail(nid):
    """FORGE-UI-2 (#195): деталь наряда — только чтение существующих таблиц.

    narads (жизненный цикл: created/approved/in_work/testing/executed,
    план/критерии/вердикт приёмки) + narad_steps (журнал исполнения FO-047,
    ensure_schema создаёт её без миграций). Ни одна запись здесь не меняется.
    """
    try:
        rows = _query(
            "SELECT id, title, description, dept, priority, risk_level, status, plan, acceptance, "
            "test_status, test_log, result, rework_count, created_at, approved_at, in_work_at, "
            "testing_at, executed_at FROM narads WHERE id=? LIMIT 1", (nid,), fetch=True)
        if not rows:
            return jsonify({"status": "error", "message": "наряд не найден"}), 404
        r = rows[0]
        steps = []
        try:
            from proxy.narad_queue import ensure_schema as _ensure_steps
            _ensure_steps()
            step_rows = _query(
                "SELECT status, reply, created_at, updated_at FROM narad_steps "
                "WHERE narad_id=? ORDER BY id ASC LIMIT 50", (nid,), fetch=True)
            for s in step_rows:
                steps.append({
                    "status": s["status"] or "",
                    "reply": (s["reply"] or "")[:400],
                    "created": s["created_at"] or "",
                    "updated": s["updated_at"] or "",
                })
        except Exception as steps_err:  # noqa: BLE001 — журнал деградирует честно, наряд не прячем
            _log_audit("narad_detail_steps_degraded", {"narad_id": nid, "error": str(steps_err)[:120]})
        return jsonify({
            "status": "ok",
            "narad": {
                "id": r["id"], "title": r["title"],
                "description": r["description"] or "",
                "dept": r["dept"] or "", "priority": r["priority"] or "normal",
                "risk": r["risk_level"], "status": r["status"] or "",
                "plan": r["plan"] or "", "acceptance": r["acceptance"] or "",
                "test_status": r["test_status"] or "none",
                "test_log": (r["test_log"] or "")[:600],
                "result": (r["result"] or "")[:600],
                "rework": r["rework_count"] or 0,
                "created": r["created_at"] or "", "approved": r["approved_at"] or "",
                "in_work": r["in_work_at"] or "", "testing": r["testing_at"] or "",
                "executed": r["executed_at"] or "",
            },
            "steps": steps,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/depts/chat")
def api_depts_chat():
    """FORGE-UI-3 (#196): ряд кнопок отделов чата — только чтение существующих
    данных. Порядок: Яна всегда первая; далее отделы, использовавшиеся за
    последние 30 дней, по use_count из dept_activity (таблица существует именно
    для этого, FO-контур RecordUserMessage); затем прочие использованные по
    свежести last_used_at; затем ни разу не использованные. Цвета — из
    DEPT_COLORS (proxy/core.py), без дублирования палитры во фронте.
    Бейджи непрочитанных: last_msg_id из dialog_history + ?seen=dept:id —
    количество сообщений отдела после последней прочитанной отметки фронта.
    """
    try:
        from datetime import datetime, timedelta, timezone
        act = {}
        try:
            rows = _query("SELECT dept, last_used_at, use_count FROM dept_activity", fetch=True)
            act = {r["dept"]: (r["last_used_at"] or "", int(r["use_count"] or 0)) for r in rows}
        except Exception:  # noqa: BLE001 — нет таблицы/БД не готова: порядок деградирует честно
            act = {}
        last_msg = {}
        try:
            rows = _query("SELECT dept, MAX(id) AS m FROM dialog_history GROUP BY dept", fetch=True)
            last_msg = {r["dept"]: int(r["m"] or 0) for r in rows}
        except Exception:  # noqa: BLE001
            last_msg = {}
        seen = {}
        for part in (request.args.get("seen") or "").split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                try:
                    seen[k.strip()] = int(v)
                except ValueError:
                    # битая отметка фронта — не молчим: warning FO-007
                    _log_error(f"depts/chat: malformed seen part skipped: {part[:40]!r}",
                               source="api_depts_chat", dept="admin", kind="input")
        unread = {}
        for dept_id, mark in seen.items():
            if mark and dept_id in DEPT_COLORS:
                try:
                    r = _query("SELECT COUNT(*) AS c FROM dialog_history WHERE dept=? AND id>?",
                               (dept_id, mark), fetch=True)
                    unread[dept_id] = int(r[0]["c"]) if r else 0
                except Exception:  # noqa: BLE001
                    unread[dept_id] = 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        fresh = [d for d in DEPT_COLORS if d != "yana" and act.get(d, ("", 0))[0] and act.get(d, ("", 0))[0] >= cutoff]
        fresh.sort(key=lambda d: (-act.get(d, ("", 0))[1], d))
        stale = [d for d in DEPT_COLORS if d != "yana" and act.get(d, ("", 0))[0] and act.get(d, ("", 0))[0] < cutoff]
        stale.sort(key=lambda d: act.get(d, ("", 0))[0], reverse=True)
        never = sorted(d for d in DEPT_COLORS if d != "yana" and not act.get(d, ("", 0))[0])
        depts = []
        for d in ["yana"] + fresh + stale + never:
            nm = DEPT_NAMES.get(d, d)
            short = (nm.split("·")[0].split("—")[0].strip() or nm)
            c = DEPT_COLORS.get(d, {})
            depts.append({
                "id": d, "name": nm, "short": short,
                "color": c.get("start", ""), "color2": c.get("end", ""),
                "last_used": act.get(d, ("", 0))[0], "uses": act.get(d, ("", 0))[1],
                "last_msg_id": last_msg.get(d, 0), "unread": unread.get(d, 0),
            })
        return jsonify({"status": "ok", "depts": depts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/depts/<dept>/dialog")
def api_dept_dialog(dept):
    """FORGE-UI-3 (#196): лента переписки отдела — чтение dialog_history
    (последний chat_id отдела, последние 50 сообщений, хронологический порядок).
    Это лента переписки, не список диалогов: role='user' → свои пузыри,
    остальные → пузыри отдела."""
    try:
        rows = _query(
            "SELECT id, role, content, created_at FROM dialog_history "
            "WHERE dept=? AND chat_id=(SELECT chat_id FROM dialog_history "
            "WHERE dept=? ORDER BY id DESC LIMIT 1) ORDER BY id DESC LIMIT 50",
            (dept, dept), fetch=True)
        msgs = [{"id": r["id"], "role": r["role"] or "assistant",
                 "content": (r["content"] or "")[:800],
                 "ts": r["created_at"] or ""} for r in reversed(rows)]
        return jsonify({"status": "ok", "messages": msgs})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/dialog/search")
def api_dialog_search():
    """FORGE-UI-3 (#196): глобальный поиск по всем перепискам (dialog_history),
    не только текущий отдел. <2 символов — пустой результат (не греем LIKE)."""
    try:
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"status": "ok", "results": []})
        rows = _query(
            "SELECT id, dept, role, content, created_at FROM dialog_history "
            "WHERE content LIKE ? ORDER BY id DESC LIMIT 30", (f"%{q}%",), fetch=True)
        results = [{"id": r["id"], "dept": r["dept"] or "", "role": r["role"] or "",
                    "content": (r["content"] or "")[:200],
                    "ts": r["created_at"] or ""} for r in rows]
        return jsonify({"status": "ok", "results": results})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/attention")
def api_attention():
    """FORGE-UI-5 (#198): сводка «Требует решения» — только чтение существующих
    данных: открытые гейты forge_gates (decision IS NULL/''), открытые находки
    admin_findings (status='open'), состояние блокировки system_lockdown (общая
    kv system_settings), версия/хеш коммита из реальных данных сборки
    (RENDER_GIT_COMMIT + файл VERSION — пин бинаря mlog)."""
    try:
        gates_count = 0
        gates = []
        try:
            gc = _query("SELECT COUNT(*) AS c FROM forge_gates WHERE decision IS NULL OR decision = ''", fetch=True)
            gates_count = int(gc[0]["c"]) if gc else 0
            g_rows = _query("SELECT id, kind, question FROM forge_gates WHERE decision IS NULL OR decision = '' ORDER BY id DESC LIMIT 20", fetch=True) or []
            gates = [{"id": g["id"], "kind": g["kind"] or "", "question": (g["question"] or "")[:200]} for g in g_rows]
        except Exception as ge:  # noqa: BLE001 — нет таблицы → честный ноль, не 500
            _log_error(f"attention: gates read failed: {ge}", source="api_attention", kind="input")
        findings = 0
        try:
            fr = _query("SELECT COUNT(*) AS c FROM admin_findings WHERE status = 'open'", fetch=True)
            findings = int(fr[0]["c"]) if fr else 0
        except Exception as fe:  # noqa: BLE001
            _log_error(f"attention: findings read failed: {fe}", source="api_attention", kind="input")
        locked = False
        try:
            lr = _query("SELECT value FROM system_settings WHERE key = 'system_lockdown' LIMIT 1", fetch=True)
            locked = bool(lr) and str(lr[0]["value"] or "").lower() == "true"
        except Exception as le:  # noqa: BLE001
            _log_error(f"attention: lockdown read failed: {le}", source="api_attention", kind="input")
        commit = (os.environ.get("RENDER_GIT_COMMIT") or "")[:7]
        version = ""
        try:
            vp = os.path.join(BASE_DIR, "VERSION")
            if os.path.isfile(vp):
                with open(vp, "r", encoding="utf-8") as fh:
                    version = fh.read().strip()[:7]
        except Exception as ve:  # noqa: BLE001
            _log_error(f"attention: version read failed: {ve}", source="api_attention", kind="input")
        return jsonify({
            "status": "ok",
            "gates": gates, "gates_total": gates_count, "findings": findings,
            "total": gates_count + findings,
            "lockdown": locked, "version": version, "commit": commit,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/audit")
def api_audit():
    """FORGE-UI-5 (#198): последние записи журнала аудита — чтение существующей
    таблицы audit_log (пишется существующей логикой, здесь ничего не меняем)."""
    try:
        rows = _query("SELECT timestamp, action, actor, dept, details FROM audit_log ORDER BY id DESC LIMIT 50", fetch=True) or []
        items = [{"ts": r["timestamp"] or "", "action": r["action"] or "", "actor": r["actor"] or "",
                  "dept": r["dept"] or "", "details": (r["details"] or "")[:160]} for r in rows]
        return jsonify({"status": "ok", "items": items})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/archive-watches")
def api_archive_watches():
    """FORGE-UI-5 (#198): отчёты на контроле — существующий механизм kv
    control_<doc_id> (system_settings — общая kv с Metalogos; запись идёт
    существующими miniapp-действиями HandleMiniAppAction, value = freq|title).
    Только чтение. Даты окончания контроля схема не предусматривает — показываем
    freq как есть (пробел дат зафиксирован в отчёте наряда)."""
    try:
        rows = _query("SELECT key, value FROM system_settings WHERE key LIKE 'control|_%' ESCAPE '|'", fetch=True) or []
        items = []
        for r in rows:
            doc_id = str(r["key"])[8:]
            val = str(r["value"] or "")
            freq, _, title = val.partition("|")
            items.append({"doc_id": doc_id, "freq": freq, "title": title})
        return jsonify({"status": "ok", "watches": items})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _ensure_forge_skills():
    """FORGE-UI-7 (#200): новая сущность скилов проекта (спроектирована в наряде):
    project_slug — привязка к проекту; type ∈ {file, link, text} (file — пробел:
    механизма загрузки нет); title — имя; content_ref — ссылка/текст/путь.
    Изоляция: скилы принадлежат проекту и не попадают в общую библиотеку офиса."""
    _query("""CREATE TABLE IF NOT EXISTS forge_project_skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_slug TEXT NOT NULL,
            type TEXT DEFAULT 'text',
            title TEXT,
            content_ref TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
    _query("CREATE INDEX IF NOT EXISTS idx_forge_skills_project ON forge_project_skills(project_slug, id)")


@app.get("/api/forge/projects")
def api_forge_projects():
    """FORGE-UI-7 (#200): список проектов FORGE — чтение существующих таблиц
    forge_projects + счётчики из forge_repos/forge_project_secrets; прогресс —
    реальный (этапы forge_stages задач проекта), при отсутствии этапов — нет
    прогресса. Ключевые значения не отдаются никогда (только счётчики)."""
    try:
        rows = _query("SELECT slug, name, customer_name, status, project_type, goal, created_at "
                      "FROM forge_projects ORDER BY created_at DESC LIMIT 50", fetch=True) or []
        rc = {r["pslug"]: int(r["c"]) for r in (_query(
            "SELECT project_slug AS pslug, COUNT(*) AS c FROM forge_repos GROUP BY project_slug", fetch=True) or [])}
        sc = {r["pslug"]: int(r["c"]) for r in (_query(
            "SELECT project_slug AS pslug, COUNT(*) AS c FROM forge_project_secrets GROUP BY project_slug", fetch=True) or [])}
        st = {}
        try:
            for r in (_query(
                    "SELECT t.project_slug AS pslug, COUNT(s.id) AS total, "
                    "SUM(CASE WHEN s.status='done' THEN 1 ELSE 0 END) AS done "
                    "FROM forge_stages s JOIN forge_tasks t ON t.id = s.task_id GROUP BY t.project_slug",
                    fetch=True) or []):
                st[r["pslug"]] = (int(r["done"] or 0), int(r["total"] or 0))
        except Exception as se:  # noqa: BLE001 — нет таблиц этапов → прогресса нет
            _log_error(f"forge projects stages read: {se}", source="api_forge_projects", kind="input")
        projects = []
        for r in rows:
            done, total = st.get(r["slug"], (0, 0))
            projects.append({
                "slug": r["slug"], "name": r["name"] or r["slug"],
                "customer": r["customer_name"] or "", "status": r["status"] or "active",
                "project_type": r["project_type"] or "", "goal": r["goal"] or "",
                "repos": rc.get(r["slug"], 0), "secrets": sc.get(r["slug"], 0),
                "stages_done": done, "stages_total": total,
                "created": (r["created_at"] or "")[:16],
            })
        return jsonify({"status": "ok", "projects": projects})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── FORGE-UI-12 (#215): создание проекта FORGE из миниаппа ──────────────────
# Тонкий route: SQL и валидация НЕ дублируются в Python — создание выполняет
# существующий mlog-паттерн ForgeCreateProject (dept/forge.mlog — вставка
# строки проекта со status='active') через мост
# dept/forge_create_bridge.mlog (mlog run + FNP_* env). Python делает только
# то, чего нет в mlog: HTTP-валидацию формы, транслитерацию slug и запуск моста.

_FORGE_PROJECT_TYPES = ("site", "android", "ai_office")
# Схема транслитерации: однобуквенные пары + многозначные (ж→zh, ч→ch, …);
# ъ/ь — отбрасываются (жёсткое→жесткое, соль→sol).
_TR_CYR = {ord(k): v for k, v in (
    p.split(":") for p in (
        "а:a б:b в:v г:g д:d е:e ж:zh з:z и:i й:y к:k л:l м:m н:n о:o п:p р:r "
        "с:s т:t у:u ф:f х:h ц:c ч:ch ш:sh щ:sch ъ: ы:y ь: э:e ю:yu я:ya ё:yo "
        "і:i ї:yi є:ie ґ:g ў:u"
    ).split())
}


def _forge_slugify(name: str) -> str:
    """Slug из названия: транслитерация кириллицы, дефисы, нижний регистр."""
    s = (name or "").strip().lower().translate(_TR_CYR)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "project"


def _forge_bridge_run(slug: str, name: str, goal: str, customer: str, ptype: str):
    """Запуск mlog-моста. Возвращает (ok, line) — строку ответа ForgeCreateProject."""
    env = os.environ.copy()
    env.update({"FNP_SLUG": slug, "FNP_NAME": name, "FNP_GOAL": goal,
                "FNP_CUSTOMER": customer, "FNP_TYPE": ptype})
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        ["./bin/mlog", "run", "dept/forge_create_bridge.mlog"],
        capture_output=True, text=True, timeout=90, env=env, cwd=repo_root)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith("Проект создан:"):
            return True, line
        if line.startswith("ОТКАЗ:"):
            return False, line
    return False, (proc.stderr or proc.stdout or "мост не вернул ответа").strip()[-300:]


@app.post("/api/forge/projects")
def api_forge_project_create():
    """FORGE-UI-12 (#215): короткая форма создания проекта (название, цель,
    заказчик, тип). Запись делает только mlog-паттерн ForgeCreateProject —
    здесь НЕТ INSERT. Slug генерируется из названия (транслитерация + дефисы),
    коллизии гасятся суффиксом -2/-3 (финальный гарант — проверка slug внутри
    ForgeCreateProject)."""
    try:
        d = request.get_json(force=True) or {}
        name = str(d.get("name") or "").strip()
        goal = str(d.get("goal") or "").strip()
        customer = str(d.get("customer") or "").strip()
        ptype = str(d.get("project_type") or "").strip()
        if not name:
            return jsonify({"status": "error", "message": "Введи название проекта"}), 400
        if ptype not in _FORGE_PROJECT_TYPES:
            return jsonify({"status": "error",
                            "message": "project_type ∈ {site, android, ai_office}"}), 400
        base = _forge_slugify(name)
        slug = base
        n = 1
        while _query("SELECT 1 FROM forge_projects WHERE slug=? LIMIT 1", (slug,), fetch=True):
            n += 1
            slug = f"{base}-{n}"
        try:
            ok, line = _forge_bridge_run(slug, name, goal, customer, ptype)
        except subprocess.TimeoutExpired:
            _log_error(f"forge create bridge timeout: slug={slug}", source="api_forge_project_create", kind="input")
            return jsonify({"status": "error", "message": "Создание превысило 90с — попробуй ещё раз"}), 504
        if not ok:
            return jsonify({"status": "error", "message": line}), 409
        return jsonify({"status": "ok", "project": {"slug": slug, "name": name,
                                                    "project_type": ptype}, "message": line})
    except Exception as e:
        _log_error(f"forge project create: {e}", source="api_forge_project_create", kind="input")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/forge/projects/<slug>")
def api_forge_project_detail(slug):
    """FORGE-UI-7 (#200): карточка проекта. Значения ключей проекта
    (forge_project_secrets.secret_ref) и данных заказчика
    (forge_customer_data.secret_ref) НЕ читаются и НЕ отдаются — только
    имена/факт наличия (SEC-5: хранятся шифрованно)."""
    try:
        rows = _query("SELECT slug, name, description, goal, project_type, customer_name, status, "
                      "departments, model_combo, created_at FROM forge_projects WHERE slug=? LIMIT 1",
                      (slug,), fetch=True)
        if not rows:
            return jsonify({"status": "error", "message": "проект не найден"}), 404
        r = rows[0]
        repos = _query("SELECT name, description, github_url, commits_count, last_commit_at "
                       "FROM forge_repos WHERE project_slug=? ORDER BY created_at ASC, name ASC",
                       (slug,), fetch=True) or []
        secret_keys = _query("SELECT env_key FROM forge_project_secrets WHERE project_slug=? ORDER BY env_key",
                             (slug,), fetch=True) or []
        cust = _query("SELECT updated_at FROM forge_customer_data WHERE project_slug=? LIMIT 1",
                      (slug,), fetch=True) or []
        _ensure_forge_skills()
        skills = _query("SELECT id, type, title, content_ref FROM forge_project_skills "
                        "WHERE project_slug=? ORDER BY id DESC LIMIT 50", (slug,), fetch=True) or []
        return jsonify({
            "status": "ok",
            "project": {
                "slug": r["slug"], "name": r["name"] or r["slug"],
                "description": r["description"] or "", "goal": r["goal"] or "",
                "project_type": r["project_type"] or "", "customer": r["customer_name"] or "",
                "status": r["status"] or "active", "departments": r["departments"] or "",
                "model_combo": r["model_combo"] or "", "created": (r["created_at"] or "")[:16],
            },
            "repos": [{"name": x["name"], "description": x["description"] or "",
                       "github_url": x["github_url"] or "", "commits": x["commits_count"] or 0,
                       "last_commit": x["last_commit_at"] or ""} for x in repos],
            "secrets": [{"env_key": x["env_key"], "set": True} for x in secret_keys],
            "customer": {"present": bool(cust),
                         "updated": (cust[0]["updated_at"] if cust else "") or ""},
            "skills": [{"id": x["id"], "type": x["type"] or "text", "title": x["title"] or "",
                        "content_ref": x["content_ref"] or ""} for x in skills],
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/forge/projects/<slug>/repos")
def api_forge_project_repo_add(slug):
    """FORGE-UI-7 (#200), Smoke-5: «Открыть дочерний репозиторий» — новая запись
    в существующей forge_repos, привязанная к тому же project_slug."""
    try:
        rows = _query("SELECT slug FROM forge_projects WHERE slug=? LIMIT 1", (slug,), fetch=True)
        if not rows:
            return jsonify({"status": "error", "message": "проект не найден"}), 404
        base = re.sub(r"[^a-z0-9\-]", "", str(slug).lower()) or "repo"
        n = 1
        name = f"{base}-child-{n}"
        while _query("SELECT 1 FROM forge_repos WHERE name=? LIMIT 1", (name,), fetch=True):
            n += 1
            name = f"{base}-child-{n}"
        _query("INSERT INTO forge_repos (name, project_slug, description) VALUES (?, ?, 'дочерний репозиторий (открыт из миниаппа)')",
               (name, slug))
        _log_audit("forge_child_repo_opened", {"project": slug, "repo": name}, dept="dev")
        return jsonify({"status": "ok", "repo": {"name": name, "project_slug": slug}})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/forge/projects/<slug>/skills")
def api_forge_project_skill_add(slug):
    """FORGE-UI-7 (#200): добавить скил проекта (text/link). Загрузка ФАЙЛОВ —
    механизма загрузки в проект нет (пробел зафиксирован в отчёте наряда)."""
    try:
        d = request.get_json(force=True) or {}
        sk_type = d.get("type")
        title = str(d.get("title") or "").strip()
        content = str(d.get("content_ref") or "").strip()
        if sk_type not in ("text", "link"):
            return jsonify({"status": "error", "message": "type ∈ {text, link} (файлы — в разработке)"}), 400
        if not title or not content:
            return jsonify({"status": "error", "message": "нужны title и content"}), 400
        rows = _query("SELECT slug FROM forge_projects WHERE slug=? LIMIT 1", (slug,), fetch=True)
        if not rows:
            return jsonify({"status": "error", "message": "проект не найден"}), 404
        _ensure_forge_skills()
        _query("INSERT INTO forge_project_skills (project_slug, type, title, content_ref) VALUES (?, ?, ?, ?)",
               (slug, sk_type, title[:200], content[:2000]))
        _log_audit("forge_project_skill_added", {"project": slug, "type": sk_type, "title": title[:80]}, dept="dev")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


_SHOP_SOURCES_DDL = ("CREATE TABLE IF NOT EXISTS shop_sources (source_id TEXT PRIMARY KEY, "
                     "enabled INTEGER DEFAULT 1, custom INTEGER DEFAULT 0, url TEXT)")

# FORGE-UI-9 (#202): честные статусы известных источников (ограничения площадок
# зафиксированы как есть; Ozon — «заблокирован антиботом», это не «выключено»)
_SHOP_SOURCE_STATUS = {
    "wb": ("работает", "ok"),
    "ozon": ("заблокирован антиботом", "warn"),
    "onliner": ("нужен слаг категории", "warn"),
    "21vek": ("нужна форма", "warn"),
}


@app.get("/api/shop/sources")
def api_shop_sources():
    """FORGE-UI-9 (#202): источники Закупок — известные (wb/ozon/onliner/21vek)
    + свои магазины (custom) из shop_sources. enabled — реальный флаг опроса."""
    try:
        _query(_SHOP_SOURCES_DDL)
        rows = {r["source_id"]: r for r in
                _query("SELECT * FROM shop_sources", fetch=True) or []}
        out = []
        for sid, label in [("wb", "Wildberries"), ("ozon", "Ozon"),
                           ("onliner", "Onliner"), ("21vek", "21vek")]:
            r = rows.pop(sid, None)
            out.append({"id": sid, "label": label, "custom": False,
                        "enabled": bool(r["enabled"]) if r else True,
                        "url": (r["url"] if r else "") or ""})
        for sid, r in rows.items():
            out.append({"id": sid, "label": sid, "custom": bool(r["custom"]),
                        "enabled": bool(r["enabled"]), "url": r["url"] or ""})
        return jsonify({"status": "ok", "sources": out})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/shop/sources/<sid>/toggle")
def api_shop_source_toggle(sid):
    """FORGE-UI-9 (#202): включить/выключить источник. Выключенный не
    опрашивается (фильтр в shop_watch.ensure_product/tick_shop_watches)."""
    try:
        d = request.get_json(force=True, silent=True) or {}
        enabled = 1 if d.get("enabled") else 0
        _query(_SHOP_SOURCES_DDL)
        if _query("SELECT 1 FROM shop_sources WHERE source_id=? LIMIT 1", (sid,), fetch=True):
            _query("UPDATE shop_sources SET enabled=? WHERE source_id=?", (enabled, sid))
        else:
            _query("INSERT INTO shop_sources (source_id, enabled) VALUES (?, ?)", (sid, enabled))
        _log_audit("shop_source_toggled", {"source": sid, "enabled": bool(enabled)})
        return jsonify({"status": "ok", "source": sid, "enabled": bool(enabled)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/shop/sources/custom")
def api_shop_source_custom():
    """FORGE-UI-9 (#202): регистрация «своего магазина» (custom=1). Парсинг не
    реализуется в этом наряде — интерфейс честно предупреждает о необходимости
    отдельной настройки сборщика."""
    try:
        from proxy.shop_watch import register_custom_source
        d = request.get_json(force=True, silent=True) or {}
        name = str(d.get("name") or "").strip()
        url = str(d.get("url") or "").strip()
        if not name or not url:
            return jsonify({"status": "error", "message": "нужны name и url"}), 400
        sid = register_custom_source(name, url)
        _log_audit("shop_source_custom_added", {"source": sid, "url": url[:120]})
        return jsonify({"status": "ok", "id": sid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/shop/settings")
def api_shop_settings_get():
    """FORGE-UI-9 (#202): настройки Закупок — дефолты вотчей (system_settings)."""
    try:
        disc = _get_setting("shop_watch_default_discount", "")
        try:
            disc = float(disc) if str(disc).strip() else None
        except (TypeError, ValueError):
            disc = None
        in_stock = str(_get_setting("shop_watch_default_in_stock", "0")).lower() in ("1", "true")
        return jsonify({"status": "ok", "default_discount_pct": disc,
                        "default_in_stock": in_stock})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/shop/settings")
def api_shop_settings_set():
    """FORGE-UI-9 (#202): сохранить дефолты вотчей (порог скидки, уведомлять
    о наличии) — используются add_watch, когда параметры не заданы явно."""
    try:
        d = request.get_json(force=True, silent=True) or {}
        if "default_discount_pct" in d:
            val = d.get("default_discount_pct")
            if val in (None, ""):
                _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES "
                       "('shop_watch_default_discount', '')")
            else:
                try:
                    fv = float(val)
                    if not 0 <= fv <= 99:
                        raise ValueError
                except (TypeError, ValueError):
                    return jsonify({"status": "error", "message": "порог — число 0..99"}), 400
                _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES "
                       "('shop_watch_default_discount', ?)", (str(fv),))
        if "default_in_stock" in d:
            v = 1 if d.get("default_in_stock") else 0
            _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES "
                   "('shop_watch_default_in_stock', ?)", (str(v),))
        _log_audit("shop_settings_saved", {"keys": sorted(d.keys())})
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/shop/dossiers")
def api_shop_dossiers():
    """FORGE-UI-13 (#216): список досье закупок из shop_dossiers (схема не
    меняется, только чтение). Фильтры: year/month/day (по created_at) и q —
    текстовый поиск по product_id, названию/запросу товара (shop_products)
    и содержимому snapshot_json. Краткие карточки: id, короткое название,
    дата, признак «на контроль» (активный shop_watches по product_id) и
    url — кликабельная ссылка на полное досье (существующий рендер
    /shop/dossier/<id>?t=HMAC, proxy/shop_dossier.dossier_url)."""
    try:
        q = (request.args.get("q") or "").strip()
        year = (request.args.get("year") or "").strip()
        month = (request.args.get("month") or "").strip()
        day = (request.args.get("day") or "").strip()
        where = ["d.format='snapshot'"]
        params = []
        if year.isdigit():
            where.append("CAST(strftime('%Y', d.created_at) AS INTEGER)=?")
            params.append(int(year))
        if month.isdigit():
            where.append("CAST(strftime('%m', d.created_at) AS INTEGER)=?")
            params.append(int(month))
        if day.isdigit():
            where.append("CAST(strftime('%d', d.created_at) AS INTEGER)=?")
            params.append(int(day))
        if q:
            like = f"%{q}%"
            where.append("(CAST(d.product_id AS TEXT) LIKE ? OR d.snapshot_json LIKE ? "
                         "OR COALESCE(p.title,'') LIKE ? OR COALESCE(p.query_text,'') LIKE ?)")
            params += [like, like, like, like]
        rows = _query(
            "SELECT d.id, d.product_id, d.created_at, COALESCE(p.title,'') AS title, "
            "COALESCE(p.query_text,'') AS qtext "
            "FROM shop_dossiers d LEFT JOIN shop_products p ON p.id = d.product_id "
            f"WHERE {' AND '.join(where)} ORDER BY d.id DESC LIMIT 200",
            tuple(params), fetch=True) or []
        try:
            watched = {r["product_id"] for r in (
                _query("SELECT product_id FROM shop_watches WHERE status='active'", fetch=True) or [])}
        except Exception:  # noqa: BLE001 — вотч-таблицы нет в базе → признака нет
            watched = set()
        from proxy.shop_dossier import dossier_url
        items = [{
            "id": r["id"], "product_id": r["product_id"],
            "title": (r["title"] or r["qtext"] or f"Товар #{r['product_id']}"),
            "created": (r["created_at"] or "")[:16],
            "on_watch": r["product_id"] in watched,
            "url": dossier_url(r["id"]),
        } for r in rows]
        return jsonify({"status": "ok", "items": items})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/shop/preview")
def api_shop_preview():
    """FORGE-UI-9 (#202): реальный запрос закупки с выбранным профилем оценки.
    best/quality/cheap/availability — score_offers (весовые); top3 — отдельная
    структура top3_by_price_bands (3 ценовых диапазона, топ-3 в каждом)."""
    try:
        from proxy.shop_watch import ensure_product, shop_source_enabled, PLATFORMS_MVP
        from proxy.shop_engine import score_offers, top3_by_price_bands
        from proxy.shop_collectors import refresh_product
        d = request.get_json(force=True, silent=True) or {}
        query = str(d.get("query") or "").strip()
        profile = str(d.get("profile") or "best")
        if not query:
            return jsonify({"status": "error", "message": "нужен query"}), 400
        pid, _details = ensure_product(query)
        for platform in PLATFORMS_MVP:
            if not shop_source_enabled(platform):
                continue
            try:
                refresh_product(pid, platform, query)
            except Exception:  # noqa: BLE001 — площадка недоступна, превью живёт
                pass
        offers = _query("SELECT * FROM shop_offers WHERE product_id=?", (pid,), fetch=True) or []
        if profile == "top3":
            res = top3_by_price_bands(offers)
            return jsonify({"status": "ok", "profile": profile,
                            "bands": res["bands"], "offers_total": len(offers)})
        res = score_offers(offers, profile=profile)
        top = sorted(res.get("offers", []), key=lambda o: o.get("total", 0), reverse=True)[:10]
        return jsonify({"status": "ok", "profile": profile, "offers": top,
                        "offers_total": len(offers)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


_RSS_NOTICE = {
    "telegram": "Сбор реализован (MON-1): чтение каналов через пользовательский аккаунт — нужен отдельный аккаунт, не основной личный. Управление каналами и сводкой — командами /lz_channel и /lz digest в Telegram.",
    "youtube": "Сбор реализован (MON-2): нужен YOUTUBE_API_KEY (Интеграции). Управление каналами — командой /lz_channel в Telegram.",
    "tiktok": "Сбор реализован (MON-3): веб-эндпоинт с лимитами запросов. Управление — командой /lz_channel в Telegram.",
}


@app.get("/api/lz/rss")
def api_lz_rss_list():
    """FORGE-UI-10 (#203): список RSS-источников ЛЗ — кодовый RSS_FEEDS,
    сееденный в таблицу состояния rss_sources + добавленные владельцем."""
    try:
        from proxy.news import _rss_state_table
        _rss_state_table()
        rows = _query("SELECT feed, url, name, tag, enabled, custom FROM rss_sources "
                      "WHERE deleted=0 ORDER BY tag, feed", fetch=True) or []
        return jsonify({"status": "ok", "feeds": [
            {"feed": r["feed"], "name": r["name"], "url": r["url"],
             "category": r["tag"], "enabled": bool(r["enabled"]),
             "custom": bool(r["custom"])} for r in rows]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/lz/rss/<feed>/toggle")
def api_lz_rss_toggle(feed):
    """FORGE-UI-10 (#203): тумблер ленты — выключенная пропускается
    collect_rss() при следующем сборе (без удаления из конфигурации)."""
    try:
        from proxy.news import _rss_state_table
        _rss_state_table()
        d = request.get_json(force=True, silent=True) or {}
        enabled = 1 if d.get("enabled") else 0
        _query("UPDATE rss_sources SET enabled=? WHERE feed=?", (enabled, feed))
        _log_audit("lz_rss_toggled", {"feed": feed, "enabled": bool(enabled)}, dept="lz")
        return jsonify({"status": "ok", "feed": feed, "enabled": bool(enabled)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.delete("/api/lz/rss/<feed>")
def api_lz_rss_delete(feed):
    """FORGE-UI-10 (#203): удаление ленты. Кодовая — мягко (deleted=1, иначе
    вернётся при сеединге); добавленная владельцем — удаляется строкой."""
    try:
        from proxy.news import _rss_state_table
        _rss_state_table()
        row = _query("SELECT custom FROM rss_sources WHERE feed=? LIMIT 1", (feed,), fetch=True)
        if not row:
            return jsonify({"status": "error", "message": "лента не найдена"}), 404
        if row[0]["custom"]:
            _query("DELETE FROM rss_sources WHERE feed=?", (feed,))
        else:
            _query("UPDATE rss_sources SET deleted=1, enabled=0 WHERE feed=?", (feed,))
        _log_audit("lz_rss_deleted", {"feed": feed}, dept="lz")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/api/lz/rss")
def api_lz_rss_add():
    """FORGE-UI-10 (#203): добавить сайт по ссылке — URL валидируется
    (feedparser) ДО сохранения; заведомо нерабочая ссылка не сохраняется."""
    try:
        from proxy.news import rss_validate_url, _rss_state_table
        d = request.get_json(force=True, silent=True) or {}
        url = str(d.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            return jsonify({"status": "error", "message": "нужен http(s) URL"}), 400
        ok, title = rss_validate_url(url)
        if not ok:
            return jsonify({"status": "error", "message": "URL не похож на рабочую RSS/Atom-ленту"}), 400
        _rss_state_table()
        base = re.sub(r"[^a-z0-9\-]", "", url.split("//", 1)[-1].lower())[:40] or "custom-feed"
        feed_id = f"custom-{base}"
        n = 2
        while _query("SELECT 1 FROM rss_sources WHERE feed=? LIMIT 1", (feed_id,), fetch=True):
            feed_id = f"custom-{base}-{n}"
            n += 1
        _query("INSERT INTO rss_sources (feed, url, name, tag, enabled, custom, deleted) "
               "VALUES (?, ?, ?, 'custom', 1, 1, 0)", (feed_id, url, title[:120]))
        _log_audit("lz_rss_added", {"feed": feed_id, "url": url[:120]}, dept="lz")
        return jsonify({"status": "ok", "feed": feed_id, "title": title})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.get("/api/lz/notices")
def api_lz_notices():
    """FORGE-UI-10 (#203): честные статусы Telegram/YouTube/TikTok контура ЛЗ
    (MON-1..4 реализованы; управление каналами — команды Telegram)."""
    return jsonify({"status": "ok", "notices": _RSS_NOTICE})


@app.post("/api/narads/<nid>/approve")
def api_narad_approve(nid):
    try:
        _query("UPDATE narads SET status='approved', approved_at=datetime('now') WHERE id=?", (nid,))
        _log_audit("narad_approve_miniapp", {"narad_id": nid})
        # FO-047: мгновенный такт очереди в фоне — одобренный наряд с
        # исполнителем берётся в работу без ожидания крона (≤14 мин).
        try:
            from proxy.narad_queue import trigger_async
            trigger_async()
        except Exception as tick_err:  # noqa: BLE001 — approve не должен падать из-за тика
            _log_audit("narad_tick_trigger_error", {"narad_id": nid, "error": str(tick_err)[:200]})
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
        kg_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph WHERE valid_to IS NULL", fetch=True)
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

    # FO-009: узлы больше не стираются — история сохраняется (kg_scan_rebuild).
    # Рёбра (knowledge_edges) вне скоупа наряда — перестраиваются как раньше.
    c.execute("DELETE FROM knowledge_edges")
    nodes_list = []

    # Run analyzer internally (not via Flask)
    analysis = _ua_analyze_internal()

    nodes_saved = 0
    edges_saved = 0
    now_ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    for fa in analysis:
        rel = fa['path']
        # Node: file
        nodes_list.append({'node_type': 'file', 'node_name': rel, 'file_path': rel,
                           'description': f"{len(fa.get('patterns', []))} patterns, {len(fa.get('routes', []))} routes"})
        nodes_saved += 1

        # Nodes + edges: patterns
        for p in fa.get('patterns', []):
            pname = p.get('name', '')
            if not pname:
                continue
            nodes_list.append({'node_type': 'pattern', 'node_name': pname, 'file_path': rel,
                               'description': f"args={p.get('args', '')} returns={p.get('returns', '')}"})
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
            nodes_list.append({'node_type': 'route', 'node_name': rname, 'file_path': rel,
                               'description': r.get('method', '')})
            nodes_saved += 1
            c.execute(
                "INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?, ?, ?, ?, ?)",
                (rel, rname, 'exposes', rel, now_ts))
            edges_saved += 1

        # Nodes + edges: tables
        for t in fa.get('tables', []):
            nodes_list.append({'node_type': 'table', 'node_name': t, 'file_path': rel,
                               'description': 'CREATE TABLE'})
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

    # FO-009: темпоральная фиксация узлов (close/insert/noop вместо wipe)
    kg_res = kg_scan_rebuild(nodes_list, source='admin_ua_graph')

    conn.commit()
    conn.close()

    summary = (f"GRAPH COMPLETE\n  Nodes: {nodes_saved} | Edges: {edges_saved}\n  "
               f"Files analyzed: {len(analysis)}\n"
               f"  KG temporal: +{kg_res['inserted']} new, ~{kg_res['updated']} updated, "
               f"={kg_res['noop']} unchanged, -{kg_res['closed_missing']} closed")
    return jsonify({'summary': summary, 'nodes': nodes_saved, 'edges': edges_saved, 'kg': kg_res})


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
        # FO-009: узлы не стираются — история сохраняется; рёбра перестраиваются
        c.execute("DELETE FROM knowledge_edges")
        nodes_list = []

        nodes_saved = 0
        edges_saved = 0
        now_ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        for fa in analysis:
            rel = fa['path']
            nodes_list.append({'node_type': 'file', 'node_name': rel, 'file_path': rel,
                               'description': f"{len(fa.get('patterns', []))}p {len(fa.get('routes', []))}r"})
            nodes_saved += 1
            for p in fa.get('patterns', []):
                pname = p.get('name', '')
                if not pname: continue
                nodes_list.append({'node_type': 'pattern', 'node_name': pname, 'file_path': rel, 'description': ''})
                nodes_saved += 1
                c.execute("INSERT INTO knowledge_edges (source_name, target_name, edge_type, file_path, updated_at) VALUES (?,?,?,?,?)",
                          (rel, pname, 'defines', rel, now_ts))
                edges_saved += 1
            for r in fa.get('routes', []):
                rname = r.get('path', '')
                if not rname: continue
                nodes_list.append({'node_type': 'route', 'node_name': rname, 'file_path': rel,
                                   'description': r.get('method', '')})
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

        # FO-009: темпоральная фиксация узлов скана
        kg_res_nc = kg_scan_rebuild(nodes_list, source='admin_ua_night_cycle')
        log.info(f"UA Night Cycle: KG temporal +{kg_res_nc['inserted']} new, ~{kg_res_nc['updated']} updated, "
                 f"={kg_res_nc['noop']} unchanged, -{kg_res_nc['closed_missing']} closed")

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
    g_nodes = _query("SELECT COUNT(*) as c FROM knowledge_graph WHERE valid_to IS NULL", fetch=True)
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

# ═══ FO-011: телеметрия офиса для Mini App (issue #71) ═══════════════════
_TELEMETRY_CACHE = {"ts": 0.0, "data": None}
_TELEMETRY_TTL = 60  # секунд — кэш по наряду


def _telemetry_traces_stats(days=7):
    """Агрегаты FO-004-трейсов: latency и доля ошибок провайдеров."""
    traces_dir = Path(DB_PATH) / "traces"
    latencies, ok_cnt, fail_cnt = [], 0, 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        if traces_dir.is_dir():
            for f in sorted(traces_dir.glob("llm_*.jsonl")):
                day = f.name[4:14]
                if day < cutoff:
                    continue
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        if rec.get("is_internal"):
                            continue
                        lat = rec.get("latency_ms")
                        if isinstance(lat, (int, float)):
                            latencies.append(lat)
                        if rec.get("ok") is True:
                            ok_cnt += 1
                        elif rec.get("ok") is False:
                            fail_cnt += 1
    except Exception as e:
        _log_error(f"telemetry trace read failed: {e}", source="telemetry", kind="data_loss")
    latencies.sort()
    def _pct(p):
        if not latencies:
            return None
        i = min(len(latencies) - 1, int(round(p / 100 * (len(latencies) - 1))))
        return round(latencies[i])
    total = ok_cnt + fail_cnt
    return {
        "avg_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "p50_ms": _pct(50), "p95_ms": _pct(95),
        "ok_calls": ok_cnt, "failed_calls": fail_cnt,
        "fail_pct": round(fail_cnt * 100.0 / total, 1) if total else None,
        "calls_total": total,
    }


@app.get("/api/telemetry")
def api_telemetry():
    """Телеметрия офиса: token economics, latency, fallback, golden-тренд.

    Кэш 60 секунд (по наряду). Рендер — на клиенте (inline SVG, без CDN).
    """
    import time as _time
    now_ts = _time.monotonic()
    if _TELEMETRY_CACHE["data"] and now_ts - _TELEMETRY_CACHE["ts"] < _TELEMETRY_TTL:
        return jsonify(_TELEMETRY_CACHE["data"])

    days = 7
    by_day = _query(
        "SELECT date(created_at) AS d, SUM(CAST(input_tokens AS INTEGER)) AS tin, "
        "SUM(CAST(output_tokens AS INTEGER)) AS tout, SUM(CAST(cost_usd AS REAL)) AS cost "
        "FROM token_usage WHERE created_at >= datetime('now', ?) "
        "GROUP BY d ORDER BY d", (f"-{days} days",), fetch=True) or []
    by_dept = _query(
        "SELECT dept, SUM(CAST(input_tokens AS INTEGER) + CAST(output_tokens AS INTEGER)) AS tokens, "
        "SUM(CAST(cost_usd AS REAL)) AS cost, COUNT(*) AS calls "
        "FROM token_usage WHERE created_at >= datetime('now', ?) "
        "GROUP BY dept ORDER BY tokens DESC LIMIT 10", (f"-{days} days",), fetch=True) or []
    combos = _query(
        "SELECT COALESCE(NULLIF(combo, ''), 'direct') AS combo, COUNT(*) AS c "
        "FROM token_usage WHERE created_at >= datetime('now', ?) GROUP BY combo ORDER BY c DESC",
        (f"-{days} days",), fetch=True) or []
    golden = _query(
        "SELECT date(created_at) AS d, ROUND(AVG(CAST(metric_value AS REAL)), 3) AS avg_score "
        "FROM dept_metrics WHERE metric_name = 'golden_eval_avg' "
        "AND created_at >= datetime('now', '-14 days') GROUP BY d ORDER BY d", fetch=True) or []

    total_tokens = sum((r["tokens"] or 0) for r in by_dept)
    total_cost = sum((r["cost"] or 0.0) for r in by_dept)
    data = {
        "window_days": days,
        "tokens_by_day": [{"day": r["d"], "tokens": (r["tin"] or 0) + (r["tout"] or 0),
                           "input": r["tin"] or 0, "output": r["tout"] or 0,
                           "cost": round(r["cost"] or 0, 4)} for r in by_day],
        "tokens_by_dept": [{"dept": r["dept"], "tokens": r["tokens"] or 0,
                            "cost": round(r["cost"] or 0, 4), "calls": r["calls"] or 0} for r in by_dept],
        "combos": [{"combo": r["combo"], "count": r["c"]} for r in combos],
        "latency": _telemetry_traces_stats(days),
        "golden_trend": [{"day": r["d"], "avg": r["avg_score"]} for r in golden],
        "totals": {"tokens": total_tokens, "cost": round(total_cost, 4)},
        "cache_ttl": _TELEMETRY_TTL,
    }
    _TELEMETRY_CACHE["ts"] = now_ts
    _TELEMETRY_CACHE["data"] = data
    return jsonify(data)


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
             ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json",
             ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    return Response(file_path.read_bytes(), mimetype=mimes.get(ext, "application/octet-stream"))
