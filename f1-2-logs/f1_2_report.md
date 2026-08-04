# Отчёт F-1.2

Хеш main (до правок): `2654a435159effcf4090b322f64990267842c873`
Ветка: `fix/f1-2-remind-parser`, коммит `e71d337`
Ветка запушена в origin.

## Предусловие: grep = 1

На main: `grep -c 'substring(text, 15.0, 16.0) == ":"' app.mlog` → **1**
Предусловие выполнено до правок ✅

## A.1–A.3: строки до/после

### A.1 (daily, line 1190)
- **До:** `if len(text) > 20.0 and substring(text, 15.0, 16.0) == ":" then {`
- **После:** `if len(text) > 20.0 and substring(text, 16.0, 17.0) == ":" then {`

### A.2 (once, line 1204)
- **До:** `if len(text) > 29.0 and substring(text, 24.0, 25.0) == ":" then {`
- **После:** `if len(text) > 29.0 and substring(text, 26.0, 27.0) == ":" then {`

### A.3 (weekly, line 1221)
- **До:** `if valid_day and len(text) > 25.0 and substring(text, 24.0, 25.0) == ":" then {`
- **После:** `if valid_day and len(text) > 25.0 and substring(text, 21.0, 22.0) == ":" then {`

## Проверочные grep-счётчики (4 штуки)

| Шаблон | Ожидание | Факт |
|---|---|---|
| `substring(text, 24.0, 25.0) == ":"` | 0 | **0** ✅ |
| `substring(text, 16.0, 17.0) == ":"` | 1 | **1** ✅ |
| `substring(text, 26.0, 27.0) == ":"` | 1 | **1** ✅ |
| `substring(text, 21.0, 22.0) == ":"` | 1 | **1** ✅ |

## Smoke через разбор: положительные и отрицательные случаи дословно

### Положительные (Python substring-эквивалент)

```
A.1 daily positive: True  (substring(16,17)=':', substring(15,16)='9')
A.2 once positive:  True  (substring(26,27)=':', substring(24,25)='0')
A.3 weekly positive: True  (day_part='mon', valid=True, substring(21,22)=':')
yearly control:     True  (substring(17,18)='-')
```

### Отрицательные

```
A.1 daily negative: False  (substring(16,17)='0')
A.2 once negative:  False  (substring(26,27)='0')
A.3 weekly negative: False  (day_part='xyz', valid=False, substring(21,22)=':')
```

## Извлечение fire_time и reminder_text

```
daily  fire_time=09:00  reminder_text=проверка
once   ev_date=2026-07-25  fire_time=09:00  reminder_text=проверка
weekly fire_time=09:00  reminder_text=проверка
yearly monthday=03-15  fire_time=09:00  reminder_text=проверка
```

Все извлечения корректны — `fire_time` = `09:00`, текст без обрезки ✅

## mlog check: parse error → **0**

```
./bin/mlog check app.mlog → 0 parse error
(2 pre-existing warnings: security_headers, csrf — not errors)
```

## git diff --stat

```
 app.mlog | 6 +++---
 1 file changed, 3 insertions(+), 3 deletions(-)
```

1 файл, 3 изменённые строки ✅

## C: ответы бота (от владельца)

Ожидается после мёржа в main и деплоя на Render.

## Чек-лист сдачи

- [x] Предусловие проверено до правок
- [x] Изменены ровно 3 условия, ветка yearly не тронута
- [x] Все четыре grep-счётчика соответствуют ожиданию
- [x] Smoke выполнен ЧЕРЕЗ РАЗБОР СТРОК, не через SQL
- [x] Отрицательные случаи дают false
- [x] mlog check → 0 parse error
- [x] git diff — 1 файл, 3 строки
- [ ] Прод-проверка владельцем: все четыре команды создают записи
- [ ] Мёрж — только по разрешению аудитора
