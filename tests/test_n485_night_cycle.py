"""Наряд #485: ночной цикл Админа — реальный запуск, честный итог, утренний раздел.

Класс ошибок (факты наряда): ночной тик бил по HTTP в несуществующий Flask
/cron/night (порт 4000; настоящий NightSlot живёт в mlog-сервере :10001) и
трактовал отсутствие ответа как «запущен(фоном)» — владелец видел ложный
статус. Фазы AdminNightCycle падали целиком от одного недоступного анализатора.
Утренний отчёт Админа не читал итог ночной проверки.

Гварды фиксируют исправленную топологию. Семантика try-присваивания и полей
TryResult.error.code/.message подтверждена живой пробой на bin/mlog 0.28.0.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
SCHEDULES = (REPO_ROOT / "dept" / "schedules.mlog").read_text(encoding="utf-8")
ROUTES_SCHED = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")


def _code_lines(src: str) -> list:
    """Некомментарные строки (упоминания в комментариях не считаются)."""
    return [l for l in src.splitlines() if not l.strip().startswith("//")]


def _segment(src: str, pattern_decl: str) -> str:
    """Тело одного паттерна: от 'pattern NAME' до следующего 'pattern '."""
    start = src.index(pattern_decl)
    rest = src[start + len(pattern_decl):]
    nxt = rest.find("\npattern ")
    return rest[:nxt] if nxt != -1 else rest


def test_night_tick_calls_night_slot_in_process():
    """A.1: слот вызывает NightSlot() в процессе; HTTP-вызова /cron/night нет."""
    seg = "\n".join(_code_lines(_segment(SCHED, "pattern NightTickSlot()")))
    assert 'http_get(base + "night"' not in seg, "тик по-прежнему бьёт по HTTP в Flask /cron/night"
    assert "try NightSlot()" in seg, "NightSlot не вызывается в процессе"
    assert "TryVal(" in seg, "вызов NightSlot не защищён TryVal"
    assert "night=FAIL(" in seg and "night=ok" in seg, "нет честных исходов ok/FAIL"
    assert "error.message" in seg, "причина ошибки не извлекается из TryResult"
    assert "запущен(фоном)" not in "\n".join(_code_lines(SCHED)), "ложный статус не убран"


def test_night_tick_core_delegates_to_slot():
    """A.1: внешний триггер /cron/night-tick (cron-job.org) — тот же код, что слот."""
    seg = "\n".join(_code_lines(_segment(APP, "pattern NightTickCore")))
    assert "NightTickSlot()" in seg, "NightTickCore должен делегировать в NightTickSlot"
    assert "http_get" not in seg, "близнецы снова разошлись: у роута своя копия диспетчера"
    assert "4000/cron/night" not in "\n".join(_code_lines(APP)), "мёртвый вызов /cron/night остался в app.mlog"


def test_admin_night_cycle_phases_protected():
    """A.2: каждый http_get фаз AdminNightCycle — под try; сбой не роняет цикл."""
    seg = "\n".join(_code_lines(_segment(ADMIN, "pattern AdminNightCycle")))
    for ep in ("admin-ua/scan", "admin-ua/analyze", "admin-ua/graph", "admin-ua/review", "admin-ua/docs"):
        lines = [l for l in seg.splitlines() if ep in l]
        assert lines and "try http_get" in lines[0], f"{ep} не защищён try"
    naked = [l for l in seg.splitlines() if "http_get(" in l and "try http_get" not in l]
    assert not naked, f"незащищённые http_get в AdminNightCycle: {naked}"
    assert "недоступна (" in seg, "нет честной строки о сбое фазы"
    assert 'kv_set("admin_last_health", health)' in seg, "здоровье кода не сохраняется для итога"


def test_night_slot_persists_and_reports():
    """A.3: NightSlot пишет итог в admin_night_reports и отдаёт владельцу.

    #550 A.1: немедленная отправка заменена outbox-записью (OutboxPut("night",
    ...)) — доставка слотом night-report в 07:15 МСК, ночью тишина.
    """
    seg = "\n".join(_code_lines(_segment(APP, "pattern NightSlot()")))
    assert "INSERT INTO admin_night_reports" in seg, "итог не сохраняется"
    assert '"night-slot"' in seg, "нет маркера scan_data='night-slot' (утренний читатель его ищет)"
    assert 'AuditLog("night_slot_done"' in seg, "нет audit-записи о завершении"
    assert 'OutboxPut("night"' in seg, "итог не уходит в outbox (#550 A.1)"
    assert "SendTelegramReply" not in seg, "ночная отправка всё ещё немедленная"
    assert 'kv_set("admin_night_summary"' in seg, "живой KV-путь #381 потерян"
    assert "try AdminNightCycle()" in seg, "Phase 3 не защищена try"
    assert "night_status" in seg, "нет честного статуса ok/partial"
    # DDL таблицы на mlog-стороне (INSERT не зависит от старта Flask)
    assert "CREATE TABLE IF NOT EXISTS admin_night_reports" in APP, "нет DDL в InitDB"


def test_morning_report_reads_night():
    """A.4: утренний ответ Админа открывается разделом «Ночная проверка»."""
    start = ROUTES_SCHED.index("def scheduler_admin_morning_reply")
    seg = ROUTES_SCHED[start:]
    nxt = seg.find("\n@app.")
    seg = seg[:nxt] if nxt != -1 else seg
    assert "admin_night_reports" in seg and "night-slot" in seg, "итог ночной проверки не читается"
    assert "Ночная проверка" in seg, "нет раздела «Ночная проверка»"
    assert "> 26.0" in seg, "порог 26 ч для «не выполнялась с <дата>» потерян"
    assert 'night_line + "\\n\\n" + reply' in seg, "раздел не предшествует комментарию (детерминированный prepend)"


def test_night_tick_registry_run_once():
    """A.5: слот night-tick в реестре — 05:00 МСК, catch_up run_once, включён."""
    assert 'name: "night-tick"' in SCHEDULES
    assert 'target: "NightTickSlot"' in SCHEDULES
    line = [l for l in SCHEDULES.splitlines() if '"night-tick"' in l][0]
    assert "run_once" in line, "пропущенное окно после пробуждения не догоняется"
    assert "enabled: true" in line


def test_deadcall_detector_no_new_dead_paths():
    """A.6: детектор мёртвых вызовов — 0 новых путей (baseline: литерал базы '/cron/')."""
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "deadcall_detector.py")],
        capture_output=True, text=True, timeout=60,
    )
    dead = [
        l.strip().split()[0]
        for l in r.stdout.splitlines()
        if l.strip().startswith("/") and "←" in l
    ]
    baseline = {"/cron/"}  # база конструируемых вызовов тика (backup/indicators/shop/evals)
    new = [d for d in dead if d not in baseline]
    assert not new, f"новые мёртвые вызовы mlog→Flask: {new}"
