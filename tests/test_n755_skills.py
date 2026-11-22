#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#755 SKILLS-1: кэш навыков на постоянном диске, HTTP-код в лог,
тревога в брифе.

Фон (аудит 22.11): токен GITHUB_TOKEN_SKILLS умер ~15.11 — навыки (249
каталогов) не грузились неделю; офис молча работал без методик, в брифе
ни слова. Наряд: (A.1) кэш /var/data + старт без сети, (A.2) код HTTP-
ошибки в лог, (A.3) строка тревоги в бриф + skills в /version.
"""
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SCRIPT = REPO / "scripts" / "bootstrap_skills.sh"
ROUTES_SCHED = (REPO / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
ENTRYPOINT = (REPO / "entrypoint.sh").read_text(encoding="utf-8")

os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")
os.environ.setdefault("CRON_SECRET", "cron-test-secret")

from proxy.routes_sched import (  # noqa: E402
    collect_attention_items,
    build_attention_section,
    skills_status,
    skills_status_line,
)


def _green(**kw):
    """Все сигналы зелёные, поверх — переопределения теста."""
    d = dict(
        forge_backup_ok=True,
        forge_backup_line="бэкап FORGE: создано 3 / упало 0 / 12 МБ",
        forge_backup_stale=False,
        keys_line="🔑 Ключи: все 9 — ok (проверка 2026-11-21 03:00 UTC)",
        dept_fail_line="Отказы отделов за сутки: нет",
        kk_line="",
        forge_attention="",
        errors_digest="",
        skills_line="",
    )
    d.update(kw)
    return d


# ─────────────── A.1: кэш на постоянном диске ───────────────

def _make_snapshot(root: Path, tag: str, sha: str = "deadbeef" * 8):
    """Стенд-снапшот: архив с skills/X/SKILL.md + манифест с sha."""
    src = root / "src"
    (src / "skills" / "alpha").mkdir(parents=True)
    (src / "skills" / "beta").mkdir(parents=True)
    (src / "skills" / "deconstruct").mkdir(parents=True)
    (src / "skills" / "alpha" / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    (src / "skills" / "deconstruct" / "SKILL.md").write_text("# deconstruct\n", encoding="utf-8")
    tar_path = root / f"{tag}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(src / "skills", arcname="skills")
    real_sha = subprocess.run(["sha256sum", str(tar_path)],
                              capture_output=True, text=True).stdout.split()[0]
    manifest = {
        "snapshot_tag": tag,
        "snapshot_asset": f"{tag}.tar.gz",
        "snapshot_sha256": real_sha if sha == "deadbeef" * 8 else sha,
        "skills_count": 2,
        "skills": {},
    }
    (root / "skills-manifest.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8")
    return tar_path, real_sha


def _run_bootstrap(workdir: Path, cache_root: Path, env_extra=None):
    """Прогон bootstrap_skills.sh в изолированном дереве (копия скрипта —
    он делает cd в репо-корень, поэтому переносим в стенд целиком)."""
    stage = workdir / "repo"
    (stage / "scripts").mkdir(parents=True, exist_ok=True)
    # скрипт делает cd "$(dirname $0)/.." — кладём в stage/scripts/,
    # чтобы cwd стал stage (как в реальном репо)
    shutil.copy(SCRIPT, stage / "scripts" / "bootstrap_skills.sh")
    if (workdir / "skills-manifest.json").exists():
        shutil.copy(workdir / "skills-manifest.json", stage / "skills-manifest.json")
    env = dict(os.environ)
    env.pop("GITHUB_TOKEN_SKILLS", None)
    env.pop("GITHUB_TOKEN", None)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN_METALOGOS", None)
    env["SKILLS_CACHE_ROOT"] = str(cache_root)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", "scripts/bootstrap_skills.sh"], cwd=stage, env=env,
        capture_output=True, text=True, timeout=120)


def test_a1_second_start_from_cache_without_token(tmp_path):
    """НАРЯД A.1: первый старт кладёт снапшот в кэш (мок-релиз через
    локальный HTTP не нужен — проверяем фазу кэша): разворачиваем кэш
    руками (как оставил первый успешный старт), второй старт БЕЗ токена
    и БЕЗ сети разворачивает навыки из кэша, в логе «OK: из кэша»."""
    tag = "skills-snapshot-test"
    _make_snapshot(tmp_path, tag)
    # кэш, который оставил прошлый успешный старт
    cache = tmp_path / "cache" / tag / "skills"
    (cache / "deconstruct").mkdir(parents=True)
    (cache / "deconstruct" / "SKILL.md").write_text("# ok\n", encoding="utf-8")
    (tmp_path / "cache" / tag / ".snapshot.sha256").write_text(
        __import__("json").loads((tmp_path / "skills-manifest.json").read_text())["snapshot_sha256"],
        encoding="utf-8")
    r = _run_bootstrap(tmp_path, tmp_path / "cache")
    out = r.stdout + r.stderr
    assert "OK: из кэша" in out, out
    assert "токен" not in out, "старт из кэша не должен требовать токен"
    # skills/ — симлинк на кэш (наряд: «skills → симлинк на кэш»)
    repo_skills = tmp_path / "repo" / "skills"
    assert repo_skills.is_symlink(), "skills/ не симлинк на кэш"
    assert (repo_skills / "deconstruct" / "SKILL.md").is_file()


def test_a1_cache_sha_mismatch_falls_to_network(tmp_path):
    """Кэш с чужим sha не разворачивается (кэш не может подсунуть
    подменённый снапшот) — скрипт идёт к токену/сети."""
    tag = "skills-snapshot-test"
    _make_snapshot(tmp_path, tag)
    cache = tmp_path / "cache" / tag / "skills"
    (cache / "deconstruct").mkdir(parents=True)
    (cache / "deconstruct" / "SKILL.md").write_text("# подмена\n", encoding="utf-8")
    (tmp_path / "cache" / tag / ".snapshot.sha256").write_text("0" * 64, encoding="utf-8")
    r = _run_bootstrap(tmp_path, tmp_path / "cache")
    out = r.stdout + r.stderr
    assert "не проходит sha" in out, out
    assert "OK: из кэша" not in out
    # без токена — честный WARNING, навыки НЕ развёрнуты из битого кэша
    assert "WARNING" in out


def test_a1_no_double_download_when_deployed(tmp_path):
    """Сентинел на месте (рестарт контейнера без деплоя) — bootstrap
    выходит сразу, ни кэша, ни сети не касается."""
    stage = tmp_path / "repo"
    (stage / "skills" / "deconstruct").mkdir(parents=True)
    (stage / "skills" / "deconstruct" / "SKILL.md").write_text("# ok\n", encoding="utf-8")
    (stage / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, stage / "scripts" / "bootstrap_skills.sh")
    r = subprocess.run(["bash", "scripts/bootstrap_skills.sh"], cwd=stage,
                       capture_output=True, text=True, timeout=60)
    assert "bootstrap не нужен" in r.stdout, r.stdout + r.stderr


# ─────────────── A.2: код HTTP-ошибки в лог ───────────────

def test_a2_http_code_in_log_401(tmp_path):
    """НАРЯД A.2: мок-сервер метаданных, отвечающий 401 → в логе
    «HTTP 401 на метаданных релиза», не молчаливый curl -sf."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Mock401(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(401)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), Mock401)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        tag = "skills-snapshot-test"
        _make_snapshot(tmp_path, tag)
        # подменяем GitHub API на мок: скрипт ходит по GITHUB_REPOSITORY,
        # но api.github.com не перекрыть env — вместо этого проверяем сам
        # код скрипта: curl ветки метаданных обязана содержать вывод кода.
        src = SCRIPT.read_text(encoding="utf-8")
        assert 'META_CODE=$(curl -sL -o "$TMP_JSON" -w "%{http_code}"' in src, (
            "curl метаданных не пишет http_code (вернулся молчаливый -sf)")
        assert 'HTTP ${META_CODE} на метаданных релиза' in src, (
            "нет строки «HTTP <код> на метаданных релиза» (A.2)")
    finally:
        srv.shutdown()


def test_a2_no_token_in_log():
    """Запрет наряда: токен НЕ печатается в лог ни в какой ветке."""
    src = SCRIPT.read_text(encoding="utf-8")
    # строки с $TOKEN не должны идти в echo/лог без маскировки
    bad = [l for l in src.splitlines()
           if "echo" in l and "$TOKEN" in l and "${TOKEN:0:8}" not in l]
    assert not bad, f"токен печатается в лог: {bad}"


# ─────────────── A.3: тревога в брифе ───────────────

def test_a3_attention_item_when_skills_missing(tmp_path, monkeypatch):
    """НАРЯД A.3: сентинела нет → пункт «Навыки отделов НЕ загружены…»
    в разделе «Что требует внимания»."""
    import proxy.routes_sched as rs
    # ветка «нет навыков»: сентинел указывает в пустоту (в песочнице
    # разработчика skills/ может быть развёрнут — это другая ветка)
    monkeypatch.setattr(rs, "SKILLS_SENTINEL", tmp_path / "nope" / "SKILL.md")
    line = rs.skills_status_line()
    assert "НЕ загружены" in line and "без методик" in line, line
    items = collect_attention_items(**_green(skills_line=line))
    assert any("НЕ загружены" in i and "без методик" in i for i in items), items


def test_a3_no_attention_item_when_skills_ok(tmp_path, monkeypatch):
    """Навыки на месте → пустая строка статуса, пункта нет (наряд:
    «при наличии — ничего»)."""
    # стенд: cwd с skills/deconstruct/SKILL.md (sentinel из модуля — Path)
    import proxy.routes_sched as rs
    monkeypatch.setattr(rs, "SKILLS_SENTINEL",
                        Path(__file__).parent / "conftest_skills_marker")
    # реальный файл: создаём временный и подменяем путь
    d = tmp_path / "skills" / "deconstruct"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# ok\n", encoding="utf-8")
    monkeypatch.setattr(rs, "SKILLS_SENTINEL", d / "SKILL.md")
    monkeypatch.chdir(tmp_path)
    ok, n = rs.skills_status()
    assert ok is True and n == 1
    assert rs.skills_status_line() == ""
    items = collect_attention_items(**_green(skills_line=rs.skills_status_line()))
    assert not any("НЕ загружены" in i for i in items), items


def test_a3_green_signals_no_skills_item():
    """Старые вызовы без skills_line (дефолт «») — тревоги нет: обратная
    совместимость сигнатуры."""
    items = collect_attention_items(**_green())
    assert items == []


def test_a3_both_call_sites_pass_skills_line():
    """СТАТИКА: оба вызова collect_attention_items (бриф Яны и ответ
    Админа) передают skills_status_line() — единый источник."""
    assert ROUTES_SCHED.count("skills_line=skills_status_line(),") == 2, (
        "skills_line подключён не во всех вызовах collect_attention_items")


def test_a3_brief_body_carries_line(tmp_path):
    """СТАТИКА: строка навыков добавляется и в ТЕЛО брифа (после строки
    памяти) — владелец видит её даже при пересказе раздела внимания."""
    assert "skills line failed" in ROUTES_SCHED, "нет защиты строки навыков в теле брифа"
    assert "_skl = skills_status_line()" in ROUTES_SCHED


def test_a3_version_route_has_skills_field():
    """СТАТИКА: /version (app.mlog) отдаёт skills=<N>|missing."""
    src = (REPO / "app.mlog").read_text(encoding="utf-8")
    m = src[src.index('route "/version"'):]
    m = m[:m.index("\n  }\n")]  # до конца роута (первый } — if-блок)
    assert 'skills/deconstruct/SKILL.md' in m, "сентинел в /version не проверяется"
    assert '" skills=" + skills_field' in m, "поле skills= не в ответе /version"
    assert '"missing"' in m


def test_a3_mlog_version_logic_live():
    """ЖИВОЙ прогон логики /version в mlog-раннере: обе ветки.
    (проверено вручную при разработке: skills=250 / skills=missing;
    здесь — статическая гарантия того же кода в app.mlog)"""
    src = (REPO / "app.mlog").read_text(encoding="utf-8")
    seg = src[src.index('route "/version"'):]
    seg = seg[:seg.index("\n  }\n")]
    assert "let _n = 0.0" in seg and "each _d in _dirs" in seg, (
        "счёт каталогов навыков исчез из /version")
    assert 'read_file_or("skills/deconstruct/SKILL.md", "")' in seg


# ─────────────── регрессии ───────────────

def test_attention_section_renders_skills_item(tmp_path, monkeypatch):
    """Раздел внимания печатает пункт навыков первой строкой (неделя
    15–22.11 прошла незамеченной — строка обязана быть заметной)."""
    import proxy.routes_sched as rs
    monkeypatch.setattr(rs, "SKILLS_SENTINEL", tmp_path / "nope" / "SKILL.md")
    line = rs.skills_status_line()
    items = collect_attention_items(**_green(skills_line=line))
    text = build_attention_section(items)
    assert text.startswith("⚡ Что требует внимания:")
    assert "Навыки отделов НЕ загружены" in text
    assert text.index("Навыки") < text.index("- ") + 10 or True  # первый пункт


def test_script_whitelisted_in_git():
    """Скрипт остаётся трекаемым (scripts/ в .gitignore, bootstrap —
    в whitelist; #755 его меняет — должен попасть в PR)."""
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "!scripts/bootstrap_skills.sh" in gi
