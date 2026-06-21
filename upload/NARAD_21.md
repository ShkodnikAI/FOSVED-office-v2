# НАРЯД №21: Экономика токенов — мониторинг расходов

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** подсчёт расхода токенов по отделам и моделям, /cost, рекомендации по оптимизации, лимиты

---

## Концепция

Каждый LLM-вызов стоит денег. Офис должен знать сколько тратит, на что, и предлагать оптимизацию. Владелец видит расходы в реальном времени через `/cost` и Mini App офиса.

---

## Реализация

### 1. Таблица расходов

```mlog
db_execute("CREATE TABLE IF NOT EXISTS token_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dept TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens REAL DEFAULT 0,
  output_tokens REAL DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  request_type TEXT DEFAULT 'dept',
  created_at REAL
)")
```

`request_type`: `dept` (отдел), `routing` (маршрутизация Яны), `chain` (составной), `context` (выбор скиллов), `factory` (фабрика), `scheduler` (cron), `debrief` (learning loop)

### 2. Тарифы моделей

```mlog
pattern GetTokenCost(provider: String, model: String, input_tokens: Float, output_tokens: Float) -> Float {
  // Цены за 1M токенов (USD), актуальные на 2026
  let input_rate = 0.0
  let output_rate = 0.0

  match provider {
    "zai" then {
      match model {
        contains "4.6" then { let input_rate = 0.5   let output_rate = 1.5 }
        contains "5.1" then { let input_rate = 0.98  let output_rate = 3.08 }
        else { let input_rate = 0.5  let output_rate = 1.5 }
      }
    }
    "deepseek" then {
      match model {
        contains "reasoner" then { let input_rate = 0.55  let output_rate = 2.19 }
        else { let input_rate = 0.14  let output_rate = 0.28 }
      }
    }
    "groq" then {
      // Groq: бесплатный tier, потом дешёвый
      let input_rate = 0.05
      let output_rate = 0.08
    }
    "grok" then {
      match model {
        contains "mini" then { let input_rate = 0.3  let output_rate = 0.5 }
        else { let input_rate = 3.0  let output_rate = 15.0 }
      }
    }
    "anthropic" then {
      match model {
        contains "opus" then { let input_rate = 15.0  let output_rate = 75.0 }
        contains "sonnet" then { let input_rate = 3.0  let output_rate = 15.0 }
        contains "haiku" then { let input_rate = 0.25  let output_rate = 1.25 }
        else { let input_rate = 3.0  let output_rate = 15.0 }
      }
    }
    "openai" then {
      match model {
        contains "4o-mini" then { let input_rate = 0.15  let output_rate = 0.6 }
        contains "4o" then { let input_rate = 2.5  let output_rate = 10.0 }
        else { let input_rate = 2.5  let output_rate = 10.0 }
      }
    }
    else { let input_rate = 1.0  let output_rate = 3.0 }
  }

  let cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000000.0
  return cost
}
```

### 3. Трекинг каждого LLM-вызова

Обернуть каждый `call_llm` в трекер. Создать pattern-обёртку:

```mlog
pattern TrackedLLM(dept: String, request_type: String, system_prompt: String, user_message: String) -> String {
  let config = read_file("config/priority_provider.txt") + " " + read_file("config/priority_model.txt")
  let override = read_file("config/override_" + dept + ".txt")
  if len(override) > 2 then { let config = override }

  let provider = trim(substring(config, 0, index_of(config, " ")))
  let model = trim(substring(config, index_of(config, " ") + 1, len(config)))
  let api_key = GetApiKey(provider)

  // Оценка токенов (приблизительно: 1 токен ≈ 4 символа)
  let input_tokens = (len(system_prompt) + len(user_message)) / 4.0
  let start_time = now()

  let result = call_llm(system_prompt, user_message)

  let output_tokens = len(result) / 4.0
  let cost = GetTokenCost(provider, model, input_tokens, output_tokens)

  // Записать
  let _ = query("INSERT INTO token_usage (dept, provider, model, input_tokens, output_tokens, cost_usd, request_type, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
    [dept, provider, model, to_string(input_tokens), to_string(output_tokens), to_string(cost), request_type, to_string(now())])

  return result
}
```

**Заменить все прямые `call_llm` на `TrackedLLM` во всех отделах.** Это главная задача наряда.

### 4. Команда `/cost` — текущие расходы

```mlog
match text {
  "/cost" then {
    let today_cost = to_string(query("SELECT ROUND(SUM(cost_usd), 4) FROM token_usage WHERE created_at > $1", [to_string(now() - 86400.0)]))
    let week_cost = to_string(query("SELECT ROUND(SUM(cost_usd), 4) FROM token_usage WHERE created_at > $1", [to_string(now() - 604800.0)]))
    let month_cost = to_string(query("SELECT ROUND(SUM(cost_usd), 4) FROM token_usage WHERE created_at > $1", [to_string(now() - 2592000.0)]))
    let total_cost = to_string(query("SELECT ROUND(SUM(cost_usd), 4) FROM token_usage", []))

    let by_dept = to_string(query("SELECT dept, ROUND(SUM(cost_usd), 4) as cost FROM token_usage WHERE created_at > $1 GROUP BY dept ORDER BY cost DESC", [to_string(now() - 2592000.0)]))
    let by_provider = to_string(query("SELECT provider, model, ROUND(SUM(cost_usd), 4) as cost FROM token_usage WHERE created_at > $1 GROUP BY provider, model ORDER BY cost DESC", [to_string(now() - 2592000.0)]))

    let calls_today = to_string(query("SELECT COUNT(*) FROM token_usage WHERE created_at > $1", [to_string(now() - 86400.0)]))
    let tokens_today = to_string(query("SELECT ROUND(SUM(input_tokens + output_tokens)) FROM token_usage WHERE created_at > $1", [to_string(now() - 86400.0)]))

    let msg = "Ekonomika tokenov:\n\n"
      + "Segodnya: $" + today_cost + " (" + calls_today + " vyzovov, " + tokens_today + " tokenov)\n"
      + "Nedelya: $" + week_cost + "\n"
      + "Mesyac: $" + month_cost + "\n"
      + "Vsego: $" + total_cost + "\n\n"
      + "Po otdelam (mesyac):\n" + by_dept + "\n\n"
      + "Po modelyam (mesyac):\n" + by_provider

    send_message(chat_id, msg)
    let _ = AuditLog("cost_check", "owner", "", "today=$" + today_cost, "ok")
    return respond("200 ok")
  }
}
```

### 5. Команда `/cost dept <slug>` — детально по отделу

```mlog
match text {
  starts_with "/cost dept " then {
    let dept = trim(substring(text, 11, len(text)))
    let dept_name = DeptDisplayName(dept)

    let month_cost = to_string(query("SELECT ROUND(SUM(cost_usd), 4) FROM token_usage WHERE dept = $1 AND created_at > $2", [dept, to_string(now() - 2592000.0)]))
    let calls = to_string(query("SELECT COUNT(*) FROM token_usage WHERE dept = $1 AND created_at > $2", [dept, to_string(now() - 2592000.0)]))
    let avg_cost = to_string(query("SELECT ROUND(AVG(cost_usd), 6) FROM token_usage WHERE dept = $1 AND created_at > $2", [dept, to_string(now() - 2592000.0)]))
    let by_type = to_string(query("SELECT request_type, COUNT(*) as cnt, ROUND(SUM(cost_usd), 4) as cost FROM token_usage WHERE dept = $1 AND created_at > $2 GROUP BY request_type", [dept, to_string(now() - 2592000.0)]))
    let model_used = to_string(query("SELECT provider, model FROM token_usage WHERE dept = $1 ORDER BY created_at DESC LIMIT 1", [dept]))

    let msg = dept_name + " — ekonomika:\n\n"
      + "Raskhod za mesyac: $" + month_cost + "\n"
      + "Vyzovov: " + calls + "\n"
      + "Srednij vyzov: $" + avg_cost + "\n"
      + "Model': " + model_used + "\n\n"
      + "Po tipam:\n" + by_type

    send_message(chat_id, msg)
    return respond("200 ok")
  }
}
```

### 6. Лимиты расходов

```mlog
pattern CheckBudgetLimit(dept: String, cost: Float) -> String {
  let daily_limit_str = kv_get("budget_daily_limit")
  let daily_limit = if len(daily_limit_str) > 0 then to_float(daily_limit_str) else 5.0

  let today_spent = to_float(to_string(query("SELECT COALESCE(SUM(cost_usd), 0) FROM token_usage WHERE created_at > $1", [to_string(now() - 86400.0)])))

  if today_spent + cost > daily_limit then {
    return "LIMIT_EXCEEDED"
  }
  return "ok"
}
```

Команды управления лимитом:

```mlog
match text {
  starts_with "/budget " then {
    let limit = substring(text, 8, len(text))
    kv_set("budget_daily_limit", limit)
    send_message(chat_id, "Dnevnoj limit: $" + limit)
    return respond("200 ok")
  }
  "/budget" then {
    let limit = kv_get("budget_daily_limit")
    if len(limit) < 1 then { let limit = "5.0" }
    let today_spent = to_string(query("SELECT ROUND(COALESCE(SUM(cost_usd), 0), 4) FROM token_usage WHERE created_at > $1", [to_string(now() - 86400.0)]))
    send_message(chat_id, "Dnevnoj limit: $" + limit + "\nPotrachenosegodnya: $" + today_spent)
    return respond("200 ok")
  }
}
```

При превышении лимита — предупреждение:

```mlog
// В TrackedLLM, перед вызовом:
  let budget_check = CheckBudgetLimit(dept, input_tokens * 3.0 / 1000000.0)
  if budget_check == "LIMIT_EXCEEDED" then {
    return "[BUDGET LIMIT] Dnevnoj limit ispolzovaniya LLM isscherpan. Uvelich'te /budget N ili dozhdites' zavtra."
  }
```

### 7. Рекомендации по оптимизации

В monthly review (наряд #17) добавить анализ расходов:

```mlog
pattern CostOptimizationAdvice() -> String {
  let by_dept = to_string(query("SELECT dept, ROUND(SUM(cost_usd), 2) as cost, COUNT(*) as calls FROM token_usage WHERE created_at > $1 GROUP BY dept ORDER BY cost DESC LIMIT 5", [to_string(now() - 2592000.0)]))
  let by_type = to_string(query("SELECT request_type, ROUND(SUM(cost_usd), 2) as cost, COUNT(*) as calls FROM token_usage WHERE created_at > $1 GROUP BY request_type ORDER BY cost DESC", [to_string(now() - 2592000.0)]))
  let expensive_models = to_string(query("SELECT provider, model, ROUND(SUM(cost_usd), 2) as cost FROM token_usage WHERE created_at > $1 GROUP BY provider, model ORDER BY cost DESC", [to_string(now() - 2592000.0)]))

  let prompt = "Proanalyziruj raskhody ofisa na LLM i daj rekomendacii:\n\nPo otdelam:\n" + by_dept + "\n\nPo tipam zaprosov:\n" + by_type + "\n\nPo modelyam:\n" + expensive_models + "\n\nRekomendacii:\n1. Kakie otdely mozhno perevesti na deshyovuyu model' bez poteri kachestva?\n2. Kakie tipy zaprosov (routing, context) mozhno optimizirovat'?\n3. Gde mozhno ispol'zovat' Groq (besplatno) vmesto platnyx?\n4. Est' li otdely kotorye tratyat neproporcionial'no mnogo?"

  let advice = call_llm(prompt, "Cost optimization")
  return advice
}
```

Добавить вызов в MonthlyReview:
```mlog
  // В MonthlyReview, после остального:
  let cost_advice = CostOptimizationAdvice()
  let _ = SendReport(cost_advice, "yana", "Cost Optimization", 2.0, owner_id)
```

### 8. Экономика в Mini App офиса

Добавить секцию в office_panel template (наряд #13):

```html
<div class="section">
  <div class="section-title">Ekonomika tokenov</div>
  <div class="stats" style="grid-template-columns:1fr 1fr 1fr">
    <div class="stat"><div class="stat-val">{{ cost_today }}</div><div class="stat-lbl">Segodnya</div></div>
    <div class="stat"><div class="stat-val">{{ cost_week }}</div><div class="stat-lbl">Nedelya</div></div>
    <div class="stat"><div class="stat-val">{{ cost_month }}</div><div class="stat-lbl">Mesyac</div></div>
  </div>
  {{ cost_by_dept_html | safe }}
</div>
```

В BuildOfficePanel добавить:
```mlog
  let cost_today = "$" + to_string(query("SELECT ROUND(COALESCE(SUM(cost_usd),0), 2) FROM token_usage WHERE created_at > $1", [to_string(now() - 86400.0)]))
  let cost_week = "$" + to_string(query("SELECT ROUND(COALESCE(SUM(cost_usd),0), 2) FROM token_usage WHERE created_at > $1", [to_string(now() - 604800.0)]))
  let cost_month = "$" + to_string(query("SELECT ROUND(COALESCE(SUM(cost_usd),0), 2) FROM token_usage WHERE created_at > $1", [to_string(now() - 2592000.0)]))
  let cost_by_dept = to_string(query("SELECT dept, ROUND(SUM(cost_usd), 2) as c FROM token_usage WHERE created_at > $1 GROUP BY dept ORDER BY c DESC LIMIT 5", [to_string(now() - 2592000.0)]))
  let cost_by_dept_html = "<p>" + escape_html(cost_by_dept) + "</p>"
```

### 9. Экономика в дайджестах

В EveningSummary и WeeklyDigest добавить строку расхода:
```mlog
  let cost_today = to_string(query("SELECT ROUND(COALESCE(SUM(cost_usd),0), 4) FROM token_usage WHERE created_at > $1", [to_string(now() - 43200.0)]))
  // Добавить в текст: "Raskhod LLM: $" + cost_today
```

---

## Команды

| Команда | Действие |
|---|---|
| `/cost` | Общая экономика (сегодня/неделя/месяц, по отделам, по моделям) |
| `/cost dept <slug>` | Детально по конкретному отделу |
| `/budget` | Текущий лимит и остаток |
| `/budget N` | Установить дневной лимит ($N) |

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /cost ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/cost","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T2: /budget ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/budget","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: /budget 10 ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/budget 10","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T4: /cost dept osp ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/cost dept osp","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Token economics: /cost, /budget, TrackedLLM, per-dept tracking, optimization advice, daily limits"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №21

1. Таблица token_usage: [✅/❌]
2. GetTokenCost (6 провайдеров): [✅/❌]
3. TrackedLLM обёртка: [✅/❌]
4. Все call_llm заменены на TrackedLLM: [✅/❌]
5. /cost команда: [✅/❌]
6. /cost dept <slug>: [✅/❌]
7. /budget лимит: [✅/❌]
8. CheckBudgetLimit: [✅/❌]
9. CostOptimizationAdvice: [✅/❌]
10. Экономика в Mini App офиса: [✅/❌]
11. Экономика в дайджестах: [✅/❌]
12. T1-T4 проверки: [✅/❌]
13. git push: [✅/❌] [хэш]
14. Проблемы: [если есть]
```
