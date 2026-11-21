"""#728 B.9–B.12 + #712 (аудит 21.11, ночь 21.11 НЕ принята): хвост наряда.

Аудит 21.11 03:31Z (ночь 21.11 не принята):
- Grapher за ночь шёл ДВАЖДЫ (night-cycle + AdminNightCycle Phase 1c
  /admin-ua/graph, dept/admin.mlog:508) — второй прогон 02:06:33–02:09:12
  поверх первого, наложение на keys night-check и NightTickSlot.
- kg_scan_rebuild держал запись 135–143 с (per-node SELECT id внутри
  чанковой транзакции, ~170 мс/узел × 855).
- ~815–855 «updated» каждую ночь при new=0..34 и неизменных файлах.
- keys night-check упал 02:08:36 database is locked (500).
- OOM 02:00:20 через 16 с после старта NightTickSlot (до UA-фаз) —
  пик между 60-с тиками mem-сборщика невидим; фазы тика без меток.

Здесь: гварды B.9 (один Grapher), B.10 (план в памяти + executemany +
[ua-tx] kg_chunk + ≤2 с/чанк), B.11 (ключ с file_path, churn=0),
B.12 (retry 60 с → not_run), #712 (фазовые night:*-метки + live-срезы
дочки каждые 5 с). Поведенческие — на tmp-БД (идиома _b3_env
test_n728_night4), статические — по исходникам (идиома B-гвардов).
"""
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ROUTES_ADMIN = REPO / "proxy" / "routes_admin.py"
ROUTES_TAIL = REPO / "proxy" / "routes_tail.py"
KG = REPO / "proxy" / "kg.py"
MEM_SAMPLER = REPO / "proxy" / "mem_sampler.py"
ADMIN_MLOG = REPO / "dept" / "admin.mlog"
APP_MLOG = REPO / "app.mlog"


# ───────────────────── B.9: один Grapher за ночь ─────────────────────

def test_b9_admin_night_cycle_no_second_grapher():
    """СТАТИКА B.9: AdminNightCycle не ЗОВЁТ /admin-ua/graph — единственный
    Grapher ночи внутри night-cycle (Phase 0 NightSlot); итог — через
    kv-мост admin_last_kg_temporal. Проверяется КОД-строка с http_get И
    /admin-ua/graph (URL содержит «//» — наивная обрезка комментариев
    по «//» ломала строку кода и мутация не ловилась). Мутация (вернуть
    http_get graph) роняет гвард."""
    src = ADMIN_MLOG.read_text(encoding="utf-8")
    seg = src[src.index("pattern AdminNightCycle"):]
    seg = seg[:seg.index("\npattern ")] if "\npattern " in seg else seg
    bad = [ln.strip() for ln in seg.splitlines()
           if "http_get" in ln and "/admin-ua/graph" in ln
           and not ln.strip().startswith("//")]
    assert not bad, (
        "AdminNightCycle всё ещё зовёт /admin-ua/graph — второй Grapher "
        f"за ночь (аудит 21.11): {bad}")
    assert "admin_last_kg_temporal" in seg, (
        "Phase 1c не читает kv-мост admin_last_kg_temporal (итог Grapher "
        "из night-cycle не попадает в отчёт)")


def test_b9_night_cycle_returns_kg_temporal():
    """СТАТИКА B.9: payload night-cycle несёт kg_temporal (строка KG-итога),
    NightSlot кладёт его в kv-мост. Мутация любого конца моста роняет."""
    ra = ROUTES_ADMIN.read_text(encoding="utf-8")
    assert "'kg_temporal': kg_temporal" in ra, (
        "night-cycle не возвращает kg_temporal — Phase 1c нечего читать")
    app = APP_MLOG.read_text(encoding="utf-8")
    assert "admin_last_kg_temporal" in app, (
        "NightSlot не кладёт kg_temporal в kv admin_last_kg_temporal")


def test_b9_manual_graph_route_kept_behind_gate():
    """Ручной /admin-ua/graph остаётся (аварийный прогон админом) и гейт B.6
    на нём не снят — B.9 убирает только автоматический двойной прогон."""
    ra = ROUTES_ADMIN.read_text(encoding="utf-8")
    assert 'def admin_ua_graph' in ra, "ручной маршрут Grapher исчез"
    graph_seg = ra[ra.index("def admin_ua_graph"):][:1500]
    assert "409" in graph_seg and "_NightCycleGate" in graph_seg, (
        "гейт B.6 на /admin-ua/graph снят")


# ─────────── B.10: kg_scan_rebuild — ≤2 с/чанк, ≤10 с суммарно ───────────

def _b10_db(tmp_path, monkeypatch):
    """tmp-БД с таблицами kg + findings (идиома _b3_env night4)."""
    os.environ['API_SECRET'] = 'test-secret-123'
    os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
    os.environ['OWNER_TELEGRAM_ID'] = '12345'
    os.environ['DATABASE_PATH'] = str(tmp_path)
    os.environ['ZAI_API_KEY'] = 'fake-key'
    os.environ['INTERNAL_API_TOKEN'] = 'tok-n728b-test-1234567890'
    import proxy.core as core
    import proxy.kg as kg
    db = str(tmp_path / "office.db")
    monkeypatch.setattr(core, "DB_FILE", db)
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT,
         node_name TEXT, file_path TEXT, description TEXT, updated_at TEXT, valid_from TEXT,
         valid_to TEXT, source_part_id INTEGER, inference INTEGER, review_status TEXT,
         parent_count INTEGER, superseded_by INTEGER);
        CREATE TABLE admin_findings (severity TEXT, category TEXT, file TEXT, issue TEXT,
         fix TEXT, status TEXT);
    """)
    conn.commit()
    conn.close()
    return core, kg, db


def test_b10_no_select_inside_chunk_transaction():
    """СТАТИКА B.10: внутри чанковой записи нет SELECT'ов (прежде —
    per-node SELECT id после каждого INSERT, ~170 мс/узел × 855 =
    135–143 с удержания; аудит 21.11)."""
    src = KG.read_text(encoding="utf-8")
    body = src[src.index("def kg_scan_rebuild"):]
    # вырезаем фазу записи (между 'conn = sqlite3.connect' и 'conn.close()'
    # первой записи) и требуем там только executemany/commit/rollback
    m = re.search(r"conn = sqlite3\.connect.*?\n    finally:\n        conn\.close\(\)",
                  body, re.S)
    assert m, "фаза записи kg_scan_rebuild не найдена"
    write_phase = m.group(0)
    assert "SELECT" not in write_phase, (
        "в чанковой транзакции остался SELECT — держатель лока "
        "(B.10: план в памяти, executemany-пакеты)")
    assert "executemany" in write_phase, "запись не executemany-пакетами"


def test_b10_ua_tx_log_per_chunk():
    """СТАТИКА B.10: [ua-tx] kg_chunk с held_ms на КАЖДЫЙ чанк (наряд:
    «в [ua-tx] — held_ms на чанк, не только суммарно»)."""
    src = KG.read_text(encoding="utf-8")
    assert '"kg_chunk"' in src, "нет фазы kg_chunk в _ua_tx_log"
    m = re.search(r"_ua_tx_log\(\"kg_chunk\".*?batch=i // KG_CHUNK", src, re.S)
    assert m, "kg_chunk логируется без номера чанка"


def test_b10_chunk_hold_under_2s_and_total_under_10s(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.10: 3000 узлов (6 чанков по 500) — запись каждого чанка
    ≤ 2 с и сумма чанковых held_ms ≤ 10 с (замер по логу kg_chunk через
    подмену _ua_tx_log). Плюс: параллельный INSERT проходит во время
    записи (критерий B.10 не роняет соседних писателей)."""
    core, kg, db = _b10_db(tmp_path, monkeypatch)
    from proxy.core import _query
    # перехват [ua-tx] kg_chunk (kg импортирует из routes_admin поздним
    # импортом внутри функции — патчим сам routes_admin)
    import proxy.routes_admin as ra
    chunk_log = []
    monkeypatch.setattr(ra, "_ua_tx_log",
                        lambda phase, **kw: chunk_log.append((phase, kw)))
    nodes = [{'node_type': 'pattern', 'node_name': f'P{i}',
              'file_path': f'f{i % 100}.mlog',
              'description': f'args=x{i}'} for i in range(3000)]
    t0 = time.perf_counter()
    res = kg.kg_scan_rebuild(nodes, source='t')
    total = time.perf_counter() - t0
    assert res['inserted'] == 3000, res
    chunks = [kw for phase, kw in chunk_log if phase == "kg_chunk"]
    assert len(chunks) == 6, f"чанков {len(chunks)}, ожидалось 6"
    worst = max(c['held_ms'] for c in chunks)
    sum_ms = sum(c['held_ms'] for c in chunks)
    assert worst <= 2000, f"чанк удержан {worst} мс > 2 с (критерий B.10)"
    assert sum_ms <= 10000, f"сумма чанков {sum_ms} мс > 10 с (критерий B.10)"
    assert total < 60, f"весь ребилд {total:.1f} с — регресс против 135–143 с"


def test_b10_parallel_writer_passes_between_chunks(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.10: между чанками commit — внешний INSERT проходит
    во время ребилда (не ждёт всего прохода)."""
    core, kg, db = _b10_db(tmp_path, monkeypatch)
    from proxy.core import _query
    import threading

    nodes = [{'node_type': 'pattern', 'node_name': f'Q{i}',
              'file_path': f'g{i % 50}.mlog', 'description': 'd'} for i in range(1500)]
    box = {}

    def _run():
        box['res'] = kg.kg_scan_rebuild(nodes, source='t')

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    ok, last = False, None
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 15.0 and th.is_alive():
        try:
            _query("INSERT INTO admin_findings (severity, category, file, issue, fix, status) "
                   "VALUES ('low', 'probe', 'p.mlog', 'x', 'y', 'open')", ())
            ok = True
            break
        except Exception as e:
            last = e
            time.sleep(0.05)
    th.join(timeout=30)
    assert box.get('res', {}).get('inserted') == 1500, box
    assert ok, f"внешний INSERT не прошёл во время ребилда: {last}"


# ───────── B.11: updated ≈ реальные изменения (ключ с file_path) ─────────

def test_b11_same_name_different_files_no_churn(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.11: одноимённые узлы разных файлов (Main1 ×30, _client
    ×28 — источник ~800 ложных updated/ночь) — самостоятельные сущности:
    повторный ребилд того же скана даёт 0 updated (все noop)."""
    core, kg, db = _b10_db(tmp_path, monkeypatch)
    nodes = [
        {'node_type': 'pattern', 'node_name': 'Main1', 'file_path': f'a{i}.mlog',
         'description': 'args=x'} for i in range(30)
    ] + [
        {'node_type': 'pattern', 'node_name': '_client', 'file_path': f'b{i}.py',
         'description': 'args='} for i in range(28)
    ]
    r1 = kg.kg_scan_rebuild(nodes, source='t')
    assert r1['inserted'] == 58 and r1['updated'] == 0, r1
    r2 = kg.kg_scan_rebuild(nodes, source='t')
    assert r2['updated'] == 0 and r2['noop'] == 58 and r2['inserted'] == 0, (
        f"ложный churn при неизменном скане: {r2} — ключ не включает file_path?")


def test_b11_real_change_still_counts_updated(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.11 (контроль-мутация): реальное изменение description
    узла — честный updated (1), прежняя версия закрыта, новая активна."""
    core, kg, db = _b10_db(tmp_path, monkeypatch)
    nodes = [{'node_type': 'pattern', 'node_name': 'Real', 'file_path': 'x.mlog',
              'description': 'args=1'}]
    kg.kg_scan_rebuild(nodes, source='t')
    nodes[0]['description'] = 'args=2'
    r = kg.kg_scan_rebuild(nodes, source='t')
    assert r['updated'] == 1 and r['noop'] == 0, r
    from proxy.core import _query
    act = _query("SELECT COUNT(*) AS c FROM knowledge_graph "
                 "WHERE node_name='Real' AND valid_to IS NULL", (), fetch=True)
    assert act[0]['c'] == 1, "после update больше одной активной версии"


def test_b11_old_key_data_migrates_cleanly(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.11 (наследие): БД со стеками старого ключа
    (node_type+node_name без file_path, 5 активных версий одного имени)
    — новый ребилд закрывает стеки и оставляет по одной активной версии
    на файл (канонизация без admin_findings-шума)."""
    core, kg, db = _b10_db(tmp_path, monkeypatch)
    from proxy.core import _query
    # старое состояние: 5 активных версий 'Main1' в 5 файлах (как на проде)
    for i in range(5):
        _query("INSERT INTO knowledge_graph (node_type, node_name, file_path, description, "
               "updated_at, valid_from, valid_to, inference, review_status, parent_count) "
               "VALUES ('pattern', 'Main1', ?, 'args=old', '2026-11-01 00:00:00', "
               "'2026-11-01 00:00:00', NULL, 1, 'pending', 1)", (f'a{i}.mlog',))
    nodes = [{'node_type': 'pattern', 'node_name': 'Main1', 'file_path': f'a{i}.mlog',
              'description': 'args=new'} for i in range(5)]
    r = kg.kg_scan_rebuild(nodes, source='t')
    assert r['updated'] == 5, f"стеки не закрыты как updated: {r}"
    act = _query("SELECT COUNT(*) AS c FROM knowledge_graph "
                 "WHERE node_name='Main1' AND valid_to IS NULL", (), fetch=True)
    assert act[0]['c'] == 5, (
        f"активных {act[0]['c']} (ожидалось 5 — по одной на файл): "
        "одноимённые узлы разных файлов схлопнуты в один — churn вернётся")


# ───────── B.12: keys night-check — retry 60 с при locked ─────────

def test_b12_retry_once_then_not_run(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.12: обе попытки с sqlite3.OperationalError(locked) —
    ОДНА повторная через 60 с (sleep патчится), затем честный 200
    not_run «не выполнена (БД занята)», не 500. audit ни разу."""
    ra_env = _b3_like_env(tmp_path, monkeypatch)
    import llm_proxy
    import sqlite3 as sq
    calls = {"n": 0}

    class _OH(sq.OperationalError):
        pass

    def _locked_attempt():
        calls["n"] += 1
        raise sq.OperationalError("database is locked")

    import proxy.key_health as kh
    monkeypatch.setattr(kh, "check_all", _locked_attempt)
    sleeps = []
    monkeypatch.setattr(ra_env["ra"].time if hasattr(ra_env["ra"], "time") else time,
                        "sleep", lambda s: sleeps.append(s))
    # time в модуле routes_admin
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s), raising=False)
    client = llm_proxy.app.test_client()
    resp = client.post('/admin/keys/night-check',
                       environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200, f"ожидался 200 not_run, получен {resp.status_code}"
    d = resp.get_json()
    assert d["status"] == "not_run", d
    assert "БД занята" in d["problems_line"], d
    assert calls["n"] == 2, f"попыток {calls['n']} (ожидалось 2: первая + retry)"
    assert sleeps == [60], f"retry не через 60 с: {sleeps}"


def test_b12_locked_then_success(tmp_path, monkeypatch):
    """ПОВЕДЕНИЕ B.12: первая попытка locked, retry успешен — итог 200
    с реальным статусом проверки (не not_run)."""
    _b3_like_env(tmp_path, monkeypatch)
    import llm_proxy
    import sqlite3 as sq
    import proxy.key_health as kh
    calls = {"n": 0}
    good = {"status": "ok", "problems_line": "", "ok_count": 3, "total": 3, "checked_at": "now"}

    def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise sq.OperationalError("database is locked")
        return {"ok_count": 3, "total": 3, "problems": []}

    monkeypatch.setattr(kh, "check_all", _flaky)
    monkeypatch.setattr(kh, "save_results", lambda s: None)
    monkeypatch.setattr(kh, "night_summary", lambda s: good)
    monkeypatch.setattr("time.sleep", lambda s: None, raising=False)
    client = llm_proxy.app.test_client()
    resp = client.post('/admin/keys/night-check',
                       environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok", resp.get_json()
    assert calls["n"] == 2


def test_b12_other_errors_still_500():
    """ПОВЕДЕНИЕ B.12: не-locked ошибка — прежний путь 500 unreachable
    (retry только для БД-занятости, не для всех сбоев)."""
    src = ROUTES_ADMIN.read_text(encoding="utf-8")
    seg = src[src.index("def admin_keys_night_check"):seg_end(src)]
    assert '"locked" in str(e) or "busy" in str(e)' in seg, (
        "фильтр locked/busy исчез — retry будет глотать любые ошибки")
    assert '"status": "unreachable"' in seg, "ветка 500 unreachable исчезла"


def seg_end(src):
    i = src.index("def admin_keys_night_check")
    nxt = src.find("\n@app.", i + 10)
    return nxt if nxt > 0 else len(src)


def _b3_like_env(tmp_path, monkeypatch):
    """Окружение как _b3_env из test_n728_night4 (герметичное к порядку)."""
    os.environ['API_SECRET'] = 'test-secret-123'
    os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
    os.environ['OWNER_TELEGRAM_ID'] = '12345'
    os.environ['DATABASE_PATH'] = str(tmp_path)
    os.environ['ZAI_API_KEY'] = 'fake-key'
    os.environ['INTERNAL_API_TOKEN'] = 'tok-n728b2-test-12345678'
    import llm_proxy  # noqa: F401
    import proxy.core as core
    import proxy.routes_admin as ra
    db = str(tmp_path / "office.db")
    monkeypatch.setattr(core, "DB_FILE", db)
    monkeypatch.setattr(ra, "DB_FILE", db)
    from proxy.core import init_db
    init_db()
    return {"ra": ra, "core": core}


# ───── #712: фазовые метки ночного тика + live-срезы дочки ─────

def test_712_night_phase_marks_exist():
    """СТАТИКА #712: метки night:<фаза> на фазах NightTickSlot —
    backup (включая rotate), indicators, shop, evals; имена фаз видны
    в mem_samples (kind='slot', ref='night:…') — требование аудита
    21.11: «назвать фазу» по меткам за 02:00:04–02:00:20. Гвард ловит
    ВЫЗОВ _night_mark (не упоминание в комментарии)."""
    tail = ROUTES_TAIL.read_text(encoding="utf-8")
    for phase in ("night:backup-rotate", "night:indicators", "night:shop", "night:evals"):
        for ph in ("before", "after"):
            calls = [ln for ln in tail.splitlines()
                     if f'_night_mark("slot", "{phase}", "{ph}"' in ln
                     and not ln.strip().startswith("#")]
            assert calls, (
                f"нет вызова _night_mark({phase}, {ph}) — фаза тика "
                "без полной пары меток (пик фазы не виден в mem_samples)")


def test_712_run_tracked_live_samples():
    """СТАТИКА+ПОВЕДЕНИЕ #712: run_tracked делает live-срезы каждые 5 с,
    пока дочка жива (OOM 02:00:20 в 16 с от старта — между 60-с тиками
    сборщика пик был невидим; live закрывает окно)."""
    src = MEM_SAMPLER.read_text(encoding="utf-8")
    assert 'phase="live"' in src or "phase='live'" in src, (
        "нет live-срезов в run_tracked — пик дочки между тиками невидим")
    assert "_live_stop" in src, "live-тред не останавливается по finally"

    # поведение: дочка живая ~6.5 с — live-тик (интервал 5 с) обязан сработать
    import proxy.mem_sampler as ms
    live_calls = []
    orig_store = ms.store_samples

    def counting_store(rows, kind, ref, phase, proc_root=None):
        if phase == "live":
            live_calls.append((kind, ref))
        return orig_store(rows, kind=kind, ref=ref, phase=phase,
                          proc_root=proc_root)

    # патчим ИМЯ В МОДУЛЕ (run_tracked зовёт глобал модуля, не замыкание)
    ms.store_samples = counting_store
    try:
        import subprocess as sp
        t0 = time.perf_counter()
        ms.run_tracked([sp.sys.executable, "-c", "import time; time.sleep(6.5)"],
                       capture_output=True, timeout=30)
        assert time.perf_counter() - t0 >= 6.0, "дочка не прожила 6 с — тест нестабилен"
    finally:
        ms.store_samples = orig_store
    assert live_calls, (
        "live-срезы не сделаны за 6.5 с работы дочки (интервал 5 с — "
        "минимум один обязан быть)")


def test_712_backup_doc_shows_copy_mechanism():
    """СТАТИКА #712: докстринг /cron/backup объясняет механизм копии
    (VACUUM INTO в дочке с RLIMIT_AS 256, не в памяти родителя) —
    «показать по коду, как он копирует» (аудит 21.11)."""
    tail = ROUTES_TAIL.read_text(encoding="utf-8")
    seg = tail[tail.index("def cron_backup"):seg_end_tail(tail)]
    assert "VACUUM INTO" in seg, "механизм копии не показан в /cron/backup"
    assert "RLIMIT" in seg or "RLIMIT_AS" in seg, (
        "предел памяти дочки не упомянут — первый подозреваемый OOM")


def seg_end_tail(src):
    i = src.index("def cron_backup")
    nxt = src.find("\n@app.", i + 10)
    return nxt if nxt > 0 else len(src)
