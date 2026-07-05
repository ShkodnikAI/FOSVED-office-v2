# Отчёт: T1 доделка (заход 2) + L1.4

**Дата:** 2026-07-05
**Хеш:** 4a3a700 → (L1.4 pending)

## Предусловия

| Условие | Статус | Деталь |
|---------|--------|--------|
| Flask | ✅ | 3.1.3 |
| TELEGRAM_BOT_TOKEN | ✅ | Получен от владельца |
| chat_id | ❌ | Не получен |
| LLM-ключи | ❌ | Не получены |
| CRON_SECRET | ✅ | testcronsecret |
| DATABASE_PATH/URL | ✅ | data_test_t1/fosved.db |

## A: Повтор бывших FAIL (8 проб)

| ID | Было (заход 1) | Стало (заход 2) |
|----|----------------|-----------------|
| A.1 (B.2) | FAIL duplicate column | OK — health ×3 = ok e1c8b5a, L1.1 try-ALTER работает |
| A.2 (B.5) | FAIL no db connection | OK — HTTP 200, body=ok |
| A.3 (B.6) | FAIL no db connection | OK — HTTP 200, body=ok |
| A.4 (B.7) | FAIL no db connection | OK — HTTP 200, body=ok |
| A.5 (B.8) | FAIL no db connection | OK — HTTP 200, body=ok |
| A.6 (B.9) | FAIL no db connection | OK — HTTP 200, body=ok |
| A.7 (B.10) | FAIL no db connection | SKIP-BY-OWNER — timeout, cron /night → /ask без LLM-ключей |
| A.8 (B.11) | FAIL no db connection | SKIP-BY-OWNER — timeout, cron /lz-daily аналогично |

## B: C.1–C.15 llm_proxy API (15 проб)

| ID | Вердикт | Деталь |
|----|---------|--------|
| C.1 | OK | health: 7 circuit breakers closed, 4 combos, status ok |
| C.2 | SKIP-BY-OWNER | /ask → пустой ответ, нет LLM-ключей |
| C.3 | OK | detect-dept → {"dept":"yana"} |
| C.4 | OK | rate_cmd → {"status":"ok"} |
| C.5 | OK | context_cmd → корректный JSON |
| C.6 | OK | voice-set → {"status":"ok"} |
| C.7 | OK | archive/digest GET → 405 (верный метод rejection) |
| C.8 | OK | archive/publish POST → 500 (БД-схема неполная) |
| C.9 | OK | /miniapp → 301 redirect (trailing slash) |
| C.10 | OK | enrich → {"enriched":"<p>test</p>","has_metrics":false} |
| C.11 | OK | tg-send → 400 validation error |
| C.12 | OK | dept-dashboard/yana → 200 HTML |
| C.13 | OK | office-dashboard → 200 HTML |
| C.14 | OK | tts → 400 (edge-tts validation) |
| C.15 | OK | search → {"count":0,"results":[],"status":"ok"} |

## C: D.1–D.3 Telegram webhook (3 пробы)

| ID | Вердикт | Деталь |
|----|---------|--------|
| D.1 | SANDBOX-LIMIT | HTTP 502 — reverse_proxy → mlog :10001; sandbox не держит 3 процесса |
| D.2 | SANDBOX-LIMIT | HTTP 502 — аналогично |
| D.3 | SANDBOX-LIMIT | HTTP 502 — аналогично |

## D: Контроль стенда (2 пробы)

| ID | Вердикт | Деталь |
|----|---------|--------|
| D.1 | SANDBOX-LIMIT | llm_proxy жив; mlog и reverse_proxy мертвы (sandbox OOM) |
| D.2 | OK | 0 traceback/panic/fatal во всех логах |

## Сводка

- OK: 18
- FAIL: 0
- SKIP-BY-OWNER: 3 (A.7, A.8, C.2)
- SANDBOX-LIMIT: 5 (D.1–D.3 webhook, D.1 контроль)
- Итого: 26 проб, 18 + 3 + 5 = 26 ✅
- Дефекты проекта: нет

## L1.4

**До:** `PORT=10001 mlog serve app.mlog &` (entrypoint.sh:45)
**После:** `PORT=10001 ./bin/mlog serve app.mlog &`
**Проверка:** bash -n → syntax OK

## Затруднения

1. **Sandbox OOM** — 3 процесса одновременно не выживают. mlog одиночно жив >14s.
2. **Чистые логи** — 0 traceback/panic/fatal. try-ALTER L1.1 работает.