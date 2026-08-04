# Отчёт: REM-1

**Дата:** 2026-08-02  
**Ветка:** `fix/rem1-reminders`  
**Хеш коммита:** `a616bc1`  
**База:** main `ae587dc`

## Подтверждение публикации

```
$ git ls-remote origin | grep rem1
a616bc138e5d80958ef8e9a0a4e32ccbc986c49e	refs/heads/fix/rem1-reminders
```

## A.1: Часовой пояс — НЕ ИЗМЕНЁН

**Затруднение:** Наряд предписывает заменить `'-3 hours'` → `'-2 hours'`, утверждая что Минск = UTC+2 летом. Это **фактически неверно**. Проверка `datetime.now(ZoneInfo('Europe/Minsk'))` показывает `+0300`. Минск не переходит на летнее время с 2011 года, UTC+3 круглый год. Москва = UTC+3. Смещения совпадают. Замена `'-3 hours'` → `'-2 hours'` сделала бы время **на час раньше** реального.

Дословаый факт: `Minsk time: 08:16 +03, UTC offset: +0300`.

Если владелец видит разницу в 1 час — это не смещение, а другая причина. Нужно разобраться отдельно.

## A.2: llm_proxy.py — часовой пояс

**Найдено:**
- `/now-time` — уже `Europe/Minsk` (UTC+3) ✅ — исправлен только комментарий с "UTC+3" на "UTC+3 year-round"
- Утренний бриф — `timezone(timedelta(hours=3))` — правильно, комментарий заменён "Moscow time" → "Minsk time"
- `Время: {time_str} (МСК)` → `Время: {time_str} (Минск)`

## B.1: Новый вид маркера `in`

Добавлен в `YanaCheckRemind` (app.mlog):

```
  if kind == "in" then {
    let _ = query("INSERT INTO yana_events (event_text, event_type, rrule_kind, chat_id, active, created_at, next_fire_at) VALUES (?, 'reminder', 'once', ?, 1, datetime('now'), datetime('now', '+' || ? || ' minutes'))", [text, chat_id, param])
    return kind + " " + param
  }
```

`grep -c 'kind == "in"' app.mlog` → 2 (valid_kind + обработчик) ✅

## B.2: Промпт знает про `in`

Добавлено в описание напоминаний:

```
in (параметр: число минут от текущего момента, например [REMIND: in|1|выключить газ]).
Для просьб вида "через N минут/часов" используй ТОЛЬКО вид in, переводя часы в минуты.
НИКОГДА не вычисляй абсолютное время сам — система посчитает его точнее.
```

`grep -c "REMIND: in|" app.mlog` → 1 ✅

## B.3: Защита от напоминаний в прошлое

После вставки `once` — проверка:

```
    let check = query("SELECT COUNT(*) AS c FROM yana_events WHERE chat_id = ? AND next_fire_at < datetime('now') AND active = 1 AND reminded_at IS NULL", [chat_id])
    let past_count = to_float(json_get(check[0], "c", "0"))
    if past_count > 0.0 then {
      let _ = SendTelegramReply(chat_id, "Внимание: напоминание поставлено на прошедшее время и не сработает. Уточни дату и время.")
    }
```

`grep -c "поставлено на прошедшее время" app.mlog` → 1 ✅

## C.1: Команда `/remind clear`

Добавлена до `/remind del`:

```
      if text == "/remind clear" then {
        let cnt = query("SELECT COUNT(*) AS c FROM yana_events WHERE active = 1 AND chat_id = ?", [chat_id])
        let n = to_string(json_get(cnt[0], "c", "0"))
        let _ = query("UPDATE yana_events SET active = 0 WHERE chat_id = ?", [chat_id])
        let _ = AuditLog("remind_clear", "yana", "cleared=" + n)
        let _ = SendTelegramReply(chat_id, "Удалено напоминаний: " + n + ". Список пуст.")
        return respond("200 ok")
      }
```

## C.2: Справка обновлена

`/remind clear — удалить все` добавлено во все 5 справочных строк.

## D.1: Запрет ложных подтверждений

Добавлен раздел `## ЗАПРЕТ ЛОЖНЫХ ПОДТВЕРЖДЕНИЙ (КРИТИЧЕСКОЕ)` в промпт Яны.

## E.1: Погода — только Минск

- `=== ПОГОДА (Москва) ===` → `=== ПОГОДА (Минск) ===`
- `🌤 Прогноз погоды в Москве` → `🌤 Прогноз погоды в Минске`
- `Время: {time_str} (МСК)` → `Время: {time_str} (Минск)`
- `# Moscow time for display` → `# Minsk time for display (UTC+3 year-round)`

`grep -c "Москв" llm_proxy.py` → 0 ✅

## Затруднения

**A.1 — смещение не изменено.** Наряд предписывает UTC+2 для Минска. Проверка показывает UTC+3. Минск и Москва в одном часовом поясе. Если владелец видит разницу — причина не в смещении, а в другом (например, время сервера отличается от реального, или TZ env var не установлен). Если владелец подтвердит, что время в боте отстаёт на 1 час — нужно проверить `TZ` env var на Render, а не менять константу.
