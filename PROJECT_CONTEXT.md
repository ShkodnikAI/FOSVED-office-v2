# FOSVED Office V2 — Project Context
# ============================================================
# Файл-контекст для AI-агента. Содержит всё необходимое для
# продолжения работы без объяснений. Читать ПЕРЕД любыми правками.
# ============================================================

## ЧТО ЭТО

AI-native офисная система на Metalogos (Rust DSL). 14 агентов-отделов,
каждый со своим профилем, скиллами, метриками. Управление через Telegram.
LLM-анализ через 7 провайдеров с фейловером. Mini App SPA для отчётов.

## АРХИТЕКТУРА (3 процесса)

```
Telegram → reverse_proxy.py (:10000)
                │
                ├──→ mlog serve app.mlog (:10001)   ← Metalogos DSL
                │       ├── dept/*.mlog (14 отделов)
                │       ├── file_cache.mlog (профили)
                │       └── SQLite (22 таблицы)
                │
                └──→ llm_proxy.py (:4000)            ← Flask
                        ├── 7 LLM провайдеров
                        ├── 11 API эндпоинтов
                        ├── TTS/STT
                        ├── /miniapp-spa (SPA)
                        └── archive, scheduler, learning
```

Startup order (entrypoint.sh): llm_proxy → mlog serve → reverse_proxy

## KEY PRINCIPLES

1. **Metalogos — ядро, Python — прослойка**
   - app.mlog (1302 строки) — маршрутизация команд, cron, lockdown
   - dept/*.mlog — логика каждого отдела (pattern-функции)
   - llm_proxy.py (2853 строк) — HTTP-прокси к LLM, Mini App, API
   - reverse_proxy.py (108 строк) — роутинг между mlog и llm_proxy

2. **Кириллица в file_cache — ТОЛЬКО транслитерация**
   - file_cache.mlog использует транслит: fc_library_osp, fc_library_yana
   - Настоящая кириллица в ключах ОСТАНОВИТ парсер Metalogos
   - DEPT_NAMES в llm_proxy.py — транслит, не кириллица

3. **Маршрутизация команд в app.mlog**
   - `if text == "/start"` — точное совпадение
   - `starts_with(text, "/osp")` — префикс
   - `send to proxy /chat` — запрос уходит в llm_proxy
   - llm_proxy определяет dept по slug: "/osp"→"osp", "/forge"→"kavalnya"

4. **Промпт отдела собирается в llm_proxy.py**
   - get_dept_prompt(dept) читает library/{dept}.md
   - + config/override_{dept}.txt (если есть)
   - + priority_model.txt / priority_provider.txt
   - Профиль отдела = system prompt для LLM

5. **Цвета отделов — в ДВУХ местах (синхронизировать!)**
   - llm_proxy.py: DEPT_COLORS (dict, hex)
   - dept/miniapp.mlog: DeptColorStart / DeptColorEnd (if-else)
   - Добавляя отдел → обновить ОБА места

## ФАЙЛОВАЯ СТРУКТУРА (ключевые файлы)

```
app.mlog                 # Главный роутер. import dept/*, InitDB, команды, cron
bin/mlog                 # Metalogos v0.7.10 бинарник (x86-64, Rust, 12MB)
llm_proxy.py             # Flask сервер. LLM-прокси, API, Mini App serving
reverse_proxy.py         # Роутер: LLM_ROUTES_PREFIXES → :4000, остальное → :10001
entrypoint.sh            # Старт 3 процессов с healthcheck
Dockerfile               # ubuntu:24.04, COPY . ., EXPOSE 10000
requirements.txt         # flask, requests, edge-tts
report_css.txt           # CSS для Mini App отчётов (inject в HTML)
file_cache.mlog          # Кэш профилей отделов (транслит!)
file_cache_skills.mlog   # Кэш скиллов отделов

dept/
  yana.mlog              # Шеф кабинета, маршрутизация, voice
  osp.mlog               # Стратегический анализ (24 скилла)
  lz.mlog                # Лаборатория знаний, 9-источник scan, Apodex
  expert.mlog            # Технический препаратор
  marketing.mlog         # Маркетинг
  finance.mlog           # Финансы
  legal.mlog             # Юрист
  dev.mlog               # Разработка (20 скиллов)
  design.mlog            # UI/UX дизайн
  qa.mlog                # Тестирование
  visual.mlog            # Визуализация
  engineering.mlog       # Инженерия
  kavalnya.mlog          # Методология
  admin.mlog             # Системный агент, night cycle (600 строк)
  chain.mlog             # Cross-dept цепочки (3 департамента макс)
  scheduler.mlog         # 6 cron функций (morning/evening/weekly/monthly/control/night)
  miniapp.mlog           # BuildReport, SendReport, FormatReportBody, dept цвета
  utils.mlog             # 13 shared patterns (AuditLog, StripHtml, DeptHashtags...)
  context.mlog           # Контекст диалога

library/                 # 14 .md профилей отделов (system prompt контент)
skills_index/            # 14 .txt файлов (список скиллов каждого отдела)
config/
  priority_model.txt     # Модель по умолчанию (сейчас: glm-4.6)
  priority_provider.txt  # Провайдер по умолчанию (сейчас: zai)
  override_{dept}.txt    # Переопределения модели/провайдера на отдел (14 файлов)

miniapp/                 # Telegram WebApp SPA (9 экранов)
  index.html             # Точка входа, hash routing
  css/vars.css           # CSS переменные (Cormorant Garamond, DM Sans, gold #C9A84C)
  css/components.css     # Компоненты
  css/screens.css        # Экраны
  css/responsive.css     # Phone/tablet/desktop брейкпоинты
  js/app.js              # Router, Telegram WebApp init
  js/api.js              # Fetch к /api/* эндпоинтам
  js/screens/            # 9 модулей: dashboard, dept, chat, report, models, economics, settings, narads, archive
```

## LLM ПРОВАЙДЕРЫ (7)

| Провайдер | URL | Timeout | Env Key |
|-----------|-----|---------|---------|
| zai | api.zai.chat/v1/chat/completions | 120s | ZAI_API_KEY |
| deepseek | api.deepseek.com/v1/chat/completions | 120s | DEEPSEEK_API_KEY |
| groq | api.groq.com/openai/v1/chat/completions | 120s | GROQ_API_KEY |
| grok | api.x.ai/v1/chat/completions | 120s | GROK_API_KEY |
| anthropic | api.anthropic.com/v1/messages | 120s | ANTHROPIC_API_KEY |
| openai | api.openai.com/v1/chat/completions | 120s | OPENAI_API_KEY |
| apodex | api.apodex.ai/v1/chat/completions | 300s | APODEX_API_KEY |

Формат: zai/deepseek/groq/grok/openai/apodex = OpenAI-compatible, anthropic = свой.
Фейловер: по списку PROVIDERS по порядку, при timeout/error → следующий.

## ENV ПЕРЕМЕННЫЕ

```
TELEGRAM_BOT_TOKEN       # Обязательный
OWNER_TELEGRAM_ID        # Обязательный (для admin команд)
LOCKDOWN_PASSWORD        # Пароль для /lockdown
CRON_SECRET              # Секрет для cron эндпоинтов
PORT                     # Порт reverse_proxy (default 10000)
PORT_PROXY               # Порт llm_proxy (default 4000)
DATABASE_PATH            # Путь к SQLite (default ./data)
TELEGRAM_ARCHIVE_CHANNEL_ID  # Канал для архива
WHISPER_API_KEY          # Для STT
WHISPER_PROVIDER         # groq или openai
ZAI_API_KEY              # LLM
DEEPSEEK_API_KEY         # LLM
GROQ_API_KEY             # LLM
GROK_API_KEY             # LLM
ANTHROPIC_API_KEY        # LLM
OPENAI_API_KEY           # LLM
APODEX_API_KEY           # LLM
```

## DB ТАБЛИЦЫ (21)

dialog_history, adapt_corrections, error_patterns, miniapp_responses,
miniapp_notes, dept_metrics, token_usage, audit_log, system_settings,
narads, admin_findings, admin_proposals, knowledge_nodes, knowledge_edges,
lz_channels, lz_monitor, learning_stats, control_watches, archive,
factory_steps, factory_deliverables

## ОТДЕЛЫ: SLUG МАППИНГ

| Команда | Slug | Файл | Цвет (start→end) | Акцент |
|---------|------|------|-------------------|--------|
| /yana | yana | dept/yana.mlog | #293133→#1a2024 | #3d4a4d |
| /osp | osp | dept/osp.mlog | #b91c1c→#7f1d1d | #dc2626 |
| /lz | lz | dept/lz.mlog | #0e7490→#164e63 | #0891b2 |
| /expert | expert | dept/expert.mlog | #3730a3→#1e1b4b | #4f46e5 |
| /marketing | marketing | dept/marketing.mlog | #c2410c→#7c2d12 | #ea580c |
| /finance | finance | dept/finance.mlog | #15803d→#14532d | #16a34a |
| /legal | legal | dept/legal.mlog | #475569→#1e293b | #64748b |
| /dev | dev | dept/dev.mlog | #1d4ed8→#1e3a8a | #2563eb |
| /design | design | dept/design.mlog | #be185d→#831843 | #ec4899 |
| /qa | qa | dept/qa.mlog | #4d7c0f→#365314 | #65a30d |
| /visual | visual | dept/visual.mlog | #7e22ce→#581c87 | #a855f7 |
| /engineering | engineering | dept/engineering.mlog | #44403c→#292524 | #78716c |
| /forge | kavalnya | dept/kavalnya.mlog | #b45309→#78350f | #d97706 |
| /admin | admin | dept/admin.mlog | #1e40af→#1e3a5f | #3b82f6 |

## REVERSE PROXY РОУТИНГ

llm_proxy (:4000) обрабатывает:
/miniapp/, /miniapp-spa/, /api/, /archive/, /scheduler/, /learning/,
/search, /tts, /stt, /audit/, /voice-set, /dept-dashboard/, /office-dashboard

mlog (:10001) обрабатывает:
/webhook/, /cron/, /status, /dept/, /office, /health, /

## ПОТОК ДАННЫХ (типичный запрос)

1. User → Telegram → /webhook/ → reverse_proxy → mlog (:10001)
2. app.mlog парсит команду, определяет dept
3. app.mlog → proxy /chat с dept, query, chat_id → llm_proxy (:4000)
4. llm_proxy собирает промпт: library/{dept}.md + override + приоритеты
5. llm_proxy → LLM API (фейловер по провайдерам)
6. llm_proxy → proxy /report с ответом → mlog (:10001)
7. app.mlog → dept/miniapp.mlog BuildReport() → HTML
8. app.mlog → Telegram sendMessage (Mini App кнопка или текст)

## ЧАСТЫЕ ПРАВКИ И ГДЕ ИХ ДЕЛАТЬ

### Добавить команду бота
→ app.mlog: новый `if text ==` или `starts_with` блок

### Добавить LLM эндпоинт
→ llm_proxy.py: новый @app.post("/...")

### Добавить новый отдел
1. dept/{name}.mlog — handler (pattern Handle{Name})
2. library/{name}.md — профиль (system prompt)
3. skills_index/{name}.txt — скиллы
4. config/override_{name}.txt — переопределения
5. app.mlog — import + slug command + SendReport routing
6. llm_proxy.py — DEPT_COLORS + DEPT_NAMES + COMMAND_DEPT slug mapping
7. dept/miniapp.mlog — DeptColorStart/End + DeptName
8. reverse_proxy.py — если нужны новые route prefix

### Изменить цвет отдела
→ llm_proxy.py DEPT_COLORS И dept/miniapp.mlog DeptColorStart/DeptColorEnd

### Добавить cron задачу
→ app.mlog (route + CRON_SECRET) + dept/scheduler.mlog (логика) + llm_proxy.py (эндпоинт)

## KNOWN GOTCHAS

1. **Кириллица в file_cache.mlog** — ТОЛЬКО транслит, иначе парсер падает
2. **Bin/mlog в .gitignore** — был удалён из ignore для коммита бинарника
3. **Slug /forge → kavalnya** — неочевидное маппирование
4. **Apodex timeout 300s** — остальные 120s
5. **DEPT_COLORS в двух местах** — рассинхрон = баг
6. **Mini App URL: /miniapp-spa** — не /miniapp (там 301 редирект)
7. **/miniapp/<id>** — отдельный роут для просмотра сохранённых отчётов
8. **StripHtml в utils.mlog** — 16 замен HTML тегов + Apodex badges
9. **Chain макс 3 отдела** — ограничение в dept/chain.mlog
10. **Stress test** — scripts/stress_test.py (167 проверок, 17 групп)

## МЕТРИКИ ПРОЕКТА

- Файлов: 101 | Папок: 17
- Строк кода: ~13 200 (без библиотек/skills)
  - .mlog: 3 038 | .py: 2 599 | .js: 1 996 | .css: 1 414 | .html: 607 | .md: 3 565
- 14 отделов | 176 скиллов | 68 команд | 11 cron-роутов
- 7 LLM провайдеров | 22 DB таблицы
- Бинарник: Metalogos v0.7.10 (12MB, x86-64, 113 builtins)