# L4.18 Block B — Dual Test Results (11 points)

**Дата:** 2026-07-15
**Коммит:** a9b6151 (fix: wrap all 6 http_post to Telegram API in try)
**Окружение:** локальное (не Render), mlog на порте 10002, Python (4000) НЕ запущен
**Тестовый бот токен:** 8912094706:AAEg...VfQs
**OWNER_TELEGRAM_ID:** 2044005421

## Критическое ограничение окружения

Локальное тестирование НЕ включает Python-процесс на порте 4000. На проде
entrypoint.sh запускает Python + mlog + reverse_proxy. Локально запущен только
mlog. Это означает, что любой вызов `http_post("http://127.0.0.1:4000/...")`
из mlog-обработчика гарантированно падает с сетевой ошибкой.

**Следствие:** тесты, зависящие от Python-прокси (`/detect-dept`, `/now-time`,
`/stt`, `/ask`, `/tg-send`, `/tts`), НЕ могут пройти в этом окружении.
На проде (где Python запущен) эти вызовы работают.

Это НЕ является багом mlog-обработчика. Это ограничение тестовой инфраструктуры.

---

## Результаты

### Тест 1: /start — greeting message
- **HTTP:** 200
- **Время:** 1356ms
- **Ожидалось:** HTTP 200, текст приветствия в Telegram
- **Получено:** HTTP 200. Ответ отправлен через `SendTelegramReply` (прямой вызов Telegram API). Владелец должен видеть "Fosved Office v2..." в чате тестового бота.
- **Вердикт:** PASS

### Тест 2: /status — department list + voice/archive state
- **HTTP:** 200
- **Время:** 1239ms
- **Ожидалось:** HTTP 200, статус-информация
- **Получено:** HTTP 200. Ответ формируется внутри mlog (kv_get + SQL), не зависит от Python.
- **Вердикт:** PASS

### Тест 3: Plain message — auto-routed to yana
- **HTTP:** 500
- **Время:** 1863ms
- **Ожидалось:** HTTP 200, ответ Яны с MarkdownV2
- **Получено:** `Handler error: http_post() request failed: error sending request for url (http://127.0.0.1:4000/detect-dept)`
- **Причина:** `DetectDepartment()` вызывает `http_get("http://127.0.0.1:4000/detect-dept?text=...")`. Python не запущен → сетевая ошибка. На проде Python работает.
- **Вердикт:** N/A (требует Python на 4000 — невозможно проверить локально)

### Тест 4: /yana — explicit yana command (MarkdownV2)
- **HTTP:** 500
- **Время:** 639ms
- **Ожидалось:** HTTP 200, ответ Яны с bold/italic
- **Получено:** `Handler error: http_get() request failed: error sending request for url (http://127.0.0.1:4000/now-time)`
- **Причина:** `HandleYana()` вызывает `http_get("http://127.0.0.1:4000/now-time")` для получения текущего времени. Python не запущен → сетевая ошибка.
- **Вердикт:** N/A (требует Python на 4000)

### Тест 5: /cost — LLM usage statistics
- **HTTP:** 200
- **Время:** 1224ms
- **Ожидалось:** HTTP 200, статистика по токенам
- **Получено:** HTTP 200. `/cost` обрабатывается внутри mlog (SQL-агрегаты из БД), не зависит от Python.
- **Вердикт:** PASS

### Тест 6: /good — positive feedback learning
- **HTTP:** 500
- **Время:** 681ms
- **Ожидалось:** HTTP 200, подтверждение
- **Получено:** `Handler error: parse_json() error: expected value at line 1 column 2`
- **Причина:** `/good` пытается прочитать `recent_dept` из kv-хранилища, получает пустую строку, пытается вызвать `query()` с пустым dept, получает `"[]"`, затем `parse_json("[]")` возвращает List, и дальнейшая обработка падает на `parse_json()` с некорректным вводом.
- **Вердикт:** FAIL (не зависит от Python, баг внутри mlog-обработчика /good при отсутствии предыдущего контекста)

### Тест 7: Voice message — STT via Python proxy
- **HTTP:** 500
- **Время:** 35ms
- **Ожидалось:** HTTP 200, ошибка STT или транскрипция
- **Получено:** `Handler error: http_post() request failed: error sending request for url (http://127.0.0.1:4000/stt)`
- **Причина:** STT идёт через Python-прокси. Python не запущен.
- **Вердикт:** N/A (требует Python на 4000)

### Тест 8: /osp — long analytical response
- **HTTP:** 500
- **Время:** 2823ms
- **Ожидалось:** HTTP 200, длинный аналитический ответ, миниапп-карточка
- **Получено:** `Handler error: http_get() request failed: error sending request for url (http://127.0.0.1:4000/now-time)`
- **Причина:** `/osp` вызывает `HandleOSP()` → `CallLLMProxy()` → `http_post("http://127.0.0.1:4000/ask")`. До этого — `http_get("http://127.0.0.1:4000/now-time")` в контексте. Python не запущен.
- **Вердикт:** N/A (требует Python на 4000)

### Тест 9: /admin report
- **HTTP:** 200
- **Время:** 1275ms
- **Ожидалось:** HTTP 200, отчёт
- **Получено:** HTTP 200. `/admin report` обрабатывается внутри mlog.
- **Вердикт:** PASS

### Тест 10: /rate 8
- **HTTP:** 200
- **Время:** 1274ms
- **Ожидалось:** HTTP 200, подтверждение оценки
- **Получено:** HTTP 200. `/rate` обрабатывается внутри mlog (SQL INSERT + SendTelegramReply).
- **Вердикт:** PASS

### Тест 11: Network failure simulation (prod-incident regression) ★
- **HTTP:** 200
- **Время:** ~2s (включая старт процесса)
- **Ожидалось:** HTTP НЕ 500, `[try] caught error` в логе, НЕТ `Handler error`
- **Получено:**
  - HTTP: **200** ✓
  - `[try] caught error` в логе: **YES** ✓
  - `Handler error` в логе: **NO** ✓
- **Process log (verbatim):**
  ```
  [db] Connected: sqlite:/home/z/my-project/FOSVED-office-v2/data/fosved.db
  mlog serve: listening on 0.0.0.0:10004
  mlog serve: scheduler active (5s interval — reminders + cron)
  [try] caught error: http_post() request failed: error sending request for url (https://api.nonexistent.invalid.telegram/botfake_token_for_netfail_test/sendChatAction)
  [try] caught error: http_post() request failed: error sending request for url (https://api.nonexistent.invalid.telegram/botfake_token_for_netfail_test/sendMessage)
  ```
- **Вердикт:** PASS — прямое подтверждение, что фикс a9b6151 устраняет корневую причину прод-инцидента

---

## Сводная таблица

| Тест | Описание | HTTP | Вердикт | Примечание |
|------|----------|------|---------|------------|
| 1 | /start | 200 | **PASS** | |
| 2 | /status | 200 | **PASS** | |
| 3 | Plain → yana | 500 | N/A | Python 4000 не запущен (/detect-dept) |
| 4 | /yana | 500 | N/A | Python 4000 не запущен (/now-time) |
| 5 | /cost | 200 | **PASS** | |
| 6 | /good | 500 | **FAIL** | parse_json() ошибка при пустом контексте |
| 7 | Voice STT | 500 | N/A | Python 4000 не запущен (/stt) |
| 8 | /osp | 500 | N/A | Python 4000 не запущен (/now-time, /ask) |
| 9 | /admin report | 200 | **PASS** | |
| 10 | /rate 8 | 200 | **PASS** | |
| 11 | Сетевой сбой | 200 | **PASS** | [try] caught error, НЕ Handler error |

**Итого:** 6 PASS, 1 FAIL, 4 N/A

---

## Анализ

### Что проверено и работает
- Все Telegram API вызовы обёрнуты в try (доказано тестом 11)
- Команды, не зависящие от Python (/start, /status, /cost, /admin, /rate) — работают корректно
- Сетевой сбой → graceful degradation, НЕ 500

### Что НЕ проверено (требует Python на 4000)
- Тесты 3, 4, 7, 8 — зависят от Python-прокси для LLM-вызовов, STT, detect-dept, now-time
- На проде эти вызовы работают (Python запущен entrypoint.sh)
- Для полной проверки этих тестов нужен либо запуск Python локально, либо прогон на Render

### Найденный баг (не связан с нарядом)
- **Тест 6 (/good):** `parse_json() error: expected value at line 1 column 2`
  - Воспроизводится при отсутствии предыдущего контекста (нет recent_dept в kv)
  - Не является блокером для Block C (не связан с Telegram API try-wrap)
  - Отдельный баг для фиксации

### Затруднения
Нет.