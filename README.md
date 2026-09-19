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

64 команды. Основные:

| Команда | Описание |
|---|---|
| `/start`, `/help`, `/status` | Инициализация, справка, статус системы |
| `/osp`, `/lz`, `/dev`, `/finance`, ... | Обращение к департаменту напрямую |
| `/chain a+b`, `/chain-parallel a+b` | Кросс-департаментная цепочка (последовательно / fan-out) |
| `/voice on/off/male/female` | Настройки голоса |
| `/fix <текст>`, `/good` | Обучение: сообщить об ошибке / записать удачный пример |
| `/debrief [dept]` | LLM-анализ корректировок |
| `/archive [id]`, `/search <запрос>` | Просмотр архива, полнотекстовый поиск |
| `/audit` | Журнал аудита |
| `/admin status` | Статус Admin-агента |
| `/lockdown on/off` | Экстренная блокировка |
| `/remember key=value`, `/memory` | Постоянная память |
| `/quarterly-review <dept>` | Ежеквартальный обзор отдела на соответствие методологии |

Полный список — `grep -oE 'starts_with\(text, "/[a-z_-]+' app.mlog`.

## Структура проекта

```
.
├── app.mlog                  # Главный роутер (~4800 строк)
├── bin/mlog                  # Metalogos v0.19.0 бинарник (x86-64, Rust, прод)
├── bin/mlog-020              # Metalogos 0.20.0 wave-3 (main 29de25a) — стейджинг-догфуд (FO-050)
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
- **ЛЗ**: `lz_monitors`, `lz_telegram_channels`, `lz_telegram_posts`, `scan_logs`
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

## Технологический стек

| Компонент | Технология |
|---|---|
| Ядро | Metalogos v0.19.0 (Rust DSL, ~394 встроенных функции: файлы, exec с песочницей, MCP-клиент, нативная графика — chart/diagram, PDF, typed memory) |
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
