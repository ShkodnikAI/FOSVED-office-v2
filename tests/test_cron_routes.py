"""Гвард #255: cron-роуты для внешнего планировщика (cron-job.org).

Вердикт 2026-09-20: исполнитель кронов — cron-job.org (не Render, не blueprint).
PR #279 добавил недостающие роуты-диспетчеры в app.mlog. Тест фиксирует их
наличие, чтобы роуты не потерялись при рефакторинге entry-файла.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")

ROUTES = [
    "/cron/shop-tick",        # SHOP-4: вотчи, kill-switch SHOP_ENABLED
    "/cron/golden-evals",     # FO-005: ночная регрессия качества
    "/cron/indicator-reminders",  # превентивные напоминания по индикаторам
    "/cron/backup",           # FO-001: ежедневный VACUUM INTO + integrity
    "/cron/night-tick",       # консолидация 2026-09-21: ОДНА задача вместо шести
]

# Существующие роуты, которые внешний крон должен дёргать (не терять при рефакторинге)
EXISTING_ROUTES = [
    "/cron/morning",          # утренний бриф (тайм-аут cron-job.org безвреден)
    "/cron/lz-daily",         # LZ daily scan
    "/cron/night",            # ночной цикл (UA + lz-daily + memory)
    "/cron/admin-reply",      # единственная живая задача до починки
]


def test_new_cron_routes_exist():
    for r in ROUTES:
        assert f'route "{r}"' in APP, f"роут {r} отсутствует в app.mlog"


def test_existing_cron_routes_still_exist():
    for r in EXISTING_ROUTES:
        assert f'route "{r}"' in APP, f"роут {r} потерян при рефакторинге"


def test_shop_tick_has_kill_switch():
    # SHOP_ENABLED guard перед вызовом watch-sweep
    idx = APP.find('route "/cron/shop-tick"')
    assert idx > 0
    body = APP[idx:idx + 800]
    assert "SHOP_ENABLED" in body
    assert "scheduler/watch-sweep" in body


def test_backup_route_uses_vacuum_into():
    idx = APP.find('route "/cron/backup"')
    assert idx > 0
    body = APP[idx:idx + 900]
    assert "VACUUM INTO" in body          # FO-001 механизм
    assert "integrity_check" in body      # проверка целостности после бэкапа


def test_night_tick_chains_all_nightly_jobs():
    # cron-job.org free лимит по числу задач: диспетчер /cron/night-tick —
    # ОДНА внешняя задача, обходит все ночные роуты сам (секрет-чек обязателен).
    # №422: тело роута перенесено в pattern NightTickCore (route-исполнитель
    # 0.21 теряет mut-контекст в ветвлениях) — цепочка проверяется в паттерне,
    # а роут обязан её вызывать.
    # #485: тело цепочки — единственное, в NightTickSlot (dept/scheduler.mlog):
    # близнецы больше не дублируют логику, NightTickCore делегирует слоту,
    # ночная фаза вызывается в процессе (не HTTP в несуществующий Flask /cron/night).
    idx = APP.find('route "/cron/night-tick"')
    assert idx > 0
    route_body = APP[idx:idx + 700]
    assert "CRON_SECRET" in route_body                # гвард секрета в роуте
    assert "NightTickCore(" in route_body             # делегирование ядру цепочки
    pat = APP.find("pattern NightTickCore(")
    assert pat > 0
    body = APP[pat:pat + 800]
    assert "NightTickSlot()" in body                  # #485: единственное тело цепочки — в слоте
    assert "http_get" not in body                     # у роута нет своей копии диспетчера
    sched = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
    slot_idx = sched.find("pattern NightTickSlot()")
    assert slot_idx > 0
    slot_body = sched[slot_idx:slot_idx + 6000]  # #550/#588: тело выросло (outbox + прямые вызовы + resume-гварды)
    assert '"backup"' in slot_body
    # #550 A.3: indicator-reminders/golden-evals — маршруты mlog :10001, Flask :4000
    # отвечал 404 (факт 4 наряда) — слот зовёт Python-эндпоинты напрямую;
    # mlog-роуты остаются ручным/аварийным фолбэком (гвард в test_n550_night_report).
    assert 'indicator-pre-reminders' in slot_body
    assert '"shop-tick"' in slot_body
    assert 'scheduler/golden-evals' in slot_body
    assert "try NightSlot()" in slot_body             # #485: ночь — в процессе, с TryVal
    # №588 A.3: resume-гварды — повторный старт не повторяет выполненные фазы
    assert "NightPhaseMark(" in slot_body and "skip(dup)" in slot_body
    # #550 A.1: итог цепочки — в outbox (доставка слотом night-report 07:15 MSK),
    # немедленной ночной отправки больше нет.
    assert 'OutboxPut("night-tick"' in slot_body
    assert "SendTelegramReply" not in slot_body
