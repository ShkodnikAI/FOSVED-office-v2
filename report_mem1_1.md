# Отчёт: MEM-1.1

**Дата:** 2026-08-02  
**Ветка:** `fix/mem1-1-json-parse`  
**Хеш коммита:** `ac551bb`  
**Коммит деплоя:** `88c7145` (включает trigger-deploy)

## Подтверждение публикации

```
$ git ls-remote origin | grep mem1-1
ac551bb7b6b0a338bcab42ee0047120536fb85e3	refs/heads/fix/mem1-1-json-parse
```

## A.1: Убрать двойной разбор

### До (строки 770–791)

```
pattern YanaRecallMemories(query: String) -> String {
  let body = json_encode({query: query, limit: 10})
  let resp = try http_post("http://127.0.0.1:4000/memory/recall", body, "application/json")
  if to_string(resp) == "()" then { return "" }
  let count = to_float(json_get(parse_json(resp), "count", "0"))
  if count == 0.0 then { return "" }
  let results = json_get(parse_json(resp), "results", "[]")
  let mut mem_text = ""
  let i = 0.0
  each r in parse_json(results) {
    ...
    let i = i + 1.0
  }
  return mem_text
}
```

**Дефект:** `parse_json(resp)` вызывается дважды (строки 775, 777); `results` — уже разобранный List от `json_get`, но строка 781 пытается `parse_json(results)`, что даёт `parse_json() expected String argument, got List` → 500.

### После

```
pattern YanaRecallMemories(query: String) -> String {
  let body = json_encode({query: query, limit: 10})
  let resp = try http_post("http://127.0.0.1:4000/memory/recall", body, "application/json")
  if to_string(resp) == "()" then { return "" }
  let parsed = parse_json(resp)
  let count = to_float(json_get(parsed, "count", "0"))
  if count == 0.0 then { return "" }
  let mut mem_text = ""
  each r in json_get(parsed, "results", "[]") {
    ...
  }
  return mem_text
}
```

**Изменения:**
- `parse_json(resp)` вызывается один раз, результат в `parsed`
- Итерация напрямую по `json_get(parsed, "results", "[]")` без повторного разбора
- Убрана неиспользуемая переменная `i`

### Grep-счётчики

```
$ grep -c "each r in parse_json" app.mlog → 0
$ grep -c "each r in json_get(parsed" app.mlog → 1
```

### mlog check

```
$ ./bin/mlog check app.mlog
2 warnings (security_headers, csrf — не относятся к наряду)
0 parse errors
```

## A.2: Проверка аналогичных дефектов

```
$ grep -n "parse_json(json_get" app.mlog dept/*.mlog → (нет совпадений)
$ grep -n "in parse_json(" app.mlog dept/*.mlog → (нет совпадений)
```

Все вызовы `parse_json(...)` в коде принимают строковую переменную (результат `http_post`, `to_string(rows)`, и т.д.), а не результат `json_get`. Аналогичных дефектов не обнаружено.

**Проверенные файлы:** `app.mlog`, `dept/utils.mlog`, `dept/osp.mlog`, `dept/visual.mlog`, `dept/admin.mlog`, `dept/finance.mlog`, `dept/lz.mlog`, `dept/qa.mlog`, `dept/dev.mlog`, `dept/kavalnya.mlog`, `dept/design.mlog`, `dept/engineering.mlog`, `dept/marketing.mlog`, `dept/legal.mlog`, `dept/expert.mlog`, `dept/scheduler.mlog`, `dept/miniapp.mlog`.

## Smoke

- **`/version`** = `88c7145` ✅
- **`/health`** = ok ✅
- **Вебхук 200** — ожидает проверки владельцем: отправить сообщение боту, убедиться что ответ приходит без 500 в логе
- **Память в ответе** — ожидает проверки владельцем: задать вопрос, ответ на который есть в памяти
- **Напоминание «через 2 минуты»** — ожидает проверки владельцем (REM-1 smoke, не удалось ранее из-за этой регрессии)

## Затруднения

- Render не подхватил первый push `ac551bb`; потребовался пустой коммит `88c7145` для триггера деплоя. Причина неясна — возможно, Render кэшировал билд или не обнаружил изменений в Dockerfile/requirements. Это не влияет на функциональность.
