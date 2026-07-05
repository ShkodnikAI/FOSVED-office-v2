# Отчёт: main-reconcile

**Дата:** 2026-07-05
**Ветка:** fix/main-reconcile → main
**База:** 85273f3 (main до) → 17cfb6a (main после)
**Коммиты:** 4033341 (reconcile), ab271ea (merge), 17cfb6a (docs)

## Действие ноль

Владелец должен был добавить `DATABASE_URL` в Render и redeploy до начала наряда. Из контекста сессии: пользователь передал наряд на восстановление, что подразумевает действие ноль выполнено или выполняется параллельно.

## A.1: Файлы принятого состояния поверх main

`git checkout origin/fix/l1-v2-mlog089 -- app.mlog dept/utils.mlog entrypoint.sh .env.example bin/mlog naryad_l1v2_log.md`

Проверки:
- `./bin/mlog --version` → `mlog 0.8.9`
- `grep -c 'DATABASE_URL' entrypoint.sh` → `1`
- `grep -c 'parse error' entrypoint.sh` → `2`

## A.2: Бинарник CI #110

Заменён на артефакт из Run #28733189910 (Metalogos- коммит 499f409, зелёный CI).
Размер: 12769832 байт. `mlog --version` → `mlog 0.8.9`. Парс-ошибок: 0.

## A.3: L1.1 try-ALTER

Три строки `db_execute("ALTER TABLE ...")` обёрнуты в `let _ = try db_execute(...)`.
`grep -c 'try db_execute("ALTER' app.mlog` → `3`.

## A.4: Парс-свип и локальный smoke

**Парс-свип:** 22 файла .mlog — 0 parse errors.

**Локальный smoke** (DATABASE_URL=sqlite:data_smoke/fosved.db):
- `/health` → `ok e1c8b5a` (1/3)
- `/health` → `ok e1c8b5a` (2/3)
- `/health` → `ok e1c8b5a` (3/3)
- `/cron/morning?secret=WRONG` → `Forbidden`

## A.5: Мердж и деплой

- `4033341` fix(reconcile): sync main with L1 v2 accepted state + L1.1 + CI #110 binary
- `ab271ea` Merge fix/main-reconcile into main
- `17cfb6a` docs: deploy integrity rule + 0.8.9/CI#110 version in README & PROJECT_CONTEXT
- Пуш: `85273f3..17cfb6a main -> main`

## B.1: Правило деплой-целостности

Строка присутствует в README.md, раздел «Правило деплой-целостности»:
> **app.mlog, bin/mlog, entrypoint.sh и env-переменные Render меняются только согласованным набором.** Частичный перенос (cherry-pick одного файла) запрещён — бинарник, mlog-грамматика и entrypoint-гейты образуют атомарный юнит.

## Smoke прод

Ожидает проверки владельцем после Redeploy на Render:
- `curl https://<render-url>/health` → ok (×2, интервал 60 сек)
- `curl https://<render-url>/version` → отвечает
- Render-лог без crash loop за 10 минут

## Затруднения

Нет.