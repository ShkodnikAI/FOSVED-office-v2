# Дорожная карта миграции офиса на Металогос

> Версия: 1.0 | Дата: 2026-08-15
> Принцип: **мигрируем только то, что не ухудшает функционал**

---

## Архитектурный контекст

### Текущее состояние
```
Telegram → Python (llm_proxy.py :4000) ←→ mlog (app.mlog :10001)
                   ↓                         ↓
              LLM с circuit breaker     SQLite, routing,
              combo chains, TTS/STT     orchestration,
              image gen, OSINT          scheduler patterns
```

- **mlog** (2779 строк в app.mlog + ~2000 в dept/*.mlog) — маршрутизация, оркестрация, контекст, диспетчеры отделов, шаблоны шедулеров
- **Python** (6061 строк в llm_proxy.py) — LLM-вызовы с circuit breaker, Telegram webhook, TTS/STT, шедулеры (execution), дашборды, память, обучение, поиск, новости, OSINT, генерация изображений, Tavily

### Ключевой паттерн делегирования
```
mlog pattern → http_post("http://127.0.0.1:4000/endpoint", payload) → Python
```

mlog собирает данные, строит контекст, затем **делегирует** выполнение Python для всего, что требует LLM, Telegram API, или Python-специфичных библиотек.

### Возможности mlog (v0.12.0 builtins)
✅ `call_llm` — нативный LLM-вызов (но БЕЗ circuit breaker, combo chains, token compression)
✅ `http_post`, `http_get` — HTTP-клиент
✅ `json_encode`, `json_get`, `parse_json` — JSON
✅ `db_execute`, `db_insert`, `query` — SQLite (параметризованные запросы)
✅ `kv_get`, `kv_set` — KV-хранилище
✅ `read_file`, `write_file`, `list_dir` — файловый I/O
✅ `env()` — переменные окружения
✅ `send_message` — Telegram sendMessage (встроенный)
✅ `each`, `while`, `match`, `if/else` — управление
✅ `try` — обработка ошибок
✅ Regex (p54_regex) — встроенный с Наряд #54
✅ Crypto, auth, templates

### Ограничения mlog
❌ Нет circuit breaker / combo chains для LLM
❌ Нет TTS/STT (edge-tts, whisper — Python-only)
❌ Нет генерации изображений
❌ Нет RSS/GDELT парсинга (нет feedparser)
❌ Нет OSINT (aliens-eye — Python-only)
❌ Нет document extraction (pymupdf, openpyxl)
❌ Нет auto-enricher (сложный Markdown→HTML с regex)
❌ Нет FosvedMemory (typed memory с temporal decay)
❌ MarkdownV2 escaping — упрощённая версия (без regex code-span awareness)

---

## Дорожная карта

### Приоритет = влияние × лёгкость × снижение сложности

| # | Компонент | Приоритет | Сложность | Статус | Что меняется |
|---|-----------|-----------|-----------|--------|--------------|
| 1 | SearchArchive — поиск по архиву | **P0** | Лёгкая | ✅ DONE | Python `/search` → mlog `query()` |
| 2 | PublishToArchive — публикация в канал | **P0** | Лёгкая | ✅ DONE | Python `/archive/publish` → mlog native |
| 3 | Learning ops — ClassifyCorrection, RecordPositive, Stats, Debrief | **P1** | Лёгкая | ✅ DONE | 4 Python endpoints → mlog patterns |
| 4 | EveningSummary — вечерняя сводка | **P1** | Лёгкая | ✅ DONE | Python → mlog native `call_llm` + `SendTelegramReplyMDV2` |
| 5 | WeeklyDigest — недельный дайджест | **P1** | Лёгкая | ✅ DONE | Аналогично EveningSummary |
| 6 | MonthlyReview — месячный обзор | **P1** | Средняя | ✅ DONE | Аналогично, + 12 dept each |
| 7 | ControlCheck — проверка прогнозов | **P1** | Средняя | ✅ DONE | mlog native call_llm |
| 8 | YanaSelfLearn — самообучение Яны | **P1** | Лёгкая | ✅ DONE | mlog native call_llm |
| 9 | ReminderCheck — напоминания | **P2** | Средняя | ⬜ TODO | Python `/scheduler/reminder-check` → mlog |
| 10 | MorningBrief — утренняя сводка | **P2** | Средняя | ⬜ TODO | Требует погоду + метрики |
| 11 | LZ Daily — ежедневный скан ЛЗ | **P2** | Средняя | ⬜ TODO | GitHub scan + LLM + Tavily |
| 12 | Telegram tg-send — отправка длинных сообщений | **P2** | Средняя | ⬜ TODO | Python `/tg-send` → mlog с разбиением |
| 13 | Dashboard HTML — генерация дашбордов | **P3** | Средняя | ⬜ TODO | Python → mlog templates |
| 14 | News collection — RSS + GDELT | **P3** | Сложная | ⬜ TODO | Требует XML парсинг |
| 15 | Tavily search — веб-поиск | **P3** | Лёгкая | ✅ DONE | mlog `TavilySearch()` pattern |
| 16 | Admin Daily — ежедневный отчёт админа | **P3** | Средняя | ⬜ TODO | Аналогично шедулерам |
| 17 | TTS/STT | — | Невозможна | 🔒 Blocked | Python-only (edge-tts, whisper) |
| 18 | Image generation | — | Невозможна | 🔒 Blocked | Python-only (ZAI SDK) |
| 19 | OSINT scanning | — | Невозможна | 🔒 Blocked | Python-only (aliens-eye) |
| 20 | Document extraction | — | Невозможна | 🔒 Blocked | Python-only (pymupdf, openpyxl) |
| 21 | LLM circuit breaker + combos | — | Невозможна | 🔒 Blocked | Критичная инфраструктура |
| 22 | Auto-enricher | — | Невозможна | 🔒 Blocked | Сложный regex + HTML |
| 23 | FosvedMemory | — | Невозможна | 🔒 Blocked | Temporal decay, RAG, conflicts |

---

## Детальные планы миграции

### #1 SearchArchive — P0 Лёгкая ⬜

**Текущее:** mlog `SearchArchive(query)` → `http_post(:4000/search, {query})` → Python SQL `LIKE %query%`

**Целевое:** mlog делает SQL напрямую:
```mlog
pattern SearchArchive(query_text: String) -> String {
  let search_term = "%" + query_text + "%"
  let rows = query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE (raw_text LIKE ?1 OR title LIKE ?1) ORDER BY id DESC LIMIT 50", [search_term])
  return json_encode(rows)
}
```

**Что удаляем из Python:** `/search` endpoint (30 строк)
**Риск:** нулевой — SQL идентичен

---

### #2 PublishToArchive — P0 Лёгкая ⬜

**Текущее:** mlog `PublishToArchive(doc_id, dept, title, content)` → Python `/archive/publish` → StripHtml + Telegram sendMessage

**Целевое:** mlog делает нативно:
```mlog
pattern PublishToArchive(doc_id: String, dept: String, title: String, content: String) -> String {
  let plain = StripHtml(content)
  let hashtags = DeptHashtags(dept)
  let text = "*" + title + "*\n\n" + substring(plain, 0, 3800) + "\n\n" + hashtags
  let token = env("TELEGRAM_BOT_TOKEN")
  let channel_id = env("ARCHIVE_CHANNEL_ID")
  let body = json_encode({chat_id: channel_id, text: text, parse_mode: "Markdown"})
  let result = try http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")
  // ... save channel_message_id to channel_archive
  return result
}
```

**Что удаляем из Python:** `/archive/publish` endpoint (70+ строк)
**Риск:** низкий — StripHtml уже в mlog, Telegram API нативно доступен

---

### #3 Learning Operations — P1 Лёгкая ⬜

**Текущее:** 4 mlog patterns делегируют в Python:
- `ClassifyCorrection(text, dept)` → `/learning/fix`
- `RecordPositiveExample(dept, query, response)` → `/learning/good`
- `GetLearningStats()` → `/learning/stats`
- `DebriefDepartment(dept)` → `/learning/debrief`

**Целевое:** mlog делает напрямую через db_execute + call_llm:
- `ClassifyCorrection` — call_llm для классификации + db_execute для сохранения
- `RecordPositiveExample` — db_insert в adapt_corrections
- `GetLearningStats` — query() агрегации
- `DebriefDepartment` — query() + call_llm для генерации дебрифа

**Что удаляем из Python:** 3 endpoint'а (`/learning/fix`, `/learning/good`, `/learning/stats`, `/learning/debrief`, ~200 строк)
**Риск:** средний — теряем circuit breaker на LLM-вызовах в ClassifyCorrection, но это не критично (learning — фоновый процесс)

---

### #4-8 Scheduler Patterns — P1 Лёгкая/Средняя ⬜

**Текущее:** Каждый шедулер в `dept/scheduler.mlog`:
1. Собирает метрики через `query()` в mlog
2. Строит payload
3. Отправляет `http_post(:4000/scheduler/X, payload)` в Python
4. Python делает LLM-вызов + Telegram отправку

**Целевое:** Шедулеры делают LLM-вызов нативно через `call_llm` и отправляют через `SendTelegramReply`:
```mlog
pattern EveningSummary() -> String {
  // ... collect metrics (already in mlog) ...
  let prompt = "Ты — Яна. Составь вечернюю сводку..."
  let messages = json_encode([{role: "system", content: yana_profile}, {role: "user", content: prompt}])
  let llm_result = call_llm(messages)  // нативный вызов
  let reply = json_get(parse_json(llm_result), "content", "")
  let _ = SendTelegramReplyMDV2(owner_id, reply)
  let _ = AuditLog("evening_summary", "scheduler", "completed")
  return "ok"
}
```

**Что удаляем из Python:** 5 endpoint'ов (`/scheduler/evening-summary`, `/scheduler/weekly-digest`, `/scheduler/monthly-review`, `/scheduler/control-check`, `/scheduler/self-learn`, ~400 строк)
**Риск:** средний — теряем circuit breaker и combo chains для шедулерных LLM-вызовов. Но шедулеры — фоновые процессы, один провайдер приемлем. Если провайдер упал — шедулер просто не отправит сводку, не критично.

---

### #9 ReminderCheck — P2 Средняя ⬜

**Текующее:** mlog `ReminderCheck()` → Python `/scheduler/reminder-check` → сложная логика RRULE парсинга + Telegram отправка

**Целевое:** mlog нативно:
- query() для due reminders
- Парсинг RRULE (daily/weekly/monthly/yearly) — уже частично в mlog (см. smoke_f1_2.mlog)
- SendTelegramReply для отправки
- db_execute для обновления next_fire_at

**Что удаляем из Python:** `/scheduler/reminder-check` (~100 строк)
**Риск:** средний — RRULE логика нетривиальна, но базовые варианты (daily, weekly, monthly) уже протестированы в mlog

---

### #10 MorningBrief — P2 Средняя ⬜

**Текущее:** mlog `MorningBrief()` → Python `/scheduler/morning-brief` → погода + метрики + LZ-находки + LLM → Telegram

**Целевое:** mlog нативно:
- http_get для погоды (OpenWeatherMap API)
- query() для метрик
- query() для LZ-находки
- call_llm для генерации сводки
- SendTelegramReplyMDV2 для отправки

**Что удаляем из Python:** `/scheduler/morning-brief` (~140 строк)
**Риск:** средний — нужна переменная OPENWEATHER_API_KEY, но API простой

---

### #11 LZ Daily — P2 Средняя ⬜

**Текущее:** Python `/scheduler/lz-daily` делает всё: GitHub scan → LLM → Tavily → Telegram

**Целевое:** Частичная миграция:
- GitHub scan: mlog может http_get + parse_json для GitHub API
- Tavily: mlog может http_post для Tavily API
- LLM: call_llm
- Telegram: SendTelegramReply

**Что удаляем из Python:** `/scheduler/lz-daily` (~160 строк)
**Риск:** средний-высокий — GitHub API pagination, Tavily context injection, но базовая функциональность достижима

---

### #12 tg-send — P2 Средняя ⬜

**Текующее:** mlog делегирует отправку длинных сообщений в Python `/tg-send`, который разбивает на части по 4096 символов

**Целевое:** mlog pattern с разбиением:
```mlog
pattern SendTelegramLong(chat_id: String, text: String) -> String {
  if len(text) <= 4096.0 then {
    return SendTelegramReply(chat_id, text)
  }
  // Разбить на части по 4096
  let part1 = substring(text, 0, 4096)
  let _ = SendTelegramReply(chat_id, part1)
  let part2 = substring(text, 4096, 8192)
  let _ = SendTelegramReply(chat_id, part2)
  // ... до 4 частей
  return "ok"
}
```

**Что удаляем из Python:** `/tg-send` endpoint (~30 строк)
**Риск:** низкий — простая логика разбиения

---

### #13 Dashboard HTML — P3 Средняя ⬜

**Текущее:** `dept_dashboard.py` (296 строк) генерирует HTML для дашбордов

**Целевое:** mlog templates (Askama-подобные, встроенные в mlog server)
- `/dept-dashboard/<slug>` → mlog route с template
- `/office-dashboard` → mlog route с template

**Что удаляем из Python:** 2 endpoint'а + dept_dashboard.py (~300 строк)
**Риск:** средний — нужно переписать HTML генерацию на mlog templates

---

### #14 News Collection — P3 Сложная ⬜

**Текущее:** Python `/cron/collect-news` + `collect_rss()` + `collect_gdelt()` — RSS/GDELT парсинг

**Проблема:** mlog нет feedparser (RSS XML парсинг). Нужен или:
- JSON API替代RSS (GDELT имеет JSON API)
- Или оставить RSS в Python, а GDELT мигрировать

**Риск:** высокий — RSS парсинг в mlog нетривиален

---

### #15 Tavily Search — P3 Лёгкая ⬜

**Текущее:** Python `/search/web` делает Tavily API call + `/lz/deep-research` интегрирует

**Целевое:** mlog pattern для Tavily:
```mlog
pattern TavilySearch(query: String) -> String {
  let api_key = env("TAVILY_API_KEY")
  let body = json_encode({
    api_key: api_key,
    query: query,
    search_depth: "advanced",
    max_results: 8,
    include_answer: true
  })
  let result = http_post("https://api.tavily.com/search", body, "application/json")
  return result
}
```

**Что удаляем из Python:** `/search/web` endpoint (~80 строк)
**Риск:** низкий — простой REST API

---

## Прогресс и метрики

### Статистика до миграции
| Слой | Строки | Endpoints |
|------|--------|-----------|
| mlog (app.mlog + dept/*.mlog) | ~4800 | 8 cron routes |
| Python (llm_proxy.py) | ~6060 | 78 endpoints |

### Ожидаемый результат после полной миграции (P0-P2)
| Слой | Строки | Endpoints | Удалено из Python |
|------|--------|-----------|-------------------|
| mlog | ~6200 (+1400) | 8 cron routes | — |
| Python | ~4900 (-1160) | ~55 (-23) | ~1160 строк, 23 endpoint'а |

### Заблокировано (остаётся в Python навсегда)
- TTS/STT (edge-tts, whisper)
- Image generation (ZAI)
- OSINT (aliens-eye)
- Document extraction (pymupdf, openpyxl)
- LLM circuit breaker + combo chains
- Auto-enricher (сложный regex)
- FosvedMemory (temporal decay, RAG)
- Telegram webhook (финальная обработка — фото, voice, entities)

---

## Порядок реализации

### Фаза 1 — P0 (быстрые победы) ✅ ВЫПОЛНЕНО
1. ✅ SearchArchive → mlog native query()
2. ✅ PublishToArchive → mlog native StripHtml + Telegram

### Фаза 2 — P1 (шедулеры + обучение) ✅ ВЫПОЛНЕНО
3. ✅ Learning operations (ClassifyCorrection, RecordPositiveExample, GetLearningStats, DebriefDepartment)
4. ✅ EveningSummary → native call_llm
5. ✅ WeeklyDigest → native call_llm
6. ✅ MonthlyReview → native call_llm
7. ✅ ControlCheck → native call_llm
8. ✅ YanaSelfLearn → native call_llm

### Фаза 2b — P3 (Tavily) ✅ ВЫПОЛНЕНО
15. ✅ Tavily search → mlog native TavilySearch() pattern

### Фаза 3 — P2 (сложные шедулеры, следующие)
9. ⬜ ReminderCheck → mlog RRULE logic
10. ⬜ MorningBrief → mlog + http_get (weather)
11. ⬜ LZ Daily → mlog + GitHub API + Tavily
12. ⬜ tg-send → mlog message splitting

### Фаза 4 — P3 (дашборды, новости, 7-10 дней)
13. ⬜ Dashboard HTML → mlog templates
14. ⬜ News collection (GDELT JSON API)
16. ⬜ Admin Daily → native call_llm

---

## Правила миграции

1. **Тестируем до удаления** — каждый мигрированный pattern тестируем вручную через Telegram перед удалением Python endpoint'а
2. **Python endpoint не удаляем до подтверждения** — помечаем как deprecated, ждём 24 часа без ошибок, потом удаляем
3. **Circuit breaker компенсация** — для шедулеров: если call_llm не отвечает, логируем ошибку и пропускаем (не критично для фоновых процессов)
4. **call_llm vs CallLLMProxy** — для пользовательских запросов (HandleLZ, HandleOSP) оставляем CallLLMProxy (circuit breaker). Для шедулеров и обучения — можно использовать call_llm
5. **Обратная совместимость** — если mlog pattern не работает, fallback на Python endpoint
