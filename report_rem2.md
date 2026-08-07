# Отчёт: REM-2

**Дата:** 2026-08-07
**Ветка:** `fix/rem2-calendar-filter`
**Хеш:** `4f72f93`
**Коммит деплоя:** `4f72f93` на main, auto-deploy на Render

## Подтверждение публикации

```
be5f04dfb751022001d53064c3344defd0046a21        refs/heads/fix/rem2-calendar-filter
```

## A.1: YanaCalendar фильтрует `active = 1`

### До (строка 834):
```sql
SELECT ... FROM yana_events WHERE created_at IS NOT NULL ORDER BY event_date ASC LIMIT 20
```

### После:
```sql
SELECT ... FROM yana_events WHERE created_at IS NOT NULL AND active = 1 ORDER BY event_date ASC LIMIT 20
```

### Проверка:
```
$ grep -c "created_at IS NOT NULL AND active = 1" app.mlog
1
$ ./bin/mlog check app.mlog 2>&1 | grep -c "parse error"
0
```

## B.1: `/remind list` показывает дату/время читаемо

### До (строка 1463):
```
let output = output + to_string(rid) + ". [" + rkind + "] " + rlocal + " — " + rtext + "\n"
```
Вывод: `1. [once] 2026-08-07 15:30 — проверить почту`
— тип в скобках выглядит как метка, дата воспринимается как второстепенная.

### После (строки 1463–1468):
```
let when = rlocal
if when == "" then {
  let when = to_string(json_get(row, "fire_time", ""))
  if when == "" then { let when = "время не указано" }
}
let output = output + to_string(rid) + ". " + rtext + " — " + when + " (" + rkind + ")\n"
```
Вывод: `1. проверить почту — 2026-08-07 15:30 (once)`
— текст первым, дата сразу за ним, тип в скобках как второстепенная деталь.
Если `next_local` пуста (weekday/monthday-виды) — берётся `fire_time`; если и она пуста — честно «время не указано».

### Проверка:
```
$ grep -c 'let when = rlocal' app.mlog
1
$ ./bin/mlog check app.mlog 2>&1 | grep -c "parse error"
0
```

## Smoke

Требует проверки владельцем через Telegram:

1. `/remind clear` → «Удалено напоминаний: N»
2. Словами «покажи напоминания» (не команда) → Яна отвечает, что напоминаний нет, **не** перечисляет удалённые
3. Поставить новое: «напомни через 3 минуты проверить почту» → `/remind list` → в строке видны текст, дата/время, тип (в скобках)
4. Словами «какие у меня напоминания» → Яна называет новое, не путает с удалёнными
5. `/health` → ok

## Затруднения

Нет.
