# Отчёт: QUEST-1 + MAIL-1 (минимум)

**Дата:** 2026-08-12
**Ветка:** `feat/sec6-integrations-screen` (linear, после SEC-6)
**Хеш:** `5bea453`
**Коммит:** `QUEST-1: dossier system + MAIL-1 minimal email`

## Архитектура

```
Metalogos (:10001)                    Python LLM Proxy (:4000)
├── dept/quest.mlog                   ├── /api/quests (CRUD)
│   ├── QuestCreate()                 ├── /api/quest/generate (docx)
│   ├── QuestList()                   ├── /api/quest/send-package (email)
│   ├── QuestStatus()                 ├── /api/email/send (general)
│   ├── QuestAdvanceStep()            ├── /api/quest/create-checkpoints
│   ├── QuestApproveStep()            ├── /api/quest/format-list
│   ├── QuestAddFile()                └── /api/quest/format-status
│   ├── QuestClose()                  
│   ├── QuestSendPackage() → Python   
│   └── QuestGenerateDocument() → Py  
├── app.mlog
│   ├── InitDB(): +3 таблицы
│   ├── import dept/quest
│   └── /quest command routing
```

## Таблицы БД (InitDB в app.mlog)

| Таблица | Назначение |
|---------|-----------|
| `quests` | Досье: id, title, type, status, current_step, total_steps, deadline |
| `quest_files` | Файлы досье: filename, version, storage_path |
| `quest_checkpoints` | Чекпоинты: step_num, step_label, status, approved_by |

## Команды Telegram (/quest)

| Команда | Что делает |
|---------|-----------|
| `/quest new <title> \| <type> \| <steps> \| <deadline>` | Создать досье |
| `/quest list` | Список активных |
| `/quest status <id>` | Подробный статус с чекпоинтами и файлами |
| `/quest next <id>` | Перейти к следующему шагу |
| `/quest approve <id>` | Одобрить текущий шаг |
| `/quest close <id>` | Закрыть досье |
| `/quest send <id> \| <email> \| <subject>` | Отправить пакет по email |

## Python API

| Эндпоинт | Метод | Защита | Назначение |
|----------|-------|--------|-----------|
| `/api/quests` | GET | @require_telegram | Список для Mini App |
| `/api/quests/<qid>` | GET | @require_telegram | Детали досье |
| `/api/quest/generate` | POST | @require_telegram | Генерация docx |
| `/api/quest/send-package` | POST | @require_telegram | Отправка по email |
| `/api/email/send` | POST | @require_telegram | Универсальная отправка |
| `/api/quest/create-checkpoints` | POST | нет | Хелпер для Metalogos (внутренний) |
| `/api/quest/format-list` | POST | нет | Хелпер форматирования |
| `/api/quest/format-status` | POST | нет | Хелпер форматирования |

## MAIL-1 (минимум)

- Отправка через `yagmail` (SMTP)
- SMTP_EMAIL и SMTP_PASSWORD в INTEGRATIONS_REGISTRY (экран SEC-6)
- Двухшаговая: Яна готовит → владелец подтверждает `/quest send`
- Аудит каждой отправки
- INTEGRATIONS_REGISTRY: 14 записей (12 + 2 SMTP)

## Ограничение Metalogos

У Metalogos нет конструкции `loop`/`for`/`while`. Циклические операции (создание N чекпоинтов, форматирование списка) делегируются Python через `http_post` к внутренним эндпоинтам. Это архитектурный паттерн: **Metalogos — оркестратор и хранитель состояния, Python — исполнитель циклов и LLM-вызовов**.

## Smoke-тест

| Проверка | Результат |
|----------|-----------|
| `python3 -c "import llm_proxy"` | ✅ |
| 8 quest/email роутов | ✅ |
| 14 интеграций (12+2 SMTP) | ✅ |
| SMTP в INTEGRATIONS_REGISTRY | ✅ |
| dept/quest.mlog создан (10 паттернов) | ✅ |
| 3 таблицы в InitDB | ✅ |
| /quest routing в app.mlog | ✅ |

## Затруднения

Металогос v0.12.0 не имеет циклов — все loop-операции делегируются Python. Это не баг, а ограничение языка. Работает через `http_post` к внутренним эндпоинтам.
