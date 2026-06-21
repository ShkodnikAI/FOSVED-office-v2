# НАРЯД №8: Mini App — автоматический пост-процессор для каждого отдела

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Результат:** ответы ≥ 800 символов → краткий анонс в чат + кнопка → стилизованная HTML-страница

---

## Что нужно сделать

### Концепция

1. LLM-отдел генерирует текст с маркировкой ([ФАКТ], [ИНТЕРПРЕТАЦИЯ], [СПЕКУЛЯЦИЯ], слои, заголовки)
2. Пост-процессор конвертирует текст → стилизованный HTML с бейджами, цветами, секциями
3. HTML сохраняется в БД с уникальным ID
4. В Telegram отправляется краткий анонс + inline-кнопка "Открыть полностью" → Mini App URL
5. Если ответ < 800 символов — текст прямо в чат (без Mini App)

### 13 цветов отделов

| Отдел | Slug | Gradient start | Gradient end | Accent |
|---|---|---|---|---|
| Яна | yana | #6366f1 | #8b5cf6 | #7c3aed |
| ОСП | osp | #dc2626 | #991b1b | #ef4444 |
| ЛЗ | lz | #0891b2 | #0e7490 | #06b6d4 |
| Эксперт | expert | #4f46e5 | #3730a3 | #6366f1 |
| Маркетинг | marketing | #f97316 | #ea580c | #fb923c |
| Финансы | finance | #16a34a | #15803d | #22c55e |
| Юрист | legal | #64748b | #475569 | #94a3b8 |
| Dev | dev | #2563eb | #1d4ed8 | #3b82f6 |
| Design | design | #ec4899 | #db2777 | #f472b6 |
| QA | qa | #84cc16 | #65a30d | #a3e635 |
| Visual | visual | #a855f7 | #9333ea | #c084fc |
| Engineering | engineering | #78716c | #57534e | #a8a29e |
| Кавальня | kavalnya | #d97706 | #b45309 | #fbbf24 |

### Бейджи

```
[ФАКТ]           → зелёный (#22c55e) бейдж
[ИНТЕРПРЕТАЦИЯ]  → синий (#3b82f6) бейдж  
[СПЕКУЛЯЦИЯ]     → жёлтый (#eab308) бейдж
```

---

## Реализация

### 1. Таблица для хранения Mini App ответов

В app.mlog, при инициализации БД:

```sql
CREATE TABLE IF NOT EXISTS miniapp_responses (
  id TEXT PRIMARY KEY,
  dept TEXT NOT NULL,
  title TEXT,
  query TEXT,
  raw_text TEXT NOT NULL,
  html TEXT NOT NULL,
  confidence TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. Builtin `generate_id()` → String

Генерация уникального ID для каждого ответа:

```rust
fn builtin_generate_id() -> Result<Value, String> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ts = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis();
    let id = format!("{:x}", ts);
    Ok(Value::Str(id))
}
```

Или проще: использовать timestamp как ID.

### 3. Builtin `format_miniapp(raw_text, dept, title, doc_id)` → String

Это ключевой builtin — пост-процессор текста в HTML. Реализуй на Rust:

```rust
fn builtin_format_miniapp(args: Vec<Value>) -> Result<Value, String> {
    let raw_text = args[0].as_str()?;
    let dept = args[1].as_str()?;
    let title = args[2].as_str()?;
    let doc_id = args[3].as_str()?;

    // Цвета по отделу
    let (grad_start, grad_end, accent) = match dept {
        "osp" => ("#dc2626", "#991b1b", "#ef4444"),
        "lz" => ("#0891b2", "#0e7490", "#06b6d4"),
        "expert" => ("#4f46e5", "#3730a3", "#6366f1"),
        "marketing" => ("#f97316", "#ea580c", "#fb923c"),
        "finance" => ("#16a34a", "#15803d", "#22c55e"),
        "legal" => ("#64748b", "#475569", "#94a3b8"),
        "dev" => ("#2563eb", "#1d4ed8", "#3b82f6"),
        "design" => ("#ec4899", "#db2777", "#f472b6"),
        "qa" => ("#84cc16", "#65a30d", "#a3e635"),
        "visual" => ("#a855f7", "#9333ea", "#c084fc"),
        "engineering" => ("#78716c", "#57534e", "#a8a29e"),
        "kavalnya" => ("#d97706", "#b45309", "#fbbf24"),
        _ => ("#6366f1", "#8b5cf6", "#7c3aed"), // yana default
    };

    let dept_name = match dept {
        "osp" => "ОСП — Отдел стратегического планирования",
        "lz" => "ЛЗ — Лаборатория знаний",
        "expert" => "Эксперт — Технический препаратор",
        "marketing" => "Маркетинг",
        "finance" => "Финансы",
        "legal" => "Юрист",
        "dev" => "Dev — Разработка",
        "design" => "Design — UI/UX",
        "qa" => "QA — Тестирование",
        "visual" => "Visual — Визуализация",
        "engineering" => "Engineering — Инженерный отдел",
        "kavalnya" => "Кавальня — Методологический контур",
        _ => "Яна — Шеф де кабинет",
    };

    // Обработка текста: замена маркеров на HTML-бейджи
    let processed = raw_text
        .replace("[ФАКТ]", r#"<span class="badge badge-fact">ФАКТ</span>"#)
        .replace("[ИНТЕРПРЕТАЦИЯ]", r#"<span class="badge badge-interp">ИНТЕРПРЕТАЦИЯ</span>"#)
        .replace("[СПЕКУЛЯЦИЯ]", r#"<span class="badge badge-spec">СПЕКУЛЯЦИЯ</span>"#);

    // Обработка заголовков: "Слой N — Название" → <h2>
    // Обработка подзаголовков: "### Текст" → <h3>
    // Обработка списков: "- текст" или "1. текст" → <li>
    // Обработка разделителей: "---" → <hr>
    // Двойной перенос → </p><p>
    // Это упрощённый markdown-to-html

    let mut html_body = String::new();
    for line in processed.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            html_body.push_str("<br>");
        } else if trimmed.starts_with("Слой ") || trimmed.starts_with("## ") {
            let heading = trimmed.trim_start_matches("## ");
            html_body.push_str(&format!(r#"<h2 class="section-heading">{}</h2>"#, heading));
        } else if trimmed.starts_with("### ") {
            let heading = trimmed.trim_start_matches("### ");
            html_body.push_str(&format!("<h3>{}</h3>", heading));
        } else if trimmed.starts_with("---") {
            html_body.push_str("<hr>");
        } else if trimmed.starts_with("- ") || trimmed.starts_with("• ") {
            let item = &trimmed[2..];
            html_body.push_str(&format!("<li>{}</li>", item));
        } else {
            html_body.push_str(&format!("<p>{}</p>", trimmed));
        }
    }

    // Дисклеймеры
    let disclaimer = match dept {
        "finance" => r#"<div class="disclaimer">Не является финансовой консультацией. Обратитесь к лицензированному специалисту.</div>"#,
        "legal" => r#"<div class="disclaimer">Не является юридической консультацией. Обратитесь к лицензированному юристу.</div>"#,
        "engineering" => r#"<div class="disclaimer">Требует review лицензированного инженера. Не использовать для строительства без проверки.</div>"#,
        _ => "",
    };

    // Финальный HTML
    let html = format!(r#"<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; color: #1e293b; background: #f8fafc; }}
.header {{ background: linear-gradient(135deg, {grad_start}, {grad_end}); padding: 32px 24px; color: white; }}
.header h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 8px; }}
.header .subtitle {{ font-size: 15px; opacity: 0.9; margin-bottom: 4px; }}
.header .meta {{ font-size: 12px; opacity: 0.7; }}
.content {{ padding: 20px 24px; max-width: 720px; margin: 0 auto; }}
.content p {{ line-height: 1.7; margin-bottom: 12px; font-size: 15px; }}
.content h2 {{ font-size: 18px; font-weight: 700; margin: 28px 0 12px; padding-bottom: 8px; border-bottom: 2px solid {accent}; color: {grad_start}; }}
.content h3 {{ font-size: 16px; font-weight: 600; margin: 20px 0 8px; }}
.content li {{ margin-left: 20px; margin-bottom: 6px; line-height: 1.6; }}
.content hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: white; margin-right: 6px; vertical-align: middle; }}
.badge-fact {{ background: #22c55e; }}
.badge-interp {{ background: #3b82f6; }}
.badge-spec {{ background: #eab308; color: #1e293b; }}
.disclaimer {{ background: #fef3cd; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 24px 0; font-size: 13px; border-radius: 0 4px 4px 0; }}
.verdict {{ background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin: 24px 0; }}
.action-bar {{ display: flex; gap: 8px; padding: 16px 24px; border-top: 1px solid #e2e8f0; background: white; position: sticky; bottom: 0; }}
.action-bar button {{ flex: 1; padding: 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: white; font-size: 13px; cursor: pointer; }}
.action-bar button:active {{ background: #f1f5f9; }}
</style>
</head>
<body>
<div class="header">
  <h1>{dept_name}</h1>
  <div class="subtitle">{title}</div>
  <div class="meta">{doc_id} · Fosved Office v2</div>
</div>
<div class="content">
  {html_body}
  {disclaimer}
</div>
<div class="action-bar">
  <button onclick="copyText()">📋 Копировать</button>
  <button onclick="shareTg()">📤 Поделиться</button>
</div>
<script>
function copyText() {{
  const text = document.querySelector('.content').innerText;
  navigator.clipboard.writeText(text).then(() => alert('Скопировано'));
}}
function shareTg() {{
  const url = window.location.href;
  window.open('https://t.me/share/url?url=' + encodeURIComponent(url));
}}
</script>
</body>
</html>"#,
        grad_start=grad_start, grad_end=grad_end, accent=accent,
        dept_name=dept_name, title=title, doc_id=doc_id,
        html_body=html_body, disclaimer=disclaimer
    );

    Ok(Value::Str(html))
}
```

**Это большой builtin.** Если слишком сложно делать в Rust — альтернатива: `format_miniapp` читает HTML-шаблон из файла (`templates/miniapp.html`) и делает простые замены `{{dept_name}}`, `{{content}}`, `{{color}}`. Тогда Rust-код минимальный, а стили — в отдельном файле.

### 4. Маршрут для Mini App

В app.mlog:

```mlog
route "/miniapp/:id" method=GET {
  let id = params.id
  let row = query("SELECT html FROM miniapp_responses WHERE id = $1", [id])
  if len(row) > 0 then {
    return respond_html("200", row)
  }
  return respond("404 Not found")
}
```

**Проблема:** параметры маршрута (`:id`) не были подтверждены как рабочие. Если не работают — используй query parameter:

```mlog
route "/miniapp" method=GET {
  let id = query_param("id")
  ...
}
```

Или добавь builtin `query_param(name)` для чтения URL query string.

### 5. Логика в обработчике отдела

Каждый отдел после получения ответа от LLM:

```mlog
let raw_reply = call_llm(provider, api_key, model, profile, query)

if len(raw_reply) >= 800 then {
  let doc_id = dept + "-" + to_string(now())
  let html = format_miniapp(raw_reply, dept, query, doc_id)
  let _ = query("INSERT INTO miniapp_responses (id, dept, title, query, raw_text, html) VALUES ($1,$2,$3,$4,$5,$6)",
    [doc_id, dept, query, query, raw_reply, html])

  let summary = substring(raw_reply, 0, 200) + "..."
  let safe_summary = escape_json(summary)
  let miniapp_url = env("RENDER_URL") + "/miniapp?id=" + doc_id

  let token = env("TELEGRAM_BOT_TOKEN")
  let url = "https://api.telegram.org/bot" + token + "/sendMessage"
  let body = "{\"chat_id\":" + chat_id + ",\"text\":\"" + safe_summary + "\",\"reply_markup\":{\"inline_keyboard\":[[{\"text\":\"Открыть полностью\",\"web_app\":{\"url\":\"" + miniapp_url + "\"}}]]}}"
  let r = http_post(url, body, "application/json")
} else {
  let safe_reply = escape_json(raw_reply)
  let token = env("TELEGRAM_BOT_TOKEN")
  let url = "https://api.telegram.org/bot" + token + "/sendMessage"
  let body = "{\"chat_id\":" + chat_id + ",\"text\":\"" + safe_reply + "\"}"
  let r = http_post(url, body, "application/json")
}
```

### 6. Переменная окружения

```
RENDER_URL=https://fosved-office-v2.onrender.com
```

Нужна для формирования Mini App URL.

---

## Новые builtins (итого)

| Builtin | Назначение |
|---|---|
| `format_miniapp(raw_text, dept, title, doc_id)` → String | Пост-процессор текст → HTML |
| `generate_id()` → String | Уникальный ID (или используй timestamp) |
| `respond_html(status, html)` → Response | Ответ с Content-Type text/html (если нет — добавь) |
| `query_param(name)` → String | Чтение URL query string (если route params не работают) |

---

## Локальная проверка

```bash
export RENDER_URL=http://localhost:10000
export ANTHROPIC_API_KEY=fake
export OWNER_TELEGRAM_ID=2044005421
export TELEGRAM_BOT_TOKEN=fake
export LOCKDOWN_PASSWORD=test123

bin/mlog serve app.mlog &
sleep 2

echo "=== T1: GET / ==="
curl http://localhost:10000/

echo "=== T2: Mini App page ==="
curl "http://localhost:10000/miniapp?id=test-123"

echo "=== T3: /osp (должен создать Mini App если ≥800) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/osp анализ","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Mini App: auto post-processor with department colors, badges, disclaimers"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №8

1. format_miniapp builtin: [✅/❌]
2. respond_html builtin: [✅/❌]
3. Таблица miniapp_responses: [✅/❌]
4. Route /miniapp: [✅/❌]
5. Inline-кнопка в Telegram: [✅/❌]
6. 13 цветов отделов: [✅/❌]
7. Бейджи ФАКТ/ИНТЕРПРЕТАЦИЯ/СПЕКУЛЯЦИЯ: [✅/❌]
8. Дисклеймеры (finance/legal/engineering): [✅/❌]
9. Порог 800 символов: [✅/❌]
10. T1-T3 проверки: [✅/❌]
11. git push: [✅/❌] [хэш коммита]
12. Проблемы: [если есть]
```
