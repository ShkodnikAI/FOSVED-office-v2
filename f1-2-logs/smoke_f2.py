#!/usr/bin/env python3
"""Smoke-test F-2: S1-S8 scenarios via SQL logic equivalent to DeliverDueReminders().
Uses SQLite in-memory database, replicates the exact query + update logic."""

import sqlite3
from datetime import datetime, timedelta

def setup_db():
    conn = sqlite3.connect(":memory:")
    # Create yana_events table matching production schema
    conn.execute("""
        CREATE TABLE yana_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_text TEXT,
            event_date TEXT,
            event_type TEXT,
            created_at TEXT,
            reminded_at TEXT,
            rrule_kind TEXT,
            fire_time TEXT,
            fire_weekday TEXT,
            fire_monthday TEXT,
            next_fire_at TEXT,
            until_date TEXT,
            active INTEGER DEFAULT 1,
            chat_id TEXT
        )
    """)
    # Create audit_log (for AuditLog pattern)
    conn.execute("""
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            actor TEXT,
            dept TEXT,
            details TEXT,
            status TEXT
        )
    """)
    conn.commit()
    return conn

def deliver_due_reminders(conn, owner_chat_id="123456789"):
    """Replicates the exact logic of DeliverDueReminders() pattern in app.mlog."""
    # Step 1: SELECT due reminders (exact query from code)
    rows = conn.execute("""
        SELECT id, COALESCE(event_text,'') AS event_text, COALESCE(rrule_kind,'') AS rrule_kind,
               COALESCE(fire_time,'') AS fire_time, COALESCE(fire_weekday,'') AS fire_weekday,
               COALESCE(fire_monthday,'') AS fire_monthday, COALESCE(chat_id,'') AS chat_id,
               COALESCE(until_date,'') AS until_date
        FROM yana_events
        WHERE active = 1 AND rrule_kind IS NOT NULL AND rrule_kind != ''
          AND next_fire_at IS NOT NULL AND next_fire_at <= datetime('now')
        ORDER BY next_fire_at ASC LIMIT 20
    """).fetchall()

    count = 0
    sent_messages = []

    for row in rows:
        rid, rtext, rkind, rfire_time, rfire_weekday, rfire_monthday, rchat, runtil = row
        target_chat = rchat if rchat else owner_chat_id
        # Simulate SendTelegramReply — always succeeds in test
        message = f"Напоминание: {rtext}"
        sent_messages.append((target_chat, message))

        # Step 2: Record delivery
        conn.execute("UPDATE yana_events SET reminded_at = datetime('now') WHERE id = ?", (rid,))

        # Step 3: Recalculate next_fire_at based on rrule_kind
        if rkind == "once":
            conn.execute("UPDATE yana_events SET active = 0 WHERE id = ?", (rid,))
        elif rkind == "daily":
            if runtil and runtil != "":
                # Check if next date exceeds until_date
                current_fire_row = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = ?", (rid,)).fetchone()
                fire_val = current_fire_row[0] if current_fire_row else ""
                if fire_val and fire_val[:10] > runtil:
                    conn.execute("UPDATE yana_events SET active = 0 WHERE id = ?", (rid,))
                else:
                    conn.execute("UPDATE yana_events SET next_fire_at = datetime(next_fire_at, '+1 day') WHERE id = ?", (rid,))
            else:
                conn.execute("UPDATE yana_events SET next_fire_at = datetime(next_fire_at, '+1 day') WHERE id = ?", (rid,))
        elif rkind == "weekly":
            if runtil and runtil != "":
                current_fire_row = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = ?", (rid,)).fetchone()
                fire_val = current_fire_row[0] if current_fire_row else ""
                if fire_val and fire_val[:10] > runtil:
                    conn.execute("UPDATE yana_events SET active = 0 WHERE id = ?", (rid,))
                else:
                    conn.execute("UPDATE yana_events SET next_fire_at = datetime(next_fire_at, '+7 days') WHERE id = ?", (rid,))
            else:
                conn.execute("UPDATE yana_events SET next_fire_at = datetime(next_fire_at, '+7 days') WHERE id = ?", (rid,))
        elif rkind == "yearly":
            if runtil and runtil != "":
                current_fire_row = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = ?", (rid,)).fetchone()
                fire_val = current_fire_row[0] if current_fire_row else ""
                if fire_val and fire_val[:10] > runtil:
                    conn.execute("UPDATE yana_events SET active = 0 WHERE id = ?", (rid,))
                else:
                    conn.execute("UPDATE yana_events SET next_fire_at = datetime(next_fire_at, '+1 year') WHERE id = ?", (rid,))
            else:
                conn.execute("UPDATE yana_events SET next_fire_at = datetime(next_fire_at, '+1 year') WHERE id = ?", (rid,))

        count += 1

    # Audit log
    conn.execute("INSERT INTO audit_log (action, actor, dept, details, status) VALUES ('reminders_delivered', 'system', 'system', ?, 'ok')", (f"sent={count}",))
    conn.commit()

    return f"sent={count}", sent_messages


def get_row(conn, id):
    """Get a row for verification."""
    return conn.execute("SELECT id, active, next_fire_at, reminded_at, until_date FROM yana_events WHERE id = ?", (id,)).fetchone()


# ============================================================
# TESTS S1-S8
# ============================================================

print("=" * 60)
print("F-2 SMOKE TESTS S1-S8")
print("=" * 60)

# ── S1: once reminder ─────────────────────────────────────
print("\n=== S1: once reminder ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('тестовое разовое', 'once', '09:00', datetime('now','-1 minute'), 1, '123456789', datetime('now'))
""")
conn.commit()
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
print(f"Result: {result}")
print(f"Message sent: {msgs}")
print(f"After: active={row[1]}, reminded_at={row[3]} (should be filled)")
assert result == "sent=1", f"Expected sent=1, got {result}"
assert row[1] == 0, f"Expected active=0, got {row[1]}"
assert row[3] is not None, "Expected reminded_at filled"
print("S1: PASS ✅")
conn.close()

# ── S2: daily reminder ────────────────────────────────────
print("\n=== S2: daily reminder ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('ежедневный тест', 'daily', '09:00', datetime('now','-1 minute'), 1, '123456789', datetime('now'))
""")
conn.commit()
# Get original next_fire_at
orig_fire = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = 1").fetchone()[0]
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
print(f"Result: {result}")
print(f"Original next_fire_at: {orig_fire}")
print(f"After: active={row[1]}, next_fire_at={row[2]}")
# Verify: shifted exactly +1 day from original
expected_new = conn.execute("SELECT datetime(?, '+1 day')", (orig_fire,)).fetchone()[0]
print(f"Expected next_fire_at: {expected_new}")
assert result == "sent=1", f"Expected sent=1, got {result}"
assert row[1] == 1, f"Expected active=1, got {row[1]}"
assert row[2] == expected_new, f"Expected {expected_new}, got {row[2]}"
print("S2: PASS ✅")
conn.close()

# ── S3: weekly reminder ───────────────────────────────────
print("\n=== S3: weekly reminder ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_weekday, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('недельный тест', 'weekly', 'mon', '09:00', datetime('now','-1 minute'), 1, '123456789', datetime('now'))
""")
conn.commit()
orig_fire = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = 1").fetchone()[0]
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
expected_new = conn.execute("SELECT datetime(?, '+7 days')", (orig_fire,)).fetchone()[0]
print(f"Result: {result}")
print(f"Original next_fire_at: {orig_fire}")
print(f"After: active={row[1]}, next_fire_at={row[2]}")
print(f"Expected: {expected_new}")
assert result == "sent=1"
assert row[1] == 1
assert row[2] == expected_new
print("S3: PASS ✅")
conn.close()

# ── S4: yearly reminder ───────────────────────────────────
print("\n=== S4: yearly reminder ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_monthday, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('годовой тест', 'yearly', '03-15', '09:00', datetime('now','-1 minute'), 1, '123456789', datetime('now'))
""")
conn.commit()
orig_fire = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = 1").fetchone()[0]
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
expected_new = conn.execute("SELECT datetime(?, '+1 year')", (orig_fire,)).fetchone()[0]
print(f"Result: {result}")
print(f"Original next_fire_at: {orig_fire}")
print(f"After: active={row[1]}, next_fire_at={row[2]}")
print(f"Expected: {expected_new}")
assert result == "sent=1"
assert row[1] == 1
assert row[2] == expected_new
print("S4: PASS ✅")
conn.close()

# ── S5: not yet due ────────────────────────────────────────
print("\n=== S5: not yet due ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('будущее напоминание', 'daily', '09:00', datetime('now','+1 hour'), 1, '123456789', datetime('now'))
""")
conn.commit()
orig_fire = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = 1").fetchone()[0]
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
print(f"Result: {result}")
print(f"Messages sent: {len(msgs)}")
print(f"After: active={row[1]}, next_fire_at={row[2]} (unchanged)")
assert result == "sent=0", f"Expected sent=0, got {result}"
assert row[1] == 1
assert row[2] == orig_fire, f"next_fire_at should be unchanged"
print("S5: PASS ✅")
conn.close()

# ── S6: inactive ───────────────────────────────────────────
print("\n=== S6: inactive ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('отключённое', 'daily', '09:00', datetime('now','-1 minute'), 0, '123456789', datetime('now'))
""")
conn.commit()
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
print(f"Result: {result}")
print(f"Messages sent: {len(msgs)}")
print(f"After: active={row[1]} (unchanged)")
assert result == "sent=0"
assert row[1] == 0
print("S6: PASS ✅")
conn.close()

# ── S7: until_date expired ────────────────────────────────
print("\n=== S7: until_date expired ===")
conn = setup_db()
# Set until_date to yesterday, next_fire_at in the past
yesterday = conn.execute("SELECT date(datetime('now','-1 day'))").fetchone()[0]
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, until_date, created_at)
    VALUES ('с ограничением', 'daily', '09:00', datetime('now','-1 minute'), 1, '123456789', ?, datetime('now'))
""", (yesterday,))
conn.commit()
orig_fire = conn.execute("SELECT next_fire_at FROM yana_events WHERE id = 1").fetchone()[0]
result, msgs = deliver_due_reminders(conn)
row = get_row(conn, 1)
print(f"Result: {result}")
print(f"until_date: {yesterday}")
print(f"next_fire_at date portion: {orig_fire[:10]}")
print(f"After: active={row[1]} (should be 0 — deactivated)")
assert result == "sent=1"
assert row[1] == 0, f"Expected active=0 (deactivated due to until_date), got {row[1]}"
print("S7: PASS ✅")
conn.close()

# ── S8: multiple due ──────────────────────────────────────
print("\n=== S8: multiple due ===")
conn = setup_db()
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('первое', 'daily', '09:00', datetime('now','-2 minutes'), 1, '123456789', datetime('now'))
""")
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('второе', 'once', '10:00', datetime('now','-1 minute'), 1, '123456789', datetime('now'))
""")
conn.execute("""
    INSERT INTO yana_events (event_text, rrule_kind, fire_time, next_fire_at, active, chat_id, created_at)
    VALUES ('третье', 'weekly', '09:00', datetime('now','-3 minutes'), 1, '123456789', datetime('now'))
""")
conn.commit()
result, msgs = deliver_due_reminders(conn)
print(f"Result: {result}")
print(f"Messages sent: {len(msgs)}")
# Check each row
row1 = get_row(conn, 1)
row2 = get_row(conn, 2)
row3 = get_row(conn, 3)
print(f"Row 1 (daily):  active={row1[1]}, next_fire_at shifted")
print(f"Row 2 (once):   active={row2[1]} (should be 0)")
print(f"Row 3 (weekly): active={row3[1]}, next_fire_at shifted")
assert result == "sent=3", f"Expected sent=3, got {result}"
assert row2[1] == 0, "once should be deactivated"
assert row1[1] == 1, "daily should remain active"
assert row3[1] == 1, "weekly should remain active"
print("S8: PASS ✅")
conn.close()

print("\n" + "=" * 60)
print("ALL S1-S8 PASSED ✅")
print("=" * 60)
