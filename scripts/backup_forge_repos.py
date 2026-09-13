#!/usr/bin/env python3
"""FOSVED Office — FORGE bare-repo backup via git bundle (FO-042, наряд #149).

Второй рубеж резервного копирования FORGE-хранилища. Зеркало GitHub — громкое
(ForgeMirror, dept/forge.mlog), но остаётся единственным рубежом: повреждение
bare-репозитория при живом GitHub им не обнаруживается. Бандлы создаются
рядом с repos на постоянном диске.

Usage:
  python3 scripts/backup_forge_repos.py backup           # бандлы + retention (+ smoke, если пора)
  python3 scripts/backup_forge_repos.py backup --smoke   # форсировать smoke-восстановление
  python3 scripts/backup_forge_repos.py list             # список бандлов

Environment:
  FORGE_REPOS_DIR        — корень хранилища (default: /var/forge/repos)
  FORGE_BUNDLE_RETENTION — сколько свежих бандлов держать на репозиторий (default: 7, SG-F1)
  FORGE_SMOKE_DAYS       — раз в сколько дней гонять smoke (default: 7)

Layout:
  <FORGE_REPOS_DIR>/forge/repos/*.git   — вход (bare-репозитории)
  <FORGE_REPOS_DIR>/forge/backups/      — выход (<name>-<YYYYMMDD>.bundle)

Итог для брифа: последняя строка stdout — «SUMMARY_LINE: …» (одна строка,
создано N / упало M / суммарный размер; smoke-статус). Полный итог —
«SUMMARY_JSON: {...}» — машиночитаемый (proxy/forge_backup.py парсит его).

Exit codes: 0 — успех; 1 — хотя бы один бандл не создался (громко);
2 — smoke-восстановление провалено (громко).
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

FORGE_REPOS_DIR = os.environ.get("FORGE_REPOS_DIR", "/var/forge/repos")
FORGE_BUNDLE_RETENTION = int(os.environ.get("FORGE_BUNDLE_RETENTION", "7"))
FORGE_SMOKE_DAYS = int(os.environ.get("FORGE_SMOKE_DAYS", "7"))

REPOS_DIR = os.path.join(FORGE_REPOS_DIR, "forge", "repos")
BACKUPS_DIR = os.path.join(FORGE_REPOS_DIR, "forge", "backups")
SMOKE_MARKER = os.path.join(BACKUPS_DIR, ".last_smoke")


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


def run_cmd(cmd: list, cwd: str = None, timeout: int = 300) -> tuple:
    """Run a command, return (returncode, combined_output)."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except Exception as e:
        return -1, str(e)


def bare_has_refs(bare: str) -> bool:
    """Пустой bare не бандлится (git bundle отказывается создавать пустой)."""
    rc, out = run_cmd(["git", "-C", bare, "for-each-ref", "--count=1"])
    return rc == 0 and out.strip() != ""


def do_bundle(bare: str, date_stamp: str) -> tuple:
    """Create a bundle for one bare repo. Returns (ok, path_or_msg, size_bytes)."""
    name = os.path.basename(bare)[: -len(".git")]
    bundle_path = os.path.join(BACKUPS_DIR, f"{name}-{date_stamp}.bundle")
    rc, out = run_cmd(["git", "-C", bare, "bundle", "create", bundle_path, "--all"])
    if rc != 0:
        return False, f"git bundle failed: {out[-300:]}", 0
    if not os.path.exists(bundle_path) or os.path.getsize(bundle_path) == 0:
        return False, "bundle file missing/empty after create", 0
    return True, bundle_path, os.path.getsize(bundle_path)


def do_retention(name: str) -> int:
    """Keep the last FORGE_BUNDLE_RETENTION bundles per repo, remove older. Returns removed count."""
    pattern = os.path.join(BACKUPS_DIR, f"{name}-*.bundle")
    bundles = sorted(glob.glob(pattern))
    removed = 0
    for old in bundles[:-FORGE_BUNDLE_RETENTION] if FORGE_BUNDLE_RETENTION > 0 else []:
        try:
            os.remove(old)
            log(f"  retention: removed {os.path.basename(old)}")
            removed += 1
        except OSError as e:
            log(f"  retention remove failed: {old} — {e}")
    return removed


def smoke_due() -> bool:
    """Smoke-восстановление раз в FORGE_SMOKE_DAYS дней (маркер-файл)."""
    if not os.path.exists(SMOKE_MARKER):
        return True
    try:
        last = datetime.fromisoformat(open(SMOKE_MARKER).read().strip())
        age_days = (datetime.now(timezone.utc) - last).total_seconds() / 86400.0
        return age_days >= FORGE_SMOKE_DAYS
    except (ValueError, OSError):
        return True


def do_smoke(bundles: list) -> tuple:
    """git clone свежайшего бандла во временный каталог → HEAD читается → log не пуст.

    Returns (ok: bool, message: str). Пустой список бандлов → пропущен (ok).
    """
    if not bundles:
        return True, "пропущен: бандлов ещё нет"
    newest = max(bundles, key=os.path.getmtime)
    tmp = tempfile.mkdtemp(prefix="forge-smoke-")
    try:
        rc, out = run_cmd(["git", "clone", "-q", newest, tmp + "/clone"], timeout=120)
        if rc != 0:
            return False, f"clone failed: {out[-300:]}"
        rc, head = run_cmd(["git", "-C", tmp + "/clone", "rev-parse", "--verify", "HEAD"])
        if rc != 0 or not head.strip():
            return False, "HEAD не читается"
        rc, logline = run_cmd(["git", "-C", tmp + "/clone", "log", "--oneline", "-1"])
        if rc != 0 or not logline.strip():
            return False, "git log пуст"
        return True, f"OK ({os.path.basename(newest)}, HEAD {head.strip()[:12]})"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def do_backup(force_smoke: bool = False) -> dict:
    """Bundle every bare repo, apply retention, run smoke if due."""
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    date_stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    bares = sorted(glob.glob(os.path.join(REPOS_DIR, "*.git")))

    created, failed, total_size = 0, 0, 0
    all_bundles = []
    failures = []

    for bare in bares:
        name = os.path.basename(bare)[: -len(".git")]
        if not bare_has_refs(bare):
            log(f"{name}: пустой репозиторий (нет refs) — бандл не создаётся, не сбой")
            continue
        ok, path_or_msg, size = do_bundle(bare, date_stamp)
        if ok:
            created += 1
            total_size += size
            all_bundles.append(path_or_msg)
            log(f"  OK: {os.path.basename(path_or_msg)} ({size / (1024 * 1024):.2f} MB)")
        else:
            failed += 1
            failures.append(f"{name}: {path_or_msg}")
            log(f"  FAIL: {name} — {path_or_msg}")
        do_retention(name)

    # бандлы прошлых дней — тоже валидные кандидаты для smoke
    all_bundles = all_bundles or sorted(glob.glob(os.path.join(BACKUPS_DIR, "*.bundle")))

    smoke_status, smoke_msg = "пропущен", "не пора (маркер свежий)"
    if bares and (force_smoke or smoke_due()):
        smoke_ok, smoke_msg = do_smoke(all_bundles)
        smoke_status = "ok" if smoke_ok else "ПРОВАЛ"
        try:
            with open(SMOKE_MARKER, "w") as f:
                f.write(datetime.now(timezone.utc).isoformat())
        except OSError as e:
            log(f"  smoke marker write failed: {e}")
        if not smoke_ok:
            log(f"  SMOKE FAIL: {smoke_msg}")
        else:
            log(f"  smoke: {smoke_msg}")

    summary = {
        "ok": failed == 0 and smoke_status != "ПРОВАЛ",
        "repos": len(bares),
        "created": created,
        "failed": failed,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "smoke": smoke_status,
        "smoke_msg": smoke_msg,
        "failures": failures,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    line = (f"создано {created}, упало {failed}, всего {summary['total_size_mb']} МБ "
            f"(репозиториев {len(bares)}); smoke-восстановление: {smoke_status}")
    return {"summary": summary, "line": line}


def do_list():
    if not os.path.exists(BACKUPS_DIR):
        log(f"Нет каталога бандлов: {BACKUPS_DIR}")
        return
    bundles = sorted(glob.glob(os.path.join(BACKUPS_DIR, "*.bundle")))
    if not bundles:
        log("Бандлов пока нет")
        return
    for b in bundles:
        size_mb = os.path.getsize(b) / (1024 * 1024)
        log(f"  {os.path.basename(b)} ({size_mb:.2f} MB)")


def main():
    parser = argparse.ArgumentParser(description="FOSVED FORGE bare-repo bundle backup")
    sub = parser.add_subparsers(dest="command", required=True)
    bk = sub.add_parser("backup", help="Create bundles + retention (+ smoke if due)")
    bk.add_argument("--smoke", action="store_true", help="Force smoke restore check")
    sub.add_parser("list", help="List bundles")
    args = parser.parse_args()

    if args.command == "list":
        do_list()
        return

    result = do_backup(force_smoke=getattr(args, "smoke", False))
    print(f"SUMMARY_JSON: {json.dumps(result['summary'], ensure_ascii=False)}")
    print(f"SUMMARY_LINE: {result['line']}")
    log(f"Backup complete: {result['line']}")
    if not result["summary"]["ok"]:
        sys.exit(2 if result["summary"]["smoke"] == "ПРОВАЛ" else 1)


if __name__ == "__main__":
    main()
