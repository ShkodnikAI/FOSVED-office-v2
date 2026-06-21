# НАРЯД №16: Агент-строитель — DevOps-контур самомодификации

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** офис может менять свой код через Telegram: наряд → подтверждение → тесты → commit → push → deploy

---

## Концепция

Владелец или Яна формулируют задачу на изменение офиса. Dev/Design/Кавальня готовят наряд. Владелец подтверждает. Агент-строитель выполняет: меняет файлы, проверяет, коммитит, деплоит. Всё через Telegram, без доступа к серверу.

---

## Архитектура

```
Владелец: "Поменяй цвет ОСП на тёмно-синий"
    │
    ▼
Яна → Dev + Design (готовят наряд)
    │
    ▼
Наряд в Telegram: что менять, в каких файлах, риск
    │
    ▼
Владелец: ✅ (inline-кнопка)
    │
    ▼
Агент-строитель:
  1. Читает файлы (read_file)
  2. Вносит изменения (write_file)
  3. Проверяет синтаксис (mlog check — если доступен)
  4. git commit + push (через GitHub API)
  5. Render auto-deploy
  6. Audit log
    │
    ▼
Результат в Telegram + audit log
```

---

## Реализация

### 1. Таблица нарядов

```mlog
db_execute("CREATE TABLE IF NOT EXISTS narads (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  requested_by TEXT NOT NULL,
  changed_files TEXT,
  risk_level TEXT DEFAULT 'low',
  status TEXT DEFAULT 'draft',
  created_at REAL,
  approved_at REAL,
  executed_at REAL,
  result TEXT
)")
```

Статусы: `draft` → `pending` → `approved` → `executing` → `done` / `failed` / `rolled_back`

### 2. Классификация риска

```mlog
pattern ClassifyRisk(files: String) -> String {
  match files {
    contains "app.mlog" then { return "high" }
    contains "config/" then { return "low" }
    contains "library/" then { return "low" }
    contains "skills/" then { return "low" }
    contains "templates/" then { return "medium" }
    contains "dept/" then { return "medium" }
    contains "Dockerfile" then { return "high" }
    contains ".env" then { return "high" }
    else { return "medium" }
  }
}
```

### 3. Неприкасаемые зоны

Агент НЕ МОЖЕТ менять:

```mlog
pattern IsImmutable(path: String) -> Float {
  if contains(path, "audit") then { return 1.0 }
  if contains(path, "lockdown") then { return 1.0 }
  if contains(path, "immutable") then { return 1.0 }
  if path == "bin/mlog" then { return 1.0 }
  return 0.0
}
```

### 4. Команда `/build` — создание наряда через LLM

```mlog
match text {
  starts_with "/build " then {
    let request = substring(text, 7, len(text))
    let _ = AuditLog("build_request", "owner", "", request, "ok")

    // LLM анализирует запрос и формирует наряд
    let build_prompt = "Ты — DevOps-агент Fosved Office. Проанализируй запрос на изменение и сформируй наряд.\n\nТребования к наряду:\n1. Какие файлы нужно изменить (пути)\n2. Что именно изменить в каждом файле\n3. Оценка риска: low (конфиг/стили) / medium (логика отделов) / high (app.mlog, Dockerfile)\n4. План отката если что-то сломается\n\nОтвечай в формате:\nФАЙЛЫ: file1.mlog, file2.mlog\nРИСК: low/medium/high\nИЗМЕНЕНИЯ:\n- file1.mlog: описание что менять\n- file2.mlog: описание что менять\nОТКАТ: описание"

    let context = BuildContext("dev", request, chat_id)
    let narad_text = call_llm(context + "\n\n" + build_prompt, "Zapros: " + request)

    let narad_id = "narad-" + to_string(to_int(now()))
    let _ = query("INSERT INTO narads (id, title, description, requested_by, status, created_at) VALUES ($1, $2, $3, 'owner', 'pending', $4)",
      [narad_id, request, narad_text, to_string(now())])

    // Показать наряд владельцу с кнопками
    let safe_narad = escape_json(narad_text)
    let body = json_encode({
      chat_id: to_float(chat_id),
      text: "Naryad " + narad_id + ":\n\n" + safe_narad,
      reply_markup: {
        inline_keyboard: [
          [
            { text: "Podtverdit'", callback_data: "approve_" + narad_id },
            { text: "Otklonit'", callback_data: "reject_" + narad_id }
          ]
        ]
      }
    })
    let token = env("TELEGRAM_BOT_TOKEN")
    http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")

    let _ = AuditLog("narad_created", "system", "dev", narad_id, "pending")
    return respond("200 ok")
  }
}
```

### 5. Обработка callback (approve/reject)

В webhook handler, блок callback_query:

```mlog
let has_callback = has_field(data, "callback_query")
if has_callback == 1.0 then {
  let cb_data = json_get(data, "callback_query.data")
  let cb_chat_id = to_string(json_get(data, "callback_query.message.chat.id"))
  let cb_id = json_get(data, "callback_query.id")

  // Ответить на callback (убрать часики)
  let token = env("TELEGRAM_BOT_TOKEN")
  http_post("https://api.telegram.org/bot" + token + "/answerCallbackQuery",
    json_encode({ callback_query_id: cb_id }), "application/json")

  if starts_with(to_string(cb_data), "approve_") then {
    let narad_id = substring(to_string(cb_data), 8, len(to_string(cb_data)))
    let _ = ExecuteNarad(narad_id, cb_chat_id)
    return respond("200 ok")
  }

  if starts_with(to_string(cb_data), "reject_") then {
    let narad_id = substring(to_string(cb_data), 7, len(to_string(cb_data)))
    let _ = query("UPDATE narads SET status = 'rejected' WHERE id = $1", [narad_id])
    send_message(cb_chat_id, "Naryad " + narad_id + " otklonyon")
    let _ = AuditLog("narad_rejected", "owner", "", narad_id, "rejected")
    return respond("200 ok")
  }

  return respond("200 ok")
}
```

### 6. Выполнение наряда

```mlog
pattern ExecuteNarad(narad_id: String, chat_id: String) -> String {
  let _ = query("UPDATE narads SET status = 'executing', approved_at = $1 WHERE id = $2",
    [to_string(now()), narad_id])
  let _ = AuditLog("narad_approved", "owner", "", narad_id, "executing")

  send_message(chat_id, "Vypolnyayu naryad " + narad_id + "...")

  // Прочитать описание наряда
  let narad_desc = to_string(query("SELECT description FROM narads WHERE id = $1", [narad_id]))

  // LLM генерирует конкретные изменения (файл → содержимое)
  let exec_prompt = "Ты — DevOps-агент. На основе наряда сгенерируй конкретные изменения файлов.\n\nФормат ответа строго:\nFILE:path/to/file.mlog\nCONTENT:\nсодержимое файла целиком\nEND_FILE\n\nТолько файлы которые нужно изменить. Полное содержимое каждого файла."

  let changes = call_llm(exec_prompt, narad_desc)

  // Парсинг и применение изменений
  let result = ApplyChanges(changes, narad_id)

  if result == "ok" then {
    // Git commit + push через GitHub API
    let git_result = GitPush(narad_id)

    if git_result == "ok" then {
      let _ = query("UPDATE narads SET status = 'done', executed_at = $1, result = 'success' WHERE id = $2",
        [to_string(now()), narad_id])
      send_message(chat_id, "Naryad " + narad_id + " vypolnen. Deploy zapushchen.")
      let _ = AuditLog("narad_executed", "system", "", narad_id, "done")
    } else {
      let _ = query("UPDATE narads SET status = 'failed', result = $1 WHERE id = $2",
        [git_result, narad_id])
      send_message(chat_id, "Naryad " + narad_id + " — oshibka git: " + git_result)
      let _ = AuditLog("narad_failed", "system", "", narad_id, git_result)
    }
  } else {
    let _ = query("UPDATE narads SET status = 'failed', result = $1 WHERE id = $2",
      [result, narad_id])
    send_message(chat_id, "Naryad " + narad_id + " — oshibka: " + result)
    let _ = AuditLog("narad_failed", "system", "", narad_id, result)
  }

  return result
}
```

### 7. Применение изменений

```mlog
pattern ApplyChanges(changes: String, narad_id: String) -> String {
  // Парсинг FILE:path\nCONTENT:\n...\nEND_FILE блоков
  let parts = split(changes, "FILE:")
  each part in parts {
    if len(part) > 5 then {
      let newline_pos = index_of(part, "\n")
      let file_path = trim(substring(part, 0, newline_pos))

      // Проверка неприкасаемости
      if IsImmutable(file_path) == 1.0 then {
        return "BLOCKED: " + file_path + " is immutable"
      }

      let content_start = index_of(part, "CONTENT:\n") + 9
      let content_end = index_of(part, "\nEND_FILE")
      let content = substring(part, content_start, content_end)

      // Бэкап перед изменением
      let backup = read_file(file_path)
      kv_set("backup_" + narad_id + "_" + file_path, backup)

      // Запись файла
      write_file(file_path, content)
      let _ = AuditLog("file_changed", "agent", "", file_path, "ok")
    }
  }
  return "ok"
}
```

### 8. Git push через GitHub API

```mlog
pattern GitPush(narad_id: String) -> String {
  let github_token = env("GITHUB_TOKEN")
  let github_repo = env("GITHUB_REPO")

  // Используем GitHub Contents API для обновления файлов
  // Для каждого изменённого файла:
  // 1. GET /repos/{owner}/{repo}/contents/{path} → получить SHA
  // 2. PUT /repos/{owner}/{repo}/contents/{path} → обновить с base64 content

  // Для простоты — один коммит через git CLI если доступен
  // Или через GitHub API Trees + Commits

  let commit_msg = "Auto: narad " + narad_id
  let headers = { "Authorization": "Bearer " + github_token, "Accept": "application/vnd.github.v3+json" }

  // Упрощённый вариант: используем http_post для GitHub API
  // Полная реализация потребует base64 encoding — если нет builtin, нужен
  // Альтернатива: subprocess git если установлен

  return "ok"
}
```

**ВАЖНО:** Полноценный git push через GitHub API требует:
1. Base64 encoding файлов (нет builtin — нужен)
2. Цепочка API-вызовов (get tree → create blobs → create tree → create commit → update ref)

**Практичнее:** установить `git` в Docker, использовать subprocess. Или добавить builtin `git_push(repo, token, files, message)`.

### 9. Builtin `git_push` (рекомендуется)

Добавить в Metalogos:

```rust
fn builtin_git_push(args: Vec<Value>) -> Result<Value, String> {
    // args[0] = repo ("owner/name")
    // args[1] = token
    // args[2] = commit message
    // Использует git CLI через subprocess
    let repo = args[0].as_str()?;
    let token = args[1].as_str()?;
    let message = args[2].as_str()?;

    let status = std::process::Command::new("git")
        .args(&["add", "."])
        .status().map_err(|e| e.to_string())?;

    let status = std::process::Command::new("git")
        .args(&["commit", "-m", message])
        .status().map_err(|e| e.to_string())?;

    let remote = format!("https://{}@github.com/{}.git", token, repo);
    let status = std::process::Command::new("git")
        .args(&["push", &remote, "main"])
        .status().map_err(|e| e.to_string())?;

    if status.success() {
        Ok(Value::Str("ok".to_string()))
    } else {
        Ok(Value::Str("git push failed".to_string()))
    }
}
```

В Dockerfile добавить `git`:
```dockerfile
RUN apt-get update && apt-get install -y ca-certificates git python3 python3-pip && rm -rf /var/lib/apt/lists/*
```

И настроить git в CMD:
```dockerfile
CMD git config --global user.email "agent@fosved.office" && git config --global user.name "Fosved Agent" && mlog serve app.mlog
```

### 10. Откат

```mlog
pattern RollbackNarad(narad_id: String, chat_id: String) -> String {
  let keys = kv_list("backup_" + narad_id + "_")
  each key in keys {
    let backup = kv_get(key)
    let file_path = replace(key, "backup_" + narad_id + "_", "")
    write_file(file_path, backup)
    let _ = AuditLog("file_rolled_back", "agent", "", file_path, "ok")
  }
  let _ = query("UPDATE narads SET status = 'rolled_back' WHERE id = $1", [narad_id])
  send_message(chat_id, "Naryad " + narad_id + " otkatyvaetsya")
  let _ = AuditLog("narad_rollback", "system", "", narad_id, "rolled_back")
  return "ok"
}
```

Команда `/rollback`:

```mlog
match text {
  starts_with "/rollback " then {
    let narad_id = substring(text, 10, len(text))
    let _ = RollbackNarad(narad_id, chat_id)
    return respond("200 ok")
  }
}
```

### 11. Команда `/narads` — список нарядов

```mlog
match text {
  "/narads" then {
    let rows = to_string(query("SELECT id, title, status FROM narads ORDER BY created_at DESC LIMIT 10", []))
    send_message(chat_id, "Poslednie naryady:\n" + rows)
    return respond("200 ok")
  }
}
```

---

## Команды

| Команда | Действие |
|---|---|
| `/build <запрос>` | Создать наряд на изменение |
| `/narads` | Список последних нарядов |
| `/rollback <narad_id>` | Откатить наряд |
| Inline ✅ | Подтвердить наряд → выполнение |
| Inline ❌ | Отклонить наряд |

---

## Переменные окружения

```
GITHUB_TOKEN=ghp_...       # Personal Access Token с push к FOSVED-office-v2
GITHUB_REPO=ShkodnikAI/FOSVED-office-v2
```

---

## Локальная проверка

```bash
export GITHUB_TOKEN=fake
export GITHUB_REPO=test/test
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /build ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/build pomenyaj cvet OSP na sinij","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T2: /narads ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/narads","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: callback approve ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"callback_query":{"id":"123","data":"approve_narad-test","message":{"chat":{"id":2044005421}},"from":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "DevOps agent: /build, narads, approve/reject, execute, rollback, git push, audit"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №16

1. Таблица narads: [✅/❌]
2. /build создаёт наряд через LLM: [✅/❌]
3. Inline approve/reject: [✅/❌]
4. ExecuteNarad: [✅/❌]
5. ApplyChanges (write_file): [✅/❌]
6. IsImmutable (неприкасаемые): [✅/❌]
7. ClassifyRisk: [✅/❌]
8. git_push builtin или subprocess: [✅/❌]
9. RollbackNarad: [✅/❌]
10. /narads список: [✅/❌]
11. /rollback команда: [✅/❌]
12. callback_query обработка: [✅/❌]
13. Audit log интеграция: [✅/❌]
14. git в Dockerfile: [✅/❌]
15. T1-T3 проверки: [✅/❌]
16. git push: [✅/❌] [хэш]
17. Проблемы: [если есть]
```
