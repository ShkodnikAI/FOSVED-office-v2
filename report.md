# Отчёт: L1.5
Дата: 2026-07-06
Ветка: fix/l1-5-timeouts → main
База: 4ddd680
Коммит: 8a91ffc → merge 14b46fb

## A.1-A.10: таймаут 240.0

| # | Строка (до) | URL | До | После |
|---|---|---|---|---|
| A.1 | 1945 | /scheduler/admin-morning-reply | 3 арг | 4 арг, 240.0 |
| A.2 | 1934 | /scheduler/lz-daily | 3 арг | 4 арг, 240.0 |
| A.3 | 1913 | /scheduler/lz-daily | 3 арг | 4 арг, 240.0 |
| A.4 | 1615 | /lz/osint | 3 арг | 4 арг, 240.0 |
| A.5 | 1594 | /lz/osint | 3 арг | 4 арг, 240.0 |
| A.6 | 1572 | /lz/osint | 3 арг | 4 арг, 240.0 |
| A.7 | 1545 | /lz/osint | 3 арг | 4 арг, 240.0 |
| A.8 | 1530 | /lz/osint | 3 арг | 4 арг, 240.0 |
| A.9 | 1506 | /lz/osint | 3 арг | 4 арг, 240.0 |
| A.10 | 218 | /ask | 3 арг | 4 арг, 240.0 |

`grep -cE 'http_post.*240.0\)' app.mlog` → **10**
`grep -cE 'http_post.*stt|learning.*application/json"\)' app.mlog` → 2 (нет 240.0)

## B: cron empty-secret guard

В каждый из 8 cron-роутов перед `if secret != cron_secret` добавлена строка:
`if cron_secret == "" then { return respond("403 Forbidden") }`

`grep -c 'if cron_secret == "" then' app.mlog` → **8**

Роуты: /cron/morning, /cron/evening, /cron/weekly, /cron/monthly, /cron/control, /cron/night, /cron/lz-daily, /cron/admin-reply

## check

`./bin/mlog check app.mlog 2>&1 | grep -c "parse error"` → **0**
(384 warnings — предсуществующие: undefined functions из других .mlog, respond 1-арг, json_get 3-арг)

## Smoke локальный

```
CRON_SECRET="" → curl /cron/morning?secret=        → Forbidden ✓
CRON_SECRET=testsecret → curl /cron/morning?secret=wrong    → Forbidden ✓
CRON_SECRET=testsecret → curl /cron/morning?secret=testsecret → прошёл guard (handler error: llm_proxy недоступен — ожидаемо) ✓
```

## Smoke прод

После деплоя: `curl /cron/lz-daily?secret=<CRON_SECRET>` — проверять отсутствие `error sending request` (таймаут 240с вместо 30с).

## Затруднения

Нет.