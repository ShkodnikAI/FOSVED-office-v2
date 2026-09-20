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
