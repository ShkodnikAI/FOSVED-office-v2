# SMOKE — Автоматический смок-тест офиса

## Запуск

```bash
BASE_URL=https://fosved-office-v2.onrender.com \
OWNER_ID=<telegram id владельца> \
BOT_TOKEN=<токен бота> \
WEBHOOK_SECRET=<секрет вебхука, если задан> \
CRON_SECRET=<секрет cron> \
python3 scripts/smoke.py
```

## Переменные окружения

| Переменная | Где взять | Обязательно |
|---|---|---|
| `BASE_URL` | URL сервиса на Render | нет (по умолчанию `https://fosved-office-v2.onrender.com`) |
| `OWNER_ID` | Telegram ID владельца (из Render env `OWNER_TELEGRAM_ID`) | да |
| `BOT_TOKEN` | Токен бота (из Render env `TELEGRAM_BOT_TOKEN`) | да |
| `WEBHOOK_SECRET` | Секрет вебхука (из Render env `TELEGRAM_WEBHOOK_SECRET`) | нет (если не задан, заголовок не шлётся) |
| `CRON_SECRET` | Секрет cron (из Render env `CRON_SECRET`) | нет (если не задан, проверка пропускается) |
| `WAIT_SECONDS` | Таймаут ожидания ответа модели | нет (по умолчанию 120) |

## Код возврата

| Код | Значение |
|---|---|
| 0 | Все проверки пройдены |
| 1 | Есть непройденные проверки |
| 2 | Не заданы обязательные переменные (OWNER_ID, BOT_TOKEN) |

## ⚠️ Важно

Скрипт отправляет боту **два реальных сообщения**. Владелец получит на них ответы в Telegram. Это нормально и служит дополнительным подтверждением работоспособности.

Не выкладывайте значения переменных окружения в логи и отчёты.
