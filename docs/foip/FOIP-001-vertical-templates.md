# FOIP-001: Project Orchestrator с вертикальными шаблонами

Статус: planned
Дата: 2026-08-25
Источник: MetaHarness (ruvnet/metaharness) — 19 vertical templates, Darwin mode, analyze-repo

## Фаза 1: Излучение

**Суть:** MetaHarness генерирует готовые агентные харнесы из шаблонов (verticals): coding, trading, support, gaming. Каждый шаблон — это набор агентов с промптами, скиллами и командами под конкретный тип задач. У нас нет шаблонов — каждый проект идёт через ручное переключение отделов.

**Проблема:** Пользователь хочет дать идею ("сделай мобильное приложение") и получить готовый результат без ручного управления отделами.

## Фаза 2: Оценка пригодности

| # | Вопрос | Ответ |
|---|--------|-------|
| 1 | Решает реальную проблему? | **Да** — автоматизация проектного пайплайна, ключевая задача |
| 2 | Нативно на Металогос? | **Да** — шаблоны = JSON в БД, фазы = call_llm + db_execute |
| 3 | Нехватки Металогоса? | **LR-003** (map для диспетчеризации отделов) — обходим if-цепочкой |
| 4 | Усиливает существующие отделы? | **Да** — Dev/Design/QA вызываются через orchestrator, не заменяются |
| 5 | Совместимо с архитектурой? | **Да** — новый dept/orchestrator.mlog + таблицы в InitDB |
| 6 | Нагрузка на Render? | **Минимальна** — SQL + call_llm, не больше чем текущий project.mlog |
| 7 | Риск потери способностей? | **Нет** — существующие отделы не трогаются, orchestrator их вызывает |

**Вердикт: ПРИНЯТЬ**

## Фаза 3: Сравнительный анализ

### Что удаляется

```
УДАЛЯЕТСЯ:
- dept/project.mlog (273 строки) — причина: заменяется на dept/orchestrator.mlog
- dept/chain.mlog (84 строки) — причина: chain-вызовы поглощаются orchestrator'ом
- dept/yana.mlog (19 строк, _deprecated_ stubs) — причина: мёртвый код
- Роутинг /project в app.mlog (~70 строк) — причина: заменяется на /projects + /project <id>
- Роутинг /chain в app.mlog (~30 строк) — причина: заменяется на /project <id> run/auto
- import dept/project, import dept/chain — причина: файлы удаляются

НЕ УДАЛЯЕТСЯ:
- Все остальные отделы (dev, design, qa, visual, expert и т.д.)
- Все pattern в app.mlog (InitDB, SendTelegramReply, HandleDeptQuery и т.д.)
- Таблица projects и project_phases (переиспользуются с обновлённой схемой)
```

### Что добавляется / перерабатывается

```
ДОБАВЛЯЕТСЯ:
- dept/orchestrator.mlog — ядро автоматизации проектов (~350 строк)
- Таблица project_templates в InitDB — преднастроенные шаблоны
- Таблица project_learnings в InitDB — эволюция (Darwin concept)
- Роутинг /projects, /project <id>, /project <id> run/auto в app.mlog (~50 строк)

ПЕРЕРАБАТЫВАЕТСЯ:
- Таблица projects — добавляются поля template_id, config
- Таблица project_phases — добавляются поля input_summary, artifacts, error
- Таблица narads — остаётся как есть (quick bug recording, ортогональна проектам)
```

### Таблица сравнения

| Аспект | Сейчас | Будет | Преимущество |
|--------|--------|-------|--------------|
| Создание проекта | `/project new platform repo desc` | `/idea` → Яна обсуждает → `/project create` | Естественный диалог вместо команды с параметрами |
| Фазы проекта | 4 жёстких (planning→design→dev→review) | N гибких из шаблона (mobile_app: 7 фаз, api: 5) | Разные типы проектов — разная глубина |
| Вызов отделов | Общий call_llm с разным системным промптом | Нативный вызов HandleDev/HandleDesign/HandleQA | Отделы используют свои скиллы, gates, верификаторы |
| Архитектура | Expert генерирует (НЕВЕРНО) | Dev генерирует (CreateArchitectureDecision) | Архитектура в компетенции Dev, не Expert |
| Обработка ошибок | Фаза помечается failed, всё | 2 повтора с исправленным промптом + rollback | Надёжнее |
| GitHub push | Файловый sync push через Python | Batch push нативно (если base64) или минимальная обёртка | Меньше Python-кода |
| Цепочка отделов | `/chain dev+design` (последовательно, без контекста) | `/project <id> auto` (с контекстом между фазами) | Каждая фаза получает результаты предыдущих |

### Проверка сохранения способностей

```
СПОСОБНОСТЬ: Quick bug recording (/наряд)
Была: app.mlog, строки 1805-1867
После: сохраняется в app.mlog (не трогается)
Риск потери: Нет
Тест: /наряд тестовый баг → подтверждение в Telegram

СПОСОБНОСТЬ: Multi-dept chain (/chain)
Была: dept/chain.mlog + app.mlog роутинг
После: удалена — заменена на /project <id> run/auto
Риск потери: Низкий — chain использовался редко, orchestrator покрывает
Тест: /project <id> auto → последовательно вызывает отделы

СПОСОБНОСТЬ: Яна делегация ([DELEGATE: slug])
Была: app.mlog, YanaCheckDelegate
После: сохраняется для быстрых вопросов (не проектных)
Риск потери: Нет
Тест: «спроси у дизайнера про типографику» → Яна делегирует в design

СПОСОБНОСТЬ: Все команды из /help
Была: app.mlog роутинг
После: /chain и /project старые — удалены, /projects новый + /наряд сохранён
Риск: Средний — нужно обновить /help текст
Тест: /help → содержит /projects, /наряд, не содержит /chain
```

## Фаза 4: Архитектурное решение

### Файлы:

| Файл | Действие |
|------|----------|
| `dept/orchestrator.mlog` | **Новый** — ProjectDiscuss, ProjectCreate, ProjectRunPhase, ProjectAutoAdvance, ProjectEvolve |
| `app.mlog` | Изменить InitDB (новые таблицы), удалить роутинг /project и /chain, добавить /projects + /project <id> + /idea, обновить /help |
| `dept/project.mlog` | **Удалить** |
| `dept/chain.mlog` | **Удалить** |
| `dept/yana.mlog` | **Удалить** |

### Затрагиваемые отделы:
- **Dev** — вызывается orchestrator'ом для фаз arch, dev (через HandleDev, не напрямую)
- **Design** — вызывается для фазы design (через HandleDesign)
- **Visual** — вызывается для дизайна-превью (через HandleDesignImage)
- **QA** — вызывается для фазы review (через HandleQA)
- **Yana** — вызывается для фазы discuss + при уточняющих вопросах

### Промпты фаз (в шаблонах, НЕ в отделах):
Каждый шаблон определяет системный промпт для каждой фазы. Промпты хранятся в JSON в таблице project_templates.

## Фаза 5: Нарыды

### НАРЯД: FOIP-001-N1
**Название:** Расчистка мёртвого кода (Фаза 0)
**Тип:** cleanup
**Приоритет:** P0
**Зависимости:** нет

```
Описание:
- Удалить dept/yana.mlog (19 строк _deprecated_ stubs)
- Удалить dept/chain.mlog (84 строки)
- Удалить dept/project.mlog (273 строки)
- Удалить роутинг /chain из app.mlog
- Удалить роутинг /project из app.mlog  
- Удалить import dept/chain и import dept/project из app.mlog
- Обновить /help текст: убрать /chain, /project старые, пока не добавлять новые

Файлы:
- [ ] app.mlog — удалить роутинги и импорты, обновить /help
- [ ] dept/yana.mlog — удалить файл
- [ ] dept/chain.mlog — удалить файл
- [ ] dept/project.mlog — удалить файл

Тестирование:
- mlog check — чисто
- Деплой — /health 200
- /help — не содержит /chain и /project
- /наряд тест — работает
- Яна делегация — работает

Критерий готовности:
Офис работает без удалённых файлов. Никаких 502.

Откат:
git revert <commit>
```

### НАРЯД: FOIP-001-N2
**Название:** Создать таблицы БД для orchestrator'а
**Тип:** feature
**Приоритет:** P0
**Зависимости:** N1

```
Описание:
Добавить в InitDB (app.mlog):
- CREATE TABLE project_templates (id, name, phases JSON, defaults JSON)
- Обновить CREATE TABLE projects (добавить template_id, config)
- Обновить CREATE TABLE project_phases (добавить input_summary, artifacts, error)
- CREATE TABLE project_learnings (template_id, phase, prompt_delta, outcome_score)
- INSERT 4 шаблона (mobile_app, website, api_service, automation)
- Миграция: ALTER TABLE для существующих таблиц (если есть данные)

Файлы:
- [ ] app.mlog — InitDB pattern

Тестирование:
- Деплой — /health 200
- SELECT FROM project_templates — возвращает 4 строки
- SELECT FROM project_learnings — пустая таблица, схема корректна

Критерий готовности:
Таблицы создаются при деплое, шаблоны заполнены.

Откат: удалить новые CREATE TABLE и INSERT из InitDB
```

### НАРЯД: FOIP-001-N3
**Название:** Реализовать dept/orchestrator.mlog
**Тип:** feature
**Приоритет:** P0
**Зависимости:** N2

```
Описание:
Создать dept/orchestrator.mlog с паттернами:
- ProjectList(chat_id) — список проектов пользователя
- ProjectStatus(project_id) — статус + история фаз
- ProjectDiscuss(chat_id, text) — Яна-диалог для обсуждения идеи
- ProjectCreate(chat_id, template_id, name, desc, repo) — создание из шаблона
- ProjectRunPhase(project_id, chat_id) — запуск следующей фазы
- ProjectAutoAdvance(project_id, chat_id) — запуск всех оставшихся фаз
- ProjectEvolve(template_id) — анализ learnings, корректировка промптов

Важно: фаза arch вызывает Dev, фаза design вызывает Design, фаза review вызывает QA.
 НЕ вызывает Expert для архитектуры (Expert — исследования, не ПО).

Файлы:
- [ ] dept/orchestrator.mlog — новый файл (~350 строк)

Тестирование:
- mlog check — чисто
- /projects — «Нет проектов.»
- /project <id> — «Проект не найден.»

Критерий готовности:
Файл парсится, базовые запросы работают.

Откат: удалить файл + import
```

### НАРЯД: FOIP-001-N4
**Название:** Роутинг в app.mlog + интеграция с Яной
**Тип:** feature
**Приоритет:** P0
**Зависимости:** N3

```
Описание:
- Добавить import dept/orchestrator в app.mlog
- Добавить роутинг:
  /idea или /start → ProjectDiscuss
  /projects → ProjectList
  /project <id> → ProjectStatus
  /project <id> run → ProjectRunPhase
  /project <id> auto → ProjectAutoAdvance
- Обновить /help текст: добавить /projects, /idea

Файлы:
- [ ] app.mlog — импорт, роутинг, /help

Тестирование:
- /help — содержит /projects, /idea, /наряд
- /projects — «Нет проектов.»
- /idea — Яна отвечает диалогом
- Деплой — /health 200

Критерий готовности:
Все новые команды отвечают.

Откат: удалить импорт, роутинг, откатить /help
```

### НАРЯД: FOIP-001-N5
**Название:** End-to-end тест: полный цикл проекта
**Тип:** test
**Приоритет:** P1
**Зависимости:** N4

```
Описание:
Прогнать полный цикл:
1. /idea «хочу сайт для продажи печенья» → Яна диалог
2. /project create website «Печать-магазин» desc repo
3. /project <id> run → фаза arch (Dev)
4. /project <id> run → фаза design (Design)
5. /project <id> status → корректный статус
6. /projects → проект в списке

Тестирование:
- Каждая фаза сохраняет результат в БД
- Статус проекта обновляется
- /projects показывает корректную информацию

Критерий готовности:
Полный цикл проходит без ошибок.
```

## Фазы 6-7: Результат внедрения

*(Заполняется после реализации)*