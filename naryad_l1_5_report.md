# Отчёт: L1.5 calendar NULL
Дата: 2026-07-19
Ветка: fix/l1-5-calendar-null (запушена)
Хеш: 0681e71
База: main be7ad06

## A.1: строка до/после

До (app.mlog:765):
```
let rows = query("SELECT event_text, event_date, event_type FROM yana_events WHERE created_at IS NOT NULL ORDER BY event_date ASC LIMIT 20", [])
```

После:
```
let rows = query("SELECT COALESCE(event_text,'') AS event_text, COALESCE(event_date,'') AS event_date, COALESCE(event_type,'напоминание') AS event_type FROM yana_events WHERE created_at IS NOT NULL ORDER BY event_date ASC LIMIT 20", [])
```

## A.2: строка до/после

До (app.mlog:1149):
```
let rows = query("SELECT event_text, event_date, event_type FROM yana_events ORDER BY event_date ASC LIMIT 20", [])
```

После:
```
let rows = query("SELECT COALESCE(event_text,'') AS event_text, COALESCE(event_date,'') AS event_date, COALESCE(event_type,'напоминание') AS event_type FROM yana_events ORDER BY event_date ASC LIMIT 20", [])
```

## Smoke: дословный вывод

Файл smoke_null.mlog — дословно из наряда (db sqlite::memory:, NULL-строка: event_text='Без даты', event_date=NULL, event_type=NULL).

### mlog run (испытание по наряду):

```
$ ./bin/mlog run /home/z/my-project/smoke_null.mlog
[db] Connected: sqlite::memory:
1. [] Без даты (напоминание)
```

Ожидание из наряда: `1. [] Без даты (напоминание)` — совпало дословно. Ни одной строки `type mismatch`.

### Контрольный тест БЕЗ COALESCE (serve, та же NULL-строка):

```
[WARNING] implicit Unit→String conversion in '+' operation: String + Unit
Handler error: type mismatch in string concatenation: String + Unit (use to_string() explicitly)
```

## mlog check

```
$ ./bin/mlog check app.mlog 2>&1 | grep -c "parse error"
0
```

Полный вывод check: 425 info/warning (undefined functions из dept/*.mlog, json_get 3-arg vs local 2-arg, respond 1-arg vs local 2-arg) + 2 warnings (security_headers, csrf). 0 parse errors.

## git diff

```
$ git diff --stat -- app.mlog
 app.mlog | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(+)
```

## Затруднения

Нет.