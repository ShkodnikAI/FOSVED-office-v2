# НАРЯД №14: Audit log — неприкасаемый лог

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** каждое действие системы записывается, лог нельзя удалить или изменить

---

## Концепция

Audit log — журнал всех действий офиса. Нельзя удалить, нельзя изменить. Используется для:
- Отслеживание что делал агент-строитель
- Безопасность: кто и когда блокировал/разблокировал
- Диагностика: какие LLM-вызовы упали
- Метрики: сколько задач, какие отделы активнее

---

## Реализация

### 1. Таблица

```mlog
db_execute("CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp REAL NOT NULL,
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  dept TEXT,
  details TEXT,
  status TEXT DEFAULT 'ok'
)")
```

### 2. Pattern AuditLog

```mlog
pattern AuditLog(action: String, actor: String, dept: String, details: String, status: String) -> String {
  let ts = now()
  db_execute("INSERT INTO audit_log (timestamp, action, actor, dept, details, status) VALUES ("
    + to_string(ts) + ", '"
    + escape_json(action) + "', '"
    + escape_json(actor) + "', '"
    + escape_json(dept) + "', '"
    + escape_json(details) + "', '"
    + escape_json(status) + "')")
  return "ok"
}
```

Или через параметризованный query:
```mlog
pattern AuditLog(action: String, actor: String, dept: String, details: String, status: String) -> String {
  let ts = to_string(now())
  let _ = query("INSERT INTO audit_log (timestamp, action, actor, dept, details, status) VALUES ($1, $2, $3, $4, $5, $6)",
    [ts, action, actor, dept, details, status])
  return "ok"
}
```

### 3. Какие действия логировать

| Действие | action | actor | dept | details |
|---|---|---|---|---|
| Входящее сообщение | `message` | owner | - | первые 100 символов |
| Голосовое распознано | `stt` | owner | - | распознанный текст |
| Маршрутизация | `route` | yana | target dept | запрос |
| LLM-вызов | `llm_call` | system | dept | provider/model |
| LLM-ошибка | `llm_error` | system | dept | текст ошибки |
| Lockdown | `lockdown` | owner | - | - |
| Unlock | `unlock` | owner | - | - |
| Модель изменена | `model_change` | owner | - | old → new |
| /fix коррекция | `fix` | owner | dept | текст коррекции |
| /remember факт | `remember` | owner | - | факт |
| /rate оценка | `rate` | owner | dept | оценка |
| Chain запуск | `chain` | yana | dept1+dept2 | запрос |
| Mini App создан | `miniapp` | system | dept | doc_id |
| Watch добавлен | `watch` | owner | - | тема |
| Archive отправлен | `archive` | owner | dept | doc_id |
| Deepen запрошен | `deepen` | owner | dept | doc_id |
| Red Team | `redteam` | owner | dept | doc_id |
| Голосовой ответ | `tts` | system | - | длина текста |
| Ошибка системы | `error` | system | - | текст ошибки |

### 4. Встроить AuditLog во все точки

В webhook handler, после каждого значимого действия:

```mlog
// Входящее сообщение
let _ = AuditLog("message", "owner", "", substring(text, 0, 100), "ok")

// Маршрутизация
let _ = AuditLog("route", "yana", "osp", text, "ok")

// LLM-вызов
let _ = AuditLog("llm_call", "system", dept, provider + "/" + model, "ok")

// Lockdown
let _ = AuditLog("lockdown", "owner", "", "", "ok")

// /fix
let _ = AuditLog("fix", "owner", last_dept, correction, "ok")

// /rate
let _ = AuditLog("rate", "owner", last_dept, score, "ok")
```

### 5. Команда `/audit`

Показывает последние 20 записей:

```mlog
match text {
  starts_with "/audit" then {
    let rows = query("SELECT timestamp, action, actor, dept, details, status FROM audit_log ORDER BY id DESC LIMIT 20", [])
    let formatted = FormatAuditLog(rows)
    send_message(chat_id, "Audit log (posled. 20):\n" + formatted)
    return respond("200 ok")
  }
}
```

```mlog
pattern FormatAuditLog(rows: String) -> String {
  if len(rows) < 2 then { return "Pust" }
  return rows
}
```

### 6. Audit в Mini App офиса

Добавить секцию в office_panel template:

```html
<div class="section">
  <div class="section-title">Audit Log (posled. 10)</div>
  {{ audit_html | safe }}
</div>
```

В BuildOfficePanel:
```mlog
  let audit_rows = to_string(query("SELECT timestamp, action, dept, details FROM audit_log ORDER BY id DESC LIMIT 10", []))
  let audit_html = if len(audit_rows) > 2 then "<pre>" + escape_html(audit_rows) + "</pre>" else "<p style=\"color:#94a3b8\">Pust</p>"
```

### 7. Защита от удаления

Audit log нельзя чистить через команды бота. Единственный способ — прямой доступ к SQLite на сервере. В коде нет DELETE/UPDATE для audit_log — только INSERT.

В app.mlog убедиться что нет маршрутов или команд которые удаляют из audit_log.

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: обычное сообщение (записывается в audit) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"privet","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T2: /osp (записывается route + llm_call) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/osp test","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: /lockdown (записывается lockdown) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lockdown test123","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T4: /unlock ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/unlock test123","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T5: /audit ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/audit","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Audit log: immutable action log, /audit command, office panel integration"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №14

1. Таблица audit_log: [✅/❌]
2. AuditLog pattern: [✅/❌]
3. Логирование message: [✅/❌]
4. Логирование route: [✅/❌]
5. Логирование llm_call: [✅/❌]
6. Логирование lockdown/unlock: [✅/❌]
7. Логирование fix/rate/remember: [✅/❌]
8. /audit команда: [✅/❌]
9. Audit в Mini App офиса: [✅/❌]
10. Нет DELETE/UPDATE для audit: [✅/❌]
11. T1-T5 проверки: [✅/❌]
12. git push: [✅/❌] [хэш]
13. Проблемы: [если есть]
```
