#!/usr/bin/env python3
"""Migrate FOSVED Office v2 DB schema from old Python column names to new unified names.
Old names were used by llm_proxy.py; new names match app.mlog (Metalogos) schema.

Usage: python3 scripts/migrate_schema.py [path_to_db]
  Default: data/fosved.db (relative to this script's parent dir)
"""

import sqlite3, sys, os

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'data', 'fosved.db')

def column_exists(cur, table, col):
    """Check if a column exists in a table."""
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    return col in cols

def rename_column(cur, table, old_col, new_col):
    """Rename a column, skipping if already renamed or not present."""
    if not column_exists(cur, table, old_col):
        print(f"  SKIP {table}.{old_col} -> {new_col} (old column not found)")
        return
    if column_exists(cur, table, new_col):
        print(f"  SKIP {table}.{old_col} -> {new_col} (already renamed)")
        return
    try:
        cur.execute(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {new_col}")
        print(f"  OK   {table}.{old_col} -> {new_col}")
    except Exception as e:
        print(f"  FAIL {table}.{old_col} -> {new_col}: {e}")

def add_column(cur, table, col, col_type):
    """Add a column, skipping if already present."""
    if column_exists(cur, table, col):
        print(f"  SKIP {table}.{col} (already exists)")
        return
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        print(f"  OK   {table}.{col} ({col_type}) added")
    except Exception as e:
        print(f"  FAIL {table}.{col}: {e}")

def main():
    print(f"=== Schema Migration ===")
    print(f"DB: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("DB file not found. Nothing to migrate (fresh install will use new schema).")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check if migration is needed: if dialog_history has 'created' but not 'created_at'
    if not column_exists(cur, 'dialog_history', 'created'):
        print("dialog_history has no 'created' column — migration already applied or fresh DB.")
        conn.close()
        return

    print("\n--- Renaming columns ---")

    # dialog_history: created -> created_at
    rename_column(cur, 'dialog_history', 'created', 'created_at')

    # adapt_corrections: original -> original_query, corrected -> correction, created -> created_at
    rename_column(cur, 'adapt_corrections', 'original', 'original_query')
    rename_column(cur, 'adapt_corrections', 'corrected', 'correction')
    rename_column(cur, 'adapt_corrections', 'created', 'created_at')

    # error_patterns: context -> query_text, created -> created_at
    rename_column(cur, 'error_patterns', 'context', 'query_text')
    rename_column(cur, 'error_patterns', 'created', 'created_at')

    # token_usage: tokens_in -> input_tokens, tokens_out -> output_tokens, cost -> cost_usd, created -> created_at
    rename_column(cur, 'token_usage', 'tokens_in', 'input_tokens')
    rename_column(cur, 'token_usage', 'tokens_out', 'output_tokens')
    rename_column(cur, 'token_usage', 'cost', 'cost_usd')
    rename_column(cur, 'token_usage', 'created', 'created_at')

    # audit_log: created -> timestamp
    rename_column(cur, 'audit_log', 'created', 'timestamp')

    # dept_metrics: rating -> metric_value, created -> created_at
    rename_column(cur, 'dept_metrics', 'rating', 'metric_value')
    rename_column(cur, 'dept_metrics', 'created', 'created_at')

    # miniapp_responses: created -> created_at
    rename_column(cur, 'miniapp_responses', 'created', 'created_at')

    # miniapp_notes: created -> created_at
    rename_column(cur, 'miniapp_notes', 'created', 'created_at')

    print("\n--- Adding new columns ---")

    # adapt_corrections: add original_response TEXT
    add_column(cur, 'adapt_corrections', 'original_response', 'TEXT')

    # error_patterns: add correction TEXT
    add_column(cur, 'error_patterns', 'correction', 'TEXT')

    # token_usage: add request_type TEXT
    add_column(cur, 'token_usage', 'request_type', 'TEXT')

    # audit_log: add actor TEXT, dept TEXT, status TEXT
    add_column(cur, 'audit_log', 'actor', 'TEXT')
    add_column(cur, 'audit_log', 'dept', 'TEXT')
    add_column(cur, 'audit_log', 'status', 'TEXT')

    # dept_metrics: add metric_name TEXT, period TEXT
    add_column(cur, 'dept_metrics', 'metric_name', "TEXT DEFAULT 'satisfaction'")
    add_column(cur, 'dept_metrics', 'period', 'TEXT')

    # miniapp_responses: add query TEXT, confidence TEXT
    add_column(cur, 'miniapp_responses', 'query', 'TEXT')
    add_column(cur, 'miniapp_responses', 'confidence', 'TEXT')

    conn.commit()
    conn.close()
    print("\n=== Migration complete ===")

if __name__ == '__main__':
    main()