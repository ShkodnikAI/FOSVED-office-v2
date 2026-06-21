# НАРЯД №15: Формы отчётов с автоматическим пост-процессором

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Образец:** OSP_LIVE_001_rev2.pdf (приложен владельцем)
**Результат:** каждый ответ отдела автоматически превращается в стилизованный HTML-отчёт

---

## Утверждённая палитра (13 отделов)

| # | Отдел | Slug | Gradient start | Gradient end | Accent | Название цвета |
|---|---|---|---|---|---|---|
| 1 | Яна | yana | #293133 | #1a2024 | #3d4a4d | Антрацит RAL 7016 |
| 2 | ОСП | osp | #b91c1c | #7f1d1d | #dc2626 | Тёмный рубин |
| 3 | ЛЗ | lz | #0e7490 | #164e63 | #0891b2 | Глубокий циан |
| 4 | Эксперт | expert | #3730a3 | #1e1b4b | #4f46e5 | Индиго |
| 5 | Маркетинг | marketing | #c2410c | #7c2d12 | #ea580c | Жжёный оранж |
| 6 | Финансы | finance | #15803d | #14532d | #16a34a | Тёмный изумруд |
| 7 | Юрист | legal | #475569 | #1e293b | #64748b | Сталь |
| 8 | Dev | dev | #1d4ed8 | #1e3a8a | #2563eb | Кобальт |
| 9 | Design | design | #be185d | #831843 | #ec4899 | Малина |
| 10 | QA | qa | #4d7c0f | #365314 | #65a30d | Оливковый |
| 11 | Visual | visual | #7e22ce | #581c87 | #a855f7 | Аметист |
| 12 | Engineering | engineering | #44403c | #292524 | #78716c | Графит |
| 13 | Кавальня | kavalnya | #b45309 | #78350f | #d97706 | Тёмная бронза |

**Правило шрифтов на градиентах:** заголовок `#ffffff`, подзаголовок `rgba(255,255,255,0.75)`.

**Бейджи (одинаковые для всех):**
- ФАКТ: фон `#16a34a`, текст `#ffffff`
- ИНТЕРПРЕТАЦИЯ: фон `#2563eb`, текст `#ffffff`
- СПЕКУЛЯЦИЯ: фон `#ca8a04`, текст `#1c1917`

---

## Концепция пост-процессора

### Что делает

LLM отдела возвращает текст с маркировкой. Пост-процессор:

1. Парсит текст → находит структуру (слои, заголовки, бейджи, таблицы, вердикт)
2. Оборачивает в HTML с CSS отдела (gradient, accent, цвета)
3. Добавляет шапку (название отдела, заголовок запроса, ID, дата, confidence)
4. Добавляет дисклеймер (Finance, Legal, Engineering)
5. Добавляет action bar (8 кнопок)
6. Добавляет индикатор глубины
7. Сохраняет в БД
8. Отдаёт по маршруту `/miniapp/{id}`

### Элементы дизайна (из образца OSP PDF)

**Шапка:**
- Gradient фон (цвет отдела)
- Название отдела (белый, 22px, bold)
- Заголовок запроса (белый, 15px)
- Метаданные: ID · дата · confidence (rgba белый, 12px)

**Секции:**
- `Слой N — Название` → `<h2>` с border-bottom цвета accent
- Подзаголовки → `<h3>`

**Бейджи в тексте:**
- `[ФАКТ]` → зелёный pill
- `[ИНТЕРПРЕТАЦИЯ]` → синий pill
- `[СПЕКУЛЯЦИЯ]` → жёлтый pill

**Карточки категорий:**
- Блок с border-left (accent) + крупная цифра + описание
- Используется для сумм, процентов, ключевых значений

**Сравнение (Нарратив vs Реальность):**
- Два блока side-by-side
- Левый: ✗ красная рамка
- Правый: ✓ зелёная рамка

**Таблица ACH:**
- Гипотеза | Аргументы | P (вероятность)
- Строки с чередующимся фоном

**Вердикт:**
- Блок с border + фон, выделенный текст

**Индикаторы наблюдения:**
- Grid 2×2 карточки с темой + значением + описанием

**Подвал:**
- Методология (мелкий шрифт)
- Дисклеймер (если нужен)

**Action bar (8 кнопок, sticky bottom):**
- Углубить (primary, цвет accent)
- Red Team (danger)
- Наблюдение
- В архив
- Замечания
- Копировать
- PDF (window.print)
- Поделиться

**Индикатор глубины (в шапке):**
- Полоска progress bar
- 25% / 50% / 75% / 100% + label

---

## Реализация

### 1. Обновить DeptColors с утверждённой палитрой

```mlog
pattern DeptColors(slug: String) -> List {
  match slug {
    "yana" then { return ["#293133", "#1a2024", "#3d4a4d"] }
    "osp" then { return ["#b91c1c", "#7f1d1d", "#dc2626"] }
    "lz" then { return ["#0e7490", "#164e63", "#0891b2"] }
    "expert" then { return ["#3730a3", "#1e1b4b", "#4f46e5"] }
    "marketing" then { return ["#c2410c", "#7c2d12", "#ea580c"] }
    "finance" then { return ["#15803d", "#14532d", "#16a34a"] }
    "legal" then { return ["#475569", "#1e293b", "#64748b"] }
    "dev" then { return ["#1d4ed8", "#1e3a8a", "#2563eb"] }
    "design" then { return ["#be185d", "#831843", "#ec4899"] }
    "qa" then { return ["#4d7c0f", "#365314", "#65a30d"] }
    "visual" then { return ["#7e22ce", "#581c87", "#a855f7"] }
    "engineering" then { return ["#44403c", "#292524", "#78716c"] }
    "kavalnya" then { return ["#b45309", "#78350f", "#d97706"] }
    else { return ["#293133", "#1a2024", "#3d4a4d"] }
  }
}
```

### 2. Template `report_page`

Полный HTML-шаблон отчёта. Это основной файл — все отделы используют один шаблон с разными цветами.

```mlog
template report_page(
  dept_name: String, title: String, doc_id: String, date: String,
  confidence: String, depth_percent: String, depth_label: String,
  grad_start: String, grad_end: String, accent: String,
  body_html: String, disclaimer: String, methodology: String
) -> Html {
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;color:#1e293b;background:#f8fafc}

.header{background:linear-gradient(135deg,{{ grad_start }},{{ grad_end }});padding:28px 24px 20px;color:#fff}
.header h1{font-size:22px;font-weight:700}
.header .subtitle{font-size:15px;color:rgba(255,255,255,.85);margin-top:6px}
.header .meta{font-size:12px;color:rgba(255,255,255,.6);margin-top:8px}
.depth-bar-wrap{display:flex;align-items:center;gap:8px;margin-top:10px}
.depth-track{flex:1;height:4px;background:rgba(255,255,255,.25);border-radius:2px}
.depth-fill{height:100%;background:#fff;border-radius:2px}
.depth-label{font-size:11px;color:rgba(255,255,255,.7)}

.content{padding:20px 24px;max-width:720px;margin:0 auto}
.content p{line-height:1.7;margin-bottom:12px;font-size:15px}
.content h2{font-size:18px;font-weight:700;margin:28px 0 12px;padding-bottom:8px;border-bottom:2px solid {{ accent }};color:{{ grad_start }}}
.content h3{font-size:16px;font-weight:600;margin:20px 0 8px;color:#334155}
.content li{margin-left:20px;margin-bottom:6px;line-height:1.6}
.content hr{border:none;border-top:1px solid #e2e8f0;margin:24px 0}

.badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:.3px;color:#fff;margin-right:6px;vertical-align:middle}
.badge-fact{background:#16a34a}
.badge-interp{background:#2563eb}
.badge-spec{background:#ca8a04;color:#1c1917}

.card-block{background:#fff;border-left:4px solid {{ accent }};border-radius:0 8px 8px 0;padding:16px 20px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card-block .big-num{font-size:28px;font-weight:700;color:{{ accent }}}
.card-block .label{font-size:13px;color:#64748b;margin-top:2px}

.compare{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}
.compare-box{border-radius:8px;padding:16px;font-size:14px;line-height:1.6}
.compare-bad{background:#fef2f2;border:1px solid #fecaca}
.compare-good{background:#f0fdf4;border:1px solid #bbf7d0}
.compare-title{font-weight:600;margin-bottom:6px;font-size:15px}

.ach-table{width:100%;border-collapse:collapse;margin:16px 0;font-size:14px}
.ach-table th{text-align:left;padding:10px 12px;background:#f1f5f9;font-weight:600;border-bottom:2px solid #e2e8f0}
.ach-table td{padding:10px 12px;border-bottom:1px solid #f1f5f9}
.ach-table tr:nth-child(even) td{background:#fafafa}
.ach-prob{font-weight:700;color:{{ accent }};text-align:right;min-width:40px}

.verdict{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:20px;margin:24px 0}
.verdict h3{font-size:16px;font-weight:700;margin-bottom:12px;color:{{ grad_start }}}
.verdict p{margin-bottom:8px}

.indicators{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}
.indicator-card{background:#fff;border-radius:8px;padding:14px;border:1px solid #e2e8f0}
.indicator-topic{font-weight:600;font-size:14px}
.indicator-value{font-size:20px;font-weight:700;color:{{ accent }};margin:4px 0}
.indicator-desc{font-size:12px;color:#64748b}

.disclaimer{background:#fef3cd;border-left:4px solid #f59e0b;padding:14px 18px;margin:24px 0;font-size:13px;border-radius:0 4px 4px 0;color:#92400e}
.methodology{font-size:11px;color:#94a3b8;text-align:center;padding:16px 24px;border-top:1px solid #e2e8f0}

.action-bar{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;padding:12px 16px;border-top:1px solid #e2e8f0;background:#fff;position:sticky;bottom:0}
.action-btn{padding:10px 4px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;font-size:11px;cursor:pointer;text-align:center;color:#334155}
.action-btn:active{background:#f1f5f9}
.action-btn.primary{background:{{ accent }};color:#fff;border-color:{{ accent }}}
.action-btn.danger{background:#fef2f2;color:#b91c1c;border-color:#fecaca}

@media print{.action-bar{display:none}.header{-webkit-print-color-adjust:exact;print-color-adjust:exact}body{background:#fff}}
</style>
</head>
<body>

<div class="header">
  <h1>{{ dept_name }}</h1>
  <div class="subtitle">{{ title }}</div>
  <div class="meta">{{ doc_id }} · {{ date }} · Confidence: {{ confidence }}</div>
  <div class="depth-bar-wrap">
    <div class="depth-track"><div class="depth-fill" style="width:{{ depth_percent }}%"></div></div>
    <span class="depth-label">{{ depth_label }}</span>
  </div>
</div>

<div class="content">
  {{ body_html | safe }}
  {{ disclaimer | safe }}
</div>

<div class="methodology">{{ methodology }}</div>

<div class="action-bar">
  <button class="action-btn primary" onclick="doAction('deepen')">Uglublit'</button>
  <button class="action-btn danger" onclick="doAction('redteam')">Red Team</button>
  <button class="action-btn" onclick="doAction('watch')">Nablyudat'</button>
  <button class="action-btn" onclick="doAction('archive')">V arkhiv</button>
  <button class="action-btn" onclick="doAction('note')">Zamechaniya</button>
  <button class="action-btn" onclick="copyText()">Kopirovat'</button>
  <button class="action-btn" onclick="window.print()">PDF</button>
  <button class="action-btn" onclick="shareReport()">Podelitsa</button>
</div>

<script>
var tg=window.Telegram.WebApp;
var docId='{{ doc_id }}';
function doAction(a){
  if(a==='note'){var t=prompt('Zamechanie:');if(!t)return;tg.sendData(JSON.stringify({action:a,doc_id:docId,text:t}));}
  else{tg.sendData(JSON.stringify({action:a,doc_id:docId}));}
  tg.close();
}
function copyText(){
  var t=document.querySelector('.content').innerText;
  navigator.clipboard.writeText(t).then(function(){tg.showAlert('Skopirovano!')});
}
function shareReport(){
  if(navigator.share){navigator.share({title:'{{ title }}',url:location.href})}
  else{tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(location.href))}
}
</script>
</body>
</html>
}
```

### 3. Pattern `FormatReportBody` — парсинг текста LLM в HTML

Это ключевой pattern. Преобразует сырой текст LLM в HTML с бейджами, секциями, карточками.

```mlog
pattern FormatReportBody(raw: String) -> String {
  let html = raw

  // Бейджи
  let html = replace(html, "[ФАКТ]", "<span class=\"badge badge-fact\">ФАКТ</span>")
  let html = replace(html, "[ИНТЕРПРЕТАЦИЯ]", "<span class=\"badge badge-interp\">ИНТЕРПРЕТАЦИЯ</span>")
  let html = replace(html, "[СПЕКУЛЯЦИЯ]", "<span class=\"badge badge-spec\">СПЕКУЛЯЦИЯ</span>")
  let html = replace(html, "[FACT]", "<span class=\"badge badge-fact\">ФАКТ</span>")
  let html = replace(html, "[INTERPRETATION]", "<span class=\"badge badge-interp\">ИНТЕРПРЕТАЦИЯ</span>")
  let html = replace(html, "[SPECULATION]", "<span class=\"badge badge-spec\">СПЕКУЛЯЦИЯ</span>")

  // Заголовки слоёв: "Слой N — Текст" или "## Текст"
  // Используем LLM для форматирования сложной структуры
  // Базовая обработка через replace:

  let html = replace(html, "\n\n", "</p><p>")
  let html = replace(html, "\n- ", "</p><li>")
  let html = replace(html, "\n---\n", "</p><hr><p>")

  // Обернуть в параграфы
  let html = "<p>" + html + "</p>"

  // Убрать пустые параграфы
  let html = replace(html, "<p></p>", "")

  return html
}
```

**Важно:** базовый FormatReportBody делает минимум — бейджи + параграфы. Для полноценного форматирования (слои → h2, таблицы ACH, карточки, сравнения) нужен более сложный парсинг. Два подхода:

**Подход A (рекомендуемый): LLM форматирует сам.** В системном промпте каждого отдела добавить инструкцию:

```
Форматируй ответ в HTML. Используй:
- <h2> для заголовков слоёв
- <h3> для подзаголовков
- <span class="badge badge-fact">ФАКТ</span> для маркировки
- <span class="badge badge-interp">ИНТЕРПРЕТАЦИЯ</span>
- <span class="badge badge-spec">СПЕКУЛЯЦИЯ</span>
- <div class="card-block"><div class="big-num">$300B+</div><div class="label">описание</div></div> для ключевых цифр
- <div class="compare"><div class="compare-box compare-bad"><div class="compare-title">✗ Нарратив</div>текст</div><div class="compare-box compare-good"><div class="compare-title">✓ Реальность</div>текст</div></div> для сравнений
- <table class="ach-table"><tr><th>Гипотеза</th><th>Аргументы</th><th>P</th></tr>...</table> для ACH
- <div class="verdict"><h3>Вердикт</h3><p>текст</p></div> для вердикта
- <div class="indicators"><div class="indicator-card"><div class="indicator-topic">тема</div><div class="indicator-value">значение</div><div class="indicator-desc">описание</div></div></div> для индикаторов
```

**Подход B: пост-процессинг Rust builtin.** Сложный regex/парсинг в Rust. Дороже в разработке, но LLM не тратит токены на HTML-теги.

**Рекомендую подход A:** LLM уже знает структуру ответа (слои, ACH, вердикт) — пусть сразу выдаёт HTML-разметку. FormatReportBody тогда просто подчищает (экранирование опасного, закрытие тегов).

### 4. Pattern `BuildReport`

Собирает полный HTML-отчёт:

```mlog
pattern BuildReport(raw_text: String, dept: String, title: String, depth: Float) -> String {
  let colors = DeptColors(dept)
  let grad_start = get(colors, 0)
  let grad_end = get(colors, 1)
  let accent = get(colors, 2)

  let dept_name = DeptDisplayName(dept)
  let doc_id = dept + "-" + to_string(to_int(now()))
  let date = to_string(to_int(now()))

  let confidence = if depth >= 4.0 then "high (verified)"
    else if depth >= 3.0 then "medium-high"
    else if depth >= 2.0 then "medium"
    else "preliminary"

  let depth_percent = to_string(to_int(depth * 25.0))
  let depth_label = if depth >= 4.0 then "Polnoe + Red Team"
    else if depth >= 3.0 then "Glubokoe"
    else if depth >= 2.0 then "Standartnyj"
    else "Bystraya ocenka"

  let body_html = FormatReportBody(raw_text)

  let disclaimer = ""
  match dept {
    "finance" then { let disclaimer = "<div class=\"disclaimer\">Ne yavlyaetsya finansovoj konsul'taciej. Obratites' k licenzirovannomu specialistu.</div>" }
    "legal" then { let disclaimer = "<div class=\"disclaimer\">Ne yavlyaetsya yuridicheskoj konsul'taciej. Obratites' k licenzirovannomu yuristu.</div>" }
    "engineering" then { let disclaimer = "<div class=\"disclaimer\">Trebuet review licenzirovannogo inzhenera. Ne ispol'zovat' dlya stroitel'stva bez proverki.</div>" }
    else { let disclaimer = "" }
  }

  let methodology = DeptMethodology(dept)

  let html = render("report_page",
    "dept_name", dept_name,
    "title", title,
    "doc_id", doc_id,
    "date", date,
    "confidence", confidence,
    "depth_percent", depth_percent,
    "depth_label", depth_label,
    "grad_start", grad_start,
    "grad_end", grad_end,
    "accent", accent,
    "body_html", body_html,
    "disclaimer", disclaimer,
    "methodology", methodology
  )

  // Сохранить в БД
  let _ = query("INSERT INTO miniapp_responses (id, dept, title, query, raw_text, html) VALUES ($1,$2,$3,$4,$5,$6)",
    [doc_id, dept, title, title, raw_text, to_string(html)])

  return doc_id
}
```

### 5. Pattern `DeptMethodology`

```mlog
pattern DeptMethodology(dept: String) -> String {
  match dept {
    "osp" then { return "OSP Fosved Office · Metodologiya: deconstruct + ACH + cantillon + narrative-vs-flows + base-rates + premortem" }
    "lz" then { return "LZ Fosved Office · Metodologiya: disruption-scoring + inflection-detection + hype-cycle + patent-analysis" }
    "expert" then { return "Expert Fosved Office · Metodologiya: rapid-immersion + combat-questions + peer-review-simulation" }
    "finance" then { return "Finance Fosved Office · Metodologiya: cashflow-forecasting + unit-economics + tax-compliance" }
    "legal" then { return "Legal Fosved Office · Metodologiya: risk-mapping + red-flag-detection + cross-jurisdiction" }
    else { return "Fosved Office v2" }
  }
}
```

### 6. Обновить инструкции LLM-промптов

В каждый library/*.md профиль отдела добавить секцию форматирования:

```markdown
## Формат ответа (HTML)

Отвечай с HTML-разметкой для красивого отображения. Используй классы:
- `<h2>Слой N — Название</h2>` для секций
- `<h3>Подзаголовок</h3>` для подсекций
- `<span class="badge badge-fact">ФАКТ</span>` — подтверждённые данные
- `<span class="badge badge-interp">ИНТЕРПРЕТАЦИЯ</span>` — твой анализ
- `<span class="badge badge-spec">СПЕКУЛЯЦИЯ</span>` — гипотеза
- `<div class="card-block"><div class="big-num">$300B+</div><div class="label">описание</div></div>` — ключевые цифры
- `<div class="verdict"><h3>Вердикт</h3><p>текст</p></div>` — итоговый вывод
- `<div class="compare"><div class="compare-box compare-bad"><div class="compare-title">✗ Нарратив</div>текст</div><div class="compare-box compare-good"><div class="compare-title">✓ Реальность</div>текст</div></div>` — сравнения
- `<table class="ach-table">...</table>` — таблица гипотез
- `<div class="indicators"><div class="indicator-card">...</div></div>` — индикаторы
```

### 7. Обновить send_miniapp

Заменить текущий send_miniapp на использование BuildReport:

```mlog
pattern SendReport(raw_reply: String, dept: String, title: String, depth: Float, chat_id: String) -> String {
  if len(raw_reply) >= 800 then {
    let doc_id = BuildReport(raw_reply, dept, title, depth)
    let summary = substring(raw_reply, 0, 200)
    let safe_summary = escape_json(summary)
    let render_url = env("RENDER_URL")
    let miniapp_url = render_url + "/miniapp/" + doc_id

    let body = json_encode({
      chat_id: to_float(chat_id),
      text: safe_summary + "...",
      reply_markup: {
        inline_keyboard: [[{
          text: "Otkryt' polnyj otchyot",
          web_app: { url: miniapp_url }
        }]]
      }
    })
    let token = env("TELEGRAM_BOT_TOKEN")
    http_post("https://api.telegram.org/bot" + token + "/sendMessage", body, "application/json")
  } else {
    send_message(chat_id, raw_reply)
  }
  return "ok"
}
```

---

## Локальная проверка

```bash
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /osp (должен создать отчёт) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/osp test","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T2: GET miniapp (проверить HTML) ==="
curl -s http://localhost:10000/miniapp/osp-test | head -20

echo "=== T3: /finance (дисклеймер) ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/finance test","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## Коммит

```bash
git commit -m "Report templates: auto post-processor, 13 dept colors, badges, depth, action bar, disclaimers"
git push origin main
```

---

## Отчёт

```
### Результат Наряда №15

1. Утверждённая палитра (13 цветов): [✅/❌]
2. template report_page: [✅/❌]
3. FormatReportBody: [✅/❌]
4. BuildReport pattern: [✅/❌]
5. DeptMethodology: [✅/❌]
6. SendReport с порогом 800: [✅/❌]
7. Бейджи ФАКТ/ИНТЕРПРЕТАЦИЯ/СПЕКУЛЯЦИЯ: [✅/❌]
8. Дисклеймеры (finance/legal/engineering): [✅/❌]
9. Индикатор глубины: [✅/❌]
10. 8 кнопок action bar: [✅/❌]
11. @media print для PDF: [✅/❌]
12. LLM-промпты обновлены (HTML-разметка): [✅/❌]
13. T1-T3 проверки: [✅/❌]
14. git push: [✅/❌] [хэш]
15. Проблемы: [если есть]
```
