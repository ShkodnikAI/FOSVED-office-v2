#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #596: UA-цикл (таймаут 600 > лимита Metalogos 300), evals=FAIL по
таймауту, ЛЗ трижды в сутки.

Гварды:
- A.1: статический обход всех http_post/http_get в app.mlog и dept/*.mlog —
  числовой таймаут в диапазоне 1..300 (тест красный на 600, зелёный на 300);
- A.1: живой прогон http_post(..., 300.0) на bin/mlog — аргумент принимается
  без HTTP_TIMEOUT_RANGE (мини-сервер на loopback, как в тестах #546);
- A.2: async=1 у /admin-ua/night-cycle и /scheduler/golden-evals — сразу
  {"job_id"}; статус running→done; повторный запрос статуса после done —
  тот же итог; неудача фоновой работы → failed с ошибкой;
- A.3: за цикл «ночь → 07:20 → 09:10» на моках Telegram сообщение с
  заголовком «LZ DAILY REPORT» отправлено ровно один раз (ночь — deliver:"none",
  бриф 07:20 — без обхода BRIEF-1 доп., полный отчёт — слот 09:10).
"""
import importlib
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n596-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')
os.environ.setdefault('CRON_SECRET', 'test-cron-secret')
os.environ.setdefault('INTERNAL_API_TOKEN', 'n596-internal-token')

REPO_ROOT = Path(__file__).resolve().parent.parent
BINARY = REPO_ROOT / "bin" / "mlog"
ITOK = "b7de70d0c58b2587"  # sha256("n596-internal-token:admin-ua")[:16], см. core.py

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402
from proxy import jobs as n596_jobs  # noqa: E402

CLIENT = flask_app.test_client()


def _cron_secret():
    """Актуальный CRON_SECRET на момент прогона: другие тест-модули меняют env
    на уровне импорта (test_golden_evals: 'cron-test-secret') — тест не должен
    зависеть от порядка сбора батарей."""
    return os.environ.get("CRON_SECRET", "")


# ──────────────────────────── A.1: статический гвард таймаутов ────────────────

_HTTP_CALL = re.compile(r'http_(?:get|post|post_multipart|download)\(')
_TIMEOUT_NUM = re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*\)\s*(?:#.*)?$')


def _strip_comment(line: str) -> str:
    # срезать // -комментарий, но НЕ «//» внутри схемы URL (http://):
    return re.sub(r'(?<!:)//.*$', '', line)


def _iter_mlog_http_lines():
    for rel in ("app.mlog",) + tuple(
        f"dept/{p.name}" for p in (REPO_ROOT / "dept").glob("*.mlog")
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            # только строки с реальными вызовами http_* (не в комментариях)
            code = _strip_comment(line)
            if _HTTP_CALL.search(code):
                yield rel, lineno, code


def test_a1_static_timeouts_within_1_300():
    """Каждый числовой таймаут http_* в app.mlog/dept/*.mlog — в 1..300.
    Красный на 600 (прод-дефект 22.10: HTTP_TIMEOUT_RANGE, UA-цикл не
    запускался вовсе). Сам гвард невакуумный: без единого числового
    таймаута в коде тест падает (защита от «пустого скана»)."""
    bad = []
    seen = 0
    for rel, lineno, code in _iter_mlog_http_lines():
        for m in re.finditer(r',\s*([0-9]+(?:\.[0-9]+)?)\s*\)', code):
            seen += 1
            val = float(m.group(1))
            if not (1.0 <= val <= 300.0):
                bad.append(f"{rel}:{lineno} timeout={val}")
    assert seen > 0, "гвард вакуумный: ни одного числового таймаута не найдено"
    assert not bad, "таймауты вне 1..300 (лимит Metalogos): " + "; ".join(bad)


def test_a1_live_call_accepts_300():
    """Живой прогон http_post(..., 300.0) на bin/mlog: аргумент принимается,
    без [HTTP_TIMEOUT_RANGE]. Мини-сервер на loopback (как в тестах #546)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)

    def _serve():
        try:
            conn, _ = srv.accept()
            conn.recv(65536)
            body = b'{"answer":"ok"}'  # ровно 15 байт — Content-Length честный
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                         b"Content-Length: 15\r\nConnection: close\r\n\r\n" + body)
            conn.close()
        except OSError:
            pass

    th = threading.Thread(target=_serve, daemon=True)
    th.start()
    probe = (
        'pattern Main1(_: String) -> String {\n'
        f'  let r = http_post("http://127.0.0.1:{port}/ping", "{{}}", "application/json", 300.0)\n'
        '  return to_string(r)\n'
        '}\n'
        'flow Main { input: String = "" -> Main1 -> output }\n'
    )
    pfile = Path("/tmp/n596_probe.mlog")
    pfile.write_text(probe, encoding="utf-8")
    try:
        proc = subprocess.run(
            [str(BINARY), "run", str(pfile)], cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "METALOGOS_HTTP_ALLOW_PRIVATE": "1"},
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"бинарь упал: {out[-1500:]}"
        assert "HTTP_TIMEOUT_RANGE" not in out, "300.0 отвергнут бинарем: " + out[-1500:]
        assert '"answer"' in out or "ok" in out, "ответ сервера не дошёл: " + out[-800:]
    finally:
        srv.close()
        pfile.unlink(missing_ok=True)


# ──────────────────────────── A.2: async-механика ────────────────────────────

def test_a2_jobs_registry_lifecycle():
    """Реестр заданий: running → done, итог стабилен между запросами статуса;
    исключение → failed с ошибкой."""
    ev = threading.Event()

    def slow():
        ev.wait(timeout=10)
        return {"status": "ok", "summary": "done-now"}

    jid = n596_jobs.start_job(slow)
    st1 = n596_jobs.get_job(jid)
    assert st1["status"] == "running", st1
    ev.set()
    for _ in range(100):
        st2 = n596_jobs.get_job(jid)
        if st2["status"] == "done":
            break
        time.sleep(0.05)
    assert st2["status"] == "done", st2
    assert st2["result"] == {"status": "ok", "summary": "done-now"}
    # повторный запрос после done — тот же итог (требование наряда)
    st3 = n596_jobs.get_job(jid)
    assert st3 == st2

    def boom():
        raise RuntimeError("phase exploded")

    jid2 = n596_jobs.start_job(boom)
    for _ in range(100):
        stf = n596_jobs.get_job(jid2)
        if stf["status"] == "failed":
            break
        time.sleep(0.05)
    assert stf["status"] == "failed" and "phase exploded" in (stf["error"] or "")
    assert n596_jobs.get_job("no-such-job") is None


def _auth_admin():
    """Проброс внутреннего токена для /admin-ua/* (гард core.before_request)."""
    import proxy.core as core
    orig = os.environ.get("INTERNAL_API_TOKEN")
    os.environ["INTERNAL_API_TOKEN"] = "n596-internal-token"
    yield
    if orig is None:
        os.environ.pop("INTERNAL_API_TOKEN", None)
    else:
        os.environ["INTERNAL_API_TOKEN"] = orig


def test_a2_night_cycle_async_status_flow(monkeypatch):
    """async=1 → сразу job_id; статус running → done; итог тот же при
    повторном запросе. Длинная фаза (stub 0.6 с > интервала опроса) —
    вердикт по статусу, не по таймауту HTTP."""
    for _ in _auth_admin():
        import proxy.routes_admin as ra
        started = threading.Event()
        release = threading.Event()

        def slow_impl():
            started.set()
            release.wait(timeout=10)
            return {"status": "ok", "summary": "UA NIGHT CYCLE COMPLETE", "health_score": 8}

        monkeypatch.setattr(ra, "_ua_night_cycle_impl", slow_impl)

        r = CLIENT.post("/admin-ua/night-cycle?async=1&itok=" + ITOK, json={})
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["status"] == "accepted" and body.get("job_id"), body
        job_id = body["job_id"]

        assert started.wait(timeout=5), "фоновая работа не стартовала"
        s1 = CLIENT.get(f"/admin-ua/night-cycle/status?job={job_id}&itok={ITOK}")
        assert s1.status_code == 200
        assert s1.get_json()["status"] in ("running", "done"), s1.get_json()

        release.set()
        for _ in range(100):
            s2 = CLIENT.get(f"/admin-ua/night-cycle/status?job={job_id}&itok={ITOK}")
            if s2.get_json()["status"] == "done":
                break
            time.sleep(0.05)
        assert s2.get_json()["status"] == "done", s2.get_json()
        assert s2.get_json()["result"]["summary"] == "UA NIGHT CYCLE COMPLETE"
        # повторный статус — тот же итог
        s3 = CLIENT.get(f"/admin-ua/night-cycle/status?job={job_id}&itok={ITOK}")
        assert s3.get_json() == s2.get_json()


def test_a2_night_cycle_sync_path_untouched(monkeypatch):
    """Без async=1 — прежнее синхронное поведение (совместимость /cron/night)."""
    for _ in _auth_admin():
        import proxy.routes_admin as ra
        monkeypatch.setattr(ra, "_ua_night_cycle_impl",
                            lambda: {"status": "ok", "summary": "SYNC", "health_score": 9})
        r = CLIENT.post("/admin-ua/night-cycle?itok=" + ITOK, json={})
        assert r.status_code == 200
        assert r.get_json()["summary"] == "SYNC"


def test_a2_golden_evals_async_status_flow(monkeypatch):
    """async=1 у /scheduler/golden-evals: job_id сразу, статус done, итог
    стабилен; гард secret на статус-роуте (403 без секрета)."""
    import proxy.routes_tail as rt

    def slow_impl(dept_list):
        time.sleep(0.3)
        return {"status": "ok", "totals": {"depts": len(dept_list)}, "results": []}

    monkeypatch.setattr(rt, "_golden_evals_impl", slow_impl)

    r = CLIENT.post(f"/scheduler/golden-evals?secret={_cron_secret()}&async=1", json={"depts": ["osp"]})
    assert r.status_code == 200, r.get_data(as_text=True)
    job_id = r.get_json()["job_id"]
    assert job_id

    s_noauth = CLIENT.get(f"/scheduler/golden-evals/status?job={job_id}&secret=wrong-{_cron_secret()}")
    assert s_noauth.status_code == 403, "статус-роут без гарда секрета"

    for _ in range(100):
        s = CLIENT.get(f"/scheduler/golden-evals/status?job={job_id}&secret={_cron_secret()}")
        if s.get_json()["status"] == "done":
            break
        time.sleep(0.05)
    assert s.get_json()["status"] == "done"
    assert s.get_json()["result"]["totals"]["depts"] == 1
    again = CLIENT.get(f"/scheduler/golden-evals/status?job={job_id}&secret={_cron_secret()}")
    assert again.get_json() == s.get_json()


# ──────────────────────────── A.3: ЛЗ один раз в сутки ────────────────────────

def test_a3_brief_does_not_trigger_lz_daily(monkeypatch):
    """Бриф 07:20 больше не запускает scheduler_lz_daily_core (обход
    «BRIEF-1 доп.» удалён)."""
    import proxy.routes_sched as rs

    called = {"n": 0}

    def spy(**kw):
        called["n"] += 1
        return {"status": "ok", "report": "SHOULD-NOT-RUN"}

    monkeypatch.setattr(rs, "scheduler_lz_daily_core", spy, raising=False)

    from proxy.core import _query
    _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")
    monkeypatch.setattr(rs, "call_llm", lambda dept, messages: {
        "reply": "ТЕСТ-БРИФ №596", "provider": "stub"})
    monkeypatch.setattr(rs, "_tg_send_formatted", lambda *a, **kw: 111)
    # соседние контуры брифа в тесте не нужны
    monkeypatch.setattr(rs, "run_forge_backup", None, raising=False)

    r = CLIENT.post("/scheduler/morning-brief", json={"owner_id": "12345"})
    # форж/ключи в песочнице могут дать 500 на внешних вызовах —
    # проверяем именно отсутствие вызова lz-daily
    assert called["n"] == 0, "бриф запустил lz-daily — обход не удалён"
    assert r.status_code in (200, 500)


def test_a3_lz_daily_report_exactly_once_in_cycle(monkeypatch):
    """Цикл «ночь → 07:20 → 09:10»: заголовок «LZ DAILY REPORT» уходит
    владельцу ровно один раз. Ночь — deliver:none (сбор без доставки),
    бриф — без обхода, 09:10 — единственная доставка полного отчёта."""
    import proxy.routes_sched as rs
    import proxy.lz_github as lz

    sent = []
    delivers = []

    def spy_send(owner_id, text, **kw):
        sent.append(text or "")
        return len(sent)

    def stub_core(dry_run, owner_id, deliver="telegram"):
        # стаб вместо реального скана (GitHub/LLM): доставку эмулируем по
        # контракту ядра — deliver != none → полный отчёт владельцу
        delivers.append(deliver)
        if deliver != "none":
            sent.append("🔍 LZ DAILY REPORT\n(полный отчёт слота 09:10)")
        return {"status": "ok", "report": "LZ DAILY REPORT: n находок",
                "scan": {"repos_found": 1, "releases_found": 0}}

    monkeypatch.setattr(rs, "_tg_send_formatted", spy_send)
    monkeypatch.setattr(lz, "_tg_send_formatted", spy_send)
    monkeypatch.setattr(lz, "scheduler_lz_daily_core", stub_core)

    # 1) ночь: NightLzPhase зовёт /scheduler/lz-daily с deliver:"none"
    r_night = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "none"})
    assert r_night.status_code == 200, r_night.get_data(as_text=True)
    assert not any("LZ DAILY REPORT" in t for t in sent), \
        f"ночь доставила полный отчёт ЛЗ: {sent[:3]}"

    # 2) 07:20: бриф — обход BRIEF-1 доп. удалён, lz-daily не запускается
    from proxy.core import _query
    _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")
    monkeypatch.setattr(rs, "call_llm", lambda dept, messages: {
        "reply": "ТЕСТ-БРИФ №596 (цикл)", "provider": "stub"})
    CLIENT.post("/scheduler/morning-brief", json={"owner_id": "12345"})

    # 3) 09:10: слот lz-daily — полный отчёт (deliver по умолчанию telegram)
    r_slot = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
    assert r_slot.status_code == 200, r_slot.get_data(as_text=True)

    assert delivers == ["none", "telegram"], delivers
    full = [t for t in sent if "LZ DAILY REPORT" in t]
    assert len(full) == 1, f"полный отчёт ЛЗ отправлен {len(full)} раз, ожидается 1"
