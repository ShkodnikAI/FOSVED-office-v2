#!/usr/bin/env python3
"""FO-042 tests: резервный контур FORGE (наряд #149).

Критерии «сделано, когда» (по наряду):
- bundle создаётся по расписанию и восстанавливается (smoke зелёный);
- пустой bare не бандлится и НЕ считается сбоем;
- retention держит ровно FORGE_BUNDLE_RETENTION свежих бандлов на репозиторий;
- итог парсится: line (для брифа) + counts (created/failed/total_size_mb);
- выгрузка forge_* пишет JSON с четырьмя секциями и зовёт sendDocument;
- summary хранится в system_settings (key forge_backup_summary) — общее kv
  с Metalogos;
- /cron/backup-forge защищён CRON_SECRET.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-fo42-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')
os.environ.setdefault('CRON_SECRET', 'test-cron-secret')

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "backup_forge_repos.py")


def _mk_bare(root: str, name: str, with_commit: bool) -> str:
    bare = os.path.join(root, "forge", "repos", f"{name}.git")
    os.makedirs(bare, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
    if with_commit:
        work = os.path.join(root, f"_work_{name}")
        os.makedirs(work, exist_ok=True)
        subprocess.run(["git", "-C", work, "init", "-q", "-b", "main"], check=True)
        with open(os.path.join(work, "f.txt"), "w") as f:
            f.write("hello\n")
        subprocess.run(["git", "-C", work, "add", "."], check=True)
        subprocess.run(["git", "-C", work, "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", "init"], check=True)
        subprocess.run(["git", "-C", work, "push", "-q", bare, "main"], check=True)
    return bare


def _run_script(root: str, *extra: str) -> tuple:
    env = {**os.environ, "FORGE_REPOS_DIR": root, "FORGE_BUNDLE_RETENTION": "7",
           "FORGE_SMOKE_DAYS": "7"}
    r = subprocess.run([sys.executable, SCRIPT, *extra], capture_output=True, text=True,
                       env=env, timeout=180)
    out = r.stdout + r.stderr
    summary, line = {}, ""
    for l in out.splitlines():
        if l.startswith("SUMMARY_JSON: "):
            summary = json.loads(l[len("SUMMARY_JSON: "):])
        if l.startswith("SUMMARY_LINE: "):
            line = l[len("SUMMARY_LINE: "):].strip()
    return r, summary, line


def test_bundle_created_and_smoke_green(tmp_path):
    """A.1/A.4: бандл создаётся, smoke-восстановление зелёный, пустой bare — не сбой."""
    root = str(tmp_path)
    _mk_bare(root, "alpha", with_commit=True)
    _mk_bare(root, "empty", with_commit=False)
    r, summary, line = _run_script(root, "backup", "--smoke")
    assert r.returncode == 0, out_tail(r)
    bundle = os.path.join(root, "forge", "backups", f"alpha-{summary['ts'][:10].replace('-', '')}.bundle")
    assert os.path.exists(bundle), f"бандл не создан: {line}"
    assert os.path.getsize(bundle) > 0
    # пустой bare: пропущен, не упал
    assert summary["repos"] == 2 and summary["created"] == 1 and summary["failed"] == 0
    assert summary["smoke"] == "ok"
    # строка для брифа: создано N, упало M, суммарный размер — одной строкой
    assert "создано 1" in line and "упало 0" in line and "МБ" in line
    assert "smoke-восстановление: ok" in line


def test_retention_keeps_seven(tmp_path):
    """A.3: retention — последние 7 бандлов на репозиторий (SG-F1), старые удаляются."""
    root = str(tmp_path)
    _mk_bare(root, "beta", with_commit=True)
    backups = os.path.join(root, "forge", "backups")
    os.makedirs(backups, exist_ok=True)
    # 9 фейковых старых бандлов за прошлые дни + git bundle за сегодня = 10
    for d in range(1, 10):
        with open(os.path.join(backups, f"beta-2026090{d}.bundle"), "wb") as f:
            f.write(b"stub")
    r, summary, line = _run_script(root, "backup", "--smoke")
    assert r.returncode == 0, out_tail(r)
    remaining = sorted(f for f in os.listdir(backups) if f.startswith("beta-") and f.endswith(".bundle"))
    assert len(remaining) == 7, f"retention держит 7, осталось {len(remaining)}: {remaining}"


def test_missing_repos_dir_is_not_crash(tmp_path):
    """Хранилища ещё нет (свежий деплой) — скрипт отрабатывает с нулевыми счётчиками."""
    root = str(tmp_path)
    r, summary, line = _run_script(root, "backup", "--smoke")
    assert r.returncode == 0
    assert summary["created"] == 0 and summary["failed"] == 0


def out_tail(r) -> str:
    return (r.stdout + r.stderr)[-400:]


# ── export_forge_state + summary store (python-плоскость) ────────────────


@pytest.fixture()
def forge_module(tmp_path, monkeypatch):
    """proxy.forge_backup с подменёнными Telegram-вызовами и живым SQLite."""
    import llm_proxy  # noqa: F401 — инициализация прокси-плоскости
    from proxy import forge_backup as fb
    from proxy.core import _query

    sent = {}

    def fake_send_document(chat_id, file_path, caption=None):
        sent["chat_id"] = chat_id
        sent["path"] = file_path
        sent["caption"] = caption
        return 4242

    monkeypatch.setattr(fb, "_tg_send_document", fake_send_document)
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "12345")
    exports_root = str(tmp_path / "exports")
    os.makedirs(exports_root, exist_ok=True)
    monkeypatch.setattr(fb, "_exports_dir", lambda: exports_root)
    _query("CREATE TABLE IF NOT EXISTS forge_projects (slug TEXT PRIMARY KEY, name TEXT, project_type TEXT, status TEXT, gate_policy TEXT, customer_name TEXT, updated_at TEXT)")
    _query("CREATE TABLE IF NOT EXISTS forge_tasks (id INTEGER PRIMARY KEY, project_slug TEXT, title TEXT, status TEXT, priority TEXT, created_by TEXT, claimed_by TEXT, updated_at TEXT)")
    _query("CREATE TABLE IF NOT EXISTS forge_gates (id INTEGER PRIMARY KEY, task_id TEXT, stage_id TEXT, kind TEXT, question TEXT, options_json TEXT, decision TEXT, created_at TEXT)")
    _query("CREATE TABLE IF NOT EXISTS forge_remarks (id INTEGER PRIMARY KEY, task_id TEXT, stage_id TEXT, commit_sha TEXT, text TEXT, kind TEXT, status TEXT, created_at TEXT)")
    for t in ("forge_projects", "forge_tasks", "forge_gates", "forge_remarks"):
        _query(f"DELETE FROM {t}")
    yield fb, sent, _query
    sent.clear()


def test_export_state_sections_and_document(forge_module):
    """B.1: четыре секции (проекты/открытые задачи/гейты без решения/открытые замечания),
    JSON-файл на диске, документ владельцу отправлен."""
    fb, sent, _query = forge_module
    _query("INSERT INTO forge_projects (slug, name, project_type, status, gate_policy, customer_name, updated_at) VALUES ('p1', 'Проект', 'site', 'active', 'key_stages', 'Заказчик', 'now')")
    _query("INSERT INTO forge_tasks (project_slug, title, status, priority) VALUES ('p1', 'Открытая', 'in_progress', 'high')")
    _query("INSERT INTO forge_tasks (project_slug, title, status, priority) VALUES ('p1', 'Закрытая', 'done', 'low')")
    _query("INSERT INTO forge_gates (task_id, kind, question, decision) VALUES (1, 'plan', 'Утвердить?', NULL)")
    _query("INSERT INTO forge_remarks (task_id, text, kind, status) VALUES (1, 'Поправить', 'fix', 'open')")

    result = fb.export_forge_state()
    assert result["ok"] is True, result["error"]
    assert result["counts"] == {"projects": 1, "tasks_open": 1, "gates_pending": 1, "remarks_open": 1}
    with open(result["path"], encoding="utf-8") as f:
        payload = json.load(f)
    assert set(payload.keys()) >= {"exported_at", "forge_projects", "forge_tasks_open", "forge_gates_pending", "forge_remarks_open"}
    assert len(payload["forge_tasks_open"]) == 1  # done не попадает
    assert sent["chat_id"] == "12345" and sent["path"] == result["path"]
    assert "гейтов без решения 1" in sent["caption"]


def test_export_state_no_owner_no_crash(forge_module, monkeypatch):
    """Без владельца документ не уйдёт, но файл и счётчики честные, ok=False — громко."""
    fb, sent, _query = forge_module
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    result = fb.export_forge_state(chat_id="")
    assert result["ok"] is False
    assert os.path.exists(result["path"])
    assert "chat_id" not in sent


def test_summary_store_roundtrip(forge_module):
    """Итог бэкапа хранится в system_settings (forge_backup_summary) — бриф читает."""
    fb, sent, _query = forge_module
    _query("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
    fb.store_backup_summary({"ok": True, "line": "создано 2, упало 0, всего 1.5 МБ (репозиториев 2); smoke-восстановление: ok"})
    rows = _query("SELECT value FROM system_settings WHERE key = 'forge_backup_summary'", fetch=True)
    assert rows and json.loads(rows[0]["value"])["ok"] is True
    assert fb.forge_backup_summary_line().startswith("создано 2")


def test_run_forge_backup_subprocess_integration(tmp_path, forge_module):
    """Сквозной прогон: python-плоскость запускает скрипт, парсит SUMMARY_JSON."""
    fb, sent, _query = forge_module
    _query("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
    root = str(tmp_path / "repos")
    _mk_bare(root, "gamma", with_commit=True)
    old = os.environ.get("FORGE_REPOS_DIR")
    os.environ["FORGE_REPOS_DIR"] = root
    try:
        result = fb.run_forge_backup(force_smoke=True)
        assert result["ok"] is True, result["raw"]
        assert result["summary"]["created"] == 1 and result["summary"]["smoke"] == "ok"
        assert "упало 0" in result["line"]
    finally:
        if old is None:
            os.environ.pop("FORGE_REPOS_DIR", None)
        else:
            os.environ["FORGE_REPOS_DIR"] = old


def test_cron_endpoint_requires_secret(forge_module):
    """/cron/backup-forge без CRON_SECRET — 403 (контур не должен быть публичным)."""
    fb, sent, _query = forge_module
    from proxy.routes_tail import app as tail_app
    tail_app.config["TESTING"] = True
    client = tail_app.test_client()
    assert client.get("/cron/backup-forge").status_code == 403
    assert client.get("/cron/backup-forge?secret=wrong").status_code == 403
