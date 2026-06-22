# МЕГА-НАРЯДЫ: ПЕРЕСБОРКА FOSVED OFFICE V2

**Выполнять строго по порядку. После каждого мега-наряда — commit + push + verify.**

---

# МЕГА-1: ФУНДАМЕНТ (60 мин)

## Шаг 1.1: Dockerfile

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y ca-certificates git python3 python3-pip curl && rm -rf /var/lib/apt/lists/*
RUN pip3 install flask requests edge-tts --break-system-packages
COPY bin/mlog /usr/local/bin/mlog
RUN chmod +x /usr/local/bin/mlog
WORKDIR /office
COPY . .
RUN mkdir -p /office/data /tmp
RUN git config --global user.email "agent@fosved.office" && git config --global user.name "Fosved Agent"
EXPOSE 10000
CMD ["bash", "entrypoint.sh"]
```

## Шаг 1.2: entrypoint.sh

```bash
#!/bin/bash
echo "Starting Fosved Office v2..."

# 1. LLM Proxy (порт 4000)
python3 llm_proxy.py &
LLM_PID=$!
echo "LLM Proxy started (PID: $LLM_PID)"
sleep 2

# Healthcheck proxy
for i in {1..10}; do
  curl -sf http://127.0.0.1:4000/health && break
  echo "Waiting for LLM proxy... ($i)"
  sleep 2
done

# 2. Metalogos (порт 10001)
PORT=10001 mlog serve app.mlog &
MLOG_PID=$!
echo "Metalogos started (PID: $MLOG_PID)"
sleep 3

# Healthcheck mlog
for i in {1..10}; do
  curl -sf http://127.0.0.1:10001/ && break
  echo "Waiting for Metalogos... ($i)"
  sleep 2
done

# 3. Reverse Proxy (порт $PORT, default 10000)
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID
```

## Шаг 1.3: reverse_proxy.py

Минимальный HTTP-прокси: порт PORT (10000), маршрутизация:
- `/miniapp/*`, `/dept-dashboard/*`, `/office-dashboard` → http://127.0.0.1:4000
- Всё остальное → http://127.0.0.1:10001

## Шаг 1.4: llm_proxy.py

Полноценный Python-сервер:
- 7 провайдеров с failover (Z.ai → DeepSeek → Groq → Grok → Claude → OpenAI → Apodex)
- `detect_dept(text)`: 13 slug-команд + 40+ расширенных + русские keywords
- `get_dept_prompt(dept)`: загрузка library/*.md
- Endpoints: `/health`, `/ask` (LLM вызов), `/lz/deep-research`, `/rate_cmd`, `/context_cmd`, `/voice-set`, `/archive/digest`
- Mini App HTML генерация: `/miniapp`, `/miniapp/<id>`, `/report`
- Department dashboards: `/dept-dashboard/<slug>`
- Office panel: `/office-dashboard`
- Audit logging в SQLite

**ВАЖНО:** proxy должен содержать `CONDENSED_PROMPTS` — краткие fallback-промпты для каждого отдела на случай если library/*.md недоступен.

**ВАЖНО:** `COMMAND_DEPT` dict должен содержать ВСЕ 13 slug-команд:
```python
COMMAND_DEPT = {
    '/yana': 'yana', '/osp': 'osp', '/lz': 'lz',
    '/expert': 'expert', '/marketing': 'marketing', '/finance': 'finance',
    '/legal': 'legal', '/dev': 'dev', '/design': 'design',
    '/qa': 'qa', '/visual': 'visual', '/engineering': 'engineering',
    '/forge': 'kavalnya',
    '/analyze': 'osp', '/scan': 'lz', '/deep': 'osp',
    # ... остальные расширенные команды
}

RUSSIAN_KEYWORDS = {
    'osp': ['проанализируй', 'прогноз', 'стратегия', 'геополитик'],
    'lz': ['технолог', 'мониторь', 'тренд', 'прорыв'],
    'expert': ['встреч', 'брифинг', 'подготовь к'],
    'marketing': ['реклам', 'аудитория', 'конверсия', 'маркетинг'],
    'finance': ['бюджет', 'cashflow', 'налог', 'финанс'],
    'legal': ['договор', 'иск', 'GDPR', 'юридическ', 'NDA'],
    'dev': ['код', 'архитектур', 'API', 'программ'],
    'design': ['дизайн', 'wireframe', 'макет', 'UI', 'UX'],
    'qa': ['тест', 'баг', 'качеств'],
    'visual': ['инфографик', 'визуализац', 'график'],
    'engineering': ['расчёт', 'нагрузк', 'конструкци', 'инженер'],
    'kavalnya': ['новый отдел', 'полигон', 'методолог'],
}
```

## Шаг 1.5: app.mlog

Главный файл (~1500 строк). Содержит:

```mlog
// Импорты
import dept/utils
import dept/context
import dept/yana
import dept/osp
// ... все 14 отделов

// Memory + DB
memory { persist: "./data/memory.db" }

// Инициализация всех таблиц
pattern InitDB() -> String {
  // ВСЕ 20 таблиц из REBUILD_PLAN.md
  db_execute("CREATE TABLE IF NOT EXISTS dialog_history (...)")
  db_execute("CREATE TABLE IF NOT EXISTS adapt_corrections (...)")
  // ... остальные
  return "ok"
}

// Server
mlogserver {
  port: env("PORT")

  route "/" method=GET { return respond("200 Fosved Office v2 alive") }
  route "/health" method=GET {
    let _ = InitDB()
    return respond("200 ok")
  }

  route "/webhook/telegram" method=POST {
    let data = json_body()
    let chat_id = to_string(json_get(data, "message.chat.id", "0"))
    let user_id = to_string(json_get(data, "message.from.id", "0"))
    let owner_id = env("OWNER_TELEGRAM_ID")
    if user_id != owner_id then { return respond("200 ok") }

    // Lockdown check
    let locked = kv_get("system_lockdown")
    if locked == "true" then {
      // Только /unlock проходит
      let text = json_get(data, "message.text", "")
      if starts_with(text, "/unlock") then { /* unlock logic */ }
      return respond("200 ok")
    }

    // Voice check
    let has_voice = has_field(data, "message.voice")
    let text = ""
    if has_voice == 1.0 then {
      let file_id = json_get(data, "message.voice.file_id")
      let text = whisper_transcribe(file_id, env("TELEGRAM_BOT_TOKEN"), env("WHISPER_API_KEY"), env("WHISPER_PROVIDER"))
      send_message(chat_id, "Распознано: " + text)
    } else {
      let text = json_get(data, "message.text", "")
    }

    // Callback query (approve/reject нарядов)
    // ... callback_query handler

    // web_app_data (Mini App actions)
    // ... web_app_data handler

    // Forwarded messages → LZ index
    // ... forward handler

    // Command routing (match)
    // ... все 98 команд

    // Fallback → Яна
    // ... default handler
  }

  // Cron endpoints (6)
  route "/cron/morning" method=GET { ... }
  route "/cron/evening" method=GET { ... }
  route "/cron/weekly" method=GET { ... }
  route "/cron/monthly" method=GET { ... }
  route "/cron/control" method=GET { ... }
  route "/cron/night" method=GET { ... }

  // Mini App routes
  route "/dept/osp" method=GET { ... }
  // ... 13 dept routes
  route "/miniapp" method=GET { ... }
  route "/office" method=GET { ... }
}
```

## Шаг 1.6: dept/*.mlog (14 файлов)

Каждый dispatcher загружает профиль из file_cache, вызывает LLM через proxy, записывает в dialog_history + audit.

## Шаг 1.7: library/*.md (14 файлов)

Профили отделов. Если оригиналы есть — скопировать. Если нет — сгенерировать LLM по спецификации из нарядов 1-6 + наряд 28 (Админ).

## Шаг 1.8: config/, skills_index/, file_cache*.mlog, report_css.txt

Создать все вспомогательные файлы.

## Шаг 1.9: bin/mlog

Скопировать из Metalogos repo (release build, 66 builtins).

## VERIFY МЕГА-1:
```bash
curl http://localhost:10000/        # alive
curl http://localhost:10000/health  # ok
# POST /webhook/telegram с /status → 13 отделов
# POST с /osp test → LLM ответ
# POST с /lockdown pwd → заблокирован
# POST с чужим user_id → игнор
```

## COMMIT: `MEGA-1: Foundation — 14 depts, routing, memory, LLM, lockdown`

---

# МЕГА-2: MINI APP + МОДЕЛИ + ЭКОНОМИКА (45 мин)

## Шаг 2.1: dept/miniapp.mlog
- DeptColors (14 цветов, через if-else, НЕ write_file)
- BuildReport (gradient header, бейджи, depth, disclaimers, action bar)
- FormatReportBody (парсинг [ФАКТ]/[ИНТЕРПРЕТАЦИЯ]/[СПЕКУЛЯЦИЯ])
- SendReport (порог 800 символов → Mini App или текст)

## Шаг 2.2: dept_dashboard.py
- HTML генерация дашбордов отделов
- Office panel HTML
- Обработка threading.Lock для concurrency

## Шаг 2.3: Маршруты в app.mlog
- /dept, /dept <slug>
- /model, /model set, /model reset
- /cost, /cost dept, /budget
- /rate

## Шаг 2.4: TrackedLLM обёртка
- Записывает каждый LLM-вызов в token_usage
- GetTokenCost (7 провайдеров)
- CheckBudgetLimit

## Шаг 2.5: Action bar (ОСП-специфичные кнопки)
- Журналист, Погружение (4 уровня), На контроль (3 частоты), Контр-прогноз
- web_app_data callback обработка

## VERIFY МЕГА-2:
```bash
# /dept osp → кнопка → HTML 200
# /model → настройки
# /cost → расход
# /rate 4 → сохранено
# GET /dept-dashboard/osp → HTML
# GET /office-dashboard → HTML
```

## COMMIT: `MEGA-2: Mini App, reports, models, economics, dashboards`

---

# МЕГА-3: CHAIN + ГОЛОС + SCHEDULER + LEARNING + AUDIT + АРХИВ (45 мин)

## Шаг 3.1: dept/chain.mlog
- ExecuteChain (до 3 отделов последовательно)
- /chain dept1+dept2 команда

## Шаг 3.2: Голос
- Обработка voice messages → whisper_transcribe → текст → обработка
- TTS: short reply (<200) + voice_enabled → tts_send
- /voice on/off/male/female → kv_set

## Шаг 3.3: dept/scheduler.mlog
- MorningBrief + YanaSelfLearn
- EveningSummary + PublishDailyDigest
- WeeklyDigest
- MonthlyReview + MonthlyDebrief
- ControlCheck
- QuarterlyAudit
- /brief, /digest, /review ручные

## Шаг 3.4: 6 cron endpoints + CRON_SECRET
- Все `/cron/*` проверяют `query_param("secret") == env("CRON_SECRET")`
- Без secret → 403

## Шаг 3.5: Learning loop
- /fix с LLM-классификацией (TOO_GENERAL, WRONG_FACTS...) → error_patterns
- /good → positive example → adapt_corrections
- /learning → статистика
- /debrief <dept> → LLM-анализ ошибок
- ProposePromptFix → callback apply_fix → /build наряд

## Шаг 3.6: Audit
- AuditLog вызывается при КАЖДОМ действии (18 типов)
- /audit → последние 20 записей
- НЕТ DELETE/UPDATE для audit_log

## Шаг 3.7: Архив
- PublishToArchive → send_message в TELEGRAM_ARCHIVE_CHANNEL_ID
- StripHtml, DeptHashtags
- /archive, /autoarchive on/off, /search

## VERIFY МЕГА-3:
```bash
# /chain osp+legal test → 200
# /voice on → ok
# /brief → brief
# /fix test → коррекция + классификация
# /good → positive
# /audit → 20 записей
# /search test → результат
# GET /cron/morning?secret=X → 200
# GET /cron/morning → 403
```

## COMMIT: `MEGA-3: Chain, voice, scheduler, learning, audit, archive`

---

# МЕГА-4: АДМИН + ФАБРИКА + ЛЗ DEEP SCAN + APODEX (30 мин)

## Шаг 4.1: dept/admin.mlog
- Профиль: ироничный перфекционист (library/admin.md)
- 12 /admin команд
- AdminBuild → inline approve/reject
- AdminFix → LLM анализ + наряд
- AdminStatus → graph nodes, open issues, health score

## Шаг 4.2: Ночной цикл
- /cron/night endpoint с CRON_SECRET
- AdminNightCycle: 5 фаз (graph → audit → metrics → autofix → proposals)
- BuildKnowledgeGraph → knowledge_graph + knowledge_edges
- ImpactAnalysis, FindOrphans
- AdminAutoFix (только low risk, НЕ app.mlog)
- AdminProposals → admin_proposals таблица
- Результат → kv_set("admin_night_summary") → в утренний brief Яны

## Шаг 4.3: Фабрика
- /factory → 7-шаговый опрос (kv_set active_order + order_step)
- HandleFactoryStep (name → tasks → departments → branding → llm → confirm → build)
- BuildClientOffice → LLM генерирует профили + структуру
- /factory_review, /factory_deploy (GitHub API), /factory_deliver, /factory_list

## Шаг 4.4: ЛЗ Deep Scan
- 9 источников: ScanWeb, ScanYouTube, ScanReddit, ScanScience, ScanGitHub, ScanSocial, ScanTelegram, ScanDarknet, DeepScan агрегатор
- /lz scan, /lz all, /lz_channel, /lz_channels, /lz_monitor

## Шаг 4.5: Apodex
- 7-й провайдер (timeout 300 сек)
- /lz deep → Apodex verified research
- /lz compare → side-by-side LLM vs Apodex
- Бейджи verified/unverified/conflicting
- Evidence graph секция в отчёте

## VERIFY МЕГА-4:
```bash
# /admin → справка
# /admin status → статус
# /admin build test → наряд
# /factory → начало опроса
# /lz deep test → 200
# GET /cron/night?secret=X → 200
```

## COMMIT: `MEGA-4: Admin agent, factory, LZ deep scan, Apodex`

---

# ФИНАЛ: СТРЕСС-ТЕСТ (20 мин)

85 тестов. Прогнать все. Формат отчёта:

```
Отделы:      [XX/65]
Интеграция:  [XX/15]
Mini App:    [XX/5]
ИТОГО:       [XX/85]

Цель: 80+/85
```

Если < 80 — список проблем + точечные фиксы + повтор.

## COMMIT: `Stress test passed: XX/85`
