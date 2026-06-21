# НАРЯД №17: Scheduler — автоматические задачи по расписанию

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** утренний brief, вечерний свод, monthly метрики, quarterly аудит, сверка контрольных прогнозов

---

## Концепция

Офис работает не только по запросу, но и проактивно. Scheduler запускает задачи по расписанию и отправляет результат владельцу в Telegram.

---

## Архитектура

Metalogos не имеет встроенного cron. Два подхода:

**Подход A (рекомендуемый): HTTP-endpoint + внешний cron.**
Render поддерживает Cron Jobs — отдельный сервис который делает HTTP GET к основному серверу по расписанию.

**Подход B: polling loop внутри сервера.**
Фоновый поток проверяет время каждую минуту. Сложнее, может конфликтовать с async.

**Выбираем подход A** — проще, надёжнее, Render поддерживает нативно.

---

## Реализация

### 1. Маршруты для cron

```mlog
// Эти маршруты вызываются Render Cron Jobs
// Защита: проверяем секретный заголовок чтобы никто извне не вызвал

route "/cron/morning" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = MorningBrief()
  return respond("200 ok")
}

route "/cron/evening" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = EveningSummary()
  return respond("200 ok")
}

route "/cron/weekly" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = WeeklyDigest()
  return respond("200 ok")
}

route "/cron/monthly" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = MonthlyReview()
  return respond("200 ok")
}

route "/cron/control" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = ControlCheck()
  return respond("200 ok")
}
```

### 2. Утренний brief (8:00, ежедневно)

```mlog
pattern MorningBrief() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")

  // Собираем данные
  let tasks_yesterday = to_string(query("SELECT COUNT(*) FROM archive WHERE created_at > $1", [to_string(now() - 86400.0)]))
  let unresolved = to_string(query("SELECT COUNT(*) FROM narads WHERE status = 'pending'", []))
  let watches = kv_list("control_")
  let corrections = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE created_at > $1", [to_string(now() - 86400.0)]))

  // LLM формирует brief
  let brief_prompt = "Ty — Yana. Sostav' utrennij brief dlya vladel'ca. Kratko, 5-7 stroki. Dannie:\n- Zadach za vchera: " + tasks_yesterday + "\n- Nereshennyh naryadov: " + unresolved + "\n- Korrekcij za vchera: " + corrections + "\n- Tem na kontrole: " + to_string(len(watches))
  let yana_profile = read_file("library/yana.md")
  let brief = call_llm(yana_profile + "\n\n" + brief_prompt, "Utrennij brief")

  send_message(owner_id, "Dobroye utro!\n\n" + brief)
  let _ = AuditLog("morning_brief", "scheduler", "yana", "", "ok")
  return "ok"
}
```

### 3. Вечерний свод (21:00, ежедневно)

```mlog
pattern EveningSummary() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")

  let tasks_today = to_string(query("SELECT COUNT(*) FROM archive WHERE created_at > $1", [to_string(now() - 43200.0)]))
  let depts_used = to_string(query("SELECT DISTINCT dept FROM archive WHERE created_at > $1", [to_string(now() - 43200.0)]))
  let avg_score = to_string(query("SELECT ROUND(AVG(metric_value), 1) FROM dept_metrics WHERE created_at > $1 AND metric_name = 'satisfaction'", [to_string(now() - 43200.0)]))

  let summary_prompt = "Ty — Yana. Sostav' vechernij svod. Kratko:\n- Zadach segodnya: " + tasks_today + "\n- Otdely rabotali: " + depts_used + "\n- Srednyaya ocenka: " + avg_score + "\n- Chto perenesti na zavtra, na chyom akcentirovat'"
  let yana_profile = read_file("library/yana.md")
  let summary = call_llm(yana_profile + "\n\n" + summary_prompt, "Vechernij svod")

  send_message(owner_id, summary)
  let _ = AuditLog("evening_summary", "scheduler", "yana", "", "ok")
  return "ok"
}
```

### 4. Еженедельный дайджест (понедельник 9:00)

```mlog
pattern WeeklyDigest() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")

  let tasks_week = to_string(query("SELECT COUNT(*) FROM archive WHERE created_at > $1", [to_string(now() - 604800.0)]))
  let top_depts = to_string(query("SELECT dept, COUNT(*) as cnt FROM archive WHERE created_at > $1 GROUP BY dept ORDER BY cnt DESC LIMIT 5", [to_string(now() - 604800.0)]))
  let avg_week = to_string(query("SELECT ROUND(AVG(metric_value), 1) FROM dept_metrics WHERE created_at > $1 AND metric_name = 'satisfaction'", [to_string(now() - 604800.0)]))
  let corrections_week = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE created_at > $1", [to_string(now() - 604800.0)]))
  let narads_week = to_string(query("SELECT COUNT(*) FROM narads WHERE created_at > $1", [to_string(now() - 604800.0)]))

  let digest_prompt = "Ty — Yana. Nedel'nyj daydzhest:\n- Zadach: " + tasks_week + "\n- Top otdely: " + top_depts + "\n- Srednyaya ocenka: " + avg_week + "\n- Korrekcij: " + corrections_week + "\n- Naryadov: " + narads_week + "\nVydeli trendy, problemy, rekomendacii."
  let yana_profile = read_file("library/yana.md")
  let digest = call_llm(yana_profile + "\n\n" + digest_prompt, "Nedel'nyj daydzhest")

  let _ = SendReport(digest, "yana", "Nedel'nyj daydzhest", 2.0, owner_id)
  let _ = AuditLog("weekly_digest", "scheduler", "yana", "", "ok")
  return "ok"
}
```

### 5. Ежемесячный review (1-е число, 10:00)

```mlog
pattern MonthlyReview() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")

  // Метрики по каждому отделу
  let depts = ["osp", "lz", "expert", "marketing", "finance", "legal", "dev", "design", "qa", "visual", "engineering", "kavalnya"]
  let metrics_summary = ""
  each dept in depts {
    let count = to_string(query("SELECT COUNT(*) FROM archive WHERE dept = $1 AND created_at > $2", [dept, to_string(now() - 2592000.0)]))
    let avg = to_string(query("SELECT ROUND(AVG(metric_value), 1) FROM dept_metrics WHERE dept = $1 AND metric_name = 'satisfaction' AND created_at > $2", [dept, to_string(now() - 2592000.0)]))
    let corr = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE dept = $1 AND created_at > $2", [dept, to_string(now() - 2592000.0)]))
    let name = DeptDisplayName(dept)
    let metrics_summary = metrics_summary + name + ": " + count + " zadach, ocenka " + avg + ", " + corr + " korrekcij\n"
  }

  let review_prompt = "Ty — Yana. Ezhemesyachnyj review ofisa:\n\n" + metrics_summary + "\nAnaliz:\n1. Kakie otdely rabotali luchshe vsego\n2. Kakie degrasdirovali\n3. Kakie ne ispol'zovalis'\n4. Rekomendacii po uluchsheniyu\n5. Predlozhit' rekalibrovku dlya otdelov s ocenkoj < 3"
  let yana_profile = read_file("library/yana.md")
  let review = call_llm(yana_profile + "\n\n" + review_prompt, "Ezhemesyachnyj review")

  let _ = SendReport(review, "yana", "Monthly Review", 3.0, owner_id)
  let _ = AuditLog("monthly_review", "scheduler", "yana", "", "ok")
  return "ok"
}
```

### 6. Сверка контрольных прогнозов

```mlog
pattern ControlCheck() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")

  // Получить все прогнозы на контроле
  let keys = kv_list("control_")
  let checks_done = 0.0

  each key in keys {
    let val = kv_get(key)
    // val = "daily|Тема прогноза" или "weekly|Тема" или "monthly|Тема"
    let pipe_pos = index_of(val, "|")
    let freq = substring(val, 0, pipe_pos)
    let topic = substring(val, pipe_pos + 1, len(val))
    let doc_id = replace(key, "control_", "")

    // Проверяем нужно ли сверять сегодня
    let should_check = 0.0
    if freq == "daily" then { let should_check = 1.0 }
    // weekly и monthly проверяются тем же cron, но реже
    // Для простоты: /cron/control вызывается ежедневно,
    // weekly проверяется по дню недели, monthly по числу

    if should_check == 1.0 then {
      // Получить оригинальный прогноз
      let original = to_string(query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [doc_id]))

      // LLM сверяет прогноз с текущей реальностью
      let check_prompt = "Ty — analitik OSP. Sver' prognoz s tekushchej real'nost'yu.\n\nOriginal'nyj prognoz:\n" + substring(original, 0, 2000) + "\n\nOtveti:\n1. Kakiye chasti prognoza podtverdilis'?\n2. Kakiye oprovergnuty?\n3. Kakiye ne provereny?\n4. Obnovlyonnyj prognoz\n5. Novaya ocenka confidence"
      let osp_profile = read_file("library/osp.md")
      let check_result = call_llm(osp_profile + "\n\n" + check_prompt, "Sverka prognoza: " + topic)

      let _ = SendReport(check_result, "osp", "Sverka: " + topic, 2.0, owner_id)
      let checks_done = checks_done + 1.0
    }
  }

  if checks_done > 0.0 then {
    let _ = AuditLog("control_check", "scheduler", "osp", to_string(checks_done) + " prognozov svereno", "ok")
  }
  return "ok"
}
```

### 7. Самообучение Яны (ежедневно)

```mlog
pattern YanaSelfLearn() -> String {
  // Яна выбирает тему дня и изучает её
  let learn_prompt = "Ty — Yana. Vyberisebetemu dlya samoobucheniya segodnya. Oblasti: AI, biznyes, upravleniye, psihologiya, tekhnologii. Kratko izuchi (3-5 abzacev). Zafiksiruytes' nahodku v pamyati."

  let yana_profile = read_file("library/yana.md")
  let learned = call_llm(yana_profile + "\n\n" + learn_prompt, "Samoobuchenie")

  // Сохранить в память
  let _ = memorize("self_learn: " + substring(learned, 0, 200), 0.6)
  let _ = AuditLog("self_learn", "scheduler", "yana", substring(learned, 0, 100), "ok")
  return "ok"
}
```

Добавить вызов в morning cron:
```mlog
route "/cron/morning" method=GET {
  ...
  let _ = MorningBrief()
  let _ = YanaSelfLearn()
  return respond("200 ok")
}
```

---

## Настройка Render Cron Jobs

В Render dashboard → New → Cron Job для каждого расписания:

| Cron Job | Schedule | URL |
|---|---|---|
| Morning Brief | `0 8 * * *` (8:00 UTC или по часовому поясу) | `GET https://fosved-office-v2.onrender.com/cron/morning?secret=<CRON_SECRET>` |
| Evening Summary | `0 21 * * *` | `GET .../cron/evening?secret=<CRON_SECRET>` |
| Weekly Digest | `0 9 * * 1` (пн 9:00) | `GET .../cron/weekly?secret=<CRON_SECRET>` |
| Monthly Review | `0 10 1 * *` (1-е число 10:00) | `GET .../cron/monthly?secret=<CRON_SECRET>` |
| Control Check | `0 12 * * *` (12:00 ежедневно) | `GET .../cron/control?secret=<CRON_SECRET>` |

**Альтернатива Render Cron Jobs:** если нет — использовать бесплатный cron-as-a-service (cron-job.org, easycron.com) для HTTP GET по расписанию.

### Переменная окружения

```
CRON_SECRET=<случайная строка 32+ символа>
```

---

## Команды ручного запуска

```mlog
match text {
  "/brief" then {
    let _ = MorningBrief()
    return respond("200 ok")
  }
  "/digest" then {
    let _ = WeeklyDigest()
    return respond("200 ok")
  }
  "/review" then {
    let _ = MonthlyReview()
    return respond("200 ok")
  }
}
```

---

## Локальная проверка

```bash
export CRON_SECRET=test123
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /cron/morning ==="
curl -s "http://localhost:10000/cron/morning?secret=test123"

echo "=== T2: /cron/evening ==="
curl -s "http://localhost:10000/cron/evening?secret=test123"

echo "=== T3: без секрета (должен 403) ==="
curl -s "http://localhost:10000/cron/morning"

echo "=== T4: /brief (ручной) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/brief","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Scheduler: morning brief, evening summary, weekly digest, monthly review, control check, self-learn"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №17

1. /cron/morning: [✅/❌]
2. /cron/evening: [✅/❌]
3. /cron/weekly: [✅/❌]
4. /cron/monthly: [✅/❌]
5. /cron/control (сверка прогнозов): [✅/❌]
6. YanaSelfLearn: [✅/❌]
7. CRON_SECRET защита: [✅/❌]
8. /brief, /digest, /review ручные: [✅/❌]
9. SendReport для дайджестов: [✅/❌]
10. Audit log интеграция: [✅/❌]
11. T1-T4 проверки: [✅/❌]
12. git push: [✅/❌] [хэш]
13. Проблемы: [если есть]
```
