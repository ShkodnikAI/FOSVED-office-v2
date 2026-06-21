# НАРЯД №13: Mini App офиса — центральная панель управления

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** `/office` → интерактивная панель: здоровье отделов, модели, ключи, lockdown, audit, экономика

---

## Концепция

Единая панель управления всем офисом. Не через команды в чате, а через UI. Открывается через `/office` → Mini App.

---

## Секции панели

### 1. Шапка
- "Fosved Office v2"
- Статус: работает / заблокирован
- Uptime (время с последнего рестарта)
- Версия

### 2. Здоровье отделов (13 карточек)
Каждый отдел — карточка с:
- Название + цвет
- Статус: активен / ошибка
- Последняя задача (когда)
- Средняя оценка (/rate)
- Кнопка → открывает дашборд отдела

Светофор:
- Зелёный: средняя оценка ≥ 4.0
- Жёлтый: оценка 3.0–3.9 или нет задач за 7 дней
- Красный: оценка < 3.0 или ошибки

### 3. Модели LLM
- Текущая приоритетная модель
- Overrides по отделам (если есть)
- Кнопки смены модели (sendData → webhook)

### 4. API Keys
- Статус каждого провайдера: ✅ настроен / ❌ нет
- Кнопка "Ввести ключ" → prompt → сохранение

### 5. Lockdown
- Статус: разблокирован / заблокирован
- Кнопка блокировки (с подтверждением пароля)

### 6. Статистика
- Задач за сегодня / неделю / месяц
- Сообщений обработано
- Голосовых распознано
- Средняя оценка по офису

---

## Реализация

### 1. Маршрут

```mlog
route "/office" method=GET {
  let html = BuildOfficePanel()
  return respond_html("200", html)
}
```

### 2. Команда `/office`

```mlog
match text {
  "/office" then {
    let render_url = env("RENDER_URL")
    let office_url = render_url + "/office"
    let body = json_encode({
      chat_id: to_float(chat_id),
      text: "Panel' upravleniya Fosved Office",
      reply_markup: {
        inline_keyboard: [[{
          text: "Otkryt' panel'",
          web_app: { url: office_url }
        }]]
      }
    })
    let token = env("TELEGRAM_BOT_TOKEN")
    http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")
    return respond("200 ok")
  }
}
```

### 3. Pattern BuildOfficePanel

```mlog
pattern BuildOfficePanel() -> String {
  // Статус lockdown
  let locked = kv_get("system_lockdown")
  let lock_status = if locked == "true" then "ZABLOKIROVAN" else "Rabotaet"
  let lock_color = if locked == "true" then "#dc2626" else "#22c55e"

  // Приоритетная модель
  let priority_provider = read_file("config/priority_provider.txt")
  let priority_model = read_file("config/priority_model.txt")

  // Статистика
  let tasks_today = to_string(query("SELECT COUNT(*) FROM archive WHERE created_at > date('now')", []))
  let tasks_week = to_string(query("SELECT COUNT(*) FROM archive WHERE created_at > date('now', '-7 days')", []))
  let tasks_total = to_string(query("SELECT COUNT(*) FROM archive", []))
  let avg_office = to_string(query("SELECT ROUND(AVG(metric_value), 1) FROM dept_metrics WHERE metric_name = 'satisfaction'", []))
  if len(avg_office) < 1 then { let avg_office = "-" }

  // Карточки отделов
  let depts = ["yana", "osp", "lz", "expert", "marketing", "finance", "legal", "dev", "design", "qa", "visual", "engineering", "kavalnya"]
  let cards_html = ""
  each dept in depts {
    let cards_html = cards_html + BuildDeptCard(dept)
  }

  // API Keys статус
  let keys_html = BuildKeysStatus()

  // Overrides
  let overrides_html = BuildOverridesHtml()

  let html = render("office_panel",
    "lock_status", lock_status,
    "lock_color", lock_color,
    "priority_provider", trim(priority_provider),
    "priority_model", trim(priority_model),
    "tasks_today", tasks_today,
    "tasks_week", tasks_week,
    "tasks_total", tasks_total,
    "avg_office", avg_office,
    "cards_html", cards_html,
    "keys_html", keys_html,
    "overrides_html", overrides_html
  )
  return to_string(html)
}
```

### 4. Pattern BuildDeptCard

```mlog
pattern BuildDeptCard(slug: String) -> String {
  let name = DeptDisplayName(slug)
  let colors = DeptColors(slug)
  let color = get(colors, 0)

  let count = to_string(query("SELECT COUNT(*) FROM archive WHERE dept = $1", [slug]))
  let avg = to_string(query("SELECT ROUND(AVG(metric_value),1) FROM dept_metrics WHERE dept = $1 AND metric_name = 'satisfaction'", [slug]))
  if len(avg) < 1 then { let avg = "-" }

  let last_task = to_string(query("SELECT created_at FROM archive WHERE dept = $1 ORDER BY created_at DESC LIMIT 1", [slug]))
  if len(last_task) < 1 then { let last_task = "net zadach" }

  // Светофор
  let avg_num = to_float(avg)
  let indicator = "gray"
  if avg_num >= 4.0 then { let indicator = "#22c55e" }
  if avg_num >= 3.0 then { if avg_num < 4.0 then { let indicator = "#eab308" } }
  if avg_num > 0.0 then { if avg_num < 3.0 then { let indicator = "#dc2626" } }

  let render_url = env("RENDER_URL")
  let dept_url = render_url + "/dept/" + slug

  return "<div class=\"dept-card\" onclick=\"window.open('" + dept_url + "')\" style=\"border-left:4px solid " + color + "\">"
    + "<div class=\"dept-indicator\" style=\"background:" + indicator + "\"></div>"
    + "<div class=\"dept-name\">" + escape_html(name) + "</div>"
    + "<div class=\"dept-stats\">" + count + " zadach · " + avg + " ocenka</div>"
    + "<div class=\"dept-last\">" + escape_html(last_task) + "</div>"
    + "</div>"
}
```

### 5. Pattern BuildKeysStatus

```mlog
pattern BuildKeysStatus() -> String {
  let result = ""

  let providers = ["ZAI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "GROK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "WHISPER_API_KEY"]
  let labels = ["Z.ai (GLM)", "DeepSeek", "Groq", "Grok (xAI)", "Anthropic", "OpenAI", "Whisper"]

  let i = 0.0
  each key_name in providers {
    let key_val = env(key_name)
    let label = get(labels, i)
    let status = if len(key_val) > 3 then "nastroyen" else "net"
    let icon = if len(key_val) > 3 then "key-ok" else "key-missing"
    let result = result + "<div class=\"key-row\"><span class=\"" + icon + "\">" + status + "</span> " + to_string(label) + "</div>"
    let i = i + 1.0
  }

  return result
}
```

### 6. Pattern BuildOverridesHtml

```mlog
pattern BuildOverridesHtml() -> String {
  let result = ""
  let depts = ["osp", "lz", "expert", "marketing", "finance", "legal", "dev", "design", "qa", "visual", "engineering", "kavalnya", "yana"]
  each dept in depts {
    let override = read_file("config/override_" + dept + ".txt")
    if len(override) > 2 then {
      let name = DeptDisplayName(dept)
      let result = result + "<div class=\"override-row\">" + escape_html(name) + ": <b>" + escape_html(trim(override)) + "</b></div>"
    }
  }
  if len(result) < 1 then { let result = "<p style=\"color:#94a3b8\">Vse otdely ispol'zuyut prioritetnuyu model'</p>" }
  return result
}
```

### 7. Обработка callback от панели

Кнопки панели отправляют sendData → webhook:

```mlog
// В webhook handler, блок web_app_data
let has_webapp = has_field(data, "message.web_app_data")
if has_webapp == 1.0 then {
  let payload_str = json_get(data, "message.web_app_data.data")
  let payload = parse_json(payload_str)
  let action = json_get(payload, "action")

  match action {
    "change_model" then {
      let provider = json_get(payload, "provider")
      let model = json_get(payload, "model")
      write_file("config/priority_provider.txt", provider)
      write_file("config/priority_model.txt", model)
      send_message(chat_id, "Model' izmenena: " + provider + " / " + model)
    }
    "set_key" then {
      let key_name = json_get(payload, "key_name")
      let key_value = json_get(payload, "key_value")
      kv_set("apikey_" + key_name, key_value)
      send_message(chat_id, "Klyuch " + key_name + " sokhranyon")
    }
    "lockdown" then {
      let pwd = json_get(payload, "password")
      let real_pwd = env("LOCKDOWN_PASSWORD")
      if pwd == real_pwd then {
        kv_set("system_lockdown", "true")
        send_message(chat_id, "Ofis zablokirovan")
      }
    }
    "unlock" then {
      let pwd = json_get(payload, "password")
      let real_pwd = env("LOCKDOWN_PASSWORD")
      if pwd == real_pwd then {
        kv_delete("system_lockdown")
        send_message(chat_id, "Ofis razblokirovan")
      }
    }
  }
  return respond("200 ok")
}
```

### 8. Template office_panel

```mlog
template office_panel(
  lock_status: String, lock_color: String,
  priority_provider: String, priority_model: String,
  tasks_today: String, tasks_week: String, tasks_total: String, avg_office: String,
  cards_html: String, keys_html: String, overrides_html: String
) -> Html {
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,'Segoe UI',Roboto,sans-serif; color:#1e293b; background:#f8fafc; }
.header { background:linear-gradient(135deg,#6366f1,#8b5cf6); padding:24px; color:#fff; }
.header h1 { font-size:22px; font-weight:700; }
.status { display:inline-block; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; color:#fff; background:{{ lock_color }}; margin-top:6px; }
.stats { display:grid; grid-template-columns:1fr 1fr 1fr 1fr; gap:8px; padding:12px; }
.stat { background:#fff; border-radius:10px; padding:12px; text-align:center; box-shadow:0 1px 2px rgba(0,0,0,.08); }
.stat-val { font-size:24px; font-weight:700; color:#6366f1; }
.stat-lbl { font-size:10px; color:#94a3b8; margin-top:2px; }
.section { padding:0 16px 12px; }
.section-title { font-size:15px; font-weight:600; margin:16px 0 8px; padding-bottom:6px; border-bottom:2px solid #6366f1; }
.dept-card { background:#fff; border-radius:10px; padding:12px; margin:6px 0; box-shadow:0 1px 2px rgba(0,0,0,.08); cursor:pointer; display:flex; align-items:center; gap:10px; }
.dept-card:active { background:#f1f5f9; }
.dept-indicator { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.dept-name { font-size:14px; font-weight:600; flex:1; }
.dept-stats { font-size:11px; color:#64748b; }
.dept-last { font-size:10px; color:#94a3b8; }
.model-box { background:#fff; border-radius:10px; padding:14px; margin:6px 0; box-shadow:0 1px 2px rgba(0,0,0,.08); }
.model-current { font-size:16px; font-weight:600; color:#6366f1; }
.model-label { font-size:11px; color:#94a3b8; }
.key-row { padding:8px 0; border-bottom:1px solid #f1f5f9; font-size:13px; }
.key-ok { color:#22c55e; font-weight:600; }
.key-missing { color:#dc2626; font-weight:600; }
.override-row { padding:6px 0; font-size:13px; border-bottom:1px solid #f1f5f9; }
.btn { padding:10px 16px; border:none; border-radius:8px; font-size:13px; cursor:pointer; margin:4px; }
.btn-primary { background:#6366f1; color:#fff; }
.btn-danger { background:#dc2626; color:#fff; }
.btn:active { opacity:.8; }
</style>
</head>
<body>
<div class="header">
  <h1>Fosved Office v2</h1>
  <div class="status">{{ lock_status }}</div>
</div>

<div class="stats">
  <div class="stat"><div class="stat-val">{{ tasks_today }}</div><div class="stat-lbl">Segodnya</div></div>
  <div class="stat"><div class="stat-val">{{ tasks_week }}</div><div class="stat-lbl">Nedelya</div></div>
  <div class="stat"><div class="stat-val">{{ tasks_total }}</div><div class="stat-lbl">Vsego</div></div>
  <div class="stat"><div class="stat-val">{{ avg_office }}</div><div class="stat-lbl">Ocenka</div></div>
</div>

<div class="section">
  <div class="section-title">Otdely</div>
  {{ cards_html | safe }}
</div>

<div class="section">
  <div class="section-title">Model' LLM</div>
  <div class="model-box">
    <div class="model-label">Prioritetnaya</div>
    <div class="model-current">{{ priority_provider }} / {{ priority_model }}</div>
  </div>
  <div class="section-title" style="margin-top:12px">Overrides</div>
  {{ overrides_html | safe }}
</div>

<div class="section">
  <div class="section-title">API Keys</div>
  {{ keys_html | safe }}
</div>

<div class="section">
  <div class="section-title">Upravlenie</div>
  <button class="btn btn-danger" onclick="lockToggle()">Lockdown</button>
</div>

<script>
const tg = window.Telegram.WebApp;
function lockToggle() {
  const pwd = prompt('Vvedite parol\':');
  if (pwd) {
    const locked = '{{ lock_status }}' === 'ZABLOKIROVAN';
    tg.sendData(JSON.stringify({action: locked ? 'unlock' : 'lockdown', password: pwd}));
    tg.close();
  }
}
</script>
</body>
</html>
}
```

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /office ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/office","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 1

echo "=== T2: GET /office (HTML) ==="
curl -s http://localhost:10000/office | head -10

echo "=== T3: callback change_model ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"web_app_data":{"data":"{\"action\":\"change_model\",\"provider\":\"anthropic\",\"model\":\"claude-sonnet-4-20250514\"}"},"from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Office dashboard: /office, health cards, models, API keys, lockdown, stats"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №13

1. template office_panel: [✅/❌]
2. BuildOfficePanel: [✅/❌]
3. BuildDeptCard (13 карточек): [✅/❌]
4. BuildKeysStatus (7 провайдеров): [✅/❌]
5. /office команда: [✅/❌]
6. GET /office (respond_html): [✅/❌]
7. Callback change_model: [✅/❌]
8. Callback lockdown/unlock: [✅/❌]
9. Статистика (today/week/total): [✅/❌]
10. json_encode для inline_keyboard: [✅/❌]
11. parse_json для web_app_data: [✅/❌]
12. T1-T3 проверки: [✅/❌]
13. git push: [✅/❌] [хэш]
14. Проблемы: [если есть]
```
