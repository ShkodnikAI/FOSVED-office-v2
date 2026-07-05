# LAYER3_REPORT.md — Слой 3: Методологические противоречия

**Дата:** 2026-06-29
**Статус:** Выполнен

---

## Блок A. FORMAT_INSTRUCTION — ограничить двумя отделами

- **A.1:** `_NO_FORMAT_DEPTS = {"yana", "admin"}` → `_ANALYTICAL_DEPTS = {"osp", "expert"}`
- **A.2:** `get_dept_prompt()` — логика инвертирована: `fmt = FORMAT_INSTRUCTION if dept in _ANALYTICAL_DEPTS else ""`
- **A.3:** `max_tokens = 16384 if dept in {"yana", "admin"} else 4096`
- **A.4:** TTS обрезка теперь пропускает yana и admin: `if dept != "yana" && dept != "admin" && len(text) > 1000.0`

## Блок B. METHODOLOGY.md — merge PATCH-001

- **B.1:** Базовый документ из `fosved-bot-main 0/fosved-bot-main/METHODOLOGY.md` (776 строк)
- **B.2:** Применены все 5 операций merge:
  1. Вставлена секция `II.1.8. Шеф де кабинет (составной)` после II.1.7
  2. Вставлена секция `II.4. Составные архетипы — правило` перед Частью III
  3. Обновлена таблица II.2 — Яна теперь «Шеф де кабинет (II.1.8), составной, 5 компонентов»
  4. Заменена секция II.3.8 — полный каталог метрик (3 основные + 8 поддерживающих)
  5. Добавлено правило для составных архетипов в чек-лист I.4 (Этап 3)
- **B.3:** Версия обновлена на 1.1 (v1.0 + PATCH-001), дата 2026-06
- Мета-секции патча («Причина патча», «Что делать») исключены
- Итог: 846 строк

## Блок C. Owner-feedback для метрик Яны

- **C.1:** Команда `/rate-yana <score> [comment]` добавлена в app.mlog после `/rate`
- **C.2:** В library/yana.md добавлена верификация через `/rate-yana`

## Блок D. Переформулировка правила Кузницы

- **D.1:** Правило 3 в library/kavalnya.md: «Не одобряет скилл без минимум 3 anti-patterns» → «Не одобряет **новый** скилл без минимум 3 anti-patterns — для существующих скиллов anti-patterns добавляются итеративно при quarterly review»

## Блок E. Структура library/knowledge/

- Создано 4 директории: `finance/jurisdictions`, `finance/business-forms`, `legal/jurisdictions`, `legal/business-forms`
- 15 placeholder-файлов с TODO-маркерами (содержание — Слой 4)

## Блок F. Механизм quarterly review

- **F.1:** Команда `/quarterly-review <dept>` добавлена в app.mlog — собирает профиль, методологию, метрики и коррекции, отправляет Кузнице для анализа
- **F.2:** Placeholder-комментарий в scheduler.mlog для автоматического триггера (Jan/Apr/Jul/Oct)

---

## Отклонения от наряда

Нет. Все блоки A-F выполнены по спецификации.

## Smoke-тесты

| Тест | Результат |
|---|---|
| S.1 Python syntax | OK |
| S.2 FORMAT только для osp/expert | OK |
| S.3 METHODOLOGY.md + II.1.8 + v1.1 | OK |
| S.4 knowledge: 15 файлов | OK (15) |
| S.5 Команды rate-yana + quarterly-review | OK |