# ПЛАН ПЕРЕСБОРКИ FOSVED OFFICE V2

**Ситуация:** репо очищено. Metalogos готов (66 builtins). Все спецификации, профили, скиллы есть. Нужно пересобрать за одну сессию.

**Стратегия:** 4 мега-наряда вместо 30 мелких. Каждый — commit + push + verify. Без возвратов.

---

## ПРИКРЕПИТЬ АГЕНТУ

| # | Файл | Зачем |
|---|---|---|
| 1 | **METALOGOS_REFERENCE.md** | Справочник языка (builtins, синтаксис, типы) |
| 2 | **library/admin.md** | Профиль Админа |
| 3 | Все **library/*.md** (13 файлов) | Профили отделов — если есть. Если нет — агент сгенерирует из спеки |
| 4 | Все **skills/fosved/** (153 SKILL.md) | Скиллы — если есть. Если нет — агент создаст stubs |
| 5 | **fosved-screens.html** | Референс дизайна Mini App |
| 6 | Этот документ | План пересборки |

---

## ХРОНОЛОГИЯ

```
МЕГА-1 (60 мин): Скелет + 13 отделов + маршрутизация + память
    → commit → push → verify (бот отвечает в Telegram)

МЕГА-2 (45 мин): Mini App + отчёты + модели + экономика
    → commit → push → verify (Mini App открывается)

МЕГА-3 (45 мин): Chain + голос + scheduler + learning + audit + архив
    → commit → push → verify (cron + /fix + /audit работают)

МЕГА-4 (30 мин): Админ + фабрика + ЛЗ Deep Scan + Apodex
    → commit → push → verify (ночной цикл + /admin)

ТЕСТ (20 мин): Стресс-тест 85 проверок
    → финальный отчёт

ИТОГО: ~3.5 часа
```

---

## АРХИТЕКТУРА (одна версия, без дублей)

```
Render (порт 10000)
    │
    ├── reverse_proxy.py (порт 10000) — маршрутизатор
    │   ├── /webhook/telegram → Metalogos (10001)
    │   ├── /cron/* → Metalogos (10001)
    │   ├── /miniapp/* → LLM proxy (4000)
    │   ├── /dept-dashboard/* → LLM proxy (4000)
    │   ├── /office-dashboard → LLM proxy (4000)
    │   └── всё остальное → Metalogos (10001)
    │
    ├── mlog serve app.mlog (порт 10001) — ядро
    │   ├── webhook handler
    │   ├── 13 department dispatchers (dept/*.mlog)
    │   ├── context manager
    │   ├── memory (SQLite)
    │   └── cron endpoints
    │
    └── llm_proxy.py (порт 4000) — LLM + Mini App
        ├── 7 LLM провайдеров (failover)
        ├── Mini App HTML генерация
        ├── Department dashboards
        └── Office panel
```

---

## ПОЛНЫЙ СПИСОК ФАЙЛОВ (итоговый)

```
fosved-office-v2/
│
├── bin/mlog                          # Metalogos binary (66 builtins, ~12MB)
├── Dockerfile                        # ubuntu:24.04 + python3 + edge-tts + git
├── entrypoint.sh                     # Запуск 3 процессов
├── reverse_proxy.py                  # HTTP router (порт 10000)
├── llm_proxy.py                      # LLM + Mini App (порт 4000)
├── dept_dashboard.py                 # HTML генерация дашбордов
├── requirements.txt                  # Python deps
├── .gitignore
├── README.md
│
├── app.mlog                          # Главный файл (~1500 строк)
├── dept/
│   ├── yana.mlog                     # Яна dispatcher
│   ├── osp.mlog                      # ОСП dispatcher
│   ├── lz.mlog                       # ЛЗ dispatcher
│   ├── expert.mlog
│   ├── marketing.mlog
│   ├── finance.mlog
│   ├── legal.mlog
│   ├── dev.mlog
│   ├── design.mlog
│   ├── qa.mlog
│   ├── visual.mlog
│   ├── engineering.mlog
│   ├── kavalnya.mlog
│   ├── admin.mlog                    # Админ dispatcher
│   ├── context.mlog                  # Контекст-менеджер
│   ├── utils.mlog                    # Утилиты (send_telegram, AuditLog...)
│   ├── miniapp.mlog                  # BuildReport, FormatReportBody
│   ├── scheduler.mlog                # MorningBrief, EveningSummary...
│   └── chain.mlog                    # ExecuteChain, DetectChain
│
├── library/                          # Профили отделов (13 + admin)
│   ├── yana.md
│   ├── osp.md
│   ├── lz.md
│   ├── expert.md
│   ├── marketing.md
│   ├── finance.md
│   ├── legal.md
│   ├── dev.md
│   ├── design.md
│   ├── qa.md
│   ├── visual.md
│   ├── engineering.md
│   ├── kavalnya.md
│   └── admin.md
│
├── skills/fosved/                    # 153 SKILL.md файлов
│   ├── spd/ (24 скилла ОСП)
│   ├── lz/ (12)
│   ├── expert/ (12)
│   ├── marketing/ (11)
│   ├── finance/ (9)
│   ├── legal/ (10)
│   ├── dev/ (20)
│   ├── design/ (12)
│   ├── qa/ (11)
│   ├── visual/ (5)
│   ├── engineering/ (12)
│   └── kavalnya/ (8)
│
├── skills_index/                     # Индексы скиллов (13 файлов)
│   ├── osp.txt
│   ├── lz.txt
│   └── ...
│
├── config/                           # Конфигурация моделей
│   ├── priority_provider.txt         # "zai"
│   ├── priority_model.txt            # "glm-4.6"
│   └── override_*.txt (14 файлов)    # пустые
│
├── file_cache.mlog                   # Library profiles as patterns
├── file_cache_skills.mlog            # Skills as patterns
├── report_css.txt                    # CSS для Mini App отчётов
│
├── data/                             # SQLite (создаётся runtime)
│   └── .gitkeep
│
└── miniapp/                          # SPA Mini App (Наряд 29 — опционально)
    ├── index.html
    ├── css/
    └── js/
```

---

## ENV VARS (Render)

```
# Обязательные
TELEGRAM_BOT_TOKEN=...
OWNER_TELEGRAM_ID=2044005421
LOCKDOWN_PASSWORD=...
CRON_SECRET=...
PORT=10000

# LLM (минимум один)
ZAI_API_KEY=...
ANTHROPIC_API_KEY=...

# LLM (опциональные)
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...
GROK_API_KEY=...
OPENAI_API_KEY=...
APODEX_API_KEY=...

# Голос (опционально)
WHISPER_API_KEY=...
WHISPER_PROVIDER=groq

# Deep Scan (опционально)
SERPAPI_KEY=...
YOUTUBE_API_KEY=...

# DevOps (опционально)
GITHUB_TOKEN=...
GITHUB_REPO=ShkodnikAI/FOSVED-office-v2

# Архив
TELEGRAM_ARCHIVE_CHANNEL_ID=-1004290868173

# Системные
RENDER_URL=https://fosved-office-v2.onrender.com
DATABASE_PATH=./data
```

---

## УТВЕРЖДЁННАЯ ПАЛИТРА

| Отдел | Slug | Start | End | Accent |
|---|---|---|---|---|
| Яна | yana | #293133 | #1a2024 | #3d4a4d |
| ОСП | osp | #b91c1c | #7f1d1d | #dc2626 |
| ЛЗ | lz | #0e7490 | #164e63 | #0891b2 |
| Эксперт | expert | #3730a3 | #1e1b4b | #4f46e5 |
| Маркетинг | marketing | #c2410c | #7c2d12 | #ea580c |
| Финансы | finance | #15803d | #14532d | #16a34a |
| Юрист | legal | #475569 | #1e293b | #64748b |
| Dev | dev | #1d4ed8 | #1e3a8a | #2563eb |
| Design | design | #be185d | #831843 | #ec4899 |
| QA | qa | #4d7c0f | #365314 | #65a30d |
| Visual | visual | #7e22ce | #581c87 | #a855f7 |
| Engineering | engineering | #44403c | #292524 | #78716c |
| Кавальня | kavalnya | #b45309 | #78350f | #d97706 |
| Админ | admin | #1e40af | #1e3a5f | #3b82f6 |

Шрифт на градиентах: #ffffff. Бейджи: ФАКТ #16a34a, ИНТЕРПРЕТАЦИЯ #2563eb, СПЕКУЛЯЦИЯ #ca8a04.

---

## ПОЛНЫЙ СПИСОК ТАБЛИЦ БД

```sql
-- Память
dialog_history (id, chat_id, role, dept, content, created_at)
adapt_corrections (id, dept, original_query, original_response, correction, created_at)
error_patterns (id, dept, error_type, query_text, correction, created_at)

-- Отчёты
miniapp_responses (id TEXT PK, dept, title, query, raw_text, html, confidence, created_at)
miniapp_notes (id, doc_id, note_text, created_at)

-- Метрики
dept_metrics (id, dept, metric_name, metric_value, period, created_at)
token_usage (id, dept, provider, model, input_tokens, output_tokens, cost_usd, request_type, created_at)

-- Безопасность
audit_log (id, timestamp, action, actor, dept, details, status)

-- DevOps
narads (id TEXT PK, title, description, requested_by, changed_files, risk_level, status, created_at, approved_at, executed_at, result)
debriefs (id, dept, period, content, actions_taken, created_at)

-- Админ
admin_reports (id, type, content, duration_sec, created_at)
admin_findings (id, severity, file_path, issue, fix_suggestion, status, created_at)
admin_proposals (id, content, status, narad_id, created_at)
knowledge_graph (id, node_type, node_name, file_path, line_start, line_end, description, updated_at)
knowledge_edges (id, source_name, target_name, edge_type, file_path, updated_at)

-- Архив
channel_archive (id, doc_id, dept, title, channel_message_id, archived_at)

-- Фабрика
factory_orders (id TEXT PK, client_name, status, requirements, departments, branding, llm_config, repo_url, render_url, created_at, completed_at)

-- ЛЗ
lz_telegram_channels (id, channel_id, channel_name, category, added_at)
lz_telegram_posts (id, channel_id, channel_name, text, date, scanned_at)
lz_monitors (id, query, sources, frequency, last_scan, created_at)

-- Система
system_settings (key TEXT PK, value TEXT)
```

---

## ПОЛНЫЙ СПИСОК КОМАНД (98)

### Общие
```
/start /help /status /office /lockdown <pwd> /unlock <pwd>
```

### Отделы (13 slug + расширенные)
```
/yana /osp /lz /expert /marketing /finance /legal
/dev /design /qa /visual /engineering /forge
/analyze /scan /deep /quickanalyze /wargame     (ОСП)
/market-research /segment /competitors /campaign  (Маркетинг)
/calc /simulate                                   (Engineering)
```

### ОСП специальные
```
/osp deep <запрос>     /osp full <запрос>
```

### ЛЗ специальные
```
/lz scan <запрос>   /lz deep <запрос>   /lz all <запрос>
/lz compare <запрос>
/lz_channel add <канал>   /lz_channels   /lz_monitor <тема>
```

### Модели
```
/model   /model set <p> <m>   /model <dept> <p> <m>
/model reset   /model list
```

### Контекст и обучение
```
/fix <текст>   /good   /rate N   /remember <факт>
/learning   /debrief <dept>
```

### Экономика
```
/cost   /cost dept <slug>   /budget   /budget N
```

### Отделы UI
```
/dept   /dept <slug>
```

### Составные
```
/chain dept1+dept2 <запрос>
```

### Голос
```
/voice on   /voice off   /voice male   /voice female
```

### Scheduler
```
/brief   /digest   /review
```

### Архив
```
/archive   /archive <doc_id>   /autoarchive on/off   /search <запрос>
```

### Админ
```
/admin   /admin status   /admin build <задача>   /admin fix <баг>
/admin analyze   /admin graph   /admin impact <файл>
/admin proposals   /admin narads   /admin rollback <id>
/admin report   /admin health
```

### Наряды
```
/narads   /rollback <id>   /build <задача>
```

### Фабрика
```
/factory   /factory_review <id>   /factory_deploy <id>
/factory_deliver <id>   /factory_list
```

### Audit
```
/audit
```

---

## 4 МЕГА-НАРЯДА

### МЕГА-1: ФУНДАМЕНТ

**Что создать:**
1. Dockerfile (ubuntu:24.04, python3, edge-tts, git, mlog)
2. entrypoint.sh (запуск 3 процессов)
3. reverse_proxy.py (порт 10000, маршрутизация)
4. llm_proxy.py (7 провайдеров, failover, LLM вызовы, Mini App HTML)
5. requirements.txt
6. app.mlog (webhook handler, lockdown, routing 13 отделов + русские keywords, все команды, все cron endpoints, init_db со всеми таблицами)
7. dept/*.mlog (14 dispatchers: 13 отделов + admin)
8. dept/utils.mlog (AuditLog, send_telegram helpers)
9. dept/context.mlog (BuildContext, SelectSkillsByKeywords, CompressDialog)
10. library/*.md (14 профилей: 13 + admin)
11. config/ (priority_provider, priority_model, 14 override files)
12. skills_index/*.txt (13 файлов)
13. file_cache.mlog + file_cache_skills.mlog
14. report_css.txt
15. .gitignore, README.md
16. data/.gitkeep
17. bin/mlog (скопировать из Metalogos)

**Проверка:**
```
GET / → alive
POST /webhook/telegram → 200
/status → 13 отделов
/osp test → LLM ответ
/lockdown → блокировка
/unlock → разблокировка
Чужой user_id → игнор
```

**Commit:** `MEGA-1: Foundation — all departments, routing, memory, LLM, lockdown`

### МЕГА-2: MINI APP + МОДЕЛИ + ЭКОНОМИКА

**Что создать/обновить:**
1. dept/miniapp.mlog (BuildReport, FormatReportBody, SendReport, DeptColors)
2. dept_dashboard.py (HTML генерация)
3. Маршруты: /miniapp/{id}, /dept/<slug>, /office-dashboard
4. /model команды в app.mlog
5. TrackedLLM обёртка
6. /cost, /budget, /rate, /dept команды
7. Inline-кнопки (web_app URL)
8. Action bar (8 кнопок + ОСП-специфичные: журналист, погружение, контроль, контр-прогноз)
9. Бейджи ФАКТ/ИНТЕРПРЕТАЦИЯ/СПЕКУЛЯЦИЯ в HTML

**Проверка:**
```
/dept osp → кнопка → HTML дашборд
/model → настройки
/cost → расход
/rate 4 → сохранено
GET /dept-dashboard/osp → HTML 200
GET /office-dashboard → HTML 200
```

**Commit:** `MEGA-2: Mini App, reports, models, economics, dashboards`

### МЕГА-3: CHAIN + ГОЛОС + SCHEDULER + LEARNING + AUDIT + АРХИВ

**Что создать/обновить:**
1. dept/chain.mlog (ExecuteChain)
2. /chain команда в app.mlog
3. Голос: обработка voice messages (whisper_transcribe), TTS (tts_send), /voice команды
4. dept/scheduler.mlog (MorningBrief, EveningSummary, WeeklyDigest, MonthlyReview, ControlCheck, YanaSelfLearn)
5. 6 cron endpoints с CRON_SECRET
6. /fix с LLM-классификацией, /good, /learning, /debrief
7. MonthlyDebrief, ProposePromptFix, QuarterlyAudit
8. /audit команда
9. PublishToArchive, StripHtml, DeptHashtags
10. /archive, /autoarchive, /search
11. PublishDailyDigest в EveningSummary

**Проверка:**
```
/chain osp+legal test → 200
/voice on → ok
/brief → brief
/fix test → коррекция + классификация
/good → положительный пример
/audit → последние 20
/archive → публикация
/search test → поиск
GET /cron/morning?secret=X → 200
GET /cron/morning → 403
```

**Commit:** `MEGA-3: Chain, voice, scheduler, learning loop, audit, archive`

### МЕГА-4: АДМИН + ФАБРИКА + ЛЗ DEEP SCAN + APODEX

**Что создать/обновить:**
1. dept/admin.mlog (все /admin команды)
2. Ночной цикл (/cron/night): BuildKnowledgeGraph, AdminCodeAudit, AdminMetricsAnalysis, AdminAutoFix, AdminProposals
3. Knowledge graph таблицы + patterns
4. ImpactAnalysis, FindOrphans
5. /factory (7-шаговый опрос), HandleFactoryStep, BuildClientOffice
6. /factory_review, /factory_deploy, /factory_deliver, /factory_list
7. ЛЗ Deep Scan (9 источников): ScanWeb, ScanYouTube, ScanReddit, ScanScience, ScanGitHub, ScanSocial, ScanDarknet, ScanTelegram, DeepScan
8. Apodex как 7-й провайдер, /lz deep, /lz compare
9. /lz_channel, /lz_channels, /lz_monitor

**Проверка:**
```
/admin → справка
/admin status → статус
/admin build test → наряд
/factory → начало опроса
/lz deep test → 200 (Apodex)
GET /cron/night?secret=X → 200
```

**Commit:** `MEGA-4: Admin agent, factory, LZ deep scan, Apodex`

### ФИНАЛ: СТРЕСС-ТЕСТ

85 тестов из Наряда №26. Цель: 80+/85.

---

## КРИТИЧЕСКИЕ УРОКИ ИЗ ПРОШЛЫХ ПОПЫТОК

1. **ОДНА ВЕРСИЯ.** Никаких ROOT vs fosved-v2. Один app.mlog, один Dockerfile, один деплой.
2. **Python proxy обязателен.** Metalogos не может всё — LLM failover, HTML генерация, rate limiting делаются в proxy.
3. **Три процесса.** entrypoint.sh запускает proxy(4000) → mlog(10001) → reverse_proxy(10000). Порядок важен.
4. **file_cache.mlog — транслитерация.** Парсер mlog может крашиться на кириллице в строках. Все library/*.md и skills преобразуются в ASCII через транслитерацию.
5. **DeptName/DeptColor — НЕ через write_file.** Использовать if-else expression или make_list. Иначе race condition.
6. **CRON_SECRET на всех /cron/*.** Иначе любой может триггерить.
7. **Dockerfile: ubuntu:24.04** (не debian:bookworm). Нужен GLIBC 2.39 для mlog binary.
8. **report_css.txt должен существовать.** Иначе BuildReport падает.
9. **Все 13 slug-команд (/osp, /marketing, /engineering...) + русские keywords.**
10. **Timeout LLM: 120 сек** минимум. Для Apodex: 300 сек.
