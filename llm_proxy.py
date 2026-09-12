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
    _compaction_summarize,
    _cfg_cache, _load_cfg,
    _ZAI_CONFIG_PATHS, _ZAI_CONFIG, _load_zai_config, _zai_headers,
    _generate_image, _IMG_DIR, _ALLOWED_SIZES,
)

# ── FO-016: компакция контекста (budget + prune + summarize + offload) ───────
from proxy.compaction import (
    compact_context, get_context_budget, PROVIDER_CONTEXT_LIMITS,
    TOOL_OUTPUT_DIR, restore_tool_output, cleanup_tool_output_files,
    estimate_tokens,
)

# ── FO-017: Dialog v2 — Part-модель + event-log с per-session seq ────────────
from proxy.dialog import (
    ensure_dialog_schema, save_message, add_part, add_tool_call,
    add_tool_result, record_compaction, replay_session, get_session_events,
    get_session_messages, get_part, migrate_dialog_history, rollback_migration,
    PART_TYPES, EVENT_TYPES,
)

# ── FO-019: профиль владельца — static/dynamic/buckets одним вызовом ─────────
from proxy.owner_profile import (
    get_owner_profile, rebuild_owner_profile, invalidate_owner_profile,
    ensure_profile_schema, current_version as profile_current_version,
)

# ── FO-020: review-очередь выведенного — approve/decline/undo ────────────────
from proxy.review import (
    get_review_queue, decide_review, queue_depth as review_queue_depth,
    notify_queue_overflow_if_needed, REVIEW_SOURCES, REVIEW_DECISIONS,
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


# ── FO-008 шаг 4c: GitHub/LZ/OSINT/news-роуты в proxy/lz_github.py ───────────
from proxy.lz_github import (
    OSINT_DISCLAIMER as OSINT_DISCLAIMER, _osint_last_time as _osint_last_time,
    OSINT_RATE_LIMIT as OSINT_RATE_LIMIT, categorize_platform as categorize_platform,
    scan_osint as scan_osint,
    GITHUB_TOKEN as GITHUB_TOKEN, GITHUB_HEADERS as GITHUB_HEADERS,
    GITHUB_WATCH_RELEASES as GITHUB_WATCH_RELEASES,
    _build_github_queries as _build_github_queries,
    _github_search as _github_search, _github_releases as _github_releases,
    scheduler_lz_daily_test as scheduler_lz_daily_test,
    scheduler_lz_daily as scheduler_lz_daily,
    scheduler_lz_daily_core as scheduler_lz_daily_core,
    scheduler_admin_daily as scheduler_admin_daily,
    _parse_github_repo as _parse_github_repo, github_push_file as github_push_file,
    lz_osint as lz_osint, news_fresh as news_fresh, lz_github_scan as lz_github_scan,
    lz_api_scan_endpoint as lz_api_scan_endpoint,
    lz_diagnose as lz_diagnose, lz_news as lz_news, news_stats as news_stats,
)
from proxy.core import (
    _collect_metrics_for_period as _collect_metrics_for_period,
    _format_metrics_text as _format_metrics_text,
)







# ── FO-008 шаг 4d: schedulers/learning/audit/search/deep-research в proxy/ ───
from proxy.core import _memorize as _memorize, RENDER_URL as RENDER_URL
from proxy.routes_sched import (
    archive_publish as archive_publish, archive_daily_digest as archive_daily_digest,
    scheduler_morning_brief as scheduler_morning_brief,
    scheduler_admin_morning_reply as scheduler_admin_morning_reply,
    scheduler_evening_summary as scheduler_evening_summary,
    scheduler_weekly_digest as scheduler_weekly_digest,
    scheduler_monthly_review as scheduler_monthly_review,
    scheduler_control_check as scheduler_control_check,
    scheduler_self_learn as scheduler_self_learn,
    learning_fix as learning_fix, learning_good as learning_good,
    learning_stats as learning_stats, learning_record as learning_record,
    learning_recall as learning_recall, learning_debrief as learning_debrief,
    audit_recent as audit_recent, search_endpoint as search_endpoint,
    lz_deep_research as lz_deep_research,
)



# ── FO-008 шаг 4e: admin/api и tail (memory/cron/golden/traces) в proxy/ ─────
from proxy.routes_admin import (
    api_dashboard as api_dashboard, api_dept as api_dept, api_models as api_models,
    api_economics as api_economics, api_narads as api_narads,
    api_narad_approve as api_narad_approve, api_narad_reject as api_narad_reject,
    api_archive as api_archive, api_admin_status as api_admin_status,
    SKIP_DIRS as SKIP_DIRS, KNOWN_BUILTINS as KNOWN_BUILTINS,
    admin_ua_scan as admin_ua_scan, admin_ua_analyze as admin_ua_analyze,
    _ua_analyze_internal as _ua_analyze_internal, _ua_scan_internal as _ua_scan_internal,
    _ua_review_internal as _ua_review_internal,
    admin_ua_graph as admin_ua_graph, admin_ua_review as admin_ua_review,
    admin_ua_impact as admin_ua_impact, admin_ua_docs as admin_ua_docs,
    admin_ua_night_cycle as admin_ua_night_cycle, admin_ua_tour as admin_ua_tour,
    miniapp_redirect as miniapp_redirect, api_integrations_list as api_integrations_list,
    api_integrations_set as api_integrations_set, api_integrations_delete as api_integrations_delete,
    miniapp_spa_index as miniapp_spa_index, miniapp_spa_static as miniapp_spa_static,
)
from proxy.routes_tail import (
    memory_recall_endpoint as memory_recall_endpoint,
    memory_remember_endpoint as memory_remember_endpoint,
    memory_stats_endpoint as memory_stats_endpoint,
    memory_answer_endpoint as memory_answer_endpoint,
    memory_maintenance_endpoint as memory_maintenance_endpoint,
    memory_conflicts_endpoint as memory_conflicts_endpoint,
    yana_auto_memorize as yana_auto_memorize,
    scheduler_reminder_check as scheduler_reminder_check,
    generate_image_endpoint as generate_image_endpoint,
    cron_collect_news as cron_collect_news, cron_backup as cron_backup,
    _FACTS_MAX_OPS as _FACTS_MAX_OPS, _FACTS_DIALOG_ROWS as _FACTS_DIALOG_ROWS,
    _FACTS_BACKFILL_DAYS as _FACTS_BACKFILL_DAYS,
    _extract_json_block as _extract_json_block,
    _consolidate_dept_day as _consolidate_dept_day, _consolidate_memory as _consolidate_memory,
    cron_consolidate_memory as cron_consolidate_memory,
    _GOLDEN_DIR as _GOLDEN_DIR, _GOLDEN_MIN_SCORE as _GOLDEN_MIN_SCORE,
    _GOLDEN_REGRESSION_DROP as _GOLDEN_REGRESSION_DROP,
    _golden_load as _golden_load, _golden_format_score as _golden_format_score,
    _golden_run_dept as _golden_run_dept, _golden_previous_avg as _golden_previous_avg,
    scheduler_golden_evals as scheduler_golden_evals,
    traces_endpoint as traces_endpoint, trace_stats_endpoint as trace_stats_endpoint,
    scheduler_watch_sweep as scheduler_watch_sweep,
    scheduler_indicator_pre_reminders as scheduler_indicator_pre_reminders,
    expert_chart as expert_chart,
    CALL_PYTHON_ALLOWED as CALL_PYTHON_ALLOWED,
    call_python_endpoint as call_python_endpoint,
)



if __name__ == "__main__":
    log.info(f"Starting LLM Proxy on port {PORT}, DB={DB_FILE}")
    log.info(f"Endpoints: health, detect-dept, ask, rate_cmd, context_cmd, voice-set, "
             f"archive/digest, archive/publish, archive/daily-digest, miniapp, enrich, tg-send, dept-dashboard, office-dashboard, "
             f"expert/chart, tts, stt, scheduler/*, learning/*, audit/recent, search, generate-image, lz/deep-research, lz/osint, memory/*, "
             f"scheduler/watch-sweep, scheduler/indicator-pre-reminders, call-python")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


