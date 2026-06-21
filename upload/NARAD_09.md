# НАРЯД №9: Контекст-менеджер — умная загрузка контекста

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Результат:** каждый отдел получает релевантный контекст вместо голого профиля; скиллы выбираются по запросу; диалоги сжимаются; память подгружается

---

## Проблема

Сейчас каждый отдел отправляет в LLM только свой профиль (library/*.md) как system prompt. Это ~30 строк. У ОСП 24 скилла, но ни один не попадает в контекст. Память (memorize/recall) не используется при формировании ответа. История диалога теряется между запросами.

Результат: LLM отвечает "вообще", а не в контексте конкретной задачи и накопленных знаний.

## Решение: трёхуровневая загрузка

```
Уровень 1 — ВСЕГДА в промпте (~2000 токенов):
  - Компактный профиль отдела
  - Жёсткие правила
  - 2-3 релевантных скилла (не все)
  - Закреплённые факты о владельце

Уровень 2 — ПО ЗАПРОСУ (~1000 токенов):
  - Релевантные факты из памяти (recall по запросу)
  - Последние 5 сообщений диалога
  - Adapt-коррекции (если есть)

Уровень 3 — ПОЛНЫЙ (редко, по команде):
  - Вся история по теме
  - Все скиллы отдела
```

---

## Реализация

### 1. Таблица диалогов

```sql
CREATE TABLE IF NOT EXISTS dialog_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL,
  role TEXT NOT NULL,
  dept TEXT,
  content TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Каждое входящее сообщение и каждый ответ записываются. Хранить последние 100 записей на chat_id, старые — удалять или сжимать.

### 2. Таблица adapt-коррекций

```sql
CREATE TABLE IF NOT EXISTS adapt_corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dept TEXT NOT NULL,
  original_query TEXT,
  original_response TEXT,
  correction TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Когда владелец говорит "не то" или "/fix ..." — коррекция сохраняется и подгружается в контекст при следующем вызове отдела.

### 3. Модуль `dept/context.mlog`

```mlog
pattern SelectSkills(dept: String, query: String) -> String {
  let skills_index = read_file("skills_index/" + dept + ".txt")

  let selected = call_llm(
    read_file("config/priority_provider.txt"),
    GetApiKey(read_file("config/priority_provider.txt")),
    read_file("config/priority_model.txt"),
    "Ты — маршрутизатор скиллов. Из списка скиллов выбери 2-3 наиболее релевантных для запроса. Верни только имена скиллов через запятую, без пояснений.",
    "Запрос: " + query + "\n\nСписок скиллов:\n" + skills_index
  )

  return selected
}
```

**СТОП — это LLM-вызов для выбора скиллов.** Дорого. Альтернатива — keyword matching:

```mlog
pattern SelectSkillsByKeywords(dept: String, query: String) -> String {
  let result = ""

  if dept == "osp" then {
    if contains(query, "прогноз") then { let result = result + read_file("skills/fosved/spd/calibration/SKILL.md") + "\n---\n" }
    if contains(query, "актор") then { let result = result + read_file("skills/fosved/spd/deep-profiling/SKILL.md") + "\n---\n" }
    if contains(query, "декомпозиц") then { let result = result + read_file("skills/fosved/spd/deconstruct/SKILL.md") + "\n---\n" }
    if contains(query, "гипотез") then { let result = result + read_file("skills/fosved/spd/calibration/SKILL.md") + "\n---\n" }
    if contains(query, "нарратив") then { let result = result + read_file("skills/fosved/spd/narrative-vs-flows/SKILL.md") + "\n---\n" }
    if contains(query, "источник") then { let result = result + read_file("skills/fosved/spd/source-triangulation/SKILL.md") + "\n---\n" }
    if contains(query, "риск") then { let result = result + read_file("skills/fosved/spd/antifragility-design/SKILL.md") + "\n---\n" }
    if contains(query, "манёвр") then { let result = result + read_file("skills/fosved/spd/strategic-maneuvers/SKILL.md") + "\n---\n" }
  }

  if dept == "expert" then {
    if contains(query, "встреч") then { let result = result + read_file("skills/fosved/expert/tactical-meeting-protocol/SKILL.md") + "\n---\n" }
    if contains(query, "вопрос") then { let result = result + read_file("skills/fosved/expert/combat-questions-design/SKILL.md") + "\n---\n" }
    if contains(query, "проект") then { let result = result + read_file("skills/fosved/expert/project-deconstruction/SKILL.md") + "\n---\n" }
  }

  if dept == "finance" then {
    if contains(query, "cashflow") then { let result = result + read_file("skills/fosved/finance/cashflow-forecasting/SKILL.md") + "\n---\n" }
    if contains(query, "налог") then { let result = result + read_file("skills/fosved/finance/tax-compliance-multi-jurisdiction/SKILL.md") + "\n---\n" }
    if contains(query, "unit") then { let result = result + read_file("skills/fosved/finance/unit-economics-calculation/SKILL.md") + "\n---\n" }
  }

  if dept == "legal" then {
    if contains(query, "договор") then { let result = result + read_file("skills/fosved/legal/contract-drafting-discipline/SKILL.md") + "\n---\n" }
    if contains(query, "GDPR") then { let result = result + read_file("skills/fosved/legal/gdpr-compliance-check/SKILL.md") + "\n---\n" }
    if contains(query, "риск") then { let result = result + read_file("skills/fosved/legal/risk-mapping-protocol/SKILL.md") + "\n---\n" }
  }

  return result
}
```

**Выбери подход:** LLM-selection (качественнее, дороже) или keyword-matching (бесплатно, грубее). Можно начать с keywords и переключить на LLM позже. Или hybrid: keywords для known patterns, LLM fallback для неизвестных.

**ВАЖНО:** Скилл-файлы были удалены из репо (агент отметил 117 stubs). Нужно восстановить реальные скиллы из загруженных zip-архивов. Без них контекст-менеджер бесполезен. Попроси владельца перезагрузить если нужно.

### 4. Загрузка истории диалога

```mlog
pattern GetRecentDialog(chat_id: String, limit: Float) -> String {
  let rows = query("SELECT role, dept, content FROM dialog_history WHERE chat_id = $1 ORDER BY created_at DESC LIMIT $2", [chat_id, to_string(limit)])
  return rows
}
```

### 5. Загрузка релевантных фактов из памяти

```mlog
pattern GetRelevantFacts(query: String) -> String {
  let facts = recall(query)
  return facts
}
```

`recall` уже использует semantic search (TF-IDF или embeddings). Возвращает релевантные memorize-записи.

### 6. Загрузка adapt-коррекций

```mlog
pattern GetCorrections(dept: String) -> String {
  let rows = query("SELECT correction FROM adapt_corrections WHERE dept = $1 ORDER BY created_at DESC LIMIT 5", [dept])
  return rows
}
```

### 7. Основная функция — сборка контекста

```mlog
pattern BuildContext(dept: String, query: String, chat_id: String) -> String {
  let profile = read_file("library/" + dept + ".md")

  let skills = SelectSkillsByKeywords(dept, query)

  let facts = recall(query)

  let dialog = GetRecentDialog(chat_id, 5)

  let corrections = GetCorrections(dept)

  let pinned = recall("pinned_fact")

  let context = profile + "\n\n"

  if len(skills) > 0 then {
    let context = context + "=== РЕЛЕВАНТНЫЕ СКИЛЛЫ ===\n" + skills + "\n\n"
  }

  if len(facts) > 0 then {
    let context = context + "=== ИЗВЕСТНЫЕ ФАКТЫ ===\n" + facts + "\n\n"
  }

  if len(pinned) > 0 then {
    let context = context + "=== ЗАКРЕПЛЁННЫЕ ФАКТЫ ===\n" + pinned + "\n\n"
  }

  if len(corrections) > 0 then {
    let context = context + "=== ПРЕДЫДУЩИЕ КОРРЕКЦИИ (учитывай их!) ===\n" + corrections + "\n\n"
  }

  if len(dialog) > 0 then {
    let context = context + "=== ПОСЛЕДНИЕ СООБЩЕНИЯ ===\n" + dialog + "\n\n"
  }

  return context
}
```

### 8. Обновить все отделы

Каждый отдел вместо:
```mlog
let profile = read_file("library/osp.md")
let reply = call_llm(provider, key, model, profile, query)
```

Теперь:
```mlog
let context = BuildContext("osp", query, chat_id)
let reply = call_llm(provider, key, model, context, query)
```

### 9. Запись диалога

После каждого входящего сообщения:
```mlog
let _ = query("INSERT INTO dialog_history (chat_id, role, dept, content) VALUES ($1, 'user', $2, $3)", [chat_id, "general", text])
```

После каждого ответа:
```mlog
let _ = query("INSERT INTO dialog_history (chat_id, role, dept, content) VALUES ($1, 'assistant', $2, $3)", [chat_id, dept, reply])
```

### 10. Сжатие диалогов

Каждые 20 сообщений — сжатие через LLM:

```mlog
pattern CompressDialog(chat_id: String) -> String {
  let count = query("SELECT COUNT(*) FROM dialog_history WHERE chat_id = $1", [chat_id])
  if count > 20 then {
    let old_messages = query("SELECT content FROM dialog_history WHERE chat_id = $1 ORDER BY created_at ASC LIMIT 15", [chat_id])
    let summary = call_llm(provider, key, model, "Сожми следующий диалог в 3-5 предложений. Сохрани ключевые факты и решения.", old_messages)
    let _ = memorize(summary, 0.8)
    let _ = query("DELETE FROM dialog_history WHERE chat_id = $1 AND id IN (SELECT id FROM dialog_history WHERE chat_id = $1 ORDER BY created_at ASC LIMIT 15)", [chat_id])
  }
  return "ok"
}
```

### 11. Команда /fix — adapt-коррекция

```mlog
if starts_with(text, "/fix ") then {
  let correction = substring(text, 5, len(text))
  let last_dept = query("SELECT dept FROM dialog_history WHERE chat_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", [chat_id])
  let last_response = query("SELECT content FROM dialog_history WHERE chat_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", [chat_id])
  let _ = query("INSERT INTO adapt_corrections (dept, original_response, correction) VALUES ($1, $2, $3)", [last_dept, last_response, correction])
  // Ответ: "Коррекция принята для отдела {dept}"
}
```

### 12. Команда /remember — закрепить факт

```mlog
if starts_with(text, "/remember ") then {
  let fact = substring(text, 10, len(text))
  let _ = memorize(fact, 1.0)
  // Ответ: "Запомнил: {fact}"
}
```

---

## Файловая структура

```
dept/
├── context.mlog          # BuildContext, SelectSkillsByKeywords, GetRecentDialog, GetCorrections, CompressDialog
├── miniapp.mlog          # уже есть
├── utils.mlog            # уже есть
├── yana.mlog
├── osp.mlog
└── ...

skills_index/             # индекс скиллов для каждого отдела (название + описание, 1 строка)
├── osp.txt               # "calibration: калибровка вероятностей\ndeconstruct: декомпозиция..."
├── lz.txt
├── expert.txt
└── ...
```

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: обычный запрос (контекст = профиль + skills) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/osp сделай прогноз по рынку AI","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T2: второй запрос (должен видеть историю) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/osp а какие риски?","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T3: /remember ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/remember мой бизнес - EdTech платформа","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T4: запрос после /remember (должен учитывать факт) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/marketing проанализируй мою аудиторию","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T5: /fix ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/fix ответ слишком общий, нужна конкретика по EdTech B2C","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Context manager: 3-level loading, skill selection, dialog history, adapt corrections, /fix, /remember"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №9

1. dept/context.mlog создан: [✅/❌]
2. Таблица dialog_history: [✅/❌]
3. Таблица adapt_corrections: [✅/❌]
4. BuildContext pattern: [✅/❌]
5. SelectSkillsByKeywords: [✅/❌] [подход: keywords / LLM / hybrid]
6. История диалога записывается: [✅/❌]
7. /fix работает: [✅/❌]
8. /remember работает: [✅/❌]
9. Сжатие диалогов: [✅/❌]
10. Все отделы используют BuildContext: [✅/❌]
11. Скиллы восстановлены из оригиналов: [✅/❌/stubs]
12. T1-T5 проверки: [✅/❌]
13. git push: [✅/❌] [хэш коммита]
14. Проблемы: [если есть]
```
