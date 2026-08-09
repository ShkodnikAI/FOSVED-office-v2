# Отчёт: WH-3

**Дата:** 2026-08-08
**Ветка:** fix/wh3-dedup-window
**Хеш:** aeb7727
**Коммит деплоя:** не деплоен — ожидает merge и ручной smoke-test

## Подтверждение публикации

```
$ git ls-remote origin | grep wh3
40867b215ef75df13c685fc210d6c1a5dcbd0261	refs/heads/fix/wh3-dedup-window
```

Ветка запушена, доступна на origin.

## A.1: Таблица создана

**До:** в `InitDB()` не было таблицы `webhook_dedup`.
**После:** добавлена строка 106:
```
db_execute("CREATE TABLE IF NOT EXISTS webhook_dedup (update_id TEXT PRIMARY KEY, seen_at TEXT DEFAULT (datetime('now')))")
```
**Проверка:** `grep -c "CREATE TABLE IF NOT EXISTS webhook_dedup" app.mlog` → **1**

## A.2: Замена блока идемпотентности

**До (строки 1039–1044):**
```
    let update_id = to_string(json_get(data, "update_id", ""))
    if update_id != "" then {
      let seen = kv_get("upd_" + update_id)
      if seen == "1" then { return respond("200 ok") }
      kv_set("upd_" + update_id, "1")
    }
```

**После (строки 1041–1049):**
```
    let update_id = to_string(json_get(data, "update_id", ""))
    if update_id != "" then {
      let recent = query("SELECT COUNT(*) AS c FROM webhook_dedup WHERE update_id = ? AND seen_at > datetime('now', '-90 seconds')", [update_id])
      let recent_count = to_float(json_get(recent[0], "c", "0"))
      if recent_count > 0.0 then { return respond("200 ok") }
      let _ = try db_execute("INSERT OR REPLACE INTO webhook_dedup (update_id, seen_at) VALUES (?, datetime('now'))", [update_id])
      let _ = try db_execute("DELETE FROM webhook_dedup WHERE seen_at < datetime('now', '-1 day')")
    }
```

**Проверки:**
- `grep -c "webhook_dedup WHERE update_id" app.mlog` → **1**
- `grep -c 'kv_get("upd_"' app.mlog` → **0** (старый kv-flag полностью удалён)
- `./bin/mlog check app.mlog` → **0 parse errors** (2 warnings — security_headers и csrf, не относятся к правке)

**Механика:**
- Окно 90 секунд: если повтор пришёл менее чем через 90 с после первой доставки — гасится (быстрый дубль).
- Если повтор пришёл позже 90 с — проходит в обработку (медленный ретрай), и `INSERT OR REPLACE` обновляет `seen_at`, продляя окно ещё на 90 с.
- `try` вокруг INSERT/DELETE — если БД недоступна, запрос не теряется (дедуп просто не работает, но обработка продолжается).

## A.3: Проверка исполнением

```
$ rm -f /tmp/wh3_test.db
$ DATABASE_URL="sqlite:/tmp/wh3_test.db" ./bin/mlog run /dev/stdin <<'MLOG'
...
MLOG

fresh_dupe_blocked=1 simulated_old_passthrough=0
```

- `fresh_dupe_blocked=1` — только что вставленная запись видна в окне «−90 секунд» → свежий дубль заблокирован ✓
- `simulated_old_passthrough=0` — запрос с порогом «+1 секунда» (будущее) не находит записей → имитация «запись старая, вне окна» → медленный ретрай прошёл бы ✓

## B.1: Чистка старых записей

Добавлена строка 1048:
```
      let _ = try db_execute("DELETE FROM webhook_dedup WHERE seen_at < datetime('now', '-1 day')")
```

**Проверка:** `grep -c "DELETE FROM webhook_dedup" app.mlog` → **1**

Выполняется на каждый входящий webhook-запрос с непустым `update_id`. Попутная чистка — без отдельного планировщика, таблица не растёт бесконечно.

## Smoke-тесты (до деплоя)

Не проводились — ожидается merge в main и деплой на Render.

**План smoke-тестов после деплоя:**
1. Владелец отправляет обычное сообщение → ответ приходит, в логе один `dept_query` (быстрые дубли гасятся).
2. Владелец отправляет запрос в ОСП с объёмным вопросом → дождаться до 4 минут. Зафиксировать: пришёл ли отчёт, если да — во сколько относительно отправки.
3. `/health` → ok, traceback = 0.

## Затруднения

Нет. Все правки — в пределах разрешённого блока, ветки отделов не затронуты.

## Чек-лист сдачи

- [x] Ветка запушена — `git ls-remote origin | grep wh3` → найдена
- [x] A.1: таблица создана
- [x] A.2: старый `kv_get("upd_"...)` полностью заменён
- [x] A.3: проверка исполнением дала ожидаемые цифры (1, 0)
- [x] B.1: чистка старых записей добавлена
- [x] mlog check parse error = 0
- [ ] Smoke: быстрые дубли не создают второй `dept_query` *(после деплоя)*
- [ ] Smoke: зафиксирован факт по ОСП *(после деплоя)*
- [x] report_wh3.md заполнен
