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
             ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json"}
    return Response(file_path.read_bytes(), mimetype=mimes.get(ext, "application/octet-stream"))
