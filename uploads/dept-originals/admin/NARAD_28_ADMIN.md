# НАРЯД №28: Админ — системный агент офиса

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** Админ — автономный агент: ночной цикл анализа, knowledge graph, автофиксы, предложения, деплой

---

## КОНЦЕПЦИЯ

Админ — системный администратор Fosved Office. Не отдел, а персона на уровне Яны. Яна общается с владельцем, Админ работает с кодом.

```
Владелец
    ├── Яна (общение, маршрутизация, brief'ы)
    ├── Админ (код, анализ, оптимизация, деплой, ночной цикл)
    └── 13 отделов (задачи)
```

Админ работает в двух режимах:
- **По запросу:** `/admin build`, `/admin fix`, `/admin analyze`
- **Автономно:** ночной цикл (3:00–7:00), анализирует код, ищет баги, предлагает улучшения

---

## ЧАСТЬ 1: ПРОФИЛЬ АДМИНА

### library/admin.md

```markdown
# Админ — системный агент Fosved Office

Ты — Админ, системный администратор AI-офиса. Не отдел, а инфраструктурная персона.

## Роль
- Анализ и оптимизация кодовой базы (.mlog файлов)
- Поиск багов, мёртвого кода, дублирования
- Построение и поддержание knowledge graph
- Автофиксы low-risk проблем
- Предложения по новым функциям и отделам
- Impact analysis перед изменениями
- Деплой и откат

## Жёсткие правила
1. НИКОГДА не менять immutable зоны (audit_log, lockdown, bin/mlog)
2. Автофиксы ТОЛЬКО для low-risk (конфиг, мёртвый код, typo)
3. Любое изменение логики — через наряд с подтверждением владельца
4. Каждое действие — в audit_log
5. Бэкап перед каждым write_file
6. Не ломай зелёное — после изменения все существующие функции должны работать

## Тон
Технический, лаконичный. Не объясняй что делаешь — показывай результат.
Формат отчёта: файл → проблема → решение → риск.
```

---

## ЧАСТЬ 2: KNOWLEDGE GRAPH

### 2.1. Таблица

```sql
CREATE TABLE IF NOT EXISTS knowledge_graph (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_type TEXT NOT NULL,
  node_name TEXT NOT NULL,
  file_path TEXT,
  line_start INTEGER,
  line_end INTEGER,
  description TEXT,
  updated_at REAL
)

CREATE TABLE IF NOT EXISTS knowledge_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name TEXT NOT NULL,
  target_name TEXT NOT NULL,
  edge_type TEXT NOT NULL,
  file_path TEXT,
  updated_at REAL
)
```

`node_type`: `file`, `pattern`, `template`, `route`, `table`, `command`, `builtin_call`
`edge_type`: `imports`, `calls`, `reads`, `writes`, `creates_table`, `sends_message`, `routes_to`

### 2.2. Pattern BuildKnowledgeGraph

```mlog
pattern BuildKnowledgeGraph() -> String {
  // 1. Список всех .mlog файлов
  let files = list_dir(".")
  let dept_files = list_dir("dept/")

  // 2. Для каждого файла — LLM извлекает структуру
  let admin_profile = read_file("library/admin.md")
  let extract_prompt = admin_profile + "\n\nИзвлеки из кода структуру. Для каждого файла верни JSON:\n{\"patterns\": [{\"name\": \"X\", \"calls\": [\"Y\", \"Z\"], \"reads\": [\"file.md\"], \"writes\": [\"file.txt\"]}], \"routes\": [\"/path\"], \"tables\": [\"name\"], \"imports\": [\"module.mlog\"], \"commands\": [\"/cmd\"]}"

  each file in files {
    if ends_with(to_string(file), ".mlog") then {
      let content = read_file(to_string(file))
      let analysis = call_llm(extract_prompt, "Файл: " + to_string(file) + "\n\n" + substring(content, 0, 3000))
      let parsed = parse_json(analysis)
      // Записать nodes и edges в таблицы
      let _ = SaveGraphNodes(to_string(file), parsed)
    }
  }

  each file in dept_files {
    if ends_with(to_string(file), ".mlog") then {
      let content = read_file("dept/" + to_string(file))
      let analysis = call_llm(extract_prompt, "Файл: dept/" + to_string(file) + "\n\n" + substring(content, 0, 3000))
      let parsed = parse_json(analysis)
      let _ = SaveGraphNodes("dept/" + to_string(file), parsed)
    }
  }

  let node_count = to_string(query("SELECT COUNT(*) FROM knowledge_graph", []))
  let edge_count = to_string(query("SELECT COUNT(*) FROM knowledge_edges", []))
  return "Graph: " + node_count + " nodes, " + edge_count + " edges"
}
```

### 2.3. Impact Analysis

```mlog
pattern ImpactAnalysis(file_path: String) -> String {
  // Найти все файлы которые зависят от file_path
  let dependents = to_string(query(
    "SELECT DISTINCT source_name FROM knowledge_edges WHERE target_name = $1",
    [file_path]
  ))

  // Найти все файлы от которых зависит file_path
  let dependencies = to_string(query(
    "SELECT DISTINCT target_name FROM knowledge_edges WHERE source_name = $1",
    [file_path]
  ))

  let result = "Impact Analysis: " + file_path + "\n\n"
    + "Зависят от этого файла:\n" + dependents + "\n\n"
    + "Этот файл зависит от:\n" + dependencies

  return result
}
```

### 2.4. Поиск проблем по графу

```mlog
pattern FindOrphans() -> String {
  // Файлы которые никто не импортирует
  let all_files = to_string(query(
    "SELECT DISTINCT node_name FROM knowledge_graph WHERE node_type = 'file'", []))
  let imported = to_string(query(
    "SELECT DISTINCT target_name FROM knowledge_edges WHERE edge_type = 'imports'", []))

  // Patterns которые никто не вызывает
  let all_patterns = to_string(query(
    "SELECT DISTINCT node_name FROM knowledge_graph WHERE node_type = 'pattern'", []))
  let called = to_string(query(
    "SELECT DISTINCT target_name FROM knowledge_edges WHERE edge_type = 'calls'", []))

  let admin_profile = read_file("library/admin.md")
  let analysis = call_llm(admin_profile,
    "Найди orphaned файлы и мёртвые функции.\n\nВсе файлы:\n" + all_files
    + "\n\nИмпортированные:\n" + imported
    + "\n\nВсе patterns:\n" + all_patterns
    + "\n\nВызываемые:\n" + called)

  return analysis
}
```

---

## ЧАСТЬ 3: НОЧНОЙ ЦИКЛ

### 3.1. Cron endpoint

```mlog
route "/cron/night" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  let _ = AdminNightCycle()
  return respond("200 ok")
}
```

Render Cron Job: `0 3 * * *` (3:00 UTC)

### 3.2. Ночной цикл (5 фаз)

```mlog
pattern AdminNightCycle() -> String {
  let owner_id = env("OWNER_TELEGRAM_ID")
  let start_time = now()
  let _ = AuditLog("night_cycle_start", "admin", "", "", "ok")

  // Фаза 1: Обновить knowledge graph
  let graph_result = BuildKnowledgeGraph()
  let _ = AuditLog("night_graph", "admin", "", graph_result, "ok")

  // Фаза 2: Аудит кода
  let code_issues = AdminCodeAudit()
  let _ = AuditLog("night_audit", "admin", "", substring(code_issues, 0, 200), "ok")

  // Фаза 3: Анализ метрик
  let metrics_analysis = AdminMetricsAnalysis()

  // Фаза 4: Автофиксы (low risk only)
  let autofixes = AdminAutoFix(code_issues)

  // Фаза 5: Формирование предложений
  let proposals = AdminProposals(code_issues, metrics_analysis)

  // Сохранить ночной отчёт
  let night_report = "NIGHT CYCLE REPORT\n\n"
    + "Graph: " + graph_result + "\n\n"
    + "Code Issues:\n" + code_issues + "\n\n"
    + "Metrics:\n" + metrics_analysis + "\n\n"
    + "Autofixes:\n" + autofixes + "\n\n"
    + "Proposals:\n" + proposals

  let duration = to_string(to_int(now() - start_time))
  let _ = query("INSERT INTO admin_reports (type, content, duration_sec, created_at) VALUES ('night_cycle', $1, $2, $3)",
    [night_report, duration, to_string(now())])

  // Сохранить для утреннего brief'а Яны
  kv_set("admin_night_summary", night_report)
  let _ = AuditLog("night_cycle_done", "admin", "", duration + "s", "ok")

  return "ok"
}
```

### 3.3. Фаза 2: Аудит кода

```mlog
pattern AdminCodeAudit() -> String {
  let admin_profile = read_file("library/admin.md")

  // Читаем ключевые файлы
  let app = read_file("app.mlog")
  let files_summary = "app.mlog: " + to_string(len(app)) + " chars\n"

  let dept_files = list_dir("dept/")
  each f in dept_files {
    if ends_with(to_string(f), ".mlog") then {
      let content = read_file("dept/" + to_string(f))
      let files_summary = files_summary + "dept/" + to_string(f) + ": " + to_string(len(content)) + " chars\n"
    }
  }

  // Orphans
  let orphans = FindOrphans()

  // LLM анализирует
  let audit_prompt = "Проведи аудит кодовой базы офиса. Ищи:\n"
    + "1. БАГИ: undefined functions, crash points, race conditions\n"
    + "2. МЁРТВЫЙ КОД: файлы и функции которые не используются\n"
    + "3. ДУБЛИРОВАНИЕ: похожий код в разных местах\n"
    + "4. БЕЗОПАСНОСТЬ: SQL injection, XSS, открытые endpoints\n"
    + "5. ПРОИЗВОДИТЕЛЬНОСТЬ: лишние LLM-вызовы, большие контексты\n\n"
    + "Формат: [SEVERITY:high/medium/low] FILE:path ISSUE:description FIX:suggestion\n\n"
    + "Файлы:\n" + files_summary + "\n\nOrphans:\n" + orphans

  let issues = call_llm(admin_profile + "\n\n" + audit_prompt,
    "app.mlog (первые 2000 символов):\n" + substring(app, 0, 2000))

  // Сохранить найденные проблемы
  let _ = SaveFindings(issues)

  return issues
}
```

### 3.4. Фаза 3: Анализ метрик

```mlog
pattern AdminMetricsAnalysis() -> String {
  // Данные за последние 24 часа
  let tasks = to_string(query("SELECT dept, COUNT(*) as cnt FROM archive WHERE created_at > $1 GROUP BY dept ORDER BY cnt DESC",
    [to_string(now() - 86400.0)]))
  let errors = to_string(query("SELECT dept, error_type, COUNT(*) FROM error_patterns WHERE created_at > $1 GROUP BY dept, error_type ORDER BY COUNT(*) DESC LIMIT 10",
    [to_string(now() - 86400.0)]))
  let scores = to_string(query("SELECT dept, ROUND(AVG(metric_value),1) as avg FROM dept_metrics WHERE metric_name = 'satisfaction' AND created_at > $1 GROUP BY dept",
    [to_string(now() - 86400.0)]))
  let unrouted = to_string(query("SELECT content FROM dialog_history WHERE dept = 'yana' AND role = 'user' AND created_at > $1 AND content NOT LIKE '/%' LIMIT 20",
    [to_string(now() - 86400.0)]))
  let cost = to_string(query("SELECT ROUND(SUM(cost_usd), 4) FROM token_usage WHERE created_at > $1",
    [to_string(now() - 86400.0)]))

  let admin_profile = read_file("library/admin.md")
  let analysis = call_llm(admin_profile,
    "Анализ метрик за 24ч:\n\nЗадачи по отделам:\n" + tasks
    + "\n\nОшибки:\n" + errors
    + "\n\nОценки:\n" + scores
    + "\n\nНераспределённые запросы (ушли к Яне вместо отдела):\n" + unrouted
    + "\n\nРасход LLM: $" + cost
    + "\n\nОтвети:\n1. Какие отделы перегружены/простаивают?\n2. Какие ошибки повторяются?\n3. Какие запросы не обслуживаются (нужен новый отдел/команда)?\n4. Расход оптимален?")

  return analysis
}
```

### 3.5. Фаза 4: Автофиксы

```mlog
pattern AdminAutoFix(issues: String) -> String {
  let fixes_applied = ""

  // Парсим issues, ищем low-severity
  let admin_profile = read_file("library/admin.md")
  let fix_prompt = "Из списка проблем выбери ТОЛЬКО те которые:\n- severity = low\n- Не затрагивают app.mlog\n- Не затрагивают логику webhook\n- Изменение < 10 строк\n- Тип: dead code, typo, unused import\n\nДля каждой: FILE:path\nACTION:delete_line/replace\nOLD:старый текст\nNEW:новый текст\nEND_FIX\n\nЕсли ничего не подходит — ответь NONE"

  let autofix_plan = call_llm(admin_profile + "\n\n" + fix_prompt, issues)

  if contains(autofix_plan, "NONE") then {
    return "No autofixes needed"
  }

  // Применить автофиксы
  // Каждый фикс: бэкап → write_file → audit
  let parts = split(autofix_plan, "FILE:")
  each part in parts {
    if len(part) > 5 then {
      let file_path = trim(substring(part, 0, index_of(part, "\n")))

      // Проверка immutable
      if contains(file_path, "audit") then { let fixes_applied = fixes_applied + "SKIPPED (immutable): " + file_path + "\n" }
      if contains(file_path, "app.mlog") then { let fixes_applied = fixes_applied + "SKIPPED (high risk): " + file_path + "\n" }

      if contains(file_path, "dept/") then {
        // Бэкап
        let backup = read_file(file_path)
        kv_set("autofix_backup_" + replace(file_path, "/", "_"), backup)

        // TODO: применить замену (OLD → NEW)
        // Для MVP — только логируем, не применяем
        let fixes_applied = fixes_applied + "PLANNED: " + file_path + "\n"
        let _ = AuditLog("autofix", "admin", "", file_path, "planned")
      }
    }
  }

  // Git push если были реальные изменения
  if contains(fixes_applied, "APPLIED") then {
    let _ = git_push("[AUTOFIX] " + fixes_applied)
  }

  return fixes_applied
}
```

### 3.6. Фаза 5: Предложения

```mlog
pattern AdminProposals(issues: String, metrics: String) -> String {
  let admin_profile = read_file("library/admin.md")

  let proposal_prompt = "На основе аудита кода и метрик сформируй предложения.\n\nТипы:\n"
    + "- NEW_DEPT: нужен новый отдел (если >30% запросов не обслуживаются)\n"
    + "- NEW_CMD: нужна новая команда (если паттерн запросов повторяется)\n"
    + "- PROMPT_FIX: нужно улучшить промпт отдела (если оценки < 3.5)\n"
    + "- OPTIMIZE: можно оптимизировать (дублирование, лишние LLM-вызовы)\n"
    + "- DEPRECATE: можно удалить (отдел/функция не используется 30+ дней)\n\n"
    + "Формат: TYPE:тип\nTITLE:краткое название\nDESCRIPTION:подробности\nRISK:low/medium/high\nEND_PROPOSAL"

  let proposals = call_llm(admin_profile + "\n\n" + proposal_prompt,
    "Issues:\n" + issues + "\n\nMetrics:\n" + metrics)

  // Сохранить предложения
  let _ = query("INSERT INTO admin_proposals (content, status, created_at) VALUES ($1, 'pending', $2)",
    [proposals, to_string(now())])

  return proposals
}
```

### 3.7. Таблицы Админа

```sql
CREATE TABLE IF NOT EXISTS admin_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  content TEXT,
  duration_sec TEXT,
  created_at REAL
)

CREATE TABLE IF NOT EXISTS admin_findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  severity TEXT NOT NULL,
  file_path TEXT,
  issue TEXT,
  fix_suggestion TEXT,
  status TEXT DEFAULT 'open',
  created_at REAL
)

CREATE TABLE IF NOT EXISTS admin_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT,
  status TEXT DEFAULT 'pending',
  narad_id TEXT,
  created_at REAL
)
```

---

## ЧАСТЬ 4: КОМАНДЫ АДМИНА

### 4.1. Маршрутизация

```mlog
match text {
  "/admin" then {
    send_message(chat_id, "Админ на связи. Команды:\n/admin status — отчёт\n/admin build <задача> — наряд\n/admin fix <баг> — исправить\n/admin analyze — анализ кода\n/admin graph — knowledge graph\n/admin impact <файл> — impact analysis\n/admin proposals — предложения\n/admin narads — список нарядов\n/admin rollback <id> — откатить\n/admin report — ночной отчёт")
    return respond("200 ok")
  }

  starts_with "/admin status" then {
    let _ = AdminStatus(chat_id)
    return respond("200 ok")
  }

  starts_with "/admin build " then {
    let task = substring(text, 13, len(text))
    let _ = AdminBuild(task, chat_id)
    return respond("200 ok")
  }

  starts_with "/admin fix " then {
    let bug = substring(text, 11, len(text))
    let _ = AdminFix(bug, chat_id)
    return respond("200 ok")
  }

  "/admin analyze" then {
    send_message(chat_id, "Запускаю анализ...")
    let issues = AdminCodeAudit()
    let _ = SendReport(issues, "admin", "Code Audit", 3.0, chat_id)
    return respond("200 ok")
  }

  "/admin graph" then {
    send_message(chat_id, "Строю knowledge graph...")
    let result = BuildKnowledgeGraph()
    send_message(chat_id, result)
    return respond("200 ok")
  }

  starts_with "/admin impact " then {
    let file = substring(text, 14, len(text))
    let impact = ImpactAnalysis(file)
    send_message(chat_id, impact)
    return respond("200 ok")
  }

  "/admin proposals" then {
    let proposals = to_string(query("SELECT content FROM admin_proposals WHERE status = 'pending' ORDER BY created_at DESC LIMIT 5", []))
    if len(proposals) > 2 then {
      send_message(chat_id, "Предложения Админа:\n\n" + proposals)
    } else {
      send_message(chat_id, "Нет активных предложений")
    }
    return respond("200 ok")
  }

  "/admin narads" then {
    let narads = to_string(query("SELECT id, title, status FROM narads ORDER BY created_at DESC LIMIT 10", []))
    send_message(chat_id, "Наряды:\n" + narads)
    return respond("200 ok")
  }

  starts_with "/admin rollback " then {
    let narad_id = substring(text, 16, len(text))
    let _ = AdminRollback(narad_id, chat_id)
    return respond("200 ok")
  }

  "/admin report" then {
    let report = kv_get("admin_night_summary")
    if len(report) > 10 then {
      let _ = SendReport(report, "admin", "Night Cycle Report", 3.0, chat_id)
    } else {
      send_message(chat_id, "Ночной отчёт пока не сформирован")
    }
    return respond("200 ok")
  }
}
```

### 4.2. /admin build

```mlog
pattern AdminBuild(task: String, chat_id: String) -> String {
  let admin_profile = read_file("library/admin.md")

  // Impact analysis
  let build_prompt = "Сформируй наряд на изменение офиса.\n\n1. Какие файлы менять\n2. Что именно в каждом\n3. Риск (low/medium/high)\n4. План отката\n5. Impact: какие части затронуты"

  let narad_text = call_llm(admin_profile + "\n\n" + build_prompt, task)

  let narad_id = "narad-" + to_string(to_int(now()))
  let _ = query("INSERT INTO narads (id, title, description, requested_by, status, created_at) VALUES ($1, $2, $3, 'owner', 'pending', $4)",
    [narad_id, task, narad_text, to_string(now())])

  let body = json_encode({
    chat_id: to_float(chat_id),
    text: "Наряд " + narad_id + ":\n\n" + escape_json(substring(narad_text, 0, 3000)),
    reply_markup: {
      inline_keyboard: [[
        { text: "Подтвердить", callback_data: "approve_" + narad_id },
        { text: "Отклонить", callback_data: "reject_" + narad_id }
      ]]
    }
  })
  let token = env("TELEGRAM_BOT_TOKEN")
  http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")

  let _ = AuditLog("admin_build", "admin", "", narad_id, "pending")
  return narad_id
}
```

### 4.3. /admin fix

```mlog
pattern AdminFix(bug_description: String, chat_id: String) -> String {
  let admin_profile = read_file("library/admin.md")

  // Найти файлы связанные с багом
  let fix_prompt = "Исправь баг в офисе. Прочитай код, найди проблему, предложи фикс.\n\nБаг: " + bug_description + "\n\nФормат:\nFILE:path\nPROBLEM:описание\nFIX:\nстарый код → новый код\nEND_FIX"

  // Читаем ключевые файлы для контекста
  let app = read_file("app.mlog")
  let fix = call_llm(admin_profile + "\n\n" + fix_prompt,
    "app.mlog:\n" + substring(app, 0, 3000))

  // Создать наряд (не автофикс — баг может быть сложным)
  let narad_id = "fix-" + to_string(to_int(now()))
  let _ = query("INSERT INTO narads (id, title, description, requested_by, risk_level, status, created_at) VALUES ($1, $2, $3, 'admin', 'medium', 'pending', $4)",
    [narad_id, "Fix: " + bug_description, fix, to_string(now())])

  let body = json_encode({
    chat_id: to_float(chat_id),
    text: "Админ нашёл решение:\n\n" + escape_json(substring(fix, 0, 2000)) + "\n\nНаряд: " + narad_id,
    reply_markup: {
      inline_keyboard: [[
        { text: "Применить", callback_data: "approve_" + narad_id },
        { text: "Отклонить", callback_data: "reject_" + narad_id }
      ]]
    }
  })
  let token = env("TELEGRAM_BOT_TOKEN")
  http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")

  return narad_id
}
```

### 4.4. /admin status

```mlog
pattern AdminStatus(chat_id: String) -> String {
  let findings_open = to_string(query("SELECT COUNT(*) FROM admin_findings WHERE status = 'open'", []))
  let proposals_pending = to_string(query("SELECT COUNT(*) FROM admin_proposals WHERE status = 'pending'", []))
  let narads_pending = to_string(query("SELECT COUNT(*) FROM narads WHERE status = 'pending'", []))
  let autofixes_today = to_string(query("SELECT COUNT(*) FROM audit_log WHERE action = 'autofix' AND timestamp > $1", [to_string(now() - 86400.0)]))
  let last_night = to_string(query("SELECT created_at FROM admin_reports WHERE type = 'night_cycle' ORDER BY created_at DESC LIMIT 1", []))
  let graph_nodes = to_string(query("SELECT COUNT(*) FROM knowledge_graph", []))
  let graph_edges = to_string(query("SELECT COUNT(*) FROM knowledge_edges", []))

  let msg = "Админ — статус:\n\n"
    + "Knowledge Graph: " + graph_nodes + " nodes, " + graph_edges + " edges\n"
    + "Открытых проблем: " + findings_open + "\n"
    + "Предложений: " + proposals_pending + "\n"
    + "Нарядов на подтверждении: " + narads_pending + "\n"
    + "Автофиксов сегодня: " + autofixes_today + "\n"
    + "Последний ночной цикл: " + last_night

  send_message(chat_id, msg)
  return "ok"
}
```

---

## ЧАСТЬ 5: ИНТЕГРАЦИЯ С ЯНОЙ

### Утренний brief включает секцию Админа

В MorningBrief (scheduler) добавить:

```mlog
  // Секция Админа в утреннем brief'е
  let admin_summary = kv_get("admin_night_summary")
  let admin_section = ""
  if len(admin_summary) > 10 then {
    let admin_section = "\n\nАдмін за ночь:\n" + substring(admin_summary, 0, 500)
  }
  // Добавить admin_section в brief
```

### Яна перенаправляет технические запросы Админу

В маршрутизации Яны:

```python
# В proxy RUSSIAN_KEYWORDS добавить:
'admin': ['оптимизируй', 'почини', 'баг', 'ошибка в коде', 'рефакторинг', 'деплой'],
```

---

## ЧАСТЬ 6: ЦВЕТ АДМИНА

Добавить в утверждённую палитру:

| Персона | Slug | Start | End | Accent |
|---|---|---|---|---|
| Админ | admin | #1e40af | #1e3a5f | #3b82f6 |

Тёмный синий (инженерный, технический).

---

## ЛОКАЛЬНАЯ ПРОВЕРКА

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /admin ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/admin","from":{"id":1},"chat":{"id":1}}}'
sleep 1

echo "=== T2: /admin status ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/admin status","from":{"id":1},"chat":{"id":1}}}'
sleep 1

echo "=== T3: /admin build добавь команду /ping ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/admin build добавь команду /ping которая отвечает pong","from":{"id":1},"chat":{"id":1}}}'
sleep 2

echo "=== T4: /admin analyze ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/admin analyze","from":{"id":1},"chat":{"id":1}}}'
sleep 2

echo "=== T5: /cron/night ==="
curl -s "http://localhost:10000/cron/night?secret=test123"

kill %1
```

---

## КОММИТ

```bash
git commit -m "Admin agent: night cycle, knowledge graph, code audit, autofixes, proposals, /admin commands"
git push origin main
```

---

## ОТЧЁТ

```
### Результат Наряда №28

1. library/admin.md профиль: [✅/❌]
2. Knowledge graph таблицы: [✅/❌]
3. BuildKnowledgeGraph: [✅/❌]
4. ImpactAnalysis: [✅/❌]
5. FindOrphans: [✅/❌]
6. /cron/night endpoint: [✅/❌]
7. AdminNightCycle (5 фаз): [✅/❌]
8. AdminCodeAudit: [✅/❌]
9. AdminMetricsAnalysis: [✅/❌]
10. AdminAutoFix: [✅/❌]
11. AdminProposals: [✅/❌]
12. /admin commands (10 команд): [✅/❌]
13. /admin build (наряды): [✅/❌]
14. /admin fix: [✅/❌]
15. /admin status: [✅/❌]
16. Интеграция с MorningBrief: [✅/❌]
17. Цвет Админа (#1e40af): [✅/❌]
18. admin_reports, admin_findings, admin_proposals таблицы: [✅/❌]
19. T1-T5 проверки: [✅/❌]
20. git push: [✅/❌] [хэш]
```
