#!/usr/bin/env python3
"""FOSVED Office — Database Backup & Restore.

Usage:
  python3 scripts/backup_db.py backup                  # Create backup now
  python3 scripts/backup_db.py backup --upload         # Backup + upload via hook
  python3 scripts/backup_db.py restore [--latest]      # Restore from latest backup
  python3 scripts/backup_db.py list                    # List available backups
  python3 scripts/backup_db.py check                   # Integrity check on live DB

Environment:
  DATABASE_PATH     — path to data dir (default: ./data)
  BACKUP_DIR        — where backups are stored (default: ./data/backups)
  BACKUP_RETENTION  — number of backups to keep (default: 7)
  BACKUP_UPLOAD_CMD — shell command to upload file (optional, receives $FILE)
"""

import argparse
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data")
BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(DATABASE_PATH, "backups"))
BACKUP_RETENTION = int(os.environ.get("BACKUP_RETENTION", "7"))
BACKUP_UPLOAD_CMD = os.environ.get("BACKUP_UPLOAD_CMD", "")

DB_FILES = ["fosved.db", "memory.db"]


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def db_paths() -> list[str]:
    """Return list of existing DB file paths."""
    found = []
    for name in DB_FILES:
        path = os.path.join(DATABASE_PATH, name)
        if os.path.exists(path):
            found.append(path)
    return found


def integrity_check(db_path: str) -> bool:
    """Run PRAGMA integrity_check on a database (or backup file)."""
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        ok = result[0] == "ok"
        if ok:
            log(f"  INTEGRITY OK: {db_path}")
        else:
            log(f"  INTEGRITY FAIL: {db_path} — {result[0]}")
        return ok
    except Exception as e:
        log(f"  INTEGRITY ERROR: {db_path} — {e}")
        return False


def table_count(db_path: str) -> int:
    """Count tables in a database."""
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def do_backup(upload: bool = False) -> int:
    """Create backups of all DB files using VACUUM INTO."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backed_up = 0

    for db_path in db_paths():
        db_name = os.path.basename(db_path)
        backup_name = f"{db_name}.{timestamp}"
        backup_path = os.path.join(BACKUP_DIR, backup_name)

        log(f"Backing up {db_path} → {backup_path}")

        # Check live DB integrity before backup
        if not integrity_check(db_path):
            log(f"  SKIP: {db_path} failed integrity check — not backing up corrupt DB")
            continue

        # VACUUM INTO creates a clean, compact copy
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(f"VACUUM INTO '{backup_path}'")
            conn.close()
        except Exception as e:
            log(f"  VACUUM INTO failed: {e}")
            # Fallback: file copy
            try:
                shutil.copy2(db_path, backup_path)
                log(f"  Fallback: file copy succeeded")
            except Exception as e2:
                log(f"  Fallback also failed: {e2}")
                continue

        # Verify backup integrity
        if not integrity_check(backup_path):
            log(f"  FAIL: backup {backup_path} is corrupt, removing")
            os.remove(backup_path)
            continue

        # Verify table count matches
        live_tables = table_count(db_path)
        backup_tables = table_count(backup_path)
        if live_tables != backup_tables:
            log(f"  WARN: table count mismatch (live={live_tables}, backup={backup_tables})")

        size_mb = os.path.getsize(backup_path) / (1024 * 1024)
        log(f"  OK: {backup_name} ({size_mb:.1f} MB, {backup_tables} tables)")
        backed_up += 1

        # Upload hook
        if upload and BACKUP_UPLOAD_CMD:
            log(f"  Uploading {backup_path}...")
            try:
                env = os.environ.copy()
                env["FILE"] = backup_path
                result = subprocess.run(
                    BACKUP_UPLOAD_CMD, shell=True, env=env,
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    log(f"  Upload OK: {result.stdout.strip()[:100]}")
                else:
                    log(f"  Upload FAILED (rc={result.returncode}): {result.stderr.strip()[:200]}")
            except Exception as e:
                log(f"  Upload error: {e}")

    # Retention: remove old backups
    if BACKUP_RETENTION > 0:
        for db_name in DB_FILES:
            pattern = os.path.join(BACKUP_DIR, f"{db_name}.*")
            backups = sorted(glob.glob(pattern), reverse=True)
            for old in backups[BACKUP_RETENTION:]:
                log(f"  Retention: removing {os.path.basename(old)}")
                os.remove(old)

    return backed_up


def do_restore(latest: bool = False) -> bool:
    """Restore databases from backup."""
    restored = 0
    for db_name in DB_FILES:
        db_path = os.path.join(DATABASE_PATH, db_name)
        pattern = os.path.join(BACKUP_DIR, f"{db_name}.*")
        backups = sorted(glob.glob(pattern), reverse=True)

        if not backups:
            log(f"No backups found for {db_name}")
            continue

        if not latest:
            # Show available backups and ask for confirmation
            log(f"Available backups for {db_name}:")
            for i, b in enumerate(backups[:10]):
                size = os.path.getsize(b) / (1024 * 1024)
                ts = os.path.basename(b).split(".")[-1] if "." in os.path.basename(b) else "?"
                log(f"  [{i}] {os.path.basename(b)} ({size:.1f} MB)")
            # Use latest by default
            backup_path = backups[0]
        else:
            backup_path = backups[0]

        # Verify backup integrity before restore
        if not integrity_check(backup_path):
            log(f"  FAIL: cannot restore corrupt backup {backup_path}")
            continue

        # Restore: copy backup over live DB
        try:
            if os.path.exists(db_path):
                # Keep a pre-restore copy
                pre_restore = f"{db_path}.pre-restore"
                shutil.copy2(db_path, pre_restore)
                log(f"  Pre-restore copy: {pre_restore}")

            shutil.copy2(backup_path, db_path)
            log(f"  RESTORED: {db_name} from {os.path.basename(backup_path)}")
            restored += 1

            # Verify restored DB
            if not integrity_check(db_path):
                log(f"  CRITICAL: restored DB failed integrity check!")

        except Exception as e:
            log(f"  Restore error: {e}")

    return restored > 0


def do_list():
    """List available backups."""
    if not os.path.exists(BACKUP_DIR):
        log(f"No backup directory: {BACKUP_DIR}")
        return

    for db_name in DB_FILES:
        pattern = os.path.join(BACKUP_DIR, f"{db_name}.*")
        backups = sorted(glob.glob(pattern), reverse=True)
        if backups:
            log(f"\n{db_name} — {len(backups)} backup(s):")
            for b in backups[:20]:
                size = os.path.getsize(b) / (1024 * 1024)
                tables = table_count(b)
                ok = integrity_check(b)
                log(f"  {'OK' if ok else 'CORRUPT'} {os.path.basename(b)} ({size:.1f} MB, {tables} tables)")
        else:
            log(f"\n{db_name} — no backups")


def do_check():
    """Run integrity check on live databases."""
    for db_path in db_paths():
        ok = integrity_check(db_path)
        tables = table_count(db_path)
        size = os.path.getsize(db_path) / (1024 * 1024)
        log(f"{'OK' if ok else 'CORRUPT'} {db_path} ({size:.1f} MB, {tables} tables)")


def main():
    parser = argparse.ArgumentParser(description="FOSVED Database Backup & Restore")
    sub = parser.add_subparsers(dest="command", required=True)

    bk = sub.add_parser("backup", help="Create backup")
    bk.add_argument("--upload", action="store_true", help="Upload via BACKUP_UPLOAD_CMD hook")

    rs = sub.add_parser("restore", help="Restore from backup")
    rs.add_argument("--latest", action="store_true", help="Use latest backup (no prompt)")

    sub.add_parser("list", help="List available backups")
    sub.add_parser("check", help="Integrity check on live DB")

    args = parser.parse_args()

    if args.command == "backup":
        count = do_backup(upload=args.upload)
        log(f"Backup complete: {count} database(s) backed up")
        sys.exit(0 if count > 0 else 1)

    elif args.command == "restore":
        ok = do_restore(latest=args.latest)
        sys.exit(0 if ok else 1)

    elif args.command == "list":
        do_list()

    elif args.command == "check":
        do_check()


if __name__ == "__main__":
    main()
