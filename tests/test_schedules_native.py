"""Гвард наряда №419 (Metalogos gh#572): нативные расписания офиса.

Планировщик = нативный cron Metalogos 0.21.0 (№418: дедуп окон, catch-up,
per-job TZ). Реестр заданий владельца — dept/schedules.mlog (SSOT:
«внесение задания = правка файла → деплой»). Живая поверхность — /schedules/*
роуты (list/bootstrap/create/remove) в границах существующей CRON_SECRET-
авторизации. Переход на 0.21 — guard-проба в entrypoint.sh (Category A аудит
кандидата; долг №327 держит прод на 0.19 — ценз в отчёте №419).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
SCHEDULES = (REPO_ROOT / "dept" / "schedules.mlog").read_text(encoding="utf-8")
HARNESS = (REPO_ROOT / "dogfood_staging.mlog").read_text(encoding="utf-8")
ENTRYPOINT = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")

# Целевой расклад (docs/render-dashboard.md, «native cron»): 7 слотов +
# night-tick + служебный lz-daily. Времена — MSK wall-clock (tz Europe/Moscow).
EXPECTED_SLOTS = {
    "admin-reply": "25 7 * * *",
    "morning-brief": "20 7 * * *",
    "control-check": "0 12 * * *",
    "evening-summary": "0 21 * * *",
    "night-tick": "0 5 * * *",
    "weekly-digest": "0 9 * * 1",
    "lz-daily": "10 9 * * *",
}


def test_registry_has_all_target_slots_with_msk():
    for name, expr in EXPECTED_SLOTS.items():
        assert f'name: "{name}"' in SCHEDULES, f"слот {name} отсутствует в реестре"
        assert f'cron: "{expr}"' in SCHEDULES, f"расписание {name} не {expr} (MSK)"
    assert SCHEDULES.count('"Europe/Moscow"') >= 8, "не все записи в Europe/Moscow"


def test_registry_keep_alive_is_external_and_disabled():
    # keep-alive не может быть нативным (входящий трафик держит free-инстанс
    # бодрым — это работа waker'а №420); в реестре — выключенная памятка.
    assert 'name: "keep-alive"' in SCHEDULES
    assert "ExternalKeepAlive" in SCHEDULES


def test_monthly_is_not_registered():
    # Решение владельца 2026-09-21 (вариант А): Monthly Review тем больше не нужен.
    assert 'name: "monthly"' not in SCHEDULES


def test_slot_patterns_exist_and_are_zero_arg():
    slots = ["MorningSlot", "EveningSlot", "WeeklySlot", "ControlSlot",
             "AdminReplySlot", "LzDailySlot", "ShopTickSlot", "GoldenEvalsSlot",
             "IndicatorRemindersSlot", "DbBackupSlot", "NightTickSlot"]
    for s in slots:
        assert f"pattern {s}() -> String" in SCHED, f"слот-паттерн {s} отсутствует в scheduler.mlog"
    # Ночной цикл (деструктивный SQL) живёт в app.mlog, не в scheduler.mlog:
    # харнесс импортирует scheduler и должен оставаться 0.21-аудит-чистым.
    assert "pattern NightSlot() -> String" in APP
    assert "pattern NightSlot" not in SCHED


def test_night_route_delegates_to_night_slot():
    # Триггер меняется, бизнес-логика — нет: тело переехало дословно.
    idx = APP.find('route "/cron/night" method=GET')
    assert idx > 0
    body = APP[idx: idx + 700]
    assert "NightSlot()" in body
    assert "DELETE FROM chain_steps" not in body  # логика — в паттерне
    # №421: DELETE переехал в грант-контур (db_execute_with_grant, ADR-0155)
    assert 'db_execute_with_grant(grant_issue("db:delete:chain_steps"' in APP
    assert '"DELETE FROM chain_steps' in APP  # и сама логика сохранилась


def test_bootstrap_is_idempotent_by_target():
    assert "pattern BootstrapSchedules() -> String" in SCHEDULES
    # Два прохода (защита от коллизии id: cron_add штампует id секундой,
    # cron_remove(id) сносит весь батч — проход 1 удаляет, проход 2 дозаполняет).
    assert "Проход 1" in SCHEDULES and "Проход 2" in SCHEDULES
    # Сканирование существующих заданий по prompt == target, переприсваивание
    # внутри each — только через let mut (иначе shadow-биндинг теряет находку).
    assert "let mut existing_id" in SCHEDULES
    assert "json_get(j, \"prompt\", \"\") == target" in SCHEDULES
    # cron_add возвращает Struct — id извлекается json_get-ом.
    assert 'json_get(added_job, "id", "?")' in SCHEDULES


def test_bootstrap_loud_fail_contract():
    # Битая запись — громкий FAIL в отчёте (не тихий пропуск); entrypoint
    # громко ругается на FAIL( в ответе.
    assert "FAIL(" in SCHEDULES
    assert "unknown target pattern" in SCHEDULES
    assert "empty cron expression" in SCHEDULES
    assert 'FAIL("*' in ENTRYPOINT or '"FAIL("' in ENTRYPOINT


def test_untrusted_decisions_hash_wrapped():
    # №327: решения на json_body/inspect-данных — через one-way redact-hash
    # (ADR-0161 sanctioned path), иначе 0.21-аудит не пускает даже харнесс.
    assert 'redact(to_string(probe), "hash_only") == redact("()", "hash_only")' in HARNESS
    assert 'redact(cron_expr, "hash_only") == redact("", "hash_only")' in SCHEDULES


def test_schedules_routes_exist_with_secret_guard():
    for path in ("app.mlog", "dogfood_staging.mlog"):
        src = APP if path == "app.mlog" else HARNESS
        for route in ("/schedules/list", "/schedules/bootstrap",
                      "/schedules/create", "/schedules/remove"):
            assert f'route "{route}"' in src, f"{route} отсутствует в {path}"
        assert src.count("CRON_SECRET") >= 4


def test_kv_persistence_declared_for_cron_store():
    # Стор cron живёт в KV (ключ cron_jobs); без memory { persist } он
    # в памяти — рестарт терял бы дедуп-штампы №418 (двойной файр).
    assert 'memory { persist: "data/metalogos_kv.db" }' in APP
    assert 'memory { persist: "data/metalogos_kv.db" }' in HARNESS


def test_harness_imports_schedules_and_stays_clean():
    assert "import dept/schedules" in HARNESS


def test_entrypoint_guarded_cutover():
    # Проба: кандидат проходит Category A аудит → serving; иначе громкий
    # откат на легаси (внешние cron-job.org продолжают работать).
    # №349 (2026-09-24): переход на 0.22.0 (ADR-0005); N023 (2026-09-24):
    # кандидат = bin/mlog (0.23.0, ADR-0006), фолбэк = mlog-020
    # (0.20.0 — последний бинарь, грузящий сырой app.mlog: lax-аудит +
    # корректный try-контракт; 0.21-сырец красный на бут-аудите, 0.19
    # выведен из ротации, ADR-0005).
    assert "MLOG_CANDIDATE" in ENTRYPOINT
    assert 'MLOG_CANDIDATE" audit "$MLOG_ENTRY"' in ENTRYPOINT
    assert "GRADUAL CUTOVER" in ENTRYPOINT
    assert 'MLOG_CANDIDATE="${MLOG_BIN:-./bin/mlog}"' in ENTRYPOINT
    assert 'MLOG_LEGACY="./bin/mlog-020"' in ENTRYPOINT
    # Гейты №259 №419: allowlist env для 0.21-пути (ценз по app.mlog+dept).
    assert "METALOGOS_ENV_ALLOWLIST" in ENTRYPOINT
    assert "CRON_SECRET" in ENTRYPOINT and "OWNER_TELEGRAM_ID" in ENTRYPOINT
    # Бутстрап реестра — только на 0.21-пути и только с секретом;
    # №425: секрет в URL — только percent-кодированным (--data-urlencode:
    # 0.21 декодирует query, литеральный '+' сырой вставкой честно давал 403).
    assert '-G "http://127.0.0.1:10001/schedules/bootstrap"' in ENTRYPOINT
    assert '--data-urlencode "secret=${CRON_SECRET}"' in ENTRYPOINT
    assert "schedules/bootstrap?secret=${CRON_SECRET}" not in ENTRYPOINT
    # VM-дефолт ADR-0171 отложен для офиса: VM-хендлеры 0.21 не видят db_decl
    # соединение (находка №419) — офисный путь на интерпретаторе.
    assert "METALOGOS_SERVE_BACKEND" in ENTRYPOINT


def test_binary_prev_good_vendored():
    # ADR-0009: прошлый-хороший 0.25.0 вендорен как тест-гвард
    # (роль mlog-024 из ADR-0008); 0.24 выведен из репо, история git хранит.
    b = REPO_ROOT / "bin" / "mlog-025"
    assert b.exists() and b.stat().st_size > 10_000_000, "bin/mlog-025 не вендорен"
    assert not (REPO_ROOT / "bin" / "mlog-024").exists(), "mlog-024 должен быть выведен (ADR-0009)"
