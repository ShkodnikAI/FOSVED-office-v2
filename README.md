<div align="center">

# FOSVED Office V2

**AI-офисная операционная система. 13 департаментов + Admin-агент. Metalogos DSL, 7 LLM-провайдеров, Telegram-native, Mini App SPA.**

</div>

---

## Обзор

FOSVED Office — самооптимизирующаяся бизнес-операционная система, полностью построенная на [Metalogos](https://github.com/ShkodnikAI/Metalogos-) — AI-ориентированном DSL на Rust. Система управляет 13 специализированными агентами-департаментами и 1 системным Admin-агентом, каждый со своей методологией, LLM-анализом, памятью, индексом скиллов и собственной метрикой. Задачи поступают через Telegram, маршрутизируются в нужный департамент, обрабатываются с помощью LLM и возвращаются в виде стилизованных Mini App-отчётов. Система учится на ошибках (6-типовая классификация), запускает запланированные дайджесты и выполняет автономные ночные аудиты.

**~9000 строк кода** на Metalogos (.mlog) и Python, **110 паттернов** (функций), **68 бот-команд**, **22 таблицы БД**.

## Архитектура

```
Telegram Bot API
       │
       ▼
Reverse Proxy (Flask, :10000)
       │
       ├──▶ Metalogos (mlog serve, :10001)
       │       │
       │       ├── app.mlog (1302 строки, маршрутизация + команды)
       │       ├── dept/*.mlog (15 модулей, 13 департаментов + утилиты)
       │       ├── file_cache.mlog (кэш профилей)
       │       ├── file_cache_skills.mlog (кэш скиллов)
       │       └── SQLite (22 таблицы)
       │
       └──▶ LLM Proxy (Flask, :4000)
               │
               ├── 7 LLM-провайдеров (zai, DeepSeek, Groq, Grok, Anthropic, OpenAI, Apodex)
               ├── Фейловер с приоритетной конфигурацией модели/провайдера
               ├── 11 API-эндпоинтов (dashboard, dept, models, economics, narads, archive, admin)
               ├── TTS (edge-tts), STT (Whisper)
               ├── Mini App SPA статика (/miniapp-spa)
               └── Архив, планировщик, обучение, аудит, поиск
```

**Порядок запуска** (entrypoint.sh): `llm_proxy (:4000)` → `mlog serve (:10001)` → `reverse_proxy (:10000)`

## 13 Департаментов + Admin

| Департамент | Роль | Скиллы | Файл |
|---|---|---|---|
| **Yana** | Руководитель кабинета, маршрутизация, голос | 12 | `dept/yana.mlog` |
| **OSP** | Стратегический анализ, планирование | 24 | `dept/osp.mlog` |
| **LZ** | Лаборатория знаний, глубокий скан 9 источников, Apodex-исследования | 12 | `dept/lz.mlog` |
| **Expert** | Технический препаратор | 12 | `dept/expert.mlog` |
| **Marketing** | Аудитория, каналы, контент | 11 | `dept/marketing.mlog` |
| **Finance** | Денежные потоки, налоги, экономика | 9 | `dept/finance.mlog` |
| **Legal** | NDA, GDPR, оценка рисков | 10 | `dept/legal.mlog` |
| **Dev** | Архитектура, генерация кода | 20 | `dept/dev.mlog` |
| **Design** | UI/UX, вайрфреймы, визуал | 12 | `dept/design.mlog` |
| **QA** | Тестирование, хаос-инженерия | 11 | `dept/qa.mlog` |
| **Visual** | Инфографика, визуализация данных | 11 | `dept/visual.mlog` |
| **Engineering** | Расчёты, нагрузки, технические задачи | 12 | `dept/engineering.mlog` |
| **Kavalnya** | Методология, стандарты | 8 | `dept/kavalnya.mlog` |
| **Admin** | Системный агент, ночной цикл, граф знаний, автофикс, мониторинг памяти | 12 | `dept/admin.mlog` |

**Итого: 176 индексированных скиллов** по 14 агентам.

## Ключевые возможности

### Мультипровайдерный LLM с фейловером
7 провайдеров (zai, DeepSeek, Groq, Grok, Anthropic, OpenAI, Apodex) с настраиваемым приоритетом. Автоматический фейловер при таймауте/ошибке. Переопределение модели и провайдера на уровне департамента через `config/override_*.txt`.

### Голос (STT/TTS)
- **STT**: Голосовые сообщения Telegram → Whisper (Groq/OpenAI) → текст → обработка департаментом
- **TTS**: Текстовые ответы → edge-tts → голосовое сообщение в Telegram (мужской/женский голос, переключаемый)

### Цикл обучения
- 6-типовая классификация ошибок (фактические, методологические, неполные, контекстные, форматные, логические)
- Команда `/fix` — захват ошибок с контекстом
- Команда `/good` — запись положительных примеров
- `/debrief` — LLM-анализ корректировок
- Запланированное самообучение интегрирует корректировки в поведение системы

### Планировщик (6 cron-задач)
- Утренний бриф, вечерняя сводка, еженедельный дайджест, ежемесячный обзор
- Контрольная проверка (верификация предсказаний из system_settings watches)
- Ночной цикл Admin (5 фаз: граф → аудит → метрики → автофикс → предложения)
- Все защищены CRON_SECRET, запускаются через GET-эндпоинты

### Архив и поиск
- Отчёты автоматически архивируются с удалением HTML-тегов и департаментными хештегами
- Ежедневные дайджесты в Telegram-канал
- Полнотекстовый поиск по всем архивным отчётам

### Кросс-департаментные цепочки
`/chain osp+legal` — последовательное выполнение по нескольким департаментам (до 3), с отчётами по каждому шагу и итоговой сводкой.

### LZ Глубокий скан (9 источников)
Web, YouTube, Reddit, Science, GitHub, Social, Telegram, Darknet, Academic — каждый источник сканируется через LLM. Провайдер Apodex для верифицированных исследований с бейджами доказательности (verified/unverified/conflicting). LZ Compare для сравнительного анализа LLM vs Apodex.

### Admin-агент (ночной цикл)
5-фазовый автономный цикл: построение графа знаний → аудит кода → анализ метрик → автофикс → предложения. Строит граф знаний из всех .mlog файлов, запускает LLM-сканирование кода, генерирует планы автофикса (пропускает неизменяемые/высокорисковые) и создаёт предложения по улучшению с механизмами одобрения/отклонения.

### Mini App SPA
9-экранное адаптивное веб-приложение для интеграции с Telegram WebApp:
- Дашборд (KPI-сетка, статус департаментов, панель администратора)
- Детали департамента (задачи, скиллы, корректировки)
- Чат (чипы департаментов, пузыри сообщений)
- Просмотр отчётов, статус моделей, экономика
- Настройки (профиль, голос, уведомления, безопасность)
- Наряды (workflow одобрения/отклонения), Архив (поиск + фильтры)

Дизайн: Cormorant Garamond + DM Sans + DM Mono, золотой акцент `#C9A84C`. Телефон (нижняя навигация) + планшет (сайдбар) + десктоп (3 колонки). Hash-маршрутизация SPA.

## Команды бота

| Команда | Описание |
|---|---|
| `/start` | Инициализация диалога |
| `/help` | Список команд |
| `/status` | Статус системы |
| `/osp`, `/lz`, `/dev`, ... | Обращение к департаменту |
| `/chain osp+legal` | Кросс-департаментная цепочка |
| `/voice on/off/male/female` | Настройки голоса |
| `/fix <текст>` | Сообщить об ошибке для обучения |
| `/good` | Записать положительный пример |
| `/learning stats` | Метрики обучения |
| `/debrief [dept]` | LLM-анализ корректировок |
| `/archive [id]` | Просмотр архивного отчёта |
| `/search <запрос>` | Полнотекстовый поиск |
| `/audit` | Журнал аудита |
| `/factory`, `/factory_review` | Пайплайн нарядов |
| `/admin status` | Статус Admin-агента |
| `/lockdown on/off` | Экстренная блокировка |
| `/remember key=value` | Постоянная память |
| `/memory` | Статус памяти (Металогос + FosvedMemory) |

## Структура проекта

```
.
├── app.mlog                  # Главный роутер (2575 строк, 68 команд)
├── bin/mlog                  # Metalogos v0.19.0 бинарник (x86-64, Rust)
├── llm_proxy.py              # LLM-прокси + API + SPA-сервер (5456 строк)
├── reverse_proxy.py          # Маршрутизатор запросов (151 строк)
├── entrypoint.sh             # Docker-запуск (3 процесса)
├── Dockerfile                # ubuntu:24.04
├── requirements.txt          # flask, requests, edge-tts
├── report_css.txt            # CSS для Mini App отчётов
├── file_cache.mlog           # Кэш профилей (транслитерированные ключи)
├── file_cache_skills.mlog    # Кэш скиллов
├── dept/
│   ├── yana.mlog             # Руководитель кабинета
│   ├── osp.mlog              # Стратегический анализ
│   ├── lz.mlog               # Лаборатория знаний (9-источник скан)
│   ├── expert.mlog           # Технический препаратор
│   ├── marketing.mlog        # Маркетинг
│   ├── finance.mlog          # Финансы
│   ├── legal.mlog            # Юрист
│   ├── dev.mlog              # Разработка
│   ├── design.mlog           # Дизайн
│   ├── qa.mlog               # Тестирование
│   ├── visual.mlog           # Визуализация
│   ├── engineering.mlog      # Инженерия
│   ├── kavalnya.mlog         # Методология
│   ├── admin.mlog            # Системный агент (ночной цикл)
│   ├── chain.mlog            # Кросс-департаментные цепочки
│   ├── scheduler.mlog        # 6 cron-планировщиков
│   ├── miniapp.mlog          # Форматирование отчётов + цвета
│   ├── utils.mlog            # Общие утилиты
│   └── context.mlog          # Управление контекстом
├── library/                  # 14 профилей департаментов (.md)
├── skills_index/             # 14 индексов скиллов (.txt)
├── config/
│   ├── priority_model.txt    # Глобальный приоритет модели
│   ├── priority_provider.txt # Глобальный приоритет провайдера
│   └── override_*.txt        # Переопределения по департаментам (14 файлов)
├── miniapp/                  # Telegram WebApp SPA
│   ├── index.html
│   ├── css/                  # vars, components, screens, responsive
│   └── js/
│       ├── app.js            # Роутер + инициализация
│       ├── api.js            # API-клиент
│       └── screens/          # 9 экранных модулей
└── data/                     # SQLite БД, runtime-данные
```

## База данных (22 таблицы)

`dialog_history`, `adapt_corrections`, `error_patterns`, `miniapp_responses`, `miniapp_notes`, `dept_metrics`, `token_usage`, `audit_log`, `system_settings`, `narads`, `debriefs`, `admin_reports`, `admin_findings`, `admin_proposals`, `knowledge_graph`, `knowledge_edges`, `channel_archive`, `factory_orders`, `lz_telegram_channels`, `lz_telegram_posts`, `lz_monitors`, `yana_events`

## Быстрый старт

```bash
git clone https://github.com/ShkodnikAI/FOSVED-office-v2.git
cd FOSVED-office-v2
```

Создать `.env`:
```
TELEGRAM_BOT_TOKEN=ваш_токен_бота
OWNER_TELEGRAM_ID=ваш_telegram_id
LOCKDOWN_PASSWORD=ваш_пароль
CRON_SECRET=ваш_секрет
ZAI_API_KEY=ваш_ключ
DEEPSEEK_API_KEY=ваш_ключ
# ... остальные ключи провайдеров
```

Docker:
```bash
docker build -t fosved .
docker run -p 10000:10000 --env-file .env fosved
```

## Правило деплой-целостности

> **app.mlog, bin/mlog, entrypoint.sh и env-переменные Render меняются только согласованным набором.** Частичный перенос (cherry-pick одного файла) запрещён — бинарник, mlog-грамматика и entrypoint-гейты образуют атомарный юнит. Нарушение этого правила привело к падению прода (85273f3 → db-роуты без fallback).

## Технологический стек

| Компонент | Технология |
|---|---|
| Ядро | Metalogos v0.19.0 (Rust DSL, встроенные функции, PDF, typed memory, reflex, mlogpkg) |
| Прокси-слой | Python 3.12 + Flask |
| База данных | SQLite |
| Голос STT | Whisper (Groq/OpenAI) |
| Голос TTS | edge-tts |
| LLM | 7 провайдеров с автоматическим фейловером |
| Контейнер | Docker (ubuntu:24.04) |
| Интерфейс | Telegram Bot API + WebApp SPA |

## Скиллы (FO-012)

Скиллы (248 каталогов, ~1100 файлов) **не хранятся в git** — каноничный снапшот живёт в GitHub Releases этого репозитория, манифест `skills-manifest.json` фиксирует тег, sha256 архива и список скиллов.

- При старте контейнера `entrypoint.sh` автоматически разворачивает `skills/` через `scripts/bootstrap_skills.sh` (нужен GitHub-токен в env: `GITHUB_TOKEN_SKILLS`, либо `GITHUB_TOKEN_METALOGOS`/`GITHUB_TOKEN`/`GH_TOKEN` с read-доступом к репо).
- Локальная разработка: распакуйте архив из последнего снапшота в корень репо или запустите `bash scripts/bootstrap_skills.sh`.
- Обновление снапшота после правки скиллов: `python3 scripts/skills_snapshot.py` → создать Release → залить ассет → закоммитить `skills-manifest.json`.
- Подробности: [docs/repo-hygiene.md](docs/repo-hygiene.md).

## Данные и восстановление

Вся память офиса хранится в двух SQLite базах в `data/`:
- `fosved.db` — 22 таблицы (dialog_history, knowledge_graph, audit_log, analysis, …)
- `memory.db` — память Яны и департаментов

### Схема бэкапа (FO-001)

Бэкапы создаются через `VACUUM INTO` (атомарный дамп SQLite) с проверкой целостности (`PRAGMA integrity_check`).

**Когда создаются бэкапы:**
- При каждом запуске контейнера (entrypoint.sh)
- По cron: `GET /cron/backup?secret=<CRON_SECRET>` (настраивается в Render cron)
- Вручную: `python3 scripts/backup_db.py backup`

**Где хранятся:** `data/backups/` (внутри контейнера). Для внешнего хранения установите `BACKUP_UPLOAD_CMD` — shell-команда, получающая `$FILE`.

**Удержание:** `BACKUP_RETENTION=7` — хранятся 7 последних копий каждой БД.

**Восстановление при старте:** entrypoint.sh проверяет `fosved.db` — если файл отсутствует или повреждён, автоматически восстанавливает из последнего бэкапа.

```bash
# Ручные команды
python3 scripts/backup_db.py backup          # создать бэкап
python3 scripts/backup_db.py backup --upload # бэкап + выгрузка
python3 scripts/backup_db.py restore --latest# восстановить из последнего
python3 scripts/backup_db.py list            # список бэкапов
python3 scripts/backup_db.py check           # проверка целостности
```

## Версии компонентов

| Компонент | Версия | Источник истины |
|---|---|---|
| Metalogos (bin/mlog) | 0.19.0 | `bin/mlog --version` |
| Metalogos grammar rev | 1 | `bin/mlog --version` |
| Python | 3.12 | Dockerfile `python3` |
| Flask | ≥3.0 | `requirements.txt` |
| SQLite | системная | ubuntu:24.04 |
| Docker base | ubuntu:24.04 | Dockerfile `FROM` |
| Node.js | системная | ubuntu:24.04 `npm` |
| edge-tts | ≥6.1 | `requirements.txt` |

> **Правило**: версия в Dockerfile-комменте и README всегда равна `bin/mlog --version`. CI-чек (FO-002) не даёт дрейфу вернуться.

## Качество

Стресс-тест: статический анализ кода по 17 группам.
Проверка синхронности зависимостей: `python3 scripts/audit_deps.py`

### LLM-трейсы (FO-004)

Каждый вызов LLM логируется в JSONL-файл (`data/traces/llm_YYYY-MM-DD.jsonl`) со схемой OTel GenAI:

| Поле | Описание |
|---|---|
| `trace_id` | Уникальный ID вызова |
| `gen_ai.system` | Провайдер (zai, deepseek, groq…) |
| `gen_ai.request.model` | Запрошенная модель |
| `gen_ai.usage.input_tokens` / `output_tokens` | Токены |
| `latency_ms` | Задержка от запроса до ответа |
| `dept` | Департамент-инициатор |
| `ok` | Успех/ошибка |

Ротация: файл > 10 МБ → `llm_YYYY-MM-DD_N.jsonl`. Хранение 7 дней. Сбой записи не ломает ответ.

API: `GET /traces?dept=&from=&to=&limit=&ok=` и `GET /trace-stats?from=&to=` (требуют Bearer).

## Лицензия

MIT