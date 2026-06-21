# НАРЯД №18: Learning loop — самоулучшение отделов

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** отделы учатся на ошибках, коррекции влияют на качество, ежемесячный debrief выявляет паттерны

---

## Концепция

Три уровня обучения:

```
Per-task (мгновенно):
  Владелец: /fix → коррекция сохраняется → следующий вызов учитывает
  Владелец: /rate → оценка влияет на метрики

Monthly (1-е число):
  Яна кластеризует ошибки → Кавальня проводит debrief →
  рекомендации по промптам → /build наряд на улучшение

Quarterly (каждые 3 месяца):
  Полный аудит: какие отделы деградировали → methodology review →
  Кавальня предлагает реорганизацию
```

---

## Реализация

### 1. Per-task: улучшенный /fix

Текущий `/fix` сохраняет коррекцию. Нужно усилить — анализировать паттерн ошибки:

```mlog
match text {
  starts_with "/fix " then {
    let correction = substring(text, 5, len(text))

    // Последний ответ и отдел
    let last_dept = to_string(query("SELECT dept FROM dialog_history WHERE chat_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", [chat_id]))
    let last_response = to_string(query("SELECT content FROM dialog_history WHERE chat_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", [chat_id]))
    let last_query = to_string(query("SELECT content FROM dialog_history WHERE chat_id = $1 AND role = 'user' ORDER BY created_at DESC LIMIT 1", [chat_id]))

    // Сохранить коррекцию с контекстом
    let _ = query("INSERT INTO adapt_corrections (dept, original_query, original_response, correction, created_at) VALUES ($1, $2, $3, $4, $5)",
      [last_dept, last_query, substring(last_response, 0, 500), correction, to_string(now())])

    // LLM классифицирует тип ошибки
    let classify_prompt = "Klassifisiruj oshibku otdela. Kategorii:\n- TOO_GENERAL (slishkom obshchij otvet)\n- TOO_LONG (mnogo vody)\n- WRONG_FACTS (oshibka v faktah)\n- WRONG_TONE (nevernyi ton)\n- MISSING_STRUCTURE (net struktury/sloyov)\n- WRONG_DEPT (nepravil'naya marshrutizaciya)\n- OTHER\n\nOtvet'yu TOLKO kategoriyej, bez poyasnenij."
    let error_type = call_llm(classify_prompt, "Zapros: " + last_query + "\nOtvet: " + substring(last_response, 0, 300) + "\nKorrekciya: " + correction)
    let error_type_clean = trim(error_type)

    // Сохранить тип ошибки
    let _ = query("INSERT INTO error_patterns (dept, error_type, query_text, correction, created_at) VALUES ($1, $2, $3, $4, $5)",
      [last_dept, error_type_clean, last_query, correction, to_string(now())])

    send_message(chat_id, "Korrekciya prinyata dlya " + DeptDisplayName(last_dept) + " (" + error_type_clean + ")")
    let _ = AuditLog("fix", "owner", last_dept, error_type_clean + ": " + correction, "ok")
    return respond("200 ok")
  }
}
```

### 2. Таблица паттернов ошибок

```mlog
db_execute("CREATE TABLE IF NOT EXISTS error_patterns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dept TEXT NOT NULL,
  error_type TEXT NOT NULL,
  query_text TEXT,
  correction TEXT,
  created_at REAL
)")
```

### 3. Per-task: /good — положительное подкрепление

```mlog
match text {
  "/good" then {
    let last_dept = to_string(query("SELECT dept FROM dialog_history WHERE chat_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", [chat_id]))
    let last_query = to_string(query("SELECT content FROM dialog_history WHERE chat_id = $1 AND role = 'user' ORDER BY created_at DESC LIMIT 1", [chat_id]))
    let last_response = to_string(query("SELECT content FROM dialog_history WHERE chat_id = $1 AND role = 'assistant' ORDER BY created_at DESC LIMIT 1", [chat_id]))

    // Сохранить как положительный пример
    let _ = query("INSERT INTO adapt_corrections (dept, original_query, original_response, correction, created_at) VALUES ($1, $2, $3, '[GOOD_EXAMPLE]', $4)",
      [last_dept, last_query, substring(last_response, 0, 500), to_string(now())])

    let _ = query("INSERT INTO dept_metrics (dept, metric_name, metric_value, period, created_at) VALUES ($1, 'satisfaction', 5.0, 'task', $2)",
      [last_dept, to_string(now())])

    send_message(chat_id, "Otlichno! Zafiksirovano kak obrazcovyj otvet " + DeptDisplayName(last_dept))
    let _ = AuditLog("good", "owner", last_dept, "", "ok")
    return respond("200 ok")
  }
}
```

### 4. Monthly debrief (вызывается из scheduler /cron/monthly)

```mlog
pattern MonthlyDebrief() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")
  let depts = ["osp", "lz", "expert", "marketing", "finance", "legal", "dev", "design", "qa", "visual", "engineering", "kavalnya"]

  each dept in depts {
    // Подсчёт ошибок по типам за месяц
    let errors = to_string(query("SELECT error_type, COUNT(*) as cnt FROM error_patterns WHERE dept = $1 AND created_at > $2 GROUP BY error_type ORDER BY cnt DESC",
      [dept, to_string(now() - 2592000.0)]))

    let total_errors = to_string(query("SELECT COUNT(*) FROM error_patterns WHERE dept = $1 AND created_at > $2",
      [dept, to_string(now() - 2592000.0)]))

    let total_tasks = to_string(query("SELECT COUNT(*) FROM archive WHERE dept = $1 AND created_at > $2",
      [dept, to_string(now() - 2592000.0)]))

    let good_count = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE dept = $1 AND correction = '[GOOD_EXAMPLE]' AND created_at > $2",
      [dept, to_string(now() - 2592000.0)]))

    let avg_score = to_string(query("SELECT ROUND(AVG(metric_value), 1) FROM dept_metrics WHERE dept = $1 AND metric_name = 'satisfaction' AND created_at > $2",
      [dept, to_string(now() - 2592000.0)]))

    // Если есть ошибки — debrief
    if to_float(total_errors) > 0.0 then {
      let debrief_prompt = "Ty — Kaval'nya (metodolog). Provedi debrief otdela " + DeptDisplayName(dept) + ".\n\nDannye za mesyac:\n- Zadach: " + total_tasks + "\n- Oshibok: " + total_errors + "\n- Khoroshih primerov: " + good_count + "\n- Srednyaya ocenka: " + avg_score + "\n- Rasklady oshibok:\n" + errors + "\n\nAnaliz:\n1. Kakiye oshibki povtoryayutsya (pattern)\n2. Pochemu (kornevaya prichina)\n3. Kak ispravit' (konkretno: izmenenie prompta / dobavleniye pravila / izmenenie skilla)\n4. Prioritet izmenenij\n\nBEZ obvinitiel'noj ritoriki. Fakt → prichina → resheniye."
      let kavalnya_profile = read_file("library/kavalnya.md")
      let debrief = call_llm(kavalnya_profile + "\n\n" + debrief_prompt, "Debrief: " + DeptDisplayName(dept))

      // Сохранить debrief
      let _ = query("INSERT INTO debriefs (dept, period, content, created_at) VALUES ($1, 'monthly', $2, $3)",
        [dept, debrief, to_string(now())])

      let _ = AuditLog("debrief", "scheduler", dept, "errors: " + total_errors, "ok")
    }
  }

  // Общий отчёт
  let all_errors = to_string(query("SELECT dept, error_type, COUNT(*) as cnt FROM error_patterns WHERE created_at > $1 GROUP BY dept, error_type ORDER BY cnt DESC LIMIT 20",
    [to_string(now() - 2592000.0)]))

  let summary_prompt = "Ty — Yana. Svodnaya po learning loop za mesyac:\n\n" + all_errors + "\n\nSformuliruj:\n1. Top-3 problemnye otdely\n2. Top-3 tipa oshibok\n3. Konkretnyye rekomendacii dlya /build naryadov\n4. Kakie otdely uluchshilis' (good_count rastyot)"
  let yana_profile = read_file("library/yana.md")
  let summary = call_llm(yana_profile + "\n\n" + summary_prompt, "Learning loop summary")

  let _ = SendReport(summary, "kavalnya", "Monthly Learning Loop", 3.0, owner_id)
  return "ok"
}
```

### 5. Таблица debriefs

```mlog
db_execute("CREATE TABLE IF NOT EXISTS debriefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dept TEXT NOT NULL,
  period TEXT NOT NULL,
  content TEXT,
  actions_taken TEXT,
  created_at REAL
)")
```

### 6. Автоматическое улучшение промптов

После debrief — Кавальня формирует конкретные изменения промпта:

```mlog
pattern ProposePromptFix(dept: String, debrief: String) -> String {
  let fix_prompt = "Na osnove debriefa predlozhi konkretnyye izmeneniya v profil' otdela (library/" + dept + ".md).\n\nDebrief:\n" + debrief + "\n\nFormat:\n1. Kakuyu stroku/pravilo dobavit'\n2. Kakuyu izmenpit'\n3. Kakuyu udalit'\n\nTol'ko izmeneniya kotorye reshayut vyyavlennye problemy."
  let kavalnya_profile = read_file("library/kavalnya.md")
  let proposal = call_llm(kavalnya_profile + "\n\n" + fix_prompt, "Prompt fix for " + dept)
  return proposal
}
```

Яна показывает предложение владельцу:

```mlog
pattern OfferPromptImprovement(dept: String, chat_id: String) -> String {
  let last_debrief = to_string(query("SELECT content FROM debriefs WHERE dept = $1 ORDER BY created_at DESC LIMIT 1", [dept]))
  if len(last_debrief) < 10 then { return "net debriefov" }

  let proposal = ProposePromptFix(dept, last_debrief)
  let safe = escape_json(proposal)

  let body = json_encode({
    chat_id: to_float(chat_id),
    text: "Predlozhenie po uluchsheniyu " + DeptDisplayName(dept) + ":\n\n" + safe,
    reply_markup: {
      inline_keyboard: [
        [
          { text: "Primenit' (/build)", callback_data: "apply_fix_" + dept },
          { text: "Otlozhit'", callback_data: "skip_fix_" + dept }
        ]
      ]
    }
  })
  let token = env("TELEGRAM_BOT_TOKEN")
  http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")
  return "ok"
}
```

Обработка callback `apply_fix_`:
```mlog
  if starts_with(to_string(cb_data), "apply_fix_") then {
    let dept = substring(to_string(cb_data), 10, len(to_string(cb_data)))
    let last_debrief = to_string(query("SELECT content FROM debriefs WHERE dept = $1 ORDER BY created_at DESC LIMIT 1", [dept]))
    let proposal = ProposePromptFix(dept, last_debrief)
    // Создать наряд автоматически
    let narad_id = "narad-fix-" + dept + "-" + to_string(to_int(now()))
    let _ = query("INSERT INTO narads (id, title, description, requested_by, status, created_at) VALUES ($1, $2, $3, 'kavalnya', 'pending', $4)",
      [narad_id, "Fix prompt " + dept, proposal, to_string(now())])
    send_message(cb_chat_id, "Naryad " + narad_id + " sozdan. Podtverdite /build.")
    return respond("200 ok")
  }
```

### 7. Quarterly audit (каждые 3 месяца)

Добавить cron endpoint:

```mlog
route "/cron/quarterly" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = QuarterlyAudit()
  return respond("200 ok")
}
```

```mlog
pattern QuarterlyAudit() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")

  // Данные за 90 дней
  let all_tasks = to_string(query("SELECT dept, COUNT(*) as cnt FROM archive WHERE created_at > $1 GROUP BY dept ORDER BY cnt DESC",
    [to_string(now() - 7776000.0)]))
  let all_errors = to_string(query("SELECT dept, COUNT(*) as cnt FROM error_patterns WHERE created_at > $1 GROUP BY dept ORDER BY cnt DESC",
    [to_string(now() - 7776000.0)]))
  let all_scores = to_string(query("SELECT dept, ROUND(AVG(metric_value), 1) as avg FROM dept_metrics WHERE metric_name = 'satisfaction' AND created_at > $1 GROUP BY dept ORDER BY avg ASC",
    [to_string(now() - 7776000.0)]))
  let debriefs_done = to_string(query("SELECT dept, COUNT(*) FROM debriefs WHERE created_at > $1 GROUP BY dept",
    [to_string(now() - 7776000.0)]))

  let audit_prompt = "Ty — Kaval'nya. Kvartal'nyj audit ofisa.\n\nZadachi po otdelam:\n" + all_tasks + "\n\nOshibki:\n" + all_errors + "\n\nOcenki:\n" + all_scores + "\n\nDebriefs provedeny:\n" + debriefs_done + "\n\nAnaliz:\n1. Kakie otdely ne ispol'zuyutsya — predlozhit' udaleniye?\n2. Kakie degradirovali — rekalibrovka\n3. Kakikh ne khvatayet — predlozhit' sozdaniye\n4. Methodology review — chto pomenyat' v podkhode\n5. Obshchiy zdorov'ye ofisa (1-10)"
  let kavalnya_profile = read_file("library/kavalnya.md")
  let audit = call_llm(kavalnya_profile + "\n\n" + audit_prompt, "Kvartal'nyj audit")

  let _ = SendReport(audit, "kavalnya", "Quarterly Audit", 4.0, owner_id)
  let _ = AuditLog("quarterly_audit", "scheduler", "kavalnya", "", "ok")
  return "ok"
}
```

### 8. Команда /learning — статистика обучения

```mlog
match text {
  "/learning" then {
    let total_fixes = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE correction != '[GOOD_EXAMPLE]'", []))
    let total_goods = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE correction = '[GOOD_EXAMPLE]'", []))
    let total_debriefs = to_string(query("SELECT COUNT(*) FROM debriefs", []))
    let top_errors = to_string(query("SELECT error_type, COUNT(*) as cnt FROM error_patterns GROUP BY error_type ORDER BY cnt DESC LIMIT 5", []))

    let msg = "Learning Loop:\n- Korrekcij (/fix): " + total_fixes + "\n- Khoroshih primerov (/good): " + total_goods + "\n- Debriefs provedeno: " + total_debriefs + "\n\nTop oshibki:\n" + top_errors
    send_message(chat_id, msg)
    return respond("200 ok")
  }
}
```

### 9. Интеграция с MonthlyReview (наряд #17)

Добавить вызов MonthlyDebrief в MonthlyReview:

```mlog
pattern MonthlyReview() -> String {
  // ... существующий код ...
  let _ = MonthlyDebrief()
  return "ok"
}
```

---

## Команды

| Команда | Действие |
|---|---|
| `/fix <текст>` | Коррекция последнего ответа (+ классификация ошибки) |
| `/good` | Отметить последний ответ как образцовый |
| `/rate N` | Оценка (уже есть из наряда #12) |
| `/learning` | Статистика обучения |
| `/debrief osp` | Ручной debrief конкретного отдела |

---

## Цикл обучения (визуально)

```
Владелец даёт задачу
       │
       ▼
Отдел отвечает (с учётом прошлых коррекций из BuildContext)
       │
       ├── /good → положительный пример → усиливает паттерн
       ├── /fix → коррекция → классификация ошибки → adapt_corrections
       ├── /rate → метрика → dept_metrics
       └── (молчание) → нейтрально
       │
       ▼
Monthly: кластеризация ошибок → debrief → предложение улучшения промпта
       │
       ▼
Владелец: ✅ → /build наряд → агент меняет library/*.md
       │
       ▼
Следующий вызов отдела → улучшенный промпт → лучше ответ
```

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /fix ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/fix slishkom obshchij otvet, nuzhna konkretika po EdTech","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T2: /good ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/good","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: /learning ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/learning","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Learning loop: /fix with error classification, /good, monthly debrief, quarterly audit, prompt improvement proposals"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №18

1. Таблица error_patterns: [✅/❌]
2. Таблица debriefs: [✅/❌]
3. /fix с классификацией ошибки: [✅/❌]
4. /good положительное подкрепление: [✅/❌]
5. /learning статистика: [✅/❌]
6. MonthlyDebrief: [✅/❌]
7. ProposePromptFix: [✅/❌]
8. QuarterlyAudit: [✅/❌]
9. /cron/quarterly endpoint: [✅/❌]
10. Интеграция с MonthlyReview: [✅/❌]
11. Callback apply_fix: [✅/❌]
12. T1-T3 проверки: [✅/❌]
13. git push: [✅/❌] [хэш]
14. Проблемы: [если есть]
```
