# Отчёт: WH-1

**Дата:** 2026-08-06
**Ветка:** `fix/wh1-checkpoint-sql`
**Хеш:** `5c6b342`
**Коммит деплоя:** ожидает мердж в main + деплой на Render

## Подтверждение публикации

```
9f9ae98eba4d9e6024bbde0c0d55a8e3b5d9e6d4	refs/heads/fix/wh1-checkpoint-sql
```

## A: какой вариант выбран

**Выбран A.2 (параметризация целиком).**

### До (строка 2251):
```
let _ = db_execute("INSERT INTO audit_log (action,actor,dept,details,status) VALUES ('checkpoint','system','webhook','step_0_after_detect_dept=' || ?1 || ','ok')", [dept])
```

### После:
```
let _ = db_execute("INSERT INTO audit_log (action,actor,dept,details,status) VALUES ('checkpoint','system','webhook',?,'ok')", ["step_0_after_detect_dept=" + dept])
```

Склеек `|| ?1 ||` в файле не осталось. Металогос-уровневая конкатенация заменена на `+`, значение передано как параметр `?`.

### Дополнительные дефекты, обнаруженные при A.3

1. **app.mlog:730 — внутренние двойные кавычки в строковом литерале.**
   - До: `вида "через N минут/часов" используй` и `говори "через N минут" без`
   - После: `вида «через N минут/часов» используй` и `говори «через N минут» без`
   - Причина: `"` внутри `"...\"..."` разрывал строку Metalogos, `через` интерпретировался как переменная.

2. **app.mlog:737 — неполная защита от пустого результата CallLLMProxy.**
   - До: `if to_string(proxy_result) == "()" then {`
   - После: `if to_string(proxy_result) == "()" or proxy_result == "" then {`
   - Причина: CallLLMProxy при ошибке HTTP возвращает `""`, а не `()`. Защита не срабатывала, parse_json("") давал 500.

## A.3: вывод локальной проверки целиком

```
[db] Connected: sqlite:./data/test_wh.db
[WARN] METALOGOS_HMAC_KEY env var not set — generating random key; sessions will not survive restart
[server] backend: interpreter (default)
mlog serve: listening on 127.0.0.1:10001
mlog serve: scheduler active (5s interval — reminders + cron)
mlog serve: CSRF token cleanup active (60s interval, 15-min TTL, 60s interval)
[try] caught error: http_post() returned status 404: {"ok":false,"error_code":404,"description":"Not Found"}
[try] caught error: http_post() request failed: error sending request for url (http://127.0.0.1:4000/detect-dept)
[try] caught error: http_get() request failed: error sending request for url (http://127.0.0.1:4000/now-time)
[try] caught error: http_get() request failed: error sending request for url (http://127.0.0.1:4000/now-weather)
[try] caught error: http_post() request failed: error sending request for url (http://127.0.0.1:4000/memory/recall)
[try] caught error: http_post() request failed: error sending request for url (http://127.0.0.1:4000/ask)
[try] caught error: http_post() returned status 404: {"ok":false,"error_code":404,"description":"Not Found"}
[try] caught error: http_post() request failed: error sending request for url (http://127.0.0.1:4000/tg-send)

Webhook response: ok [HTTP 200]
grep "Handler error\|SQL error": NO MATCHES
```

Все `http_post() request failed` — норма (сайдкар и Telegram API недоступны локально).

## B.1: список проверенных INSERT, что исправлено

### app.mlog — 10 INSERT INTO audit_log:

| Строка | Тип | Действие |
|--------|-----|----------|
| 732 | Статический литерал | Без изменений |
| 832 | Статический литерал | Без изменений |
| 834 | Статический литерал | Без изменений |
| 836 | Статический литерал | Без изменений |
| 838 | Статический литерал | Без изменений |
| 850 | Статический литерал | Без изменений |
| 1252 | Статический литерал | Без изменений |
| **2251** | **Была склейка `|| ?1 ||`** | **Параметризована (A.2)** |
| 2266 | Статический литерал | Без изменений |
| 2269 | Статический литерал | Без изменений |

### dept/utils.mlog — 1 INSERT INTO audit_log:

| Строка | Тип | Действие |
|--------|-----|----------|
| 6 | Параметризована (`?1`, `?2`, `?3`) | Без изменений |

### Прочие `||` в SQL (не audit_log):

Строки 894, 905, 915, 924, 928, 1493, 1508, 1524, 1539 — SQL-уровневые `||` внутри `datetime()` в INSERT INTO `yana_events`. Параметры переданы через `?`, склейка безопасна. Без изменений.

Строка `dept/admin.mlog:466` — `'Fix: ' || ?2` в INSERT INTO `narads`. SQL-уровневая, параметр через `?2`. Без изменений.

### Проверка `mlog check`:
```
2 warnings (security_headers, csrf) — 0 parse errors
```

## C.1: вывод проверки маршрутизации (пять строк)

```
/webhook/telegram -> MLOG
/webhook/miniapp-action -> LLM
/cron/morning -> MLOG
/health -> MLOG
/miniapp/x -> LLM
```

Совпало с ожидаемым построчно.

## C.2: Python-обработчик сохранён

Обработчик в `llm_proxy.py:4956` не удалён. Возврат к нему — раскомментирование одной строки в `reverse_proxy.py:18`.

## Smoke

Деплой ещё не произведён. Smoke-тесты будут выполнены после мерджа и деплоя на Render.

## Затруднения

1. **Два дополнительных дефекта обнаружены при A.3** — оба были скрыты SQL-ошибкой на строке 2251 (выполнение не доходило до этих строк). Исправлены в том же коммите:
   - Внутренние кавычки в строке 730 → `«»`
   - Неполная защита от пустого CallLLMProxy результата → добавлена проверка `or proxy_result == ""`

2. **`mlog check` не ловит ни один из трёх дефектов** — все три ошибки происходят внутри строковых литералов или при определённых условиях выполнения. Кандидат в требования: проверка SQL внутри `db_execute` (prior art: `sqlx`).
