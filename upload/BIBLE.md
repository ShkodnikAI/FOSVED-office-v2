# FOSVED Office v2 — BIBLE (Единый источник истины)

> Читай ЭТОТ файл ПЕРЕД любыми изменениями. Новый агент должен уметь начать работу прочитав только этот файл + STATE.md.

---

## 0. КРИТИЧЕСКИЕ БАГИ (почему Яна не отвечает)

**Корневая причина**: код писался под предположения об API Metalogos, которые не совпали с реальным v0.7.10. Mlog крашился до вызова прокси.

| # | Баг | Кол-во мест | Статус |
|---|-----|-------------|--------|
| B1 | `return` НЕ ключевое слово — `return respond(...)` крашит | ~32 | Нужно проверить |
| B2 | `if cond then {` — `then` только для тернарников, блоки без него | ~25 | Нужно проверить |
| B3 | `data.message` — dot notation для JSON нет, нужен `json_get(data, "message")` | критично в webhook | Нужно проверить |
| B4 | `db {}` и `memory {}` — неправильный синтаксис конфигурации | в начале файла | Нужно проверить |
| B5 | `sqlite::memory:` — отдельная БД на каждое подключение, таблицы не видны между запросами | глобально | Нужно проверить |

**Действие для нового агента**: Прогнать `fast_check.sh` и проверить все 5 категорий багов в app.mlog. Если `return respond(...)` или `then {` присутствуют — исправить.

---

## 1. Архитектура

```
Telegram <-> Render (reverse_proxy.py :10000)
                |
         Python proxy (llm_proxy.py :4000)
                |
         Metalogos mlog (app.mlog :10001)
```

- **reverse_proxy.py** (106 строк) — единственная точка входа (порт 10000), маршрутизирует `/miniapp/*`, `/office-dashboard`, `/dept-dashboard/*` → Python:4000, всё остальное → Metalogos:10001
- **llm_proxy.py** (~5531 строк) — ТОЛЬКО stdlib + gTTS, все LLM-вызовы, TTS, дашборды, ~30 HTTP-эндпоинтов
- **app.mlog** (768 строк) — webhook обработчик, создание таблиц, маршрутизация команд, cron-эндпоинты
- **dept_dashboard.py** (367 строк) — HTML-дашборды для Mini App
- **entrypoint.sh** (86 строк) — health-check mlog (:10001) и proxy (:4000), fatal exit если mlog не стартовал

## 2. Git — SUBMODULE!

```bash
# ВСЕ git операции через:
git -C /home/z/my-project/fosved-v2 <command>
# cd НЕ сохраняется между bash-вызовами!
```

Репо: `https://github.com/ShkodnikAI/FOSVED-office-v2.git`
Последний commit: `2c76063` — NARAD-28: Admin system agent

## 3. Metalogos mlog v0.7.10 — КРИТИЧЕСКИ ВАЖНО

### 3.1. Версия

Бинарник в `bin/mlog` — **v0.7.10** (с 18.06.2026).
Проверка: `./bin/mlog --version`
Предыдущая версия v0.7.9 была до этого. v0.4.0 — древняя.

### 3.2. Что РАБОТАЕТ в v0.7.10 (проверено)

| Фича | Статус | Примечание |
|------|--------|------------|
| `respond()` как early return | OK | Прерывает выполнение handler-а |
| `respond_html("200", "body")` | OK | Отдаёт HTML |
| `render("TemplateName", args...)` | OK | Возвращает Html (opaque type) |
| `template Name(...) -> Html { return ... }` | OK | |
| `else if` chaining | OK | `if ... { } else if ... { } else { }` |
| `let mut x = ...; x = ...` | OK | Мутация в route handler-ах |
| `has_field(data, "key")` в `if` | OK | Возвращает 1/0, работает как truthy |
| `json_get(data, "key", "default")` | OK | 3-арг форма с дефолтом |
| `json_get(data, "a.b.c")` | OK | Dot-path для вложенных ключей |
| `let x = x + 1` внутри each | OK | Shadowing/аккумуляция |
| `db { url: "sqlite:data/fosved.db" }` | OK | Файловая БД, персистентна |
| `match ... then { } else { }` | OK | Pattern matching |
| `try { }` | OK | Error handling |
| `if cond then a else b` | OK | Тернарник (then ВАЖЕН здесь) |
| `return expr` | OK | `return` — ключевое слово (v0.7.10+?) |
| `kv_get()`, `kv_set()`, `kv_delete()` | OK | Key-value хранилище |

### 3.3. Forbidden patterns (НЕ работают / крашат)

| Паттерн | Почему крашит | Правильная замена |
|---------|--------------|-------------------|
| `json_get(data, "field") != ""` | Возвращает `Unit` для отсутствующего ключа; `Unit != String` = type mismatch crash | `has_field(data, "field")` для проверки; `json_get(data, "field", "default")` для значения |
| `if X != "" and X != "{}" {` | `and` не является ключевым словом — "undefined variable: and" | Вложенные `if` |
| `\u041f\u0430\u043d...` в строках | Unicode escapes ломают парсер | Реальные кириллические символы |
| `if cond then { block }` | `then` только для тернарников: `if cond then a else b` | Блоки: `if cond { ... }` |
| `data.message` (dot notation для JSON) | Нет dot notation для JSON | `json_get(data, "message")` |
| `let mut x = ...` + `x = ...` внутри `each` | "cannot assign to immutable variable" | `let x = x + ...` (shadowing) |
| `typeof()` | Не существует | Не использовать |
| `sqlite::memory:` | Отдельная БД на каждое подключение — таблицы не видны между запросами | `sqlite:data/fosved.db` |
| `env()` внутри `db {}` | Не поддерживается | Литеральная строка в db {} |
| `return respond(...)` (в v0.7.9) | `return` не было ключевым словом | Просто `respond(...)` — он прерывает сам |
| `db { url: env("...") }` | env() не работает в конфиге | `db { url: "sqlite:data/fosved.db" }` |
| `memory { ... }` | Не существует как конфигурация | `recall("key")` / `memorize("key", val)` |

**ВАЖНО**: Текущий код app.mlog был написан при переходе v0.7.9 → v0.7.10. Часть багов (B1-B5) из раздела 0 может всё ещё присутствовать. Запусти отладку!

### 3.4. Правильный API v0.7.10

```mlog
// === JSON parsing (POST body) ===
let data = json_body()
let field = json_get(data, "field")           // Unit если нет ключа!
let field = json_get(data, "field", "default") // с дефолтом — БЕЗОПАСНО
let nested = json_get(data, "a.b.c", "")       // dot-path для вложенных
let exists = has_field(data, "field")          // возвращает 1/0, можно в if напрямую

// === Respond — ПРЕРЫВАЕТ выполнение ===
respond("200 OK", "body")
respond_html("200", "<b>html</b>")

// === Тернарник (then ВАЖЕН) ===
let x = if len(s) > 4 then s else "default"

// === DB ===
db { url: "sqlite:data/fosved.db" }  // файловая БД, В НАЧАЛЕ ФАЙЛА
query("SELECT ...", [])              // параметризованный

// === Memory ===
recall("key")                       // "" если нет
memorize("key", value)              // 2 арга
memorize("key", value, ttl_hours)   // 3 арга с TTL
kv_get("key") / kv_set("key", val) / kv_delete("key")

// === HTTP ===
http_get(url)
http_post(url, body)  // content_type по умолчанию application/json
query_param("name")

// === Template + Render ===
template Page(t: String, b: String) -> Html {
  return "<html><body><h1>" + t + "</h1><p>" + b + "</p></body></html>"
}
let html = render("Page", "Title", "Body")
respond_html("200", to_string(html))

// === Scoping: let внутри блоков МОДИФИЦИРУЕТ внешнюю переменную ===
let x = "outer"
if true {
  let x = "inner"  // меняет внешний x!
}
// x == "inner"

// === each: let внутри each тоже модифицирует внешнюю переменную ===
let sum = 0.0
each i in [1.0, 2.0, 3.0] {
  let sum = sum + i  // аккумулирует!
}
// sum == 6.0

// === Env ===
let token = env("TELEGRAM_BOT_TOKEN")  // работает в коде, НЕ в db {}

// === String utils ===
starts_with(s, prefix)
contains(s, substr)
substring(s, start, end)
len(s)
replace(s, old, new)
to_string(x)  // конвертация в строку (важно для json_get результатов)
```

### 3.5. Критические правила для app.mlog

1. **ВСЕ `json_get` без default — потенциальный Unit** — используй 3-арг форму
2. **`respond()` ПРЕРЫВАЕТ выполнение** — можно использовать как early return
3. **`has_field()` возвращает 1/0** — можно в `if` напрямую без `== 1.0` (но == 1.0 тоже работает)
4. **`and`/`or` НЕ работают** — "undefined variable" — используй вложенные `if`
5. **CREATE TABLE IF NOT EXISTS** в каждом обработчике — безопасно
6. **`let mut` НЕ работает внутри `each`** — используй `let x = x + ...` (shadowing)
7. **`if cond { }` — БЕЗ `then`** — `then` только в тернарниках `if cond then a else b`
8. **`db { url: "..." }` — только литеральная строка**, без `env()`
9. **JSON: только `json_get()`** — dot notation `data.field` не работает

## 4. Python proxy (llm_proxy.py)

- ~5531 строк, ТОЛЬКО stdlib: urllib, http.server, sqlite3, json, re, html, io, time, threading, pathlib
- Единственная внешняя зависимость: gTTS (pip3 install gTTS)
- Своё хранилище в `report.db` (SQLite) — отдельные таблицы от mlog
- Порты: :4000 (HTTP), health на /health
- LLM Fallback chain: GLM-4.6 → GLM-5.1 → DeepSeek → Groq → Grok → Claude → OpenAI

### 4.1. Ключевые эндпоинты llm_proxy.py

| Эндпоинт | Метод | Описание |
|----------|-------|----------|
| `/health` | GET | Health check |
| `/route?chat_id=X` | POST | Маршрутизация в LLM (основной чат) |
| `/chain` | POST | Chain-of-thought через несколько отделов |
| `/context_cmd` | POST | Контекстные команды (/fix, /remember, /good, /learning, /debrief) |
| `/classify` | POST | Классификация запроса по отделам |
| `/transcribe` | POST | Speech-to-text (голосовые) |
| `/voice_cmd` | POST | Настройки голоса (on/off/male/female) |
| `/model` | POST | Смена модели |
| `/rate_cmd` | POST | Оценка ответа 1-5 |
| `/admin_cmd` | POST | Админ-команды |
| `/narad_action` | POST | Действия с нарядами (approve/reject) |
| `/prompt_fix` | POST | Применить auto-fix |
| `/scheduler` | POST | Планировщик (brief/digest/review) |
| `/factory` | POST | Фабрика нарядов |
| `/cost` | POST | Статистика токенов |
| `/budget` | POST | Бюджет |
| `/archive` | POST | Архивация |
| `/search` | POST | Поиск |
| `/lz_index` | POST | Индексация для LZ (forwarded posts) |
| `/office_action` | POST | Действия офис-панели |
| `/miniapp_action` | POST | Mini App действия |
| `/miniapp` | GET | Mini App HTML |

### 4.2. Окружение (env vars)

```
TELEGRAM_BOT_TOKEN        — токен бота
OWNER_TELEGRAM_ID         — ID владельца (только он может пользоваться)
DEEPSEEK_API_KEY          — DeepSeek
GROQ_API_KEY              — Groq
GLM_46_API_KEY            — GLM-4.6
GLM_51_API_KEY            — GLM-5.1
ANTHROPIC_API_KEY         — Claude
OPENAI_API_KEY            — OpenAI (если есть)
GROK_API_KEY              — Grok (если есть)
RENDER_SERVICE_URL        — URL сервиса на Render
LOCKDOWN_PASSWORD         — пароль для /lockdown
PORT                      — публичный порт (10000 по умолчанию)
```

## 5. Деплой на Render

- **Dockerfile** — `ubuntu:24.04` (нужен GLIBC 2.39 для mlog v0.7.10) + python3 + python3-pip + ffmpeg
- **Cache busting** — менять `LABEL build_id="..."` в Dockerfile
- **entrypoint.sh** — wget/curl health-check на :4000 и :10001, fatal exit если mlog не стартовал
- **Render URL**: `https://fosved-office-v2.onrender.com`
- **Webhook**: `https://fosved-office-v2.onrender.com/webhook/telegram`
- **Reset webhook**: GET `/reset-webhook` (автоматически устанавливает)
- **Диагностика**: GET `/diag-keys` — шлёт в Telegram длины всех API ключей

## 6. Структура файлов

```
fosved-v2/
  app.mlog              # 768 строк — основной mlog-сервер
  llm_proxy.py          # 5531 строк — Python proxy (LLM, TTS, дашборды)
  reverse_proxy.py      # 106 строк — входной reverse proxy
  dept_dashboard.py     # 367 строк — HTML-дашборды для Mini App
  entrypoint.sh         # 86 строк — Docker entrypoint с health-check
  Dockerfile            # ubuntu:24.04, GLIBC 2.39
  bin/mlog              # Metalogos binary v0.7.10 (12MB, через Git LFS)
  dept/                 # Mlog-файлы 13 отделов
    yana.mlog           # 5.4KB — Яна (основной бот)
    osp.mlog            # 12KB — ОСП (оперативный штаб)
    lz.mlog             # 9.1KB — ЛЗ (ландшафт знаний)
    expert.mlog         # 7.2KB — Эксперт
    dev.mlog            # 12KB — Разработка
    design.mlog         # 7.9KB — Дизайн
    qa.mlog             # 8.2KB — QA
    engineering.mlog    # 9.2KB — Инженерия
    marketing.mlog      # 8.4KB — Маркетинг
    legal.mlog          # 4.3KB — Право
    finance.mlog        # 8.2KB — Финансы
    visual.mlog         # 4.1KB — Визуал
    kavalnya.mlog       # 7.2KB — Кавальня (тренинг)
    chain.mlog          # 2.8KB — Chain-of-thought
    department.mlog     # 1KB — Базовый модуль отдела
    utils.mlog          # 3.2KB — Утилиты
    file_cache.mlog     # 7.9KB — Файловый кэш
    file_cache_skills.mlog # 26KB — Кэш скиллов
  library/              # Промпты-файлы (загружаются автоматически)
    yana.md             # 13KB — Промпт Яны
    admin.md            # 1.5KB — Промпт админа
    osp.md              # 15KB — Промпт ОСП
    lz.md               # 18KB — Промпт ЛЗ
    expert.md           # 19KB — Промпт эксперта
    dev.md              # 18KB — Промпт разработки
    design.md           # 15KB — Промпт дизайна
    qa.md               # 14KB — Промпт QA
    engineering.md      # 27KB — Промпт инженерии
    marketing.md        # 22KB — Промпт маркетинга
    finance.md          # 13KB — Промпт финансов
    legal.md            # 14KB — Промпт права
    visual.md           # 14KB — Промпт визуала
    kavalnya.md         # 19KB — Промпт кавальни
    METHODOLOGY-PATCH-001.md # 16KB — Методология
    yana-skills/        # 11 скиллов Яны (anticipation, crisis, delegation, domain-rapid-entry, health, companionship, memory, office-shielding, owner-state-reading, proxy-representation, pushback-with-loyalty)
  std/                  # Stdlib mlog (string, math, collections)
  data/                 # SQLite БД (создаётся в Dockerfile)
  miniapp_template.html # Шаблон миниаппа
  BIBLE.md              # ЭТОТ ФАЙЛ
  STATE.md              # Состояние проекта
  TODO.md               # Что сейчас в работе
  fast_check.sh         # Автопроверка перед коммитом
  README.md             # Полная документация проекта
  CHANGELOG.md          # История изменений
```

## 7. Метод бинарного поиска для mlog parse errors

Если `mlog serve app.mlog` падает с parse error:

```bash
# Найти строку с ошибкой:
head -n 100 app.mlog > /tmp/test.mlog
echo '  }' >> /tmp/test.mlog
mlog serve /tmp/test.mlog  # Если OK — ошибка после строки 100

# Сужать диапазон:
head -n 150 app.mlog > /tmp/test.mlog
echo '  }' >> /tmp/test.mlog
mlog serve /tmp/test.mlog  # Если краш — ошибка между 100 и 150
```

## 8. 14 отделов (текущий список)

| Отдел | Slug | Файл | Статус |
|-------|------|------|--------|
| Яна (основной бот) | yana | dept/yana.mlog | Активен |
| ОСП (оперативный штаб) | osp | dept/osp.mlog | Активен |
| ЛЗ (ландшафт знаний) | lz | dept/lz.mlog | Активен |
| Эксперт | expert | dept/expert.mlog | Активен |
| Разработка | dev | dept/dev.mlog | Активен |
| Дизайн | design | dept/design.mlog | Активен |
| QA | qa | dept/qa.mlog | Активен |
| Инженерия | eng | dept/engineering.mlog | Активен |
| Маркетинг | mkt | dept/marketing.mlog | Активен |
| Право | legal | dept/legal.mlog | Активен |
| Финансы | fin | dept/finance.mlog | Активен |
| Визуал | visual | dept/visual.mlog | Активен |
| Кавальня (тренинг) | kavalnya | dept/kavalnya.mlog | Активен |
| Админ (системный агент) | admin | library/admin.md | Нарядр 28 (новый) |

## 9. LLM Fallback Chain

```
GLM-4.6 (GLM_46_API_KEY) → GLM-5.1 (GLM_51_API_KEY) → DeepSeek (DEEPSEEK_API_KEY)
→ Groq (GROQ_API_KEY) → Grok (GROK_API_KEY) → Claude (ANTHROPIC_API_KEY)
→ OpenAI (OPENAI_API_KEY)
```