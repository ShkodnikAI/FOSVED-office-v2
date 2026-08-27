# FOIP-003: Пакетная реализация 11 фич

Статус: planned
Дата: 2026-08-25
Автор: Владелец

## Фазы реализации

### Фаза 1: Фундамент (без этого ничего остальное не работает надёжно)

---

**НАРЯД FOIP-003.1: Session Log**
Приоритет: P0
Зависимости: нет
Тип: feature

Таблица `session_log` — append-only лог всех событий сессии.
Каждый call_llm, каждое сообщение юзера, каждый результат инструмента.

Файлы:
- [ ] `app.mlog` InitDB — добавить CREATE TABLE session_log
- [ ] `app.mlog` — pattern LogSessionEvent(chat_id, type, data)
- [ ] `app.mlog` CallLLMProxy — после вызова записать событие в лог
- [ ] `app.mlog` HandleDeptQuery — записать user_message и assistant_message

Тест:
- `/dev что такое металогос` → в БД появилась строка session_log с type=user_message
- `/dev что такое металогос` → в БД появилась строка session_log с type=assistant_message
- `mlog check` чисто

Откат: git revert

---

**НАРЯД FOIP-003.2: Resilient LLM Calling**
Приоритет: P0
Зависимости: нет
Тип: feature

Обёртка вокруг CallLLMProxy: при пустом ответе или ошибке — повторить
с другой моделью из конфига. Кулдаун неработающих моделей через kv_set.

Файлы:
- [ ] `app.mlog` — pattern CallLLMResilient(dept, messages) с fallback логикой
- [ ] `app.mlog` — pattern GetModelFallbackChain(dept) читает config/override_<dept>.txt
- [ ] `app.mlog` — pattern SetModelCooldown(model, minutes) / IsModelCooled(model)
- [ ] `app.mlog` CallLLMProxy — заменить на CallLLMResilient в HandleDeptQuery

Тест:
- Если основная модель возвращает пустой ответ — переключается на следующую
- Если модель в кулдауне — пропускается
- `mlog check` чисто

Откат: git revert

---

**НАРЯД FOIP-003.3: Token Metering**
Приоритет: P0
Зависимости: FOIP-003.1 (session_log)
Тип: feature

Запись токенов в session_log при каждом вызове. Оценка стоимости.
Агрегация для /stats и /costs.

Файлы:
- [ ] `app.mlog` CallLLMProxy — после вызова записать tokens_in, tokens_out, model в session_log
- [ ] `app.mlog` — pattern LogTokenUsage(chat_id, dept, model, tokens_in, tokens_out)
- [ ] `app.mlog` — pattern EstimateTokenCost(model, tokens_in, tokens_out) — таблица цен в KV
- [ ] `app.mlog` InitDB — добавить таблицу daily_stats (агрегированная)

Тест:
- Вызов отдела → в session_log есть строки с tokens_in и tokens_out
- `/cost` показывает накопленную статистику

Откат: git revert

---

### Фаза 2: Интеллект (маршрутизация и контекст)

---

**НАРЯД FOIP-003.4: Smart Model Routing**
Приоритет: P1
Зависимости: FOIP-003.2, FOIP-003.3
Тип: feature

Конфигурируемая маршрутизация моделей: приоритеты, cost-aware выбор,
статистика успешности. Таблица model_routing_config вместо
одного priority_model.txt.

Файлы:
- [ ] `app.mlog` InitDB — CREATE TABLE model_routing_config
- [ ] `app.mlog` — pattern GetBestModel(dept) — выбирает модель по конфигу
- [ ] `app.mlog` — pattern RecordModelResult(dept, model, success, latency)
- [ ] `app.mlog` — интегрировать в CallLLMResilient
- [ ] Удалить config/priority_model.txt после миграции данных

Тест:
- Конфиг с двумя моделями → используется первая по приоритету
- Первая модель «падает» → используется вторая
- `/model` показывает текущий routing config

Откат: git revert

---

**НАРЯД FOIP-003.5: Context Compaction**
Приоритет: P1
Зависимости: FOIP-003.1 (session_log)
Тип: feature

Когда сессия длинная — старые сообщения суммируются, хранится саммари +
последние N сообщений. Предотвращает переполнение контекста на 512MB.

Файлы:
- [ ] `app.mlog` — pattern EstimateTokens(text) — len(text)/4
- [ ] `app.mlog` — pattern CompactIfNeeded(chat_id, max_tokens)
- [ ] `app.mlog` — pattern GetCompactedHistory(chat_id, limit) — читает саммари + последние N
- [ ] `app.mlog` BuildContext — использовать GetCompactedHistory вместо GetRecentDialog

Тест:
- Длинная сессия (20+ сообщений) → BuildContext возвращает саммари старых + полные последние 10
- Короткая сессия → без компакции, всё как раньше
- Яна отвечает так же хорошо как до изменения (регрессия)

Откат: git revert

---

**НАРЯД FOIP-003.6: Три канала ввода (followup/steer/inject)**
Приоритет: P1
Зависимости: FOIP-003.1
Тип: feature

followup = обычное сообщение (сейчас так и работает)
steer = коррекция активного процесса
inject = тихий контекст от другого отдела (без пробуждения)

Файлы:
- [ ] `app.mlog` — pattern InjectContext(target_dept, context_text)
- [ ] `app.mlog` — pattern GetInjectedContext(dept) — читает и очищает inject-буфер
- [ ] `app.mlog` — pattern SteerDept(dept, correction) — kv_set для mid-turn коррекции
- [ ] `app.mlog` BuildContext — добавить GetInjectedContext в сборку контекста

Тест:
- Один отдел inject'ит контекст в другой → при следующем вызове целевой отдел видит контекст
- Inject без сообщения юзера → отдел не пробуждается, контект ждёт

Откат: git revert

---

### Фаза 3: Улучшения dev

---

**НАРЯД FOIP-003.7: Plan Mode**
Приоритет: P1
Зависимости: нет
Тип: feature

Для сложных запросов в dev — сначала план, потом действие.
Включается автоматически для многошаговых задач или вручную /dev plan.

Файлы:
- [ ] `dept/dev.mlog` — pattern DevPlanMode(query, chat_id) — генерирует план через call_llm
- [ ] `dept/dev.mlog` — интегрировать в FullPipeline: если DetectTaskType = multi-step → plan mode
- [ ] `dept/dev.mlog` — добавить команду /dev-plan <запрос>

Тест:
- `/dev-plan сделай интернет-магазин` → возвращает план, не код
- `/dev сделай лендинг` → если задача простая, сразу код (без plan mode)
- `/dev сделай SaaS платформу` → plan mode (сложная задача)

Откат: git revert

---

**НАРЯД FOIP-003.8: Вертикальные шаблоны проектов**
Приоритет: P1
Зависимости: FOIP-003.7 (Plan Mode)
Тип: feature

Готовые архитектуры: landing, dashboard, e-commerce, saas, portfolio.
Dev выбирает шаблон по типу задачи, не генерирует с нуля.

Файлы:
- [ ] `dept/templates.mlog` — НОВЫЙ ФАЙЛ: 5 шаблонов как pattern'ы
- [ ] `dept/templates.mlog` — pattern TemplateList(), TemplateGet(type)
- [ ] `dept/dev.mlog` — DetectTaskType → определение типа шаблона
- [ ] `dept/dev.mlog` FullPipeline — вставить TemplateGet перед call_llm
- [ ] `app.mlog` — import dept/templates

Тест:
- `/dev сделай лендинг для кофейни` → в ответе есть структура из шаблона landing
- `/dev создай дашборд аналитики` → структура из шаблона dashboard
- Шаблоны содержат: стек, структуру файлов, компоненты

Откат: git revert

---

**НАРЯД FOIP-003.9: Provider-first Codegen (упрощённый)**
Приоритет: P2
Зависимости: FOIP-003.8 (шаблоны)
Тип: feature

Владелец загружает design tokens (цвета, шрифты) → dev генерирует код
с этими токенами, а не выдуманными. Без Figma API — вручную.

Файлы:
- [ ] `app.mlog` InitDB — CREATE TABLE design_tokens
- [ ] `dept/dev.mlog` — pattern StoreDesignTokens(name, tokens_json)
- [ ] `dept/dev.mlog` — pattern GetDesignTokens(name) — читает из БД
- [ ] `dept/dev.mlog` FullPipeline — если есть tokens → вставляет в промпт генерации
- [ ] `app.mlog` — команда /tokens set <name> <json> и /tokens list

Тест:
- `/tokens set mybrand {"primary": "#FF5733", "font": "Inter"}` → сохраняется
- `/dev сделай лендинг с брендом mybrand` → в коде используются #FF5733 и Inter

Откат: git revert

---

### Фаза 4: Улучшения marketing

---

**НАРЯД FOIP-003.10: Product Marketing Context**
Приоритет: P1
Зависимости: нет
Тип: feature

Единый структурированный документ продукта (12 секций) в KV.
Все маркетинговые ответы читают его первым.

Файлы:
- [ ] `dept/marketing.mlog` — pattern SetProductContext(chat_id, text)
- [ ] `dept/marketing.mlog` — pattern GetProductContext(chat_id) — kv_get
- [ ] `dept/marketing.mlog` — добавить чтение контекста в BuildMarketingContext
- [ ] `app.mlog` — команда /marketing-context set <текст> и /marketing-context show

Тест:
- `/marketing-context set Мой продукт: SaaS для автоматизации...` → сохраняется
- `/marketing какие каналы нам подойдут` → ответ учитывает продукт из контекста
- Без контекста → маркетинг работает как раньше (регрессия)

Откат: git revert

---

**НАРЯД FOIP-003.11: Библиотека 139 маркетинговых идей**
Приоритет: P1
Зависимости: FOIP-003.10 (product context)
Тип: feature

Таблица с 139 идеями, тегами AARRR, бюджетом, стадией.
Маркетинг подбирает 3-5 релевантных идей под контекст продукта.

Файлы:
- [ ] `app.mlog` InitDB — CREATE TABLE marketing_ideas
- [ ] `app.mlog` InitDB — начальная загрузка 139 идей (INSERT)
- [ ] `dept/marketing.mlog` — pattern GetRelevantIdeas(query, count) — call_llm с базой
- [ ] `dept/marketing.mlog` — добавить в intent classification: если «ideas» или «идеи» → GetRelevantIdeas
- [ ] `app.mlog` — команда /marketing-ideas <запрос>

Тест:
- `/marketing-ideas как привлечь первых пользователей` → 3-5 конкретных идей с тегами
- Каждая идея имеет: название, AARRR стадию, бюджет, описание

Откат: git revert

---

**НАРЯД FOIP-003.12: CRO-аудит**
Приоритет: P2
Зависимости: нет
Тип: feature

7-мерный анализ конверсии страницы. Пользователь присылает текст →
маркетинг анализирует по фреймворку.

Файлы:
- [ ] `dept/marketing.mlog` — pattern CROAudit(text, chat_id) — call_llm с CRO фреймворком
- [ ] `dept/marketing.mlog` — добавить в роутинг: если «cro» или «конверсия» → CROAudit
- [ ] `app.mlog` — команда /cro <текст страницы>

Тест:
- `/cro` + текст лендинга → анализ по 7 критериям с конкретными замечаниями
- Без ключевого слова — маркетинг работает как раньше (регрессия)

Откат: git revert

---

### Фаза 5: Видимость

---

**НАРЯД FOIP-003.13: Analytics через Telegram**
Приоритет: P1
Зависимости: FOIP-003.3 (token metering)
Тип: feature

Команды /stats и /costs — статистика по отделам и моделям прямо в Telegram.

Файлы:
- [ ] `app.mlog` — pattern ShowStats(chat_id) — агрегация из daily_stats
- [ ] `app.mlog` — pattern ShowCosts(chat_id) — стоимость по отделам из session_log
- [ ] `app.mlog` — добавить /stats и /costs в роутинг команд
- [ ] `app.mlog` — pattern AggregateDailyStats() — для scheduler/ручного вызова

Тест:
- `/stats` → таблица: отдел, вызовы, токены, ошибки
- `/costs` → таблица: отдел, модель, стоимость
- Без истории — «нет данных»

Откат: git revert

---

### Фаза 6: Очистка (только после полной проверки всех фич)

---

**НАРЯД FOIP-003.14: Удаление мусорного project pipeline**
Приоритет: P2
Зависимости: FOIP-003.8 (шаблоны как замена)
Тип: cleanup

Удалить наивный linear pipeline. Expert больше не в роли архитектора.

Файлы:
- [ ] Удалить `dept/project.mlog` полностью
- [ ] `app.mlog` — убрать `import dept/project`
- [ ] `app.mlog` — удалить блок /project (строки ~1869-1940)
- [ ] `app.mlog` — удалить «Projects:» из /help текста
- [ ] `app.mlog` InitDB — удалить CREATE TABLE projects и project_phases

Тест:
- `mlog check` чисто
- `/help` — нет /project команд
- Все остальные команды работают (регрессия)

Откат: git revert

---

**НАРЯД FOIP-003.15: Проверка и возможное удаление chain.mlog**
Приоритет: P3
Зависимости: нет
Тип: cleanup

chain.mlog используется для /chain команды. Если она нужна — оставляем.
Если нет — удаляем.

Файлы:
- [ ] Проверить: используется ли /chain реально
- [ ] Если нет — удалить `dept/chain.mlog`, убрать import и /chain из app.mlog
- [ ] Если да — оставить, добавить тест

Откат: git revert

---

## Порядок реализации

```
Фаза 1 (фундамент):
  FOIP-003.1 Session Log
  FOIP-003.2 Resilient LLM (параллельно с 1)
  FOIP-003.3 Token Metering (после 1)

Фаза 2 (интеллект):
  FOIP-003.4 Smart Routing (после 2+3)
  FOIP-003.5 Context Compaction (после 1)
  FOIP-003.6 Три канала (после 1)

Фаза 3 (dev):
  FOIP-003.7 Plan Mode
  FOIP-003.8 Шаблоны (после 7)
  FOIP-003.9 Codegen (после 8)

Фаза 4 (marketing):
  FOIP-003.10 Product Context
  FOIP-003.11 Библиотека идей (после 10)
  FOIP-003.12 CRO-аудит

Фаза 5 (видимость):
  FOIP-003.13 Analytics (после 3)

Фаза 6 (очистка):
  FOIP-003.14 Удаление project pipeline (после 8)
  FOIP-003.15 Проверка chain (после всего)
```

## Не затрагивается (защита Яны)

- dept/yana.mlog — все gate'ы, anti_format, делегационная логика
- dept/expert.mlog — компетенция брифинги/автопром
- HandleDeptQuery — базовая диспетчеризация
- BuildContext — базовая сборка контекста (расширяется, не заменяется)
- Все команды /yana, /remind, /calendar, /voice
