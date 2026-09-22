<div align="center">

# FOSVED Office V2

**AI-офисная операционная система. 14 департаментов + Admin-агент. Metalogos DSL, собственный контур разработки FORGE, MCP-интеграция, Guardian permission-matrix. Telegram-native, Mini App SPA.**

</div>

---

## Обзор

FOSVED Office — самооптимизирующаяся бизнес-операционная система, построенная на [Metalogos](https://github.com/ShkodnikAI/Metalogos-) — AI-ориентированном DSL на Rust — с прокси-слоем на Python. Система управляет 13 специализированными агентами-департаментами, 1 системным Admin-агентом и собственным контуром разработки (FORGE): хранилищем репозиториев, конвейером проверок и живым превью, целиком реализованным на нативном Metalogos. Задачи поступают через Telegram, маршрутизируются в нужный департамент, обрабатываются с помощью LLM (с бюджетным контролем, канареечным сравнением моделей и параллельным fan-out для сложных запросов) и возвращаются в виде стилизованных Mini App-отчётов.

**~4800 строк** в главном роутере (`app.mlog`), **~12400 строк** в прокси-пакете (`proxy/`), **68 таблиц БД**, **64 команды бота**, **15 модулей отделов** (.mlog).

## Архитектура

```
Telegram Bot API
       │
       ▼
Reverse Proxy (Flask)
       │
       ├──▶ Metalogos (mlog serve, :10001)
       │       │
       │       ├── app.mlog (~4800 строк, маршрутизация + команды + FORGE-роуты)
       │       ├── dept/*.mlog (15 модулей: 13 департаментов + forge + утилиты)
       │       └── SQLite (68 таблиц)
       │
       └──▶ LLM Proxy (Flask, :4000)
               │
               ├── llm_proxy.py — тонкий фасад-сборщик (FO-008 стренглер)
               ├── proxy/ — 27 модулей, ~12400 строк:
               │     core, providers, routes_core/admin/sched/tail,
               │     budget, shadow, chain_parallel, chain_durable,
               │     guardian, mcp_server, forge_backup, forge_secrets,
               │     lz_github, lz_sources, news, dialog, compaction,
               │     owner_profile, reports, resilience, review, redact,
               │     kg, telegram, voice, departments
               ├── 7+ LLM-провайдеров с фейловером, бюджетным контролем
               │   и канареечным (shadow) сравнением моделей
               └── Mini App SPA статика (/miniapp-spa), FORGE-веб (/repos)
```

**Порядок запуска** (entrypoint.sh): `llm_proxy (:4000)` → `mlog serve (:10001)` → `reverse_proxy`

## Департаменты

Профили читаются из `library/*.md` (основной, активно используемый источник — `read_file("library/" + dept + ".md")` в диспетчере). Параллельно существует более новый декларативный слой `departments/*.md` (frontmatter: `mode`, `temperature` + системный промпт) — младший, не заменяет `library/` целиком.

| Департамент | Роль | Файл |
|---|---|---|
| **Yana** | Руководитель кабинета, маршрутизация, голос | `dept/yana.mlog` |
| **OSP** | Стратегический анализ, планирование | `dept/osp.mlog` |
| **LZ** | Лаборатория знаний — детерминированные API-источники (arXiv, HN Algolia, GitHub Search) + GitHub-скан | `dept/lz.mlog` |
| **Expert** | Технический препаратор | `dept/expert.mlog` |
| **Marketing** | Аудитория, каналы, контент | `dept/marketing.mlog` |
| **Finance** | Денежные потоки, налоги, экономика, инфографика (нативные Metalogos-диаграммы) | `dept/finance.mlog` |
| **Legal** | NDA, GDPR, оценка рисков | `dept/legal.mlog` |
| **Dev** | Архитектура, генерация кода, **интеграция с контуром FORGE** | `dept/dev.mlog` |
| **Design** | UI/UX, вайрфреймы, визуал | `dept/design.mlog` |
| **QA** | Тестирование, хаос-инженерия | `dept/qa.mlog` |
| **Visual** | Инфографика, визуализация данных | `dept/visual.mlog` |
| **Engineering** | Расчёты, нагрузки, технические задачи | `dept/engineering.mlog` |
| **Kavalnya** | Методология, стандарты, обучение | `dept/kavalnya.mlog` |
| **Admin** | Системный агент, ночной цикл, граф знаний, автофикс | `dept/admin.mlog` |

Каждый вызов дисциплинирован диспетчером напрямую на реальный обработчик отдела (`Handle<Dept>`), не через общий проходной маршрут — важное архитектурное свойство, восстановленное после длительного аудита осени 2026.

## Ключевые возможности

### Мультипровайдерный LLM с бюджетом и канареечной оценкой
7+ провайдеров с фейловером. **Бюджетный контроль** (soft/hard/stop лимиты в сутки на департамент). **Shadow-оценка** — канареечный роутинг с сравнением через verifier, без риска для основного трафика. Компакция контекста департаментов (budget + prune + summarize + offload).

### Guardian — permission-matrix
Декларативная политика прав в `guardian_base.json` (версионируется коммитом): правило `deny` **скрывает** инструмент от LLM целиком, не просто блокирует вызов. По умолчанию заперты `http_*`, `web_*`, `search_web*`, `tavily_*`, `exec_*` для всех департаментов — открываются точечно. Overlay на уровне департамента — в таблице `guardian_rules`, оценка last-match-wins.

### MCP — Model Context Protocol
Офис умеет быть **и клиентом, и сервером** MCP:
- `mcp_servers/github`, `mcp_servers/filesystem` — встроенные MCP-серверы, вызываются через `mcp_call`/`mcp_list_tools` (нативные функции Metalogos, stdio-транспорт).
- `proxy/mcp_server.py` — офис сам отдаёт **память наружу** как MCP-сервер (Memory-MCP), с отдельным гейтом на запись (`FOSVED_MCP_ALLOW_WRITE`).

### FORGE — собственный контур разработки
Полный цикл постановки, реализации и передачи проекта, реализованный **целиком на нативном Metalogos**, без внешних CI/CD:
- **Хранилище** — bare git-репозитории на постоянном диске, зеркалирование в приватные репозитории настоящего GitHub (передача заказчику — штатной кнопкой GitHub).
- **Гейт на границе** — секреты, ревью, статическая проверка, тест, документация, линт — до публикации коммита, не после.
- **Стоп-гейты владельца** — задание и план утверждаются перед работой; кнопки в Telegram; история решений по находкам (отклонённое не предлагается повторно).
- **Протокол правок** — теговый разбор ответа модели, нечёткое сопоставление диффов вместо немедленного отказа, метрика доли правок с первой попытки.
- **Изоляция прогонов** — `ulimit`/`unshare` для запуска сгенерированного кода, whitelist опасных паттернов с git-чекпоинтом перед риском.
- **Превью** — статическое (файлы напрямую) и живое (по требованию, с автогашением).
- **Резервный контур** — `git bundle`, ежедневная выгрузка `forge_*` таблиц, checkpoint-метки.
- Веб-интерфейс: `/repos`, `/repos/project`, `/repos/task` — в едином визуальном языке «Диспетчерская» с остальным Mini App.

### Голос (STT/TTS)
- **STT**: голосовые сообщения Telegram → Whisper → текст → обработка департаментом.
- **TTS**: текстовые ответы → edge-tts → голосовое сообщение (мужской/женский голос).
- Стриминг и voice-UX: статусы набора текста, кусочная отдача, voice-render на Python-стороне.

### Цикл обучения
6-типовая классификация ошибок, `/fix`, `/good`, `/debrief`, запланированное самообучение. Review-очередь выведенного знания — approve/decline/undo перед тем, как оно повлияет на поведение.

### Планировщик
Утренний бриф (включает принудительное обновление ЛЗ-скана и сборщика новостей — надёжнее отдельного Cron Job Render), вечерняя сводка, дайджесты, ночной цикл Admin, контрольная проверка предсказаний.

### Кросс-департаментные цепочки
`/chain osp+legal` — последовательное выполнение. **Fan-out + debate** — параллельный запуск нескольких департаментов с последующим судейством. **Durable-степы** — чекпоинты и `resume` для многошаговых цепочек, переживают падение процесса.

### Темпоральный граф знаний
`knowledge_graph`/`knowledge_edges` — версии вместо перезаписи, история изменений сохраняется, не теряется при каждом ночном цикле Admin.

### Mini App SPA — «Диспетчерская»
Единый визуальный язык на всех экранах (консолидирован отдельным нарядом после того, как редизайн и старые страницы отчётов разошлись в разные стили): тёплая бумага (`#EFEAE0`/`#FBF8F2`), чернильный текст (`#1C1B18`), кирпично-алый акцент-печать (`#A8321E`), Newsreader + IBM Plex Sans/Mono. Экраны: Главная, Архив, Чат, Наряды, Настройки, Отделы, **Интеграции** (SEC-6), **FORGE/Репозитории**. Телефон/планшет/десктоп — один и тот же источник данных, не отдельные хранилища.

## Команды бота

Живые команды извлекаются из обработчиков `app.mlog` (`starts_with(text, "/...")` и точные `==`)
и гвардятся тестом `tests/test_readme_commands.py`: расхождение live-vs-docs равно нулю в обе стороны.
В бэктиках — точный литерал команды; аргументы указаны после него.

### Служебные и статус

| Команда | Назначение |
|---|---|
| `/start` | приветствие, список департаментов |
| `/help` | справка по командам |
| `/status` | статус системы и департаментов |
| `/office`, `/dept` | веб-панель офиса (ссылки) |
| `/stats` | статистика диалогов |
| `/cost`, `/costs` | расходы по чату |
| `/narads` | последние 10 нарядов |
| `/review` | review-очередь выведенного (approve/decline/undo) |
| `/audit` | последние 20 строк audit-журнала |
| `/brief` | отправить morning brief немедленно |
| `/digest` | вечерняя сводка |
| `/calendar` | ближайшие события календаря |
| `/learning` | статистика цикла обучения |

### Департаменты (прямой вызов)

| Команда | Назначение |
|---|---|
| `/yana` | персональный ассистент |
| `/osp`, `/osp deep`, `/osp full`, `/osp wargame` | ОСП: разбор вопроса (режимы глубины, варгейм) |
| `/lz`, `/lz deep`, `/lz osint`, `/lz osint advanced`, `/lz profile` <actor> | Лаборатория знаний: скан, OSINT, профилирование |
| `/expert` | экспертный департамент |
| `/marketing` | маркетинг |
| `/finance` | финансы |
| `/legal`, `/legal check` <сущность> | юрист; due diligence по сущности |
| `/dev`, `/dev-forge` <запрос> | разработка; запрос в FORGE из dev |
| `/design`, `/design-image` | дизайн; генерация изображения |
| `/qa` | QA |
| `/visual` | визуальный департамент |
| `/engineering` | инженерия |
| `/forge`, `/forge-export` | маршрут в kavalnya; экспорт FORGE-состояния |

### Аналитическая диспетчеризация (маршруты)

| Команда | Маршрут |
|---|---|
| `/analyze`, `/deep`, `/quickanalyze`, `/wargame` | ОСП |
| `/scan` | ЛЗ |
| `/calc`, `/simulate` | инженерия |
| `/campaign`, `/competitors`, `/segment`, `/market-research` | маркетинг |
| `/issue`, `/ci`, `/docs` | dev |

### Маркетинг (рабочие команды)

| Команда | Назначение |
|---|---|
| `/cro` <текст> | рост конверсии |
| `/marketing-ideas` <запрос> | генерация идей |
| `/marketing brand-check` | проверка бренда |
| `/marketing-context`, `/marketing-context set` <json>, `/marketing-context default` | контекст маркетинга |

### FORGE и фабрика

| Команда | Назначение |
|---|---|
| `/newproject` | мастер создания проекта FORGE (форма) |
| `/factory` <запрос> | фабричный заказ |
| `/factory_list` | последние 10 заказов |
| `/factory_deliver`, `/factory_deploy`, `/factory_review` <id> | статус заказа |

### ЛЗ: каналы и мониторы

| Команда | Назначение |
|---|---|
| `/lz_channel add` <параметры> | добавить канал |
| `/lz_channels` | список каналов |
| `/lz_monitor` <тема> | монитор темы |

### Память и обучение

| Команда | Назначение |
|---|---|
| `/remember` <факт> | записать факт в постоянную память |
| `/fix` <текст> | сообщить об ошибке (коррекция) |
| `/good` | записать удачный пример |
| `/rate`, `/rate-yana` <оценка> | оценить ответ Яны |
| `/score` <dept> | оценка департамента |
| `/debrief` [dept] | LLM-анализ корректировок |
| `/quarterly-review` [dept] | ежеквартальный обзор методологии |

### Напоминания и квесты

| Команда | Назначение |
|---|---|
| `/remind`, `/remind once`, `/remind daily`, `/remind weekly`, `/remind yearly`, `/remind del` <id> | напоминания |
| `/quest`, `/quest new`, `/quest send`, `/quest list`, `/quest next`, `/quest approve`, `/quest close`, `/quest status` | квесты |

### Архив

| Команда | Назначение |
|---|---|
| `/archive` [id] | просмотр архива |
| `/autoarchive` <...> | настройки автоархивации |
| `/search` <запрос> | полнотекстовый поиск |

### Модели и бюджет

| Команда | Назначение |
|---|---|
| `/model`, `/model set` <...>, `/model-cost set` <...> | назначение моделей и цен |
| `/budget` <...> | бюджет LLM |

### Админ и безопасность

| Команда | Назначение |
|---|---|
| `/admin` <...> | admin-агент (status и пр.) |
| `/lockdown`, `/unlock` <пароль> | экстренная блокировка / разблокировка |

### Голос, цепочки, прочее

| Команда | Назначение |
|---|---|
| `/voice` | голос: вкл/выкл, мужской/женский |
| `/chain`, `/chain continue` | кросс-департаментная цепочка; режимы parallel/debate (FO-026) |
| `/inject` <...> | инъекция контекста |
| `/verify` <...> | верификация |
| `/shadow` <...> | shadow-прогоны |

## Структура проекта

```
.
├── app.mlog                  # Главный роутер (~4800 строк)
├── bin/mlog                  # Metalogos v0.19.0 бинарник (x86-64, Rust, легаси-фолбэк)
├── bin/mlog-020              # Metalogos 0.20.0 wave-3 (main 29de25a) — стейджинг-догфуд (FO-050)
├── bin/mlog-021              # Metalogos 0.21.0 (52f2aa7) — ПРОД-кандидат, guard-переход №419/№421
├── llm_proxy.py              # Тонкий фасад-сборщик (FO-008), точка входа
├── proxy/                    # 27 модулей, ~12400 строк — вся логика LLM-прокси
│   ├── core.py                    # Flask-приложение, auth, конфиг
│   ├── providers.py                # 7+ LLM-провайдеров, фейловер
│   ├── budget.py, shadow.py        # Бюджетный контроль, канареечная оценка
│   ├── guardian.py                 # Permission-matrix (FO-015)
│   ├── mcp_server.py               # Memory-MCP офиса наружу (FO-021)
│   ├── forge_backup.py, forge_secrets.py  # Резервный контур и ключи FORGE
│   ├── chain_parallel.py, chain_durable.py  # Fan-out+debate, durable-степы
│   ├── lz_github.py, lz_sources.py, news.py # Источники данных ЛЗ
│   ├── dialog.py, compaction.py    # История диалога, компакция контекста
│   ├── owner_profile.py, reports.py, kg.py  # Профиль владельца, отчёты, граф знаний
│   └── routes_core/admin/sched/tail.py      # HTTP-роуты по назначению
├── reverse_proxy.py          # Маршрутизатор запросов
├── entrypoint.sh             # Docker-запуск (3 процесса)
├── Dockerfile                # ubuntu:24.04, зависимости из requirements.txt
├── secrets_crypto.py         # Шифрование секретов (SEC-5)
├── auto_enricher.py          # Обогащение отчётов (бейджи, таблицы, markdown→HTML)
├── llm_verifier.py           # Верификация ответов моделей
├── doc_extract.py            # Извлечение текста из документов
├── guardian_base.json        # Базовая политика прав (FO-015)
├── report_css.txt            # CSS для страниц отчётов (устаревающий стиль)
├── dept/
│   ├── yana.mlog, osp.mlog, lz.mlog, expert.mlog, marketing.mlog,
│   │   finance.mlog, legal.mlog, dev.mlog, design.mlog, qa.mlog,
│   │   visual.mlog, engineering.mlog, kavalnya.mlog, admin.mlog
│   ├── forge.mlog            # Контур разработки FORGE (~1800 строк)
│   ├── forge_model.mlog      # Модель данных FORGE
│   ├── chain.mlog            # Кросс-департаментные цепочки
│   ├── scheduler.mlog        # Cron-планировщики
│   ├── miniapp.mlog          # Форматирование отчётов
│   └── utils.mlog, context.mlog, handlers_fallback.mlog
├── library/                  # Профили департаментов (.md) — основной источник
├── departments/               # Декларативные профили (frontmatter) — младший слой
├── mcp_servers/
│   ├── github/, filesystem/  # Встроенные MCP-серверы
├── skills_index/              # Индексы скиллов
├── config/                    # Приоритеты моделей/провайдеров по департаментам
├── miniapp/                   # Telegram WebApp SPA (единый файл index.html + assets)
├── memories/                  # FosvedMemory — типизированная память
├── lib/                       # fosved_memory.py
└── docs/                      # FOIP-предложения, аудит веток, параметры ОСП
```

## База данных (68 таблиц)

Основные группы:

- **Диалог и обучение**: `dialog_history`, `adapt_corrections`, `error_patterns`, `debriefs`
- **Метрики и аудит**: `dept_metrics`, `token_usage`, `audit_log`, `daily_stats`, `session_log`, `trace_log`, `rate_limits`
- **Архив**: `dept_archive`, `channel_archive`, `miniapp_responses`, `miniapp_notes`
- **Admin / граф знаний**: `admin_reports`, `admin_findings`, `admin_proposals`, `knowledge_graph`, `knowledge_edges`
- **ОСП**: `analysis`, `asymmetric_bet`, `indicator`, `watchlist_item`, `brier_score_log`, `calibration_curve_point`, `research_source`, `dept_verification`
- **ЛЗ**: `lz_monitors`, `lz_telegram_channels`, `lz_github_updates`, `scan_logs`
- **FORGE** (15 таблиц): `forge_projects`, `forge_repos`, `forge_tasks`, `forge_stages`, `forge_briefs`, `forge_remarks`, `forge_finding_decisions`, `forge_gates`, `forge_previews`, `forge_runs`, `forge_project_secrets`, `forge_customer_data`, `forge_step_config`, `forge_whitelist`, `forge_edit_stats`
- **Отделы**: `dev_tasks`, `campaign_verifications`, `legal_assessments`, `training_sessions`, `marketing_ideas`, `visual_artifacts`, `visual_templates`, `design_tokens`, `style_evolution`
- **Прочее**: `narads`, `factory_orders`, `quests`, `quest_files`, `quest_checkpoints`, `system_settings`, `secrets_store`, `webhook_dedup`, `yana_events`, `yana_delegation_log`, `yana_forgetting_incidents`, `chain_steps`

## Быстрый старт

```bash
git clone https://github.com/ShkodnikAI/FOSVED-office-v2.git
cd FOSVED-office-v2
```

Создать `.env` (см. `.env.example` за полным списком):
```
TELEGRAM_BOT_TOKEN=ваш_токен_бота
OWNER_TELEGRAM_ID=ваш_telegram_id
LOCKDOWN_PASSWORD=ваш_пароль
CRON_SECRET=ваш_секрет
SECRETS_MASTER_KEY=ключ_для_шифрования_секретов
ZAI_API_KEY=ваш_ключ
DEEPSEEK_API_KEY=ваш_ключ
# ... остальные ключи провайдеров, GitHub-токен для FORGE-зеркалирования
```

Docker:
```bash
docker build -t fosved .
docker run -p 10000:10000 --env-file .env fosved
```

## Правило деплой-целостности

> **app.mlog, bin/mlog, entrypoint.sh и env-переменные Render меняются только согласованным набором.** Частичный перенос (cherry-pick одного файла) запрещён — бинарник, mlog-грамматика и entrypoint-гейты образуют атомарный юнит. Нарушение этого правила неоднократно приводило к падению прода — от рассинхронизации db-роутов до молчаливого игнорирования `.dockerignore` нужного файла зависимостей.

## Как добавить задание в офис (нативный cron, наряд №419)

Планировщик офиса — нативный cron Metalogos; реестр заданий владельца —
`dept/schedules.mlog` (SSOT). **Внесение задания = правка файла → деплой.**

1. Открой `dept/schedules.mlog` и добавь запись в `SchedulesRegistry()`:

   ```
   { name: "my-task", cron: "30 10 * * *", tz: "Europe/Moscow",
     target: "MySlotPattern", catch_up: "run_once", enabled: false }
   ```

   - `cron` — стандартные 5 полей, **время в Москве (MSK = UTC+3)**; `10 30 * * *` = 10:30 МСК.
   - `target` — имя zero-arg паттерна (он обязан существовать: `scheduler.mlog`, `app.mlog` или модуль в `dept/`); бутстрап громко отказывает неизвестной цели (`FAIL(...)`).
   - **Новые записи — `enabled: false`**; включение — отдельная правка (владелец включает сознательно).
2. Разовое задание (напоминание-задание): вместо `cron` укажи `at: <unix-epoch seconds>`.
   Расчёт момента: `date -d "2026-10-01 15:00 +0300" +%s`. Доставка — через
   `remind` в `ReminderCheck`; бутстрап не дублирует то же сообщение и пропускает
   прошедшие моменты.
3. Деплой (merge → Render). При старте `entrypoint.sh` вызывает
   `/schedules/bootstrap` — реестр перерегистрируется идемпотентно по `target`:
   неизменные задания получают `KEEP` (история `run_count`/`last_run` сохраняется),
   изменённые — `REMOVE-STALE`+`ADD`, выключенные — `REMOVE`.
4. Проверка без рестарта (№425: секрет в URL — только percent-кодированным:
   0.21 и Flask декодируют query, литеральный '+' сырой вставкой даёт 403):
   `curl -sG "https://fosved-office-v2.onrender.com/schedules/list" --data-urlencode "secret=$CRON_SECRET"`
   — стор + сверка с реестром; `.../schedules/bootstrap` с тем же
   `--data-urlencode` — ручной перезапуск бутстрапа; `POST
   .../schedules/create|remove` — точечные правки поверх стора (та же
   CRON_SECRET-авторизация, что у `/cron/*`).
5. HTTP-роуты `/cron/*` остаются ручным/аварийным триггером; двойной запуск в
   одном окне безопасен (дедуп №418).

Подробности и статус перехода прод на 0.21 — `docs/render-dashboard.md`,
секция «Native cron Metalogos». **Статус (наряд №422, первый прод-бут на
0.21 от 2026-09-22):** прод работает на 0.21; entrypoint дополнительно ставит
`METALOGOS_HTTP_ALLOW_PRIVATE=1` (SSRF-гвард 0.21 по умолчанию резал
штатный loopback-канал mlog → LLM-прокси), бутстрап нативного реестра
ретраится трижды, version-чек ходит с INTERNAL_API_TOKEN. Тела диалоговых
роутов (`/webhook/telegram`, `/repos/task`, `/cron/night-tick`) вынесены в
паттерны: route-исполнитель 0.21 теряет mut-контекст в ветвлениях
(апстрим-репорт в Metalogos). Известный апстрим-ложняк аудита — эвристика
SECRETS («sk_» совпадает внутри «task_id»/«risk_level», нужен word-boundary).

Дополнение (наряд №423, 2026-09-22): `CRON_SECRET` оставлен без ротации
(решение владельца — периметр приватный; компенсация — access-лог прокси
маскирует `secret=`/`token=`/`password=` значения фильтром
`QuerySecretMasker`, гвард `tests/test_proxy_log_masking.py`; триггеры
пересмотра — в docs/render-dashboard.md). 403 на `/cron/morning` в бут-логе —
рассинхрон секрета между URL cron-job.org и env Render (диагноз пробой на
реальном 0.21: совпадение даёт 200, пустой env даёт 403, отсутствие в
allowlist даёт громкий 500; деталей — docs/render-dashboard.md, §№423).

Дополнение (наряд №424, 2026-09-22): живая проба прода нашла оверрайд
`METALOGOS_ENV_ALLOWLIST` из дашборда Render, затирающий дефолт entrypoint:
env("CRON_SECRET") читался, а env("INTERNAL_API_TOKEN") давал 500
ENV_NOT_PERMITTED — `/version` лежала. Entrypoint теперь держит ценз env()
как нижнюю границу (guard доливает отсутствующие имена к любому оверрайду)
и печатает эффективный список в бут-лог; гвард
`tests/test_env_allowlist_guard.py`. Владельцу: переменную из дашборда
удалить (или оставить только как дополнение); деталей —
docs/render-dashboard.md, §№424.

## Технологический стек

| Компонент | Технология |
|---|---|
| Ядро | Metalogos 0.21.0 (Rust DSL, ~400 встроенных функций: файлы, exec с песочницей, MCP-клиент, нативная графика — chart/diagram, PDF, typed memory, label-lattice + гранты; легаси-фолбэк 0.19.0, см. entrypoint guard-переход) |
| Прокси-слой | Python 3.12 + Flask, разбит на пакет `proxy/` (27 модулей) |
| База данных | SQLite, 68 таблиц |
| Голос STT | Whisper |
| Голос TTS | edge-tts |
| LLM | 7+ провайдеров, бюджетный контроль, канареечная (shadow) оценка |
| MCP | Клиент (stdio) + собственный Memory-MCP сервер наружу |
| Контейнер | Docker (ubuntu:24.04), зависимости из `requirements.txt` |
| Интерфейс | Telegram Bot API + WebApp SPA + FORGE веб-панель |

## Качество

Smoke-джоб в CI — локальный подъём фасада перед мержем. Стресс-тест: статический анализ кода. Проверка синхронности зависимостей: `python3 scripts/audit_deps.py`.

## Лицензия

MIT
