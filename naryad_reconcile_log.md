# Лог: main-reconcile

Дата: 2026-07-05
Ветка: fix/main-reconcile
База: main 85273f3 → итог main 17cfb6a

## A.1. Файлы принятого состояния

```
git checkout origin/fix/l1-v2-mlog089 -- app.mlog dept/utils.mlog entrypoint.sh .env.example bin/mlog naryad_l1v2_log.md
```

Проверки:
- `./bin/mlog --version` → `mlog 0.8.9` ✅
- `grep -c 'DATABASE_URL' entrypoint.sh` → 1 ✅
- `grep -c 'parse error' entrypoint.sh` → 2 ✅

## A.2. Бинарник CI #110

Артефакт `mlog-linux-x86_64` из Run #28733189910 (коммит 499f409, зелёный CI).
Размер: 12769832 байт.

Проверки:
- `./bin/mlog --version` → `mlog 0.8.9` ✅
- `./bin/mlog check app.mlog 2>&1 | grep -c "parse error"` → 0 ✅

## A.3. L1.1 try-ALTER

```diff
- db_execute("ALTER TABLE dept_archive ADD COLUMN forecast_value REAL")
- db_execute("ALTER TABLE dept_verification ADD COLUMN actual_value REAL")
- db_execute("ALTER TABLE dept_verification ADD COLUMN outcome_flag TEXT")
+ let _ = try db_execute("ALTER TABLE dept_archive ADD COLUMN forecast_value REAL")
+ let _ = try db_execute("ALTER TABLE dept_verification ADD COLUMN actual_value REAL")
+ let _ = try db_execute("ALTER TABLE dept_verification ADD COLUMN outcome_flag TEXT")
```

Проверка: `grep -c 'try db_execute("ALTER' app.mlog` → 3 ✅

## A.4. Парс-свип и smoke

Парс-свип — 22 файла .mlog, 0 parse errors каждый:

```
app.mlog: 0 | file_cache.mlog: 0 | file_cache_skills.mlog: 0
dept/admin.mlog: 0 | dept/chain.mlog: 0 | dept/context.mlog: 0
dept/design.mlog: 0 | dept/dev.mlog: 0 | dept/engineering.mlog: 0
dept/expert.mlog: 0 | dept/finance.mlog: 0 | dept/kavalnya.mlog: 0
dept/legal.mlog: 0 | dept/lz.mlog: 0 | dept/marketing.mlog: 0
dept/miniapp.mlog: 0 | dept/osp.mlog: 0 | dept/qa.mlog: 0
dept/scheduler.mlog: 0 | dept/utils.mlog: 0 | dept/visual.mlog: 0
dept/yana.mlog: 0
```

Smoke (локальный, DATABASE_URL=sqlite:data_smoke/fosved.db):
- /health → `ok e1c8b5a` (1/3) ✅
- /health → `ok e1c8b5a` (2/3) ✅
- /health → `ok e1c8b5a` (3/3) ✅
- /cron/morning?secret=WRONG → `Forbidden` ✅

## A.5. Мердж

- Коммит reconcile: 4033341
- Мерж в main: ab271ea (Merge fix/main-reconcile into main)
- Коммит B.1: 17cfb6a (docs: deploy integrity rule + 0.8.9)
- Пуш: `85273f3..17cfb6a main -> main` ✅

## B.1. Правило деплой-целостности

Добавлено в README.md (раздел «Правило деплой-целостности» перед стеком):
> app.mlog, bin/mlog, entrypoint.sh и env-переменные Render меняются только согласованным набором.

Также исправлены версии 0.7.10→0.8.9 в README.md и PROJECT_CONTEXT.md.

## Затруднения

Нет.