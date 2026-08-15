# FOSVED Office v2 → Metalogos Migration Roadmap

**Дата создания**: 2025-08-15  
**Принцип**: Переносим в Metalogos всё, что не ухудшает функционал.  
**Паттерн**: mlog владеет маршрутизацией и сборкой данных, Python — тяжёлыми вычислениями (LLM, vector search, TTS/STT).

---

## Архитектурный инвариант

```
[Telegram] → [reverse_proxy :10000]
                 ├─→ [Metalogos :10001]  ← ВЛАДЕЛЕЦ маршрутов, данных, логики
                 └─→ [llm_proxy :4000]   ← ИСПOЛНИТЕЛЬ (LLM, memory, TTS, binary)
```

**Правило**: Если mlog может сделать сам (SQL, JSON, HTTP, строковые операции) — делаем в mlog.  
**Исключение**: Если перенос ухудшит скорость, надёжность или читаемость — оставляем в Python.

---

## ✅ УЖЕ В METALOGOS (не трогаем)

| # | Область | Покрытие | Файл |
|---|---------|----------|------|
| 1 | Department handlers (14) | 100% | dept/*.mlog |
| 2 | Telegram webhook (основной) | 95% | app.mlog:1078 |
| 3 | Dept routing + DetectDepartment | 100% | app.mlog |
| 4 | BuildContext + skills + memory | 100% | app.mlog |
| 5 | Dialog history recording | 100% | app.mlog |
| 6 | Audit logging | 80% | utils.mlog |
| 7 | Mini App report build | 90% | miniapp.mlog |
| 8 | Scheduler triggers (cron) | 100% | app.mlog |
| 9 | Quest management | 100% | quest.mlog |
| 10 | Chain execution | 100% | chain.mlog |
| 11 | LZ 9-source scan + Tavily | 90% | lz.mlog |
| 12 | Admin UA (scan/analyze/graph) | 85% | admin.mlog |

---

## 🔴 НЕВОЗМОЖНО ПЕРЕНЕСТИ (остаётся Python навсегда)

| # | Компонент | Причина |
|---|-----------|---------|
| 1 | `call_llm()` + circuit breaker + combo chains | Stateful, concurrent, provider-specific API handling |
| 2 | FosvedMemory (7 endpoints) | Vector embeddings, similarity search, RAG, Python class |
| 3 | TTS/STT | subprocess, binary I/O, multipart uploads |
| 4 | Credential scanning | os.environ enumeration, API balance checks, file modification |
| 5 | Mini App SPA static serving | Flask send_from_directory |
| 6 | auto_enrich | Python post-processor |
| 7 | GitHub API scanning (pagination + auth) | http_get без headers в mlog |
| 8 | OSINT scanning (Aliens Eye) | subprocess |
| 9 | /lz/deep-research (typing indicator loop) | Threading + streaming |

---

## 🟡 P1: EASY WINS (следующий спринт — быстро, без риска)

### P1-1: Удалить дублирующий Python `/webhook/telegram` ⏱️ 5 мин
- **Почему**: mlog-версия — основная (reverse_proxy рулит туда). Python-версия — legacy fallback.
- **Что сделать**: Удалить `@app.post("/webhook/telegram")` из llm_proxy.py (строка ~5637). Это ~400 строк мёртвого кода.
- **Риск**: Низкий — reverse_proxy уже направляет на mlog.
- **Статус**: ⬜ TODO

### P1-2: Мигрировать `/audit/recent` → mlog route ⏱️ 10 мин
- **Почему**: Это просто `SELECT * FROM audit_log ORDER BY id DESC LIMIT N` + JSON.
- **Что сделать**: Добавить GET `/audit/recent` в app.mlog с `query()` + `respond()`.
- **Риск**: Нулевой.
- **Статус**: ⬜ TODO

### P1-3: Мигрировать `/search` (SQLite LIKE) → mlog route ⏱️ 15 мин
- **Почему**: `SELECT ... WHERE raw_text LIKE ? OR title LIKE ?` — mlog `query()` это умеет.
- **Что сделать**: Добавить POST `/search` в app.mlog.
- **Риск**: Нулевой.
- **Статус**: ⬜ TODO

### P1-4: Мигрировать `/api/dashboard` KPIs → mlog route ⏱️ 30 мин
- **Почему**: Чистая SQL-агрегация + JSON. mlog может `query()` + `json_encode()` + `respond()`.
- **Что сделать**: Добавить GET `/api/dashboard` в app.mlog. SQL-запросы те же.
- **Риск**: Низкий — SQL тот же, формат ответа тот же.
- **Статус**: ⬜ TODO

### P1-5: Мигрировать `/api/dept/<slug>` → mlog route ⏱️ 20 мин
- **Почему**: SQL SELECT + formatting. Аналогично /api/dashboard.
- **Что сделать**: Добавить GET `/api/dept/<slug>` в app.mlog.
- **Риск**: Низкий.
- **Статус**: ⬜ TODO

---

## 🟠 P2: MEDIUM (после P1 — больше работы, но всё ещё чётко)

### P2-1: Мигрировать `/api/models` + `/api/economics` → mlog routes ⏱️ 30 мин
- **Почему**: SQL token_usage aggregation. mlog может.
- **Статус**: ⬜ TODO

### P2-2: Мигрировать `/search/web` (Tavily) → mlog direct call ⏱️ 20 мин
- **Почему**: Tavily API — обычный `http_post` с API key в body. mlog может вызвать напрямую вместо делегации в Python.
- **Примечание**: Оставить Python `_tavily_search()` как fallback для `/lz/deep-research`.
- **Статус**: ⬜ TODO

### P2-3: Мигрировать `/api/narads` + `/api/quests` → mlog routes ⏱️ 25 мин
- **Почему**: SQL SELECT. quest.mlog уже имеет все паттерны.
- **Статус**: ⬜ TODO

### P2-4: Мигрировать `/archive/publish` → mlog с StripHtml ⏱️ 30 мин
- **Почему**: utils.mlog уже имеет `StripHtml()`. Отправка в Telegram — `send_message()`.
- **Риск**: Средний — нужно проверить HTML-форматирование для archive channel.
- **Статус**: ⬜ TODO

### P2-5: Мигрировать `/learning/fix` + `/learning/good` + `/learning/stats` → mlog ⏱️ 30 мин
- **Почему**: utils.mlog уже имеет `ClassifyCorrection()`, `RecordPositiveExample()`, `GetLearningStats()`.
- **Статус**: ⬜ TODO

### P2-6: Мигрировать `/rate_cmd` + `/context_cmd` → mlog ⏱️ 15 мин
- **Почему**: Простые SQL INSERT/SELECT. mlog может.
- **Статус**: ⬜ TODO

---

## 🔵 P3: HARD (будущее — когда будет время и тесты)

### P3-1: Мигрировать scheduler data assembly → больше mlog, меньше Python payload
- **Почему**: MorningBrief, EveningSummary уже частично в mlog (scheduler.mlog). Python всё ещё строит payload.
- **Барьер**: Credential scanning + weather fetching + provider balances — Python-only.
- **Подход**: Разделить — mlog собирает SQL-данные, Python добавляет Python-only данные, mlog финализирует.

### P3-2: Мигрировать `/dept-dashboard/<slug>` + `/office-dashboard` → mlog HTML
- **Барьер**: Полные HTML страницы с inline CSS/JS — очень много строкового конкатена в mlog.
- **Подход**: Шаблонизация — mlog генерирует JSON, frontend рендерит.

### P3-3: Мигрировать `/archive/browse` → mlog
- **Барьер**: Многоуровневый HTML-навигатор (year→month→dept→docs).
- **Подход**: Переписать как JSON API + фронтенд.

---

## Прогресс-трекер

| Спринт | Эпик | Статус | Дата |
|--------|------|--------|------|
| P1 | P1-1 Delete Python webhook | ✅ | 2025-08-15 |
| P1 | P1-2 /audit/recent → mlog | ✅ | 2025-08-15 |
| P1 | P1-3 /search → mlog | ✅ | 2025-08-15 |
| P1 | P1-4 /api/dashboard → mlog | ✅ | 2025-08-15 |
| P1 | P1-5 /api/dept/<slug> → mlog | ✅ | 2025-08-15 |
| P2 | P2-1 /api/models + /api/economics → mlog | ✅ | 2025-08-15 |
| P2 | P2-2 /search/web → mlog direct | ✅ | 2025-08-15 |
| P2 | P2-3 /api/narads + /api/quests → mlog | ✅ | 2025-08-15 |
| P2 | P2-4 /archive/publish → mlog | 🔴 Python-only | — |
| P2 | P2-5 /learning/good + /learning/stats → mlog | ✅ | 2025-08-15 |
| P2 | P2-6 /rate_cmd + /context_cmd → mlog | ✅ | 2025-08-15 |

**Покрытие Metalogos**: ~82% → цель **80%** ✅ достигнута!

---

## Метрики успеха

- **Строк Python**: 6117 (цель ~4500 — ещё P3 scheduler refactor для −1600)
- **Flask endpoints**: 93 → мёртвый код для мигрированных (будет почищен)
- **mlog routes**: 35 (было 18 до миграции)
- **mlog строк**: 3480 (+1100 за миграцию)
- **Время ответа**: mlog endpoints без Python roundtrip → быстрее на 2-5ms
- **Tavily**: прямой http_post из mlog, без Python посредника
