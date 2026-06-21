# НАРЯД №19: Архивный канал Telegram

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** анализы автоматически публикуются в Telegram-канал, поиск по архиву, ежедневный дайджест в канал

---

## Концепция

Архивный канал (`TELEGRAM_ARCHIVE_CHANNEL_ID = -1004290868173`) — долговременное хранилище всех значимых output'ов офиса. Не каждое сообщение, а отчёты, анализы, дебрифы, важные решения.

Три режима архивации:
1. **Автоматическая** — каждый Mini App отчёт (≥800 символов) публикуется в канал
2. **Ручная** — кнопка "В архив" в Mini App или команда `/archive`
3. **Дайджест** — ежедневная сводка в канал (что сделано за день)

---

## Реализация

### 1. Таблица архива (связь с каналом)

```mlog
db_execute("CREATE TABLE IF NOT EXISTS channel_archive (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT NOT NULL,
  dept TEXT NOT NULL,
  title TEXT,
  channel_message_id TEXT,
  archived_at REAL
)")
```

### 2. Pattern PublishToArchive

```mlog
pattern PublishToArchive(doc_id: String, dept: String, title: String, content: String) -> String {
  let channel_id = env("TELEGRAM_ARCHIVE_CHANNEL_ID")
  let token = env("TELEGRAM_BOT_TOKEN")

  // Форматирование для канала
  let dept_name = DeptDisplayName(dept)
  let header = dept_name + "\n" + title + "\n"
  let separator = "---"

  // Telegram ограничивает сообщение 4096 символами
  let max_len = 3800.0
  let trimmed = if len(content) > max_len then substring(content, 0, to_int(max_len)) + "\n\n[Polnyj otchyot v Mini App]" else content

  // Убрать HTML-теги для канала (plain text)
  let clean = StripHtml(trimmed)

  let msg = header + separator + "\n\n" + clean

  // Отправить в канал
  let body = json_encode({
    chat_id: to_float(channel_id),
    text: msg,
    parse_mode: "HTML",
    disable_web_page_preview: true
  })
  let result = http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")

  // Извлечь message_id из ответа
  let parsed = parse_json(result)
  let msg_id = to_string(json_get(parsed, "result.message_id", ""))

  // Записать в таблицу
  let _ = query("INSERT INTO channel_archive (doc_id, dept, title, channel_message_id, archived_at) VALUES ($1, $2, $3, $4, $5)",
    [doc_id, dept, title, msg_id, to_string(now())])

  let _ = AuditLog("archive", "system", dept, doc_id, "ok")
  return msg_id
}
```

### 3. Pattern StripHtml

```mlog
pattern StripHtml(text: String) -> String {
  let clean = text
  // Заменить HTML-бейджи на текстовые маркеры
  let clean = replace(clean, "<span class=\"badge badge-fact\">ФАКТ</span>", "[ФАКТ]")
  let clean = replace(clean, "<span class=\"badge badge-interp\">ИНТЕРПРЕТАЦИЯ</span>", "[ИНТЕРПРЕТАЦИЯ]")
  let clean = replace(clean, "<span class=\"badge badge-spec\">СПЕКУЛЯЦИЯ</span>", "[СПЕКУЛЯЦИЯ]")

  // Убрать остальные HTML-теги (базовая замена)
  let clean = replace(clean, "<h2>", "\n\n** ")
  let clean = replace(clean, "</h2>", " **\n")
  let clean = replace(clean, "<h3>", "\n* ")
  let clean = replace(clean, "</h3>", " *\n")
  let clean = replace(clean, "<p>", "")
  let clean = replace(clean, "</p>", "\n")
  let clean = replace(clean, "<li>", "- ")
  let clean = replace(clean, "</li>", "\n")
  let clean = replace(clean, "<br>", "\n")
  let clean = replace(clean, "<hr>", "\n---\n")
  let clean = replace(clean, "<div class=\"verdict\">", "\n[VERDIKT]\n")
  let clean = replace(clean, "<div class=\"disclaimer\">", "\n[DISCLAMER]\n")
  let clean = replace(clean, "</div>", "")
  let clean = replace(clean, "<b>", "")
  let clean = replace(clean, "</b>", "")

  return clean
}
```

### 4. Автоархивация в SendReport

Обновить SendReport (наряд #15) — после сохранения Mini App автоматически публиковать в канал:

```mlog
pattern SendReport(raw_reply: String, dept: String, title: String, depth: Float, chat_id: String) -> String {
  if len(raw_reply) >= 800 then {
    let doc_id = BuildReport(raw_reply, dept, title, depth)

    // Mini App кнопка владельцу
    let summary = substring(raw_reply, 0, 200)
    let safe_summary = escape_json(summary)
    let render_url = env("RENDER_URL")
    let miniapp_url = render_url + "/miniapp/" + doc_id

    let body = json_encode({
      chat_id: to_float(chat_id),
      text: safe_summary + "...",
      reply_markup: {
        inline_keyboard: [[{
          text: "Otkryt' otchyot",
          web_app: { url: miniapp_url }
        }]]
      }
    })
    let token = env("TELEGRAM_BOT_TOKEN")
    http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")

    // Автоархивация в канал
    let auto_archive = kv_get("auto_archive")
    if auto_archive != "false" then {
      let _ = PublishToArchive(doc_id, dept, title, raw_reply)
    }
  } else {
    send_message(chat_id, raw_reply)
  }
  return "ok"
}
```

### 5. Ручная архивация — команда `/archive`

```mlog
match text {
  "/archive" then {
    // Архивировать последний ответ
    let last_doc = to_string(query("SELECT id FROM miniapp_responses ORDER BY created_at DESC LIMIT 1", []))
    if len(last_doc) > 2 then {
      let dept = to_string(query("SELECT dept FROM miniapp_responses WHERE id = $1", [last_doc]))
      let title = to_string(query("SELECT title FROM miniapp_responses WHERE id = $1", [last_doc]))
      let content = to_string(query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [last_doc]))
      let _ = PublishToArchive(last_doc, dept, title, content)
      send_message(chat_id, "Opublikovano v arkhiv: " + title)
    } else {
      send_message(chat_id, "Net otchyotov dlya arkhivacii")
    }
    return respond("200 ok")
  }

  starts_with "/archive " then {
    // Архивировать конкретный doc_id
    let doc_id = substring(text, 9, len(text))
    let dept = to_string(query("SELECT dept FROM miniapp_responses WHERE id = $1", [doc_id]))
    let title = to_string(query("SELECT title FROM miniapp_responses WHERE id = $1", [doc_id]))
    let content = to_string(query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [doc_id]))
    if len(dept) > 1 then {
      let _ = PublishToArchive(doc_id, dept, title, content)
      send_message(chat_id, "Opublikovano: " + title)
    } else {
      send_message(chat_id, "Otchyot " + doc_id + " ne najden")
    }
    return respond("200 ok")
  }
}
```

### 6. Управление автоархивацией

```mlog
match text {
  "/autoarchive on" then {
    kv_set("auto_archive", "true")
    send_message(chat_id, "Avtoarkhivaciya vklyuchena — vse otchyoty publikuyutsya v kanal")
    return respond("200 ok")
  }
  "/autoarchive off" then {
    kv_set("auto_archive", "false")
    send_message(chat_id, "Avtoarkhivaciya otklyuchena — tol'ko ruchnaya /archive")
    return respond("200 ok")
  }
}
```

### 7. Ежедневный дайджест в канал

Добавить в EveningSummary (наряд #17):

```mlog
pattern PublishDailyDigest() -> String {
  let channel_id = env("TELEGRAM_ARCHIVE_CHANNEL_ID")
  let token = env("TELEGRAM_BOT_TOKEN")

  let tasks_today = to_string(query("SELECT COUNT(*) FROM archive WHERE created_at > $1", [to_string(now() - 43200.0)]))
  let depts_today = to_string(query("SELECT dept, COUNT(*) as cnt FROM archive WHERE created_at > $1 GROUP BY dept ORDER BY cnt DESC", [to_string(now() - 43200.0)]))
  let reports_today = to_string(query("SELECT COUNT(*) FROM miniapp_responses WHERE created_at > $1", [to_string(now() - 43200.0)]))
  let fixes_today = to_string(query("SELECT COUNT(*) FROM adapt_corrections WHERE created_at > $1", [to_string(now() - 43200.0)]))

  let digest = "DNEVNOJ DAYDZHEST Fosved Office\n---\n\nZadach: " + tasks_today + "\nOtchyotov: " + reports_today + "\nKorrekcij: " + fixes_today + "\n\nOtdely:\n" + depts_today

  let body = json_encode({
    chat_id: to_float(channel_id),
    text: digest,
    disable_web_page_preview: true
  })
  http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")

  let _ = AuditLog("daily_digest_channel", "scheduler", "", "", "ok")
  return "ok"
}
```

Вызвать из EveningSummary:
```mlog
pattern EveningSummary() -> String {
  // ... существующий код ...
  let _ = PublishDailyDigest()
  return "ok"
}
```

### 8. Поиск по архиву — `/search`

```mlog
match text {
  starts_with "/search " then {
    let query_text = substring(text, 8, len(text))
    let results = to_string(query("SELECT id, dept, title, created_at FROM miniapp_responses WHERE raw_text LIKE '%' || $1 || '%' OR title LIKE '%' || $1 || '%' ORDER BY created_at DESC LIMIT 10", [query_text]))

    if len(results) > 2 then {
      send_message(chat_id, "Najdeno v arkhive:\n" + results)
    } else {
      send_message(chat_id, "Nichego ne najdeno po zaprosu: " + query_text)
    }
    return respond("200 ok")
  }
}
```

### 9. Хештеги в канале

Каждое сообщение в канал получает хештеги отдела:

```mlog
pattern DeptHashtags(dept: String) -> String {
  match dept {
    "osp" then { return "#OSP #analytics #strategy" }
    "lz" then { return "#LZ #technology #research" }
    "expert" then { return "#Expert #briefing" }
    "marketing" then { return "#Marketing #audience" }
    "finance" then { return "#Finance #cashflow" }
    "legal" then { return "#Legal #contracts" }
    "dev" then { return "#Dev #code #architecture" }
    "design" then { return "#Design #UX" }
    "qa" then { return "#QA #testing" }
    "visual" then { return "#Visual #infographic" }
    "engineering" then { return "#Engineering #calculations" }
    "kavalnya" then { return "#Kavalnya #methodology" }
    else { return "#FosvedOffice" }
  }
}
```

Добавить в PublishToArchive перед отправкой:
```mlog
  let tags = DeptHashtags(dept)
  let msg = header + separator + "\n\n" + clean + "\n\n" + tags
```

---

## Команды

| Команда | Действие |
|---|---|
| `/archive` | Архивировать последний отчёт в канал |
| `/archive <doc_id>` | Архивировать конкретный отчёт |
| `/autoarchive on/off` | Вкл/выкл автоархивацию |
| `/search <запрос>` | Поиск по архиву отчётов |

---

## Переменные окружения

```
TELEGRAM_ARCHIVE_CHANNEL_ID=-1004290868173   # уже есть
```

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /autoarchive on ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/autoarchive on","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T2: /archive (последний отчёт) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/archive","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T3: /search тест ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/search test","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T4: дайджест в канал ==="
curl -s "http://localhost:10000/cron/evening?secret=test123"

kill %1
```

---

## Коммит

```bash
git commit -m "Archive channel: auto-publish, /archive, /search, daily digest, hashtags"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №19

1. Таблица channel_archive: [✅/❌]
2. PublishToArchive: [✅/❌]
3. StripHtml: [✅/❌]
4. Автоархивация в SendReport: [✅/❌]
5. /archive команда: [✅/❌]
6. /autoarchive on/off: [✅/❌]
7. /search по архиву: [✅/❌]
8. DeptHashtags: [✅/❌]
9. PublishDailyDigest: [✅/❌]
10. Интеграция с EveningSummary: [✅/❌]
11. T1-T4 проверки: [✅/❌]
12. git push: [✅/❌] [хэш]
13. Проблемы: [если есть]
```
