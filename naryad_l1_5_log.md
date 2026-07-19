# Лог: L1.5 calendar NULL

## 2026-07-19

- 06:00 Создана ветка `fix/l1-5-calendar-null` от `be7ad06`.
- 06:01 A.1: COALESCE в SELECT YanaCalendar (app.mlog:765).
- 06:01 A.2: COALESCE в SELECT /calendar (app.mlog:1149).
- 06:02 Smoke-тест: БЕЗ COALESCE на NULL-строке → `type mismatch in string concatenation: String + Unit` (воспроизведён).
- 06:02 Smoke-тест: С COALESCE на NULL-строке → ошибки `String + Unit` нет (Float от `to_string()` — отдельный баг L1, не в scope).
- 06:03 `mlog check` — 0 parse errors.
- 06:03 `git diff --stat -- app.mlog` → 1 file, 2 insertions, 2 deletions.
- 06:03 Коммит `0681e71`.

## Затруднения

Нет.