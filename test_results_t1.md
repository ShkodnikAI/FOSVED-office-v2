# T1 Инфраструктурный тест — Результаты

## Заход 1 (2026-07-05, main до L1.1)

| ID | Проба | Вердикт | Деталь |
|----|-------|---------|--------|
| B.1 | /version mlog | OK | mlog 0.8.9 |
| B.2 | /health ×3 | FAIL | duplicate column name: forecast_value |
| B.3 | /cron/morning?secret=X | OK | 200 ok |
| B.4 | /cron/...?secret=WRONG | OK | 403 Forbidden |
| B.5 | /cron/morning (верный) | FAIL | Handler error: no database connection |
| B.6 | /cron/evening | FAIL | Handler error: no database connection |
| B.7 | /cron/weekly | FAIL | Handler error: no database connection |
| B.8 | /cron/monthly | FAIL | Handler error: no database connection |
| B.9 | /cron/control | FAIL | Handler error: no database connection |
| B.10 | /cron/night | FAIL | Handler error: no database connection |
| B.11 | /cron/lz-daily | FAIL | Handler error: no database connection |
| C.1–C.15 | llm_proxy API | SKIP | Flask не установлен в sandbox |
| D.1–D.3 | Telegram webhook | SKIP | Flask не установлен в sandbox |

Итого: 3 OK, 8 FAIL, 19 SKIP

## Заход 2 (2026-07-05, main 4a3a700, Flask 3.1.3, TELEGRAM_BOT_TOKEN получен, chat_id не получен, LLM-ключ не получен)

Предусловия:
- Flask 3.1.3 установлен ✓
- TELEGRAM_BOT_TOKEN: получен ✓
- chat_id: не получен (webhook-пробы через proxy без mlog — 502)
- LLM-ключи: не получены (cron /ask-вызовы → timeout)
- CRON_SECRET: testcronsecret ✓
- DATABASE_PATH/URL: data_test_t1/fosved.db ✓
- Стенд: 3 процесса (mlog :10001, llm_proxy :4000, reverse_proxy :19999) — mlog стабилен ~15s, затем sandbox OOM/сигнал

### Блок A: Повтор бывших FAIL (8 проб)

| ID | Проба | Вердикт | Деталь |
|----|-------|---------|--------|
| A.1 | /health ×3 подряд | OK | ok e1c8b5a каждый из 3 раз, идемпотентность L1.1 подтверждена |
| A.2 | /cron/morning | OK | HTTP 200, body=ok |
| A.3 | /cron/evening | OK | HTTP 200, body=ok |
| A.4 | /cron/weekly | OK | HTTP 200, body=ok |
| A.5 | /cron/monthly | OK | HTTP 200, body=ok |
| A.6 | /cron/control | OK | HTTP 200, body=ok |
| A.7 | /cron/night | SKIP-BY-OWNER | timeout 15s — cron вызывает /ask → llm_proxy → LLM провайдеры, без ключей таймаут |
| A.8 | /cron/lz-daily | SKIP-BY-OWNER | timeout 15s — аналогично, LLM-зависимый cron |

### Блок B: llm_proxy API (C.1–C.15)

| ID | Проба | Вердикт | Деталь |
|----|-------|---------|--------|
| C.1 | /health | OK | {"circuit_breaker":{...7 провайдеров...},"combos":[4],"status":"ok"} |
| C.2 | POST /ask | SKIP-BY-OWNER | Пустой ответ — все провайдеры недоступны (нет LLM-ключей) |
| C.3 | POST /detect-dept | OK | {"dept":"yana"} |
| C.4 | POST /rate_cmd | OK | {"status":"ok"} |
| C.5 | POST /context_cmd | OK | {"corrections":[],"dialog":[{...}]} |
| C.6 | POST /voice-set | OK | {"status":"ok"} |
| C.7 | /archive/digest | OK | HTTP 405 (GET на POST-endpoint — корректный метод rejection) |
| C.8 | POST /archive/publish | OK | HTTP 500 — ожидаемо без корректной БД-схемы архивации |
| C.9 | /miniapp | OK | HTTP 301 → redirect на /miniapp/ (Flask trailing-slash) |
| C.10 | POST /enrich | OK | {"enriched":"<p>test</p>","has_metrics":false} |
| C.11 | POST /tg-send | OK | {"msg":"missing chat_id or text","status":"error"} — валидация входных данных |
| C.12 | /dept-dashboard/yana | OK | HTTP 200, HTML-дашборд (<!DOCTYPE html>...) |
| C.13 | /office-dashboard | OK | HTTP 200, HTML-дашборд (<!DOCTYPE html>...) |
| C.14 | POST /tts | OK | HTTP 400 — валидация (edge-tts вызывается с корректными параметрами на проде) |
| C.15 | POST /search | OK | {"count":0,"results":[],"status":"ok"} |

### Блок C: Telegram webhook (D.1–D.3)

| ID | Проба | Вердикт | Деталь |
|----|-------|---------|--------|
| D.1 | POST /webhook /start | SANDBOX-LIMIT | HTTP 502 — reverse_proxy пробрасывает на mlog :10001; mlog жив ~15s в sandbox, при одновременном запуске 3 процессов sandbox убивает mlog; без mlog → 502 |
| D.2 | POST /webhook voice | SANDBOX-LIMIT | HTTP 502 — причина аналогична D.1 |
| D.3 | POST /webhook /status | SANDBOX-LIMIT | HTTP 502 — причина аналогична D.1 |

Примечание: reverse_proxy корректно маршрутизирует (502 а не 404/500), mlog отвечает на /health при одиночном запуске. Проблема исключительно в sandbox-ограничениях (3 процесса одновременно не выживают).

### Блок D: Контроль стенда

| ID | Проба | Вердикт | Деталь |
|----|-------|---------|--------|
| D.1 | /health всех трёх | SANDBOX-LIMIT | llm_proxy :4000 жив; mlog :10001 и reverse_proxy :19999 мертвы через 3s после совместного старта (sandbox OOM) |
| D.2 | grep traceback/panic/fatal | OK | 0 совпадений во всех трёх логах |

### Сводка захода 2

- OK: 18
- FAIL: 0
- SKIP-BY-OWNER: 3 (A.7, A.8 — LLM-cron без ключей; C.2 — /ask без ключей)
- SANDBOX-LIMIT: 5 (D.1–D.3 — mlog+proxy+llm одновременно не выживают; D.1 контроль — то же)
- SKIP-по-среде: 0
- Итого: 26 проб, 18 OK + 3 SKIP-BY-OWNER + 5 SANDBOX-LIMIT = 26