# Layer 1 Report — DB Schema Unification
Date: 2026-06-28

## Блок A — Миграция
- A.1: scripts/migrate_schema.py создан: да (87 строк, идемпотентный, 15 переименований + 10 добавлений колонок)
- A.2: entrypoint.sh обновлён: да (строка `python3 scripts/migrate_schema.py data/fosved.db` перед стартом llm_proxy)
- Smoke-test миграции: PASSED (S.2) — старая БД с 8 таблицами успешно мигрирована, все данные сохранены

## Блок B — CREATE TABLE
- B.1: Все 10 CREATE TABLE обновлены: да
  - miniapp_responses: +query, +confidence, created→created_at
  - miniapp_notes: created→created_at
  - dept_metrics: rating→metric_value, +metric_name, +period, created→created_at
  - token_usage: tokens_in→input_tokens, tokens_out→output_tokens, cost→cost_usd, +request_type, created→created_at
  - audit_log: created→timestamp, +actor, +dept, +status
  - dialog_history: created→created_at
  - adapt_corrections: original→original_query, corrected→correction, +original_response, created→created_at
  - error_patterns: context→query_text, +correction, created→created_at
  - system_settings: id INTEGER→key TEXT PRIMARY KEY, убраны id/updated
  - channel_archive: без изменений (уже корректная схема)
- Синтаксис-проверка: PASSED (S.1)

## Блок C — Python-запросы
- C.1 dialog_history: 6 замен (1 INSERT, 4 SELECT, 1 r["created"]→r["created_at"]), 0 остатков старых имён
- C.2 adapt_corrections: 14 замен (2 INSERT, 5 SELECT, 7 r["original"]/r["corrected"]/r["created"]), 0 остатков
- C.3 error_patterns: 5 замен (1 INSERT, 1 SELECT, 1 r["context"], 1 p["context"], 1 r["created"]), 0 остатков
- C.4 token_usage: 3 INSERT + global SUM() замены + conditions variable + WHERE created>=? (все через regex), 0 SQL-остатков
- C.5 audit_log: 5 замен (2 INSERT включая _log_audit функцию, 2 SELECT, 2 r["created"]→r["timestamp"]), 0 остатков
- C.6 dept_metrics: 3 замен (1 INSERT с metric_name/value/period, все AVG(rating)→AVG(CAST(metric_value AS REAL))), 0 остатков
- C.7 miniapp_responses: 11 замен (6 SELECT, 4 r["created"], 1 r.get("created")), 0 остатков
- C.8 miniapp_notes: 1 замена (INSERT), 0 остатков
- C.9 финальный синтаксис: PASSED

## Блок D — scheduler.mlog
- D.1: 3 замены archive → channel_archive: да (строки 113, 116, 171)
- created_at → archived_at: да

## Блок E — context.mlog
- E.1: skills/fosved/ → skills/: да (строка 52)

## Smoke-test
- S.1 py_compile: PASSED
- S.2 миграция старой БД: PASSED (15 переименований + 10 новых колонок)
- S.3 идемпотентность: PASSED (повторный запуск — "migration already applied")
- S.4 свежая БД: PASSED (все 10 таблиц с корректными колонками)
- S.5 нет старых имён: PASSED (0 SQL-остатков; JSON API-ключи "tokens_in"/"created" оставлены намеренно)

## Примечания
- `_log_audit()` получил третий параметр `dept="system"` для заполнения новой колонки audit_log.dept
- JSON API-ключи в ответах (`"tokens_in"`, `"tokens_out"`, `"created"`) не переименованы — это контракт API, не SQL
- Python-переменная `cost` (локальный расчёт) не переименована — не является SQL-ссылкой
- system_settings: PRIMARY KEY изменён с `id INTEGER` на `key TEXT` — соответствует app.mlog схеме
- Файл apply_layer1.py (временный скрипт трансформации) удалён