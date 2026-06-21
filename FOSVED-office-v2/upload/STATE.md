# FOSVED Office v2 — STATE (Состояние проекта)

> Одна строка на наряд/событие. Обновляй после каждого изменения.

## Наряды 1-22: Все выполнены

| # | Наряд | Статус | Комментарий |
|---|-------|--------|-------------|
| 1 | Базовый бот + webhook | ✅ | |
| 2 | LLM прокси (DeepSeek) | ✅ | |
| 3 | Миниапп Template | ✅ | |
| 4 | Voice (TTS/STT) | ✅ | /voice-set заменён на /voice |
| 5 | Орг. структура | ✅ | |
| 6 | Chain-of-thought | ✅ | |
| 7 | Профили отделов | ✅ | |
| 8 | Скилл-файлы для отделов | ⚠️ | Stubs, реальные скиллы не загружены |
| 9 | Маршрутизация по отделам | ✅ | |
| 10 | LLM мульти-модель | ✅ | |
| 11 | Voice male/female | ⚠️ | Код есть, но маппинг не используется |
| 12 | Контекстная память | ✅ | |
| 13 | Office Panel (miniapp) | ✅ | |
| 14 | Scheduler (cron) | ✅ | 12ч окно для daily digest |
| 15 | Audit trail | ✅ | |
| 16 | Мульти-язычность | ✅ | |
| 17 | Адаптация (adapt) | ✅ | |
| 18 | Debriefs | ✅ | БД-таблица добавлена в NARAD-23 |
| 19 | Risk Dashboard | ✅ | |
| 20 | Наряд-менеджмент | ✅ | |
| 21 | Budget tracker | ⚠️ | check_budget_limit — dead code |
| 22 | DEPT_DISPLAY_NAMES + yana | ✅ | Дублирование исправлено |

## Наряд 23: Аудит + исправления

| Исправление | Статус |
|-------------|--------|
| 3 missing DB tables в llm_proxy.py (kv_store, debriefs, audit_log) | ✅ |
| DEPT_DISPLAY_NAMES дублирование | ✅ |
| and/or → вложенные if в app.mlog | ✅ |
| \uXXXX → реальные кириллические символы | ✅ |
| entrypoint.sh полный rewrite с health-check | ✅ |
| Dockerfile: python3-pip добавлен | ✅ |
| reverse_proxy: /office-dashboard и /dept-dashboard/ | ✅ |

## Наряд 24: Наряд-менеджмент (расширенный) — ✅

## Наряд 25: Office Factory — ✅

## Наряд 26: Стресс-тест — ⚠️ (нужен перезапуск после отладки)

## Наряд 27: README rewrite — ✅

## Наряд 28: Admin system agent — ✅ (код написан, не протестирован)

Коммит: `2c76063` — NARAD-28: Admin system agent — night cycle, knowledge graph, code audit, autofixes, proposals, /admin commands

## Сессия: Webhook Unit Fix (2026-06-18)

| Проблема | Статус |
|----------|--------|
| **КРИТИЧЕСКИЙ БАГ**: `json_get()` возвращает `Unit` для отсутствующих JSON ключей; сравнение `Unit != ""` крашило КАЖДЫЙ webhook запрос | ✅ Исправлено |
| `has_field()` + 3-арг `json_get()` вместо прямых сравнений | ✅ |
| Voice handling обёрнут в `has_field()` | ✅ |
| Forwarded channel posts обёрнуты в `has_field()` | ✅ |
| Callback handler: gate для non-message updates | ✅ |

## Сессия: mlog v0.7.9 → v0.7.10 upgrade (2026-06-18)

| Изменение | Статус |
|-----------|--------|
| mlog binary обновлён до v0.7.10 | ✅ |
| `and`/`or` теперь поддерживаются | ✅ |
| `Unit == String` теперь возвращает false вместо crash | ✅ |
| `\uXXXX` теперь парсится корректно | ✅ |
| `if cond then { }` — `then` для блоков стал работать? | ⚠️ НЕОПРЕДЕЛЕНО — проверить! |

## АКТИВНАЯ ПРОБЛЕМА: Яна не отвечает (2026-06-18)

**Корневая причина** (предположение пользователя):
Код app.mlog содержит баги из-за несоответствия предполагаемого и реального API mlog:

1. `return respond(...)` — в 32 местах, может крашить если `return` не ключевое слово
2. `if cond then {` — в 25 местах, `then` может быть только для тернарников
3. `data.message` — dot notation для JSON не существует, нужен `json_get()`
4. `db {}` / `memory {}` — может быть неправильный синтаксис конфигурации
5. `sqlite::memory:` — может создавать отдельную БД на подключение

**Текущий db конфиг**: `db { url: "sqlite:data/fosved.db" }` — выглядит правильно.
**Текущий app.mlog**: использует `json_get()` для JSON, `has_field()` для проверок.

**Действие**: Новый агент должен проверить все 5 категорий и исправить.

## Известные некритичные проблемы

- K4: file_cache_skills — stubs, не подключены к реальным скиллам
- N8: skill-файлы отделов — заглушки
- N11: male/female TTS — код есть, но не используется в маршрутизации
- N21: check_budget_limit — dead code
- N14: daily digest — 12ч окно (не полные сутки)
- Factory deploy — не пушит в GitHub автоматически

## Деплой

- Репо: `https://github.com/ShkodnikAI/FOSVED-office-v2.git`
- Последний commit: `2c76063` — NARAD-28: Admin system agent
- Build ID: `v2-mlog-v0.7.10-glibc239`
- Render URL: `https://fosved-office-v2.onrender.com`
- Webhook: `https://fosved-office-v2.onrender.com/webhook/telegram`
- Статус: запушено, но Яна не отвечает (см. "АКТИВНАЯ ПРОБЛЕМА" выше)

## Git лог (последние 10 коммитов)

```
2c76063 NARAD-28: Admin system agent — night cycle, knowledge graph, code audit, autofixes, proposals, /admin commands
fa19dd5 fix: dept_dashboard init own threading.Lock (crashed on Render)
56d4b6f fix: add /rate_cmd, /dept-dashboard/, dept_dashboard.py to Docker
29942be fix: voice, short replies, typing indicator
5809aa5 fix: /miniapp route without doc_id now returns HTML instead of 404
a41dcb1 fix: Dockerfile ubuntu:24.04 for GLIBC 2.39 (mlog v0.7.10 requires)
fab6e5a app.mlog: migrate to Metalogos v0.7.10 API
2f12dcd chore: update mlog binary to v0.7.10 (and/or, Unit==, \uXXXX, if-then stmt)
c7a76f6 upgrade: mlog v0.4.0 -> v0.7.9, update BIBLE.md + fast_check.sh
458b592 chore: update mlog binary to v0.7.9
```

## Размеры файлов

| Файл | Строк |
|------|-------|
| app.mlog | 768 |
| llm_proxy.py | 5531 |
| reverse_proxy.py | 106 |
| dept_dashboard.py | 367 |
| entrypoint.sh | 86 |
| bin/mlog | 12MB (Git LFS) |