#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#735 LZ-3: GitHub-скан ЛЗ — фильтр новизны, подвал, глубина, стоп-лист
пакетов, NVD-сверка CVE.

Факты аудита 20.11: «пять дней подряд 17 репозиториев и 12 релизов» —
потолок в коде (8×per_page=3, 4×per_page=3), sort=updated возвращает
одни и те же крупные репо, seen_release_keys — локальный set на один
прогон, lz_github_updates писалась ПОСЛЕ анализа и на входе не
читалась. Комментарий-дефект аудита 20.11 (A.4): «CVSS 9.8» принят за
«пакет cvss 9.8» → ложная пометка на абзаце про системный OpenSSL
образа. A.5: CVE-2026-121481 в NVD не подтверждён.

Здесь: A.1 (второй прогон = 0 новых, модель не вызвана), A.2 (подвал
«новых N из M»), A.3 (10 результатов до фильтра, константы), A.4
(стоп-лист + системные библиотеки), A.5 (NVD-мок: найден/не найден).
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
LZ_GH_SRC = (REPO / "proxy" / "lz_github.py").read_text(encoding="utf-8")

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')


_LZ_GH_DDL = ("CREATE TABLE IF NOT EXISTS lz_github_updates ("
              "id INTEGER PRIMARY KEY AUTOINCREMENT, update_id TEXT UNIQUE, "
              "channel_id TEXT, channel_name TEXT, text TEXT, date TEXT, "
              "scanned_at TEXT DEFAULT (datetime('now')))")


def _env(tmp_path, monkeypatch):
    """tmp-БД + таблица lz_github_updates (на проде её создаёт mlog
    InitDB — app.mlog:221; python init_db её не создаёт, _query глотает
    sqlite3.Error, поэтому DDL в тесте — как в проде, дословно)."""
    os.environ['DATABASE_PATH'] = str(tmp_path)
    import proxy.core as core
    db = str(tmp_path / "office.db")
    monkeypatch.setattr(core, "DB_FILE", db)
    from proxy.core import init_db, _query
    init_db()
    _query(_LZ_GH_DDL, ())
    return _query


def _run_daily(tmp_path, monkeypatch, lzg):
    """Прогон lz-daily через Flask-контекст (роут /scheduler/lz-daily,
    deliver=none — без Telegram; core требует app context). Возврат —
    dict ответа (report распарсен, не сырая JSON-строка)."""
    import json as _json
    import llm_proxy  # noqa: F401
    client = lzg.app.test_client()
    r = client.post("/scheduler/lz-daily",
                    json={"owner_id": "", "dry_run": False, "deliver": "none"})
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:300])
    return _json.loads(r.get_data(as_text=True))


# ───────── A.1: фильтр новизны на входе ─────────

def test_a1_constants_and_read_before_analysis():
    """A.3 константы + A.1 чтение lz_github_updates ДО анализа
    (статика: _seen_updates вызван до Phase 2, а не после)."""
    assert "LZ_REPOS_PER_QUERY = 10" in LZ_GH_SRC, "нет константы LZ_REPOS_PER_QUERY"
    assert "LZ_RELEASES_PER_REPO = 5" in LZ_GH_SRC, "нет константы LZ_RELEASES_PER_REPO"
    assert "def _seen_updates()" in LZ_GH_SRC, "нет хелпера чтения прошлых прогонов"
    core_idx = LZ_GH_SRC.index("def scheduler_lz_daily_core")
    seen_idx = LZ_GH_SRC.index("_seen_updates()", core_idx)  # вызов ВНУТРИ core
    analysis_idx = LZ_GH_SRC.index("# ── Phase 2: LLM Analysis", core_idx)
    assert core_idx < seen_idx < analysis_idx, (
        "прошлые update_id должны читаться до анализа, не после")


def test_a1_second_run_zero_new_no_llm(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ (тест-кейс наряда): второй прогон с тем же ответом
    GitHub-мока → 0 новых, модель не вызывается (ветка «новых находок
    нет»)."""
    _query = _env(tmp_path, monkeypatch)
    import proxy.lz_github as lzg

    gh_mock = [
        {"name": "owner/agent-framework", "desc": "LLM agents", "stars": 100,
         "lang": "Python", "updated": "2026-11-20", "pushed_at": "2026-11-19T10:00:00Z",
         "url": "https://github.com/owner/agent-framework", "created": "2026-01-01"},
    ]
    rel_mock = [
        {"repo": "langchain-ai/langchain", "tag": "v1.2.3", "name": "v1.2.3",
         "body": "fixes", "date": "2026-11-19", "url": "https://github.com/x/releases"},
    ]
    monkeypatch.setattr(lzg, "_github_search", lambda q, per_page=10, **kw: list(gh_mock))
    monkeypatch.setattr(lzg, "_github_releases", lambda repo: list(rel_mock))
    monkeypatch.setattr(lzg, "GITHUB_WATCH_RELEASES", ["langchain-ai/langchain"])
    llm_calls = {"n": 0}
    monkeypatch.setattr(lzg, "call_llm", lambda *a, **kw: llm_calls.__setitem__("n", llm_calls["n"] + 1) or {"reply": "", "provider": "-", "tokens_in": 0, "tokens_out": 0})
    monkeypatch.setattr(lzg, "_tg_send_message", lambda *a, **kw: 1)
    monkeypatch.setattr(lzg, "_tg_send_report_with_button", lambda *a, **kw: 1)

    # прогон 1: запись в БД (dry_run=False), модель зовётся — новое есть
    r1 = _run_daily(tmp_path, monkeypatch, lzg)
    assert llm_calls["n"] == 1, "первый прогон обязан звать модель (новое есть)"
    # прогон 2: тот же мок — 0 новых, модель НЕ вызвана
    r2 = _run_daily(tmp_path, monkeypatch, lzg)
    assert llm_calls["n"] == 1, (
        f"повторный прогон вызвал модель ({llm_calls['n']}) — фильтр новизны не работает")
    rep2 = r2.get("report", "")
    assert "новых находок нет" in rep2, f"нет ветки «новых нет»: {rep2[:300]}"
    assert "новых 0" in rep2, f"подвал без «новых 0»: {rep2[:300]}"


def test_a1_repo_with_fresh_push_marked_updated(tmp_path, monkeypatch):
    """A.1: репо в базе + pushed_at новее даты записи → возвращается с
    пометкой «(обновлён)», а не молча теряется."""
    _query = _env(tmp_path, monkeypatch)
    import proxy.lz_github as lzg
    _query("INSERT INTO lz_github_updates (update_id, channel_id, channel_name, text, date) "
           "VALUES ('gh:repo:owner/agent-framework', 'github', 'Python', 'LLM agents', '2026-11-10')", ())
    gh_mock = [
        {"name": "owner/agent-framework", "desc": "LLM agents", "stars": 150,
         "lang": "Python", "updated": "2026-11-20", "pushed_at": "2026-11-19T10:00:00Z",
         "url": "https://github.com/owner/agent-framework", "created": "2026-01-01"},
    ]
    monkeypatch.setattr(lzg, "_github_search", lambda q, per_page=10, **kw: list(gh_mock))
    monkeypatch.setattr(lzg, "_github_releases", lambda repo: [])
    monkeypatch.setattr(lzg, "GITHUB_WATCH_RELEASES", [])
    seen = lzg._seen_updates()
    assert "gh:repo:owner/agent-framework" in seen, "хелпер не видит запись базы"


# ───────── A.2: подвал с новизной ─────────

def test_a2_footer_new_of_total():
    """A.2: подвал «просмотрено M репозиториев (новых N), K релизов
    (новых L)» — формат наряда, обе строки пути (отчёт и «новых нет»)."""
    assert "репозиториев (новых {repos_new})" in LZ_GH_SRC, (
        "подвал без счётчика новых репозиториев")
    assert "релизов (новых {releases_new})" in LZ_GH_SRC, (
        "подвал без счётчика новых релизов")


# ───────── A.3: глубина скана ─────────

def test_a3_search_uses_stars_and_pushed_filter():
    """A.3: sort=stars + фильтр pushed:>=<сегодня-7> (вместо
    sort=updated, возвращавшего одни и те же репо)."""
    assert 'sort="stars"' in LZ_GH_SRC, "дефолт поиска не stars"
    assert "pushed:>=" in LZ_GH_SRC, "нет фильтра свежести pushed"
    assert "timedelta(days=7)" in LZ_GH_SRC, "окно pushed не 7 дней"


def test_a3_mock_10_results_reach_filter(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ: мок с 10 результатами на запрос — все доходят до
    фильтра A.1 (per_page=10, не 3)."""
    _env(tmp_path, monkeypatch)
    import proxy.lz_github as lzg
    got = {"per_page": None}

    def mock_search(q, per_page=10, **kw):
        got["per_page"] = per_page
        return [{"name": f"o/r{i}", "desc": "d", "stars": 1, "lang": "Python",
                 "updated": "2026-11-20", "pushed_at": "2026-11-20T00:00:00Z",
                 "url": f"https://github.com/o/r{i}", "created": "2026-01-01"}
                for i in range(10)]

    monkeypatch.setattr(lzg, "_github_search", mock_search)
    repos = lzg._github_search("q")
    assert len(repos) == 10, "мок отдал 10 — все должны дойти"
    import llm_proxy  # noqa: F401
    client = lzg.app.test_client()
    r = client.post("/scheduler/lz-daily",
                    json={"owner_id": "", "dry_run": True, "deliver": "none"})
    assert r.status_code == 200
    assert got["per_page"] == 10, (
        f"per_page={got['per_page']} — глубина не 10 (A.3)")


# ───────── A.4: стоп-лист не-пакетов ─────────

def test_a4_cvss_not_a_package():
    """ПОВЕДЕНИЕ (абзац из отчёта 20.11): «OpenSSL 3.0.13 … CVSS 9.8»
    про СИСТЕМНЫЙ OpenSSL образа — пометки «пакет в стеке офиса не
    используется» НЕТ (cvss — не пакет; openssl — библиотека образа)."""
    import proxy.lz_github as lzg
    text = ("Пункт 1: OpenSSL 3.0.13 системного образа ubuntu:24.04 — "
            "критический багфикс для нашего офиса. CVSS 9.8. "
            "Речь о системной библиотеке, которую наш офис получает "
            "с обновлениями образа.")
    out, marks = lzg.annotate_foreign_stack_claims(text)
    assert marks == 0, f"ложная пометка на CVSS/OpenSSL: {marks}"
    assert "не используется" not in out, "ложная пометка в тексте"


def test_a4_real_foreign_package_still_marked():
    """Контроль: реально чужой pip-пакет («наш langchain 1.0») — пометка
    остаётся (стоп-лист не глушит проверку стека #721)."""
    import proxy.lz_github as lzg
    text = "Наш langchain 1.0 пайплайн требует обновления офиса."
    out, marks = lzg.annotate_foreign_stack_claims(text)
    assert marks == 1, "чужой пакет не помечен — стоп-лист заширил норму"
    assert "не используется" in out


def test_a4_stoplist_and_os_libs_constants():
    """A.4: стоп-лист содержит токены из инцидента (CVSS, CVE, TLS, PR,
    v, ISO); системные библиотеки образа (openssl, libssl, glibc) — в
    известных."""
    import proxy.lz_github as lzg
    for tok in ("cvss", "cve", "tls", "pr", "v", "iso"):
        assert tok in lzg._NOT_A_PACKAGE, f"«{tok}» нет в стоп-листе"
    for lib in ("openssl", "libssl", "glibc"):
        assert lib in lzg._STACK_KNOWN_BASE, f"«{lib}» нет в известных (образ)"


# ───────── A.5: сверка CVE с NVD ─────────

def test_a5_unconfirmed_cve_marked():
    """ПОВЕДЕНИЕ: CVE не найден в NVD (мок пуст) → строка «⚠️ CVE не
    подтверждён в NVD» (кейс аудита: CVE-2026-121481)."""
    import proxy.lz_github as lzg
    lzg._NVD_CACHE.clear()

    class _Resp:
        status_code = 200
        def json(self):
            return {"vulnerabilities": []}

    monkeypatch_resp = _Resp()
    import proxy.lz_github
    orig_get = lzg.http_requests.get

    def fake_get(url, **kw):
        if "nvd.nist.gov" in url:
            return monkeypatch_resp
        return orig_get(url, **kw)

    lzg.http_requests.get = fake_get
    try:
        out, n = lzg.verify_cves("Обновление затрагивает CVE-2026-121481 в OpenSSL.")
        assert n == 1
        assert "CVE-2026-121481: ⚠️ CVE не подтверждён в NVD" in out
    finally:
        lzg.http_requests.get = orig_get
        lzg._NVD_CACHE.clear()


def test_a5_confirmed_cve_facts_from_nvd():
    """ПОВЕДЕНИЕ: CVE найден → CVSS и дата из NVD (не от модели):
    «CVE-…: CVSS 9.8, опубликован 2026-04-01 (NVD)»."""
    import proxy.lz_github as lzg
    lzg._NVD_CACHE.clear()

    class _Resp:
        status_code = 200
        def json(self):
            return {"vulnerabilities": [{"cve": {
                "published": "2026-04-01T00:00:00.000",
                "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.8}}]},
            }}]}

    resp = _Resp()
    orig_get = lzg.http_requests.get

    def fake_get(url, **kw):
        if "nvd.nist.gov" in url:
            return resp
        return orig_get(url, **kw)

    lzg.http_requests.get = fake_get
    try:
        out, n = lzg.verify_cves("Уязвимость CVE-2026-31789 в OpenSSL.")
        assert n == 1
        assert "CVE-2026-31789: CVSS 9.8, опубликован 2026-04-01 (NVD)" in out
        assert "не подтверждён" not in out
    finally:
        lzg.http_requests.get = orig_get
        lzg._NVD_CACHE.clear()


def test_a5_verify_called_in_daily():
    """A.5 подключён в путь отчёта (после annotate #721) + подвал
    «CVE сверено с NVD: N»."""
    assert "verify_cves(analysis)" in LZ_GH_SRC, "NVD-сверка не в пути отчёта"
    ann_idx = LZ_GH_SRC.index("annotate_foreign_stack_claims(analysis)")
    ver_idx = LZ_GH_SRC.index("verify_cves(analysis)")
    assert ann_idx < ver_idx, "сверка CVE должна идти после пометок стека"
    assert "CVE сверено с NVD" in LZ_GH_SRC, "подвал без счётчика CVE"
