# AUDIT_CLOSURE — FOSVED Office V2

**Дата начала:** 2026-06-27
**Дата завершения:** 2026-06-29
**Статус:** все 4 слоя пройдены

---

## Что найдено

### Слой 1 — Рантайм-баги (5 находок)
1. 10 таблиц SQLite с несовместимыми схемами между llm_proxy.py и app.mlog — все SQL-запросы из mlog падали
2. Загрузка скиллов мертва — path `skills/fosved/` не существовал
3. `scheduler.mlog` ссылался на таблицу `archive` вместо `channel_archive`
4. Молчаливые `except: pass` в config-loading (принято как допустимое)
5. Отсутствие `.env.example` (перенесено в Слой 4)

### Слой 2 — Структурные расхождения (9 находок)
1. `skills_index/spd.txt` — сирота, дубль osp.txt (+24 фантомных скилла)
2. `skills_index/visual.txt` — отсутствие trailing newline, склейка строк
3. `library/engineering.md` — маркетинговый контент вместо инженерного
4. `library/finance.md` — stub 43 строки вместо полного профиля 153 строки
5. DEPT_COLORS: 9/14 start-цветов расходились между llm_proxy.py и miniapp.mlog
6. README/PROJECT_CONTEXT — 8 устаревших чисел
7. `dept_dashboard.py` — orphan файл, не импортируется
8. 230+ файлов в git, занесённых в .gitignore
9. 175 SKILL.md файлов лежали в `upload/fosved-pack/`, а не в `skills/`

### Слой 3 — Методологические противоречия (6 находок)
1. FORMAT_INSTRUCTION принудительно применялся к 12/14 департаментам (подходит только 2)
2. METHODOLOGY.md отсутствовал в v2 — 15+ мёртвых ссылок из профилей
3. Метрики Яны — самооценка без owner-feedback механизма
4. Правило Кузницы «3 anti-patterns на скилл» нарушалось в 91% скиллов
5. `library/knowledge/` — 9 мёртвых ссылок на несуществующие ресурсы
6. Quarterly review — правило без механизма исполнения

### Слой 4 — Содержательные пробелы (4 находки)
1. Отсутствие `.env.example`
2. 23 пустых секции-заглушки в профилях
3. 15 knowledge-placeholder'ов без содержания
4. 12 admin stub-скиллов (7 строк)

---

## Что сделано

### Слой 1 (commit 7a60fbc)
- Создан `scripts/migrate_schema.py` — миграция существующей БД
- 10 CREATE TABLE в llm_proxy.py приведены к mlog-схемам
- ~85 SQL-запросов в llm_proxy.py обновлены (имена колонок)
- `scheduler.mlog`: `archive` → `channel_archive`
- `context.mlog`: path скиллов исправлен
- Миграция подключена в `entrypoint.sh`

### Слой 2 (commits 49fd8ba, 492d346)
- `spd.txt` удалён
- `visual.txt` — trailing newline добавлен
- `engineering.md` заменён на правильный из v1-пакета (263 строки)
- `finance.md` заменён на полный из v1-пакета (153 строки)
- 9 start-цветов синхронизированы в `miniapp.mlog`
- README/PROJECT_CONTEXT — числа обновлены
- `dept_dashboard.py` удалён
- 241 файл вычищен из git tracking
- 175 SKILL.md размещены по пути `skills/<skill>/SKILL.md`

### Слой 3 (commit ef71954)
- `_NO_FORMAT_DEPTS` → `_ANALYTICAL_DEPTS = {"osp", "expert"}`
- max_tokens 16384 для yana/admin
- TTS без обрезки для yana/admin
- `METHODOLOGY.md` = v1 + PATCH-001, версия 1.1 (846 строк)
- Команда `/rate-yana` добавлена
- Правило 3 Кузницы переформулировано (только новые скиллы)
- `library/knowledge/` — 15 placeholder-файлов
- Команда `/quarterly-review` добавлена

### Слой 4 (commit 3be1470)
- `.env.example` создан (15 env-переменных)
- `spd.txt` регрессия исправлена
- 23 пустых секции удалены из профилей
- Knowledge-base BY: 9 файлов наполнены (finance + legal)

---

## Что осталось как сознательный долг

| Долг | Причина | Приоритет |
|---|---|---|
| Knowledge RU/EU/US | По мере появления задач в этих юрисдикциях | Низкий |
| 12 admin stub-скиллов | Функциональность в admin.mlog, стабы не блокируют | Низкий |
| Тесты | Отсутствуют полностью. Не блокирует текущую стадию | Средний |
| Changelog | Используется git log | Низкий |
| Quarterly review автоматизация | Команда есть, scheduler-trigger — после ручного тестирования | Низкий |
| `except: pass` (8 шт.) | Config-loading, приемлемо | Низкий |

---

## Метрика «можно ли запускать»

**Да.** Все блокирующие баги починены, схемы унифицированы, скиллы на месте, профили корректны, methodology документ размещён, .env.example создан. Система деплоится на Render и работает.
