# dept/dev.mlog — почему отключён, что реально сломано

Комментарий в `app.mlog:33` («TEMP DISABLED 2026-08-25: parse error») — неточный диагноз. Файл парсится. Реальные проблемы — в содержимом.

На `main` импорт всё ещё закомментирован. `/dev` идёт через generic `HandleDeptQuery("dev")`.

## Как проверять

`mlog check dept/dev.mlog` без `--root` даёт ложные «undefined function».

Правильно: `mlog check dept/dev.mlog --root app.mlog`.

## Категории

### A — коллизии имён

`DISCLAIMER_TOP`, `DISCLAIMER_BOTTOM`, `STATUS_DRAFTED`, `STATUS_ARCHIVED`, `DetectCommand`, `WrapWithDisclaimer`, `DeclineOutOfScope`, `QuarterlyMethodologyReview`, `FullPipeline`, `RouteByCommand`.

Ренейм с префиксом `Dev*`.

### B — несуществующие функции

- `to_lower` → `lower`
- `split_by` → `split`
- `hash` — нет; `DevMakeId(seed)` на `now()` + длина сида
- `SendTelegramMessage` → `send_message(chat_id, text)`
- `date_now` / `date_add_days` — нет в Metalogos

### C — арность

`svg_group`/`svg_rect`/`svg_canvas`, `index_of`, `join` — лишние аргументы.
`SearchArchive`, `EnforceHardRules`, `FullPipeline` — расхождение сигнатур в самом файле.

### D — SQL

`query()` с нелитеральной SQL. Писать `query("... WHERE id = ?1", [id])`, не склейку строк.

### Parse-risk: склеенные ключевые слова

На main есть: `andcontains`, `ifis_breaking`, `ifIsValidTransition`, `ifgate.passed`, `ifqa_gate.passed`, `iftransition.success`.

## Маршрут

Даже после `import dept/dev` точка входа `/dev` остаётся `HandleDeptQuery`, если не сменить вызов на `HandleDev(query, chat_id)` (около `app.mlog:3957`).

`dept/design` не трогать в этом наряде.
