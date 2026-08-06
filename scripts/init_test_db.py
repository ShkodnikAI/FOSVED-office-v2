#!/usr/bin/env python3
"""Create test DB with all InitDB tables for WH-1 local test."""
import sqlite3, os

db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'test_wh.db')
os.makedirs(os.path.dirname(db_path), exist_ok=True)
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()

TABLES = [
    "CREATE TABLE IF NOT EXISTS dialog_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, dept TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS adapt_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, original_query TEXT, original_response TEXT, correction TEXT, corr_type TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS error_patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, error_type TEXT, query_text TEXT, correction TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS miniapp_responses (id TEXT PRIMARY KEY, dept TEXT, title TEXT, query TEXT, raw_text TEXT, html TEXT, confidence TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS miniapp_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, note_text TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS dept_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, metric_name TEXT, metric_value TEXT, period TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS token_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, provider TEXT, model TEXT, input_tokens TEXT, output_tokens TEXT, cost_usd TEXT, request_type TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP, action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT)",
    "CREATE TABLE IF NOT EXISTS narads (id TEXT PRIMARY KEY, title TEXT, description TEXT, requested_by TEXT, changed_files TEXT, risk_level TEXT, status TEXT, created_at TEXT DEFAULT (datetime('now')), approved_at TEXT, executed_at TEXT, result TEXT)",
    "CREATE TABLE IF NOT EXISTS debriefs (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, period TEXT, content TEXT, actions_taken TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS admin_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, content TEXT, duration_sec TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS admin_findings (id INTEGER PRIMARY KEY AUTOINCREMENT, severity TEXT, file_path TEXT, issue TEXT, fix_suggestion TEXT, status TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS admin_proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, status TEXT, narad_id TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT, node_name TEXT, file_path TEXT, line_start TEXT, line_end TEXT, description TEXT, updated_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS knowledge_edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT, target_name TEXT, edge_type TEXT, file_path TEXT, updated_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS channel_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, dept TEXT, title TEXT, channel_message_id TEXT, archived_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS factory_orders (id TEXT PRIMARY KEY, client_name TEXT, status TEXT, requirements TEXT, departments TEXT, branding TEXT, llm_config TEXT, repo_url TEXT, render_url TEXT, created_at TEXT DEFAULT (datetime('now')), completed_at TEXT)",
    "CREATE TABLE IF NOT EXISTS lz_telegram_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, channel_name TEXT, category TEXT, added_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS lz_telegram_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT, channel_name TEXT, text TEXT, date TEXT, scanned_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS lz_monitors (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, sources TEXT, frequency TEXT, last_scan TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS yana_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_text TEXT, event_date TEXT, event_type TEXT DEFAULT 'reminder', created_at TEXT DEFAULT (datetime('now')), reminded_at TEXT, rrule_kind TEXT, fire_time TEXT, fire_weekday TEXT, fire_monthday TEXT, next_fire_at TEXT, until_date TEXT, active INTEGER DEFAULT 1, chat_id TEXT)",
    "CREATE TABLE IF NOT EXISTS analysis (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, full_result TEXT, status TEXT DEFAULT 'drafted', verification_date TEXT, confidence TEXT, created_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS research_source (id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, url TEXT, title TEXT, tier TEXT DEFAULT 'secondary', claim TEXT, created_at TEXT DEFAULT (datetime('now')), FOREIGN KEY(analysis_id) REFERENCES analysis(id))",
    "CREATE TABLE IF NOT EXISTS dept_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, title TEXT, content TEXT, source_query TEXT, archived_at TEXT DEFAULT (datetime('now')))",
    "CREATE TABLE IF NOT EXISTS remind_store (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, text TEXT, fire_at TEXT, created_at TEXT DEFAULT (datetime('now')), fired INTEGER DEFAULT 0)",
]

for ddl in TABLES:
    c.execute(ddl)
conn.commit()
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
conn.close()
print(f"Created {len(tables)} tables in {db_path}")
