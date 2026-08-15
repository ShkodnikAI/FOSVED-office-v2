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

## 🟡 P1: EASY WINS ✅ DONE

### P1-1: Удалить дублирующий Python `/webhook/telegram` ✅
### P1-2: Мигрировать `/audit/recent` → mlog route ✅
### P1-3: Мигрировать `/search` (SQLite LIKE) → mlog route ✅
### P1-4: Мигрировать `/api/dashboard` KPIs → mlog route ✅
### P1-5: Мигрировать `/api/dept/<slug>` → mlog route ✅

---

## 🟠 P2: MEDIUM ✅ DONE (кроме P2-4)

### P2-1: Мигрировать `/api/models` + `/api/economics` → mlog routes ✅
### P2-2: Мигрировать `/search/web` (Tavily) → mlog direct call ✅
### P2-3: Мигрировать `/api/narads` + `/api/quests` → mlog routes ✅
### P2-4: Мигрировать `/archive/publish` → mlog 🔴 Python-only (TBD)
### P2-5: Мигрировать `/learning/good` + `/learning/stats` → mlog ✅
### P2-6: Мигрировать `/rate_cmd` + `/context_cmd` → mlog ✅

---

## 🔵 P3: HARD ✅ DONE

### P3-1: Мигрировать scheduler data assembly → mlog собирает SQL-данные ✅
- **Что сделано**: MorningBrief() в scheduler.mlog теперь собирает 6 SQL-запросов
  (dialog_24h, active_depts, narads_pending, corrections_24h, calls_yesterday, cost_yesterday, top_depts)
  и передаёт в payload Python. Python morning-brief использует предсобранные данные
  из payload если они есть, иначе fallback на локальные SQL-запросы.
- **Результат**: Python экономит 4 SQL-запроса на каждый morning-brief вызов.
- **Дата**: 2025-08-16

### P3-2: Мигрировать `/dept-dashboard/<slug>` + `/office-dashboard` → mlog JSON API ✅
- **Что сделано**: Новые маршруты `/api/dept-dashboard?slug=X` и `/api/office-dashboard`
  в app.mlog возвращают JSON вместо HTML. Python HTML-версии остаются как fallback.
  Frontend (Mini App) может рендерить JSON клиент-side.
- **Данные dept-dashboard**: slug, name, color, calls_7d, cost_7d, tokens, avg_rating,
  model_override, priority_provider, corrections (5 recent)
- **Данные office-dashboard**: calls_today/week/month, cost_month, priority_provider/model,
  departments[] (13 depts с calls, rating, level, model), audit (10 recent), providers[]
- **Дата**: 2025-08-16

### P3-3: Мигрировать `/archive/browse` → mlog JSON API ✅
- **Что сделано**: Новый маршрут `/api/archive/browse` с drill-down через query params:
  - Без params → list years
  - ?year=2025 → list months
  - ?year=2025&month=08 → list departments
  - ?year=2025&month=08&dept=lz → list documents
- **Месяцы**: Русские названия (Январь-Декабрь) через lookup table
- **Дата**: 2025-08-16

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
| P3 | P3-1 MorningBrief SQL assembly → mlog | ✅ | 2025-08-16 |
| P3 | P3-2 /api/dept-dashboard + /api/office-dashboard → mlog JSON | ✅ | 2025-08-16 |
| P3 | P3-3 /api/archive/browse → mlog JSON | ✅ | 2025-08-16 |

**Покрытие Metalogos**: ~87% → цель **80%** ✅ достигнута и превышена!

---

## Метрики успеха

- **Строк Python**: ~6120 (morning-brief экономит 4 SQL при вызове из mlog)
- **Flask endpoints**: 93 → Python HTML dashboards теперь опциональны (JSON API в mlog)
- **mlog routes**: 38 (+3 за P3: /api/dept-dashboard, /api/office-dashboard, /api/archive/browse)
- **mlog строк**: ~3745 (+265 за P3)
- **Время ответа**: mlog JSON API быстрее HTML Python — нет шаблонизации
- **Tavily**: прямой http_post из mlog, без Python посредника
- **Scheduler**: MorningBrief экономит 4 SQL-запроса (собраны в mlog, переданы в payload)
