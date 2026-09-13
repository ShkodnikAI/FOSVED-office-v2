"""FO-042 (наряд #149): резервный контур FORGE — python-плоскость.

Две обязанности:
1. Резервный контур (§15): запуск scripts/backup_forge_repos.py (git bundle
   bare-репозиториев), парсинг итога, запись строки для брифа в
   system_settings (key forge_backup_summary — общее kv с Metalogos).
2. Выгрузка состояния FORGE (§10): выборка forge_projects / открытых
   forge_tasks / гейтов без решения / открытых замечаний → JSON-файл на
   постоянном диске → документом владельцу в Telegram. Телеграм — канал
   доставки, не хранилище: файл остаётся в FORGE_REPOS_DIR/forge/exports.

Неудачи ГРОМКИЕ: бэкап-сбой попадает в строку брифа и в audit_log, не глушится.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

from proxy.core import log, _query, _log_audit, _log_error, DB_PATH
from proxy.telegram import _tg_send_document

# Скрипт-бэкап живёт в scripts/ рядом с корнем репо
_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "backup_forge_repos.py")


def _exports_dir() -> str:
    """Выгрузки — на постоянном диске рядом с repos; недоступен — fallback в data/."""
    root = os.environ.get("FORGE_REPOS_DIR", "/var/forge/repos")
    primary = os.path.join(root, "forge", "exports")
    try:
        os.makedirs(primary, exist_ok=True)
        return primary
    except OSError as e:
        log.warning(f"[forge_backup] exports dir {primary} unwritable ({e}) — fallback в data/")
        fallback = os.path.join(os.environ.get("DATABASE_PATH", "./data"), "forge_exports")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def run_forge_backup(force_smoke: bool = False) -> dict:
    """Запустить bundle-бэкап скриптом. Возвращает {ok, line, summary, raw}.

    Никогда не бросает исключение наружу — вызывающий (бриф) должен
    продолжаться при любой неудаче бэкапа; неудача фиксируется в итоге.
    """
    cmd = [sys.executable, _SCRIPT, "backup"]
    if force_smoke:
        cmd.append("--smoke")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=420,
                           env={**os.environ})
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"^SUMMARY_JSON: (.*)$", out, re.M)
        summary = {}
        if m:
            try:
                summary = json.loads(m.group(1))
            except json.JSONDecodeError:
                summary = {"parse_error": m.group(1)[:200]}
        m2 = re.search(r"^SUMMARY_LINE: (.*)$", out, re.M)
        line = m2.group(1).strip() if m2 else ""
        ok = r.returncode == 0
        result = {"ok": ok, "rc": r.returncode, "line": line, "summary": summary, "raw": out[-800:]}
        if not ok:
            _log_error(f"forge bundle backup rc={r.returncode}: {line or out[-300:]}",
                       source="forge_backup", kind="backup")
        _log_audit("forge_bundle_backup", {"ok": ok, "rc": r.returncode, "line": line}, "system")
        return result
    except subprocess.TimeoutExpired:
        _log_error("forge bundle backup timeout 420s", source="forge_backup", kind="backup")
        return {"ok": False, "rc": 124, "line": "бэкап FORGE: таймаут 420 с — громкая неудача",
                "summary": {"ok": False, "timeout": True}, "raw": ""}
    except Exception as e:
        _log_error(f"forge bundle backup failed: {e}", source="forge_backup", kind="backup")
        return {"ok": False, "rc": -1, "line": f"бэкап FORGE: сбой запуска ({e})",
                "summary": {"ok": False, "error": str(e)}, "raw": ""}


def store_backup_summary(result: dict) -> None:
    """Строка итога — в system_settings (key forge_backup_summary): бриф читает оттуда."""
    try:
        value = json.dumps({
            "line": result.get("line", ""),
            "ok": result.get("ok", False),
            "ts": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)
        _query("INSERT INTO system_settings (key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               ("forge_backup_summary", value))
    except Exception as e:
        # не критично: бриф возьмёт пустую строку, бэкап-файлы уже созданы
        log.warning(f"[forge_backup] summary store failed (non-fatal): {e}")


def forge_backup_summary_line() -> str:
    """Свежая строка итога из system_settings (для ручных вызовов брифа)."""
    try:
        rows = _query("SELECT value FROM system_settings WHERE key = 'forge_backup_summary'", fetch=True)
        if rows:
            data = json.loads(rows[0]["value"])
            return data.get("line", "")
    except Exception as e:
        log.warning(f"[forge_backup] summary read failed: {e}")
    return ""


def export_forge_state(chat_id: str = "") -> dict:
    """Выгрузка forge_* в JSON-файл + документ владельцу (§10).

    Возвращает {ok, path, counts, msg_id, error}. Не бросает исключений.
    """
    counts = {"projects": 0, "tasks_open": 0, "gates_pending": 0, "remarks_open": 0}
    try:
        projects = _query(
            "SELECT slug, name, project_type, status, gate_policy, customer_name, updated_at "
            "FROM forge_projects ORDER BY updated_at DESC", fetch=True) or []
        tasks = _query(
            "SELECT id, project_slug, title, status, priority, created_by, claimed_by, updated_at "
            "FROM forge_tasks WHERE status NOT IN ('done', 'archived') ORDER BY id", fetch=True) or []
        gates = _query(
            "SELECT id, task_id, stage_id, kind, question, options_json, created_at "
            "FROM forge_gates WHERE decision IS NULL OR decision = '' ORDER BY id", fetch=True) or []
        remarks = _query(
            "SELECT id, task_id, stage_id, commit_sha, text, kind, status, created_at "
            "FROM forge_remarks WHERE status = 'open' ORDER BY id", fetch=True) or []
        counts = {"projects": len(projects), "tasks_open": len(tasks),
                  "gates_pending": len(gates), "remarks_open": len(remarks)}
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source": "FOSVED Office FO-042",
            "forge_projects": projects,
            "forge_tasks_open": tasks,
            "forge_gates_pending": gates,
            "forge_remarks_open": remarks,
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(_exports_dir(), f"forge_state_{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        # retention выгрузок: последние 7 файлов
        try:
            exports = sorted(f for f in os.listdir(os.path.dirname(path))
                             if f.startswith("forge_state_") and f.endswith(".json"))
            for old in exports[:-7]:
                os.remove(os.path.join(os.path.dirname(path), old))
        except OSError as e:
            log.warning(f"[forge_backup] export retention failed (non-fatal): {e}")
        # документ владельцу: явно переданный chat_id или OWNER_TELEGRAM_ID
        owner = str(chat_id or "").strip() or str(os.environ.get("OWNER_TELEGRAM_ID", "")).strip()
        msg_id = None
        if owner:
            caption = (f"Состояние FORGE: проектов {counts['projects']}, открытых задач "
                       f"{counts['tasks_open']}, гейтов без решения {counts['gates_pending']}, "
                       f"открытых замечаний {counts['remarks_open']}")
            msg_id = _tg_send_document(owner, path, caption)
        ok = msg_id is not None
        _log_audit("forge_state_export", {"ok": ok, "path": os.path.basename(path), **counts}, "system")
        return {"ok": ok, "path": path, "counts": counts, "msg_id": msg_id, "error": "" if ok else "sendDocument не сработал (нет токена/владельца)"}
    except Exception as e:
        _log_error(f"forge state export failed: {e}", source="forge_backup", kind="export")
        return {"ok": False, "path": "", "counts": counts, "msg_id": None, "error": str(e)[:300]}
