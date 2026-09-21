# Render Dashboard — инвентарь сервисов вне blueprint

**Канонический источник** конфигурации prod-службы — **Render Dashboard**
(workspace My Workspace), настроен вручную. `render.yaml` с 2026-09-20 управляет
только стейджингом FO-050 (blueprint): старая схема кронов была невалидной
(docker+startCommand, plan free у cron) и была отвергнута валидатором при первом
Apply — см. #182, #276.

**⚠️ Вердикт 2026-09-20 (скрин владельца + поиск дашборда): cron-сервисов в
Render НЕТ и НЕ БЫЛО** — всего 4 сервиса: prod web, staging web, PostgreSQL
`fosved-bot-bd`, 1 suspended. Старый render.yaml с кронами ни разу не применялся;
аудит #244 ошибочно принял таблицу ниже за «настроенные вручную» джобы.
Следствие: 11 периодических задач НЕ выполнялись по расписанию (частичные
исключения: startup-бэкап при деплое; reminder-check внутренним шедулером mlog).
Создание планировщика — наряд #255.

**Преемник (2026-09-22, наряд №420):** исполнитель расписаний = **нативный cron
Metalogos** (№418/№419); waker (бодрствование free-инстанса Render) = **GitHub
Actions** `.github/workflows/keepalive.yml`; cron-job.org выводится из исполнения
(cutover-чеклист — в секции waker ниже).

**Правила:**
- Любое ручное изменение в дашборде → обновить этот файл тем же днём (иначе дрейф).
- Таблица кронов ниже — СПЕЦИФИКАЦИЯ к созданию, не инвентарь работающих джоб: #255.
- Восстановление/пересоздание — сверять с этим инвентарём построчно.

## Prod: fosved-office-v2 (web, docker, plan free, region frankfurt)

- Runtime: Docker (Dockerfile, entrypoint.sh). Free tier: засыпает после 15 мин неактивности — keep-alive-крона НЕ существует (см. вердикт выше); фактический план сервиса уточняется (#255).
- Env: секреты заданы в дашборде НАПРЯЗУЮ на сервисе (группы `fosved-secrets` НЕ существует — валидатор Render 2026-09-20; список ниже). `DATABASE_URL` в дашборде НЕ задаётся (#269):
  entrypoint.sh сам ставит sqlite-URL, Prisma-ветка недостижима.

## Секреты prod-сервиса fosved-office-v2 (24 ключа, заданы в дашборде напрямую)

`TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `TELEGRAM_ARCHIVE_CHANNEL_ID`,
`TELEGRAM_WEBHOOK_SECRET`, `CRON_SECRET`, `API_SECRET`, `DEEPSEEK_API_KEY`,
`GROQ_API_KEY`, `ZAI_API_KEY`, `GITHUB_TOKEN_METALOGOS`, `TAVILY_API_KEY`,
`BACKUP_UPLOAD_CMD`, `FORGE_MASTER_KEY`, `FORGE_GITHUB_OWNER` — sync (секреты);
`BACKUP_RETENTION=7`, `METALOGOS_SERVE_ALLOW_EXEC=1`, `METALOGOS_EXEC_TIMEOUT_SECS=60`,
`METALOGOS_MCP_TIMEOUT_SECS=30`, `SHOP_ENABLED=1`, `PORT=10000` — значения;
`METALOGOS_MCP_ALLOWLIST=mcp_servers/github,mcp_servers/filesystem,mcp_servers/markets,mcp_servers/web,mcp_servers/media`;
`METALOGOS_AUDIT_LOG_PATH=/office/data/logs/metalogos_audit.log`;
`FOSVED_MCP_FS_ROOT=/office/data/documents`; `FORGE_REPOS_DIR=/var/forge/repos`.

## Cron-джобы (11) — СПЕЦИФИКАЦИЯ (в Render НЕ созданы, вердикт 2026-09-20)

| # | Имя | Расписание (UTC) | Вызов |
|---|-----|------------------|-------|
| 1 | collect-news | `0 * * * *` (ежечасно) | GET /cron/collect-news?secret=CRON_SECRET |
| 2 | lz-daily | `10 6 * * *` (06:10; после collect-news 06:00) | POST /scheduler/lz-daily `{"dry_run":false}` |
| 3 | tool-output-cleanup | `30 6 * * *` (FO-016, ретеншн data/tool_output) | GET /cron/cleanup-tool-output?secret= |
| 4 | morning-brief | `20 4 * * 1-5` (будни; бэкап+выгрузка до LLM) | POST /scheduler/morning-brief `{"owner_id":OWNER_TELEGRAM_ID}` |
| 5 | watch-sweep | `0 6 * * *` (SHOP-вотчи: deltas, lastCheckAt) | POST /scheduler/watch-sweep |
| 6 | indicator-pre-reminders | `0 3 * * *` (verifyDate ≤ 7 дней) | POST /scheduler/indicator-pre-reminders `{"days_ahead":7}` |
| 7 | db-backup | `0 2 * * *` (FO-001: VACUUM INTO + integrity + retention) | GET /cron/backup?secret= |
| 8 | golden-evals | `30 2 * * *` (FO-005; регрессия → алерт) | POST /scheduler/golden-evals?secret= `{}` |
| 9 | memory-consolidation | `30 3 * * *` (FO-006: dialog_history → факты) | GET /cron/consolidate-memory?secret= `{"days":1}` |
| 10 | keep-alive | `*/14 * * * *` (не даёт уснуть free-инстансу) | GET /health; GET /cron/narad-tick?secret= (FO-047); GET staging /health (FO-050) |
| 11 | shop-tick | `0 */6 * * *` (SHOP-4: WB/Ozon вотчи, kill-switch SHOP_ENABLED=0) | GET /cron/shop-tick?secret= |

База prod: `{prod-url}` = `https://fosved-office-v2.onrender.com`; стейджинг:
`https://fosved-office-v2-staging.onrender.com` (создаётся blueprint'ом из render.yaml).

## Исполнитель кронов: cron-job.org (внешний, workspace владельца) — состояние 2026-09-20

Скрины владельца (полный список 2026-09-20 20:45). Секрет в URL задач —
CRON_SECRET (засветился на скрине → ротация после починки). «Monthly Review»
в списке НЕТ — подтверждено владельцем 2026-09-21 (первоначальная сверка
по скрину ошиблась).

- **Жива:** Admin Reply `/cron/admin-reply` (200 OK ежедневно 7:27, 2.1 c).
- **Тайм-аут безвреден:** Morning Brief `/cron/morning` (30 c лимит крона, LLM дольше;
  бриф доходит — подтверждено владельцем). Запускается ежедневно.
- **Monthly Review — темы больше нет (решение владельца 2026-09-21, вариант А):**
  месячный обзор НЕ нужен — у владельца уже есть Morning Brief, Evening Summary
  и Weekly Digest. Роут `/cron/monthly` остаётся в коде и никем не вызывается —
  безвредно; отчёт «📅 Месячный обзор» приходить не будет. Удалять нечего,
  HISTORY не нужен.
- **НА ПАУЗЕ с августа (след. запуск «Неактивно») — фикс URL недостаточен, нужен
  тумблер включения:** Control Check `/cron/control` (пауза с 05.08, HTTP error),
  Evening Summary `/cron/evening` (с 05.08), Night Cycle `/cron/night` (с 06.08),
  Weekly Digest `/cron/weekly` (с 10.08, понедельники).
- News Collect в списке больше нет — вопрос снят.
- **Лимит числа задач (free)** → консолидация (#280): Night Cycle НЕ создавать заново,
  а редактировать: URL → `/cron/night-tick` (`0 2 * * *`) — диспетчер сам обходит
  `/cron/backup` → `/cron/indicator-reminders` → `/cron/shop-tick` →
  `/cron/golden-evals` → `/cron/night`; итог цепочки — одним Telegram-сообщением;
  тайм-аут крона безвреден (прецедент Morning Brief).
- **Целевой расклад (7 слотов, все живые):** Admin Reply, Morning Brief, Control
  Check (починить+включить), Evening Summary (починить+включить), Night Cycle →
  night-tick (включить), Weekly Digest (починить+включить, понедельники),
  Keep Alive → `/health` (новая, каждые 10 мин — прод на free-плане Render спит
  без трафика, холодный старт роняет ночные задачи).
- **Не создавать:** Reminders — тикает внутренним шедулером mlog-serve (5s interval);
  tool-output-cleanup — ретеншн FO-016 не реализован как endpoint (отдельная мелочь);
  narad-tick (FO-047) — диспетчер не реализован; collect-news — нет источников.
- После настройки: обновить эту секцию фактами (имена задач, расписания) — правило дрейфа.

## Native cron Metalogos (наряд №419, 2026-09-21) — целевая архитектура

Планировщик офиса = **нативный cron Metalogos 0.21.0** (наряд №418: дедуп окон,
catch-up `run_once|skip`, per-job IANA TZ, payload-контракт, рестарт-персистность
через KV-стор `data/metalogos_kv.db`). Внешний cron-job.org выводится из
исполнения; keep-alive (бодрствование free-инстанса Render) — waker на
GitHub Actions (наряд №420), потому что нативный тик не генерирует входящий
трафик и не считает время мёртвого контейнера.

**Реестр заданий владельца (SSOT): `dept/schedules.mlog`** — «внесение задания =
правка файла → деплой → бутстрап перерегистрирует стор идемпотентно по target».
Новые записи по умолчанию `enabled: false` — владелец включает сознательно.
Разовые задания — записи с `at: <epoch>` (регистрируются через `remind`,
доставка в `ReminderCheck`); recipe расчёта epoch — в README-runbook.
Живая поверхность (без рестарта): `/schedules/list`, `/schedules/bootstrap`,
`/schedules/create`, `/schedules/remove` — та же CRON_SECRET-авторизация, что
у `/cron/*`.

**Целевой расклад нативных заданий (tz Europe/Moscow, времена MSK wall-clock):**

| Имя | Cron (MSK) | Цель (zero-arg паттерн) | Внешний аналог |
|-----|------------|--------------------------|----------------|
| admin-reply | `25 7 * * *` | AdminReplySlot | cron-job.org «Admin Reply» (7:27) |
| morning-brief | `20 7 * * *` | MorningSlot (+YanaSelfLearn) | cron-job.org «Morning Brief» |
| control-check | `0 12 * * *` | ControlSlot | «Control Check» (на паузе с 05.08) |
| evening-summary | `0 21 * * *` | EveningSlot | «Evening Summary» (на паузе с 05.08) |
| night-tick | `0 5 * * *` | NightTickSlot (цепочка backup → indicators → shop → evals → night) | «Night Cycle»/night-tick |
| weekly-digest | `0 9 * * 1` | WeeklySlot | «Weekly Digest» (понедельники) |
| lz-daily | `10 9 * * *` | LzDailySlot | cron-job.org «LZ daily» |
| keep-alive | `*/10 * * * *` | GH Actions `.github/workflows/keepalive.yml` (№420) | «Keep Alive» |

**HTTP-фолбэк (п.4 наряда):** все `/cron/*`-роуты остаются ручным/аварийным
триггером; дедуп окон №418 делает двойной запуск (HTTP + нативный тик в одном
окне) безопасным. На легаси-пути (см. ниже) внешние cron-job.org продолжают
быть исполнителем без изменений.

**Статус перехода (честно, наряд №419):** прод остаётся на бинаре 0.19.0 —
Category A аудит app.mlog на 0.21 блокирует бут: долг №327
(UNTRUSTED_DECISION, антиинъекция) — ~430 сайтов диалогового контура, плюс
33 деструктивных SQL-сайта без грант-контура (№390) и clearance-хвост
(SECRET_EGRESS_NETWORK 30, UNTRUSTED_EGRESS_NETWORK 35, TAINT_PERSISTENCE 14 —
уже advisory под мостом ADR-0161, который на 0.21 добавит миграционный наряд).
`entrypoint.sh` держит **guard-пробу**: кандидат `bin/mlog-021` проходит аудит →
прод автоматически режется на 0.21 (+ env-allowlist №259, бутстрап реестра,
`METALOGOS_SERVE_BACKEND=interpreter` — VM-хендлеры 0.21 не видят db_decl
соединение, находка №419); не проходит → громкий лог и fallback `./bin/mlog`.
Откат — env-строкой (`MLOG_BIN=./bin/mlog`), `MLOG_BIN_FORCE=1` — форс-режим.
Стейджинг FO-050 доказал нативный цикл на 0.21: бутстрап 7×ADD → рестарт →
стор персистентен (7 заданий) → ре-бутстрап KEEP×7 без дублей; `next_run`
в TZ задания (07:25 MSK = +03:00); create/remove поверх стора без рестарта.

**Наблюдаемые апстрим-находки №419 (кандидаты в Metalogos-наряды):**
1. `cron_add` штампует id секундным таймстампом — батч-регистрация в одну
   секунду даёт одинаковые id; `cron_remove(id)` тогда сносит весь батч.
   Бутстрап №419 обходит двухпроходной схемой (remove → re-add), апстримный
   фикс — наносекунды/счётчик в id.
2. VM-serve (дефолт ADR-0171) не прокидывает db_decl-соединение в хендлеры:
   `[db] Connected` в логе, но любой `query()` в роуте = `no database
   connection` на `METALOGOS_SERVE_BACKEND=vm`; interpreter работает.
3. `init_reminder_persist` никем не вызывается — напоминания (remind) живут
   в памяти и не переживают рестарт вопреки комментарию в коде; реестровые
   one-shot-задания перерегистрируются бутстрапом (past-skip), так что офису
   не мешает.

**Ротация CRON_SECRET (п.5 наряда):** старое значение засветилось на скрине
владельца 2026-09-20. Новое значение сгенерировано и передано владельцу с
отчётом №419; применяется в дашборде Render В МОМЕНТ перехода прод на 0.21
(или одновременно с обновлением URL задач cron-job.org): до тех пор ротация
сломала бы внешние триггеры легаси-пути. `tests/test_cron_routes.py` и
фикстуры используют собственные тестовые секреты и ротации не требуют.

## Waker: GitHub Actions keep-alive (наряд №420, 2026-09-22) — финальная архитектура исполнителей

**Итоговая схема:** бизнес-расписания исполняет **нативный cron Metalogos**
(реестр `dept/schedules.mlog`, дедуп окон/catch-up/TZ — №418, бутстрап и живая
поверхность — №419); бодрствование free-инстанса Render обеспечивает **waker на
GitHub Actions** (`.github/workflows/keepalive.yml`) — нативный тик не генерирует
входящий трафик и не считает время мёртвого контейнера. Внешний cron-job.org
выводится из исполнения (cutover-чеклист ниже). Это преемница вердикта #255:
исполнитель расписаний = нативный cron Metalogos; waker = GH Actions.

**Параметры workflow:** schedule `*/10 * * * *` + ручной `workflow_dispatch`;
concurrency-группа `keep-alive` с `cancel-in-progress` (перекрытия пропускаются —
новый пинг отменяет зависший предыдущий); `timeout-minutes: 5`; секретов нет
(`/health` публичен), `permissions: {}`. Шаги: пинг прода
`https://fosved-office-v2.onrender.com/health` — блокирующий (ожидание 200,
`--max-time 120` покрывает холодный старт Render ~50–80 с); пинг стейджинга
`https://fosved-office-v2-staging.onrender.com/health` — неблокирующий
(`continue-on-error`), пока FO-050 активен: стейджинг на free-плане может быть
намеренно спящим/выключенным. Waker НЕ дёргает `/cron/*`-бизнес-маршруты.

**Дрейф расписания GH Actions (задокументировано, приемлемо):** `schedule` —
best-effort, задержки под нагрузкой достигают минут и больше. Для keep-alive это
не критично: любой пинг чаще окна сна (15 мин) держит инстанс живым; точное
время обеспечивает нативный cron (№418).

**Cutover-чеклист (исполняет владелец; старт — когда оба предусловия выполнены):**

1. *Предусловие А:* прод на 0.21 — guard-проба entrypoint перерезала кандидата
   автоматически (проверка: в логе деплоя entrypoint громко сообщает выбор
   бинаря: кандидат 0.21 или fallback `./bin/mlog` 0.19). До этого нативный
   cron на проде не живёт.
2. *Предусловие Б:* реестр жив на проде — `GET /schedules/bootstrap`
   (CRON_SECRET) → `GET /schedules/list`: 7 слотов реестра, `next_run` в TZ
   Europe/Moscow.
3. Владелец выключает задачи cron-job.org в workspace (состояние 2026-09-20,
   секция выше): живые — **Admin Reply**, **Morning Brief**; остальные уже на
   паузе с августа (Control Check, Evening Summary, Night Cycle, Weekly
   Digest); «Monthly Review» отсутствует.
4. Keep-alive GH Actions остаётся единственной внешней зависимостью офиса
   (workflow уже в main; прогоны позеленеют после починки квоты Actions —
   офисная issue #306).
5. *Rollback-путь:* включить задачи cron-job.org обратно (те же URL; после
   ротации CRON_SECRET — обновить секрет в URL задач, иначе задачи начнут
   получать 401). Нативный контур при этом не ломается: дедуп окон №418 делает
   двойной запуск в одном окне безопасным.
6. Наблюдение 24–48 ч после cutover: слоты приходят в Telegram из нативного
   контура; затем обновить секцию cron-job.org фактами (правило дрейфа).

**Runbook добавления задания (нативный контур):**

1. Добавить запись в реестр `dept/schedules.mlog` (name, cron в TZ
   Europe/Moscow, target zero-arg паттерн; новые записи по умолчанию
   `enabled: false`).
2. Деплой в main (Render пересобирает контейнер).
3. Бутстрап: `GET /schedules/bootstrap` с CRON_SECRET (идемпотентен —
   повторный запуск даёт KEEP, дедуп-штампы переживают рестарт).
4. Проверка: `GET /schedules/list` (или билтин `cron_list()` в mlog-скрипте,
   REFERENCE Metalogos §4.17.3) — задание в списке, `next_run` в TZ задания.
5. Включение: перевести запись в `enabled: true` + повторный бутстрап (или
   `POST /schedules/create` точечно).

## Прочее замеченное в workspace (2026-09-20, скрин владельца)

- `fosved-bot-bd` — PostgreSQL 18, Available, Frankfurt, 4 мес. КТО ИСПОЛЬЗУЕТ —
  не установлено (prod на sqlite: DATABASE_URL не задаётся, #269); кандидат на
  удаление после сверки, сейчас НЕ трогаем.
- 1 сервис в состоянии Suspended — имя не видно на скрине, уточняется (#255).

## Staging (в blueprint, для сверки): fosved-office-v2-staging

web, docker, plan free, frankfurt; env: ТОЛЬКО `MLOG_BIN=./bin/mlog-020` +
`MLOG_ENTRY=dogfood_staging.mlog` (#277: группы `fosved-secrets` не существует,
секреты — по потребности вручную; прод-токен бота НЕ давать — конфликт поллинга).
VM-флип: `METALOGOS_SERVE_BACKEND=vm` после
апгрейда бинаря (FO-050).
