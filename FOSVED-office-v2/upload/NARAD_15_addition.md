# ДОПОЛНЕНИЕ К НАРЯДУ №15: Кнопки Mini App по отделам

**Добавить к наряду №15 и выполнить вместе.**

---

## Кнопки для ВСЕХ отделов (базовый набор)

| Кнопка | Действие | Реализация |
|---|---|---|
| Копировать | Скопировать текст отчёта | `navigator.clipboard.writeText()` |
| PDF | Сохранить как PDF | `window.print()` с `@media print` |
| Поделиться | Переслать ссылку | `navigator.share()` или `tg.openTelegramLink()` |
| Важные замечания | Строка ввода → сохранение к отчёту | Текстовое поле + кнопка "Сохранить" → sendData |

### "Важные замечания" — реализация

Не prompt(), а постоянно видимая строка внизу отчёта:

```html
<div class="notes-section">
  <div class="notes-title">Vazhnye zamechaniya</div>
  <div class="notes-list" id="notesList"></div>
  <div class="notes-input">
    <input type="text" id="noteInput" placeholder="Dobavit' zamechanie..." />
    <button onclick="addNote()">+</button>
  </div>
</div>
```

CSS:
```css
.notes-section{padding:16px 24px;border-top:1px solid #e2e8f0}
.notes-title{font-size:14px;font-weight:600;color:#334155;margin-bottom:8px}
.notes-list{margin-bottom:8px}
.note-item{background:#fffbeb;border-left:3px solid #f59e0b;padding:8px 12px;margin:4px 0;font-size:13px;border-radius:0 4px 4px 0;display:flex;justify-content:space-between}
.note-item .note-time{font-size:11px;color:#94a3b8}
.notes-input{display:flex;gap:6px}
.notes-input input{flex:1;padding:8px 12px;border:1px solid #e2e8f0;border-radius:6px;font-size:13px}
.notes-input button{padding:8px 14px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-weight:600;cursor:pointer}
```

JS:
```javascript
function addNote() {
  var input = document.getElementById('noteInput');
  var text = input.value.trim();
  if (!text) return;

  // Показать локально
  var list = document.getElementById('notesList');
  var now = new Date().toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'});
  list.innerHTML += '<div class="note-item"><span>' + text + '</span><span class="note-time">' + now + '</span></div>';
  input.value = '';

  // Отправить боту
  tg.sendData(JSON.stringify({action: 'note', doc_id: docId, text: text}));
}
```

Замечания сохраняются в БД (append к raw_text отчёта) и видны при повторном открытии.

---

## Дополнительные кнопки для ОСП

| Кнопка | Действие | Описание |
|---|---|---|
| Журналист | Генерация статьи | LLM переписывает анализ в журналистский формат: без реквизитов, без бейджей, живой язык, понятный обычному читателю |
| Погружение | Выбор глубины | Меню с 4 уровнями → LLM доанализирует до выбранного уровня |
| На контроль | Архив + расписание | Сохранение с выбором частоты сверки: ежедневно / еженедельно / ежемесячно |
| Контр-прогноз | Альтернативный сценарий | LLM строит максимально противоположный прогноз с аргументами |

### Кнопка "Журналист"

При нажатии → sendData → webhook → LLM переписывает:

```mlog
// В HandleMiniAppAction
match action {
  "journalist" then {
    let raw = query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [doc_id])
    let title = query("SELECT title FROM miniapp_responses WHERE id = $1", [doc_id])
    let journalist_prompt = "Ты — журналист-аналитик. Перепиши следующий аналитический отчёт в формат журналистской статьи. Требования:\n- Без служебных реквизитов (ID, confidence, методология)\n- Без бейджей [ФАКТ]/[ИНТЕРПРЕТАЦИЯ]/[СПЕКУЛЯЦИЯ]\n- Живой, увлекательный язык\n- Понятный обычному читателю без специальной подготовки\n- Сохрани все ключевые факты и выводы\n- Добавь лид-абзац (зацепка)\n- Структура: лид → контекст → основная часть → вывод\n- Длина: 1000-1500 слов\n- Заголовок — яркий, журналистский"
    let context = BuildContext("osp", to_string(title), chat_id)
    let article = call_llm(context + "\n\n" + journalist_prompt, to_string(raw))
    let _ = SendReport(article, "osp", "Stat'ya: " + to_string(title), 2.0, chat_id)
    return "ok"
  }
}
```

HTML в Mini App — отдельная кнопка с иконкой:

```html
<button class="action-btn" onclick="doAction('journalist')">
  <i class="icon">&#9997;</i> Zhurnalist
</button>
```

### Кнопка "Погружение" (степень погружения)

Раскрывающееся меню с 4 уровнями:

```html
<div class="depth-menu" id="depthMenu" style="display:none">
  <div class="depth-option" onclick="setDepth(1)">
    <div class="depth-dot" style="background:#94a3b8"></div>
    <div><b>Bystraya ocenka</b><br><span style="font-size:11px;color:#64748b">2-3 sloya, 10 sek</span></div>
  </div>
  <div class="depth-option" onclick="setDepth(2)">
    <div class="depth-dot" style="background:#3b82f6"></div>
    <div><b>Standartnyj</b><br><span style="font-size:11px;color:#64748b">5-7 sloyov, ACH</span></div>
  </div>
  <div class="depth-option" onclick="setDepth(3)">
    <div class="depth-dot" style="background:#f59e0b"></div>
    <div><b>Glubokoe</b><br><span style="font-size:11px;color:#64748b">8-10 sloyov, premortem, cantillon</span></div>
  </div>
  <div class="depth-option" onclick="setDepth(4)">
    <div class="depth-dot" style="background:#dc2626"></div>
    <div><b>Polnoe + Red Team</b><br><span style="font-size:11px;color:#64748b">12+ sloyov, kontr-analiz</span></div>
  </div>
</div>
```

CSS:
```css
.depth-menu{background:#fff;border:1px solid #e2e8f0;border-radius:8px;margin:8px 16px;overflow:hidden}
.depth-option{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;border-bottom:1px solid #f1f5f9}
.depth-option:last-child{border:none}
.depth-option:active{background:#f8fafc}
.depth-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
```

JS:
```javascript
function toggleDepth() {
  var m = document.getElementById('depthMenu');
  m.style.display = m.style.display === 'none' ? 'block' : 'none';
}
function setDepth(level) {
  tg.sendData(JSON.stringify({action: 'deepen_to', doc_id: docId, depth: level}));
  tg.close();
}
```

Обработка в webhook:
```mlog
  "deepen_to" then {
    let depth = to_float(json_get(payload, "depth"))
    let raw = query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [doc_id])
    let title = query("SELECT title FROM miniapp_responses WHERE id = $1", [doc_id])

    let depth_instruction = ""
    match depth {
      1.0 then { let depth_instruction = "Bystraya ocenka. 2-3 sloya. Kratko." }
      2.0 then { let depth_instruction = "Standartnyj analiz. 5-7 sloyov. ACH 3 gipotezy." }
      3.0 then { let depth_instruction = "Glubokoe preparirovanie. 8-10 sloyov. ACH 5 gipotez. Premortem. Kantil'onovskij analiz." }
      4.0 then { let depth_instruction = "Polnoe preparirovanie + Red Team. 12+ sloyov. ACH, premortem, kantillon, narrative-vs-flows, source triangulation. Posle analiza — sam sebe Red Team: slepye pyatna i kontrargumenty." }
      else { let depth_instruction = "Standartnyj analiz." }
    }

    let context = BuildContext("osp", to_string(title), chat_id)
    let deeper = call_llm(context, depth_instruction + "\n\nPredydushchij analiz:\n" + to_string(raw) + "\n\nUglubi do urovnya " + to_string(depth))
    let _ = SendReport(deeper, "osp", to_string(title) + " (depth " + to_string(to_int(depth)) + ")", depth, chat_id)
    return "ok"
  }
```

### Кнопка "На контроль"

Меню выбора частоты сверки:

```html
<div class="control-menu" id="controlMenu" style="display:none">
  <div class="control-option" onclick="setControl('daily')">Ezhrdnevno</div>
  <div class="control-option" onclick="setControl('weekly')">Ezhenedel'no</div>
  <div class="control-option" onclick="setControl('monthly')">Ezhemesyachno</div>
</div>
```

JS:
```javascript
function toggleControl() {
  var m = document.getElementById('controlMenu');
  m.style.display = m.style.display === 'none' ? 'block' : 'none';
}
function setControl(freq) {
  tg.sendData(JSON.stringify({action: 'control', doc_id: docId, frequency: freq}));
  tg.close();
}
```

Обработка:
```mlog
  "control" then {
    let freq = json_get(payload, "frequency")
    let title = query("SELECT title FROM miniapp_responses WHERE id = $1", [doc_id])
    // Сохранить в watchlist с частотой
    kv_set("control_" + doc_id, freq + "|" + to_string(title))
    // Отправить в архив
    let archive_channel = env("TELEGRAM_ARCHIVE_CHANNEL_ID")
    let raw = query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [doc_id])
    let archive_msg = "[OSP KONTROL'] " + to_string(title) + "\nChastota: " + freq + "\n\n" + substring(to_string(raw), 0, 3000)
    send_message(archive_channel, archive_msg)
    send_message(chat_id, "Na kontrole (" + freq + "): " + to_string(title))
    return "ok"
  }
```

Scheduler (наряд №17) будет проверять `kv_list("control_")` и запускать сверку по расписанию.

### Кнопка "Контр-прогноз"

```mlog
  "counter_forecast" then {
    let raw = query("SELECT raw_text FROM miniapp_responses WHERE id = $1", [doc_id])
    let title = query("SELECT title FROM miniapp_responses WHERE id = $1", [doc_id])
    let counter_prompt = "Ты — контр-аналитик. Построй максимально противоположный прогноз к данному анализу. Требования:\n- Найди все слабые места исходного прогноза\n- Построй альтернативный сценарий где всё идёт наоборот\n- Используй те же факты но интерпретируй их с противоположной позиции\n- Оцени вероятность контр-сценария\n- Укажи какие индикаторы покажут что контр-сценарий реализуется\n- Формат: ACH с минимум 3 контр-гипотезами"
    let context = BuildContext("osp", to_string(title), chat_id)
    let counter = call_llm(context + "\n\n" + counter_prompt, to_string(raw))
    let _ = SendReport(counter, "osp", "Kontr-prognoz: " + to_string(title), 3.0, chat_id)
    return "ok"
  }
```

---

## Итоговый action bar

### Для ВСЕХ отделов (4 кнопки + строка замечаний):

```html
<div class="action-bar">
  <button class="action-btn" onclick="copyText()">Kopirovat'</button>
  <button class="action-btn" onclick="window.print()">PDF</button>
  <button class="action-btn" onclick="shareReport()">Podelitsa</button>
</div>
<div class="notes-section">...</div>
```

### Для ОСП (4 базовые + 4 специальные + строка замечаний):

```html
<div class="action-bar osp-bar">
  <button class="action-btn primary" onclick="doAction('journalist')">Zhurnalist</button>
  <button class="action-btn" onclick="toggleDepth()">Pogruzhenie</button>
  <button class="action-btn" onclick="toggleControl()">Na kontrol'</button>
  <button class="action-btn danger" onclick="doAction('counter_forecast')">Kontr-prognoz</button>
  <button class="action-btn" onclick="copyText()">Kopirovat'</button>
  <button class="action-btn" onclick="window.print()">PDF</button>
  <button class="action-btn" onclick="shareReport()">Podelitsa</button>
</div>
<div id="depthMenu" style="display:none">...</div>
<div id="controlMenu" style="display:none">...</div>
<div class="notes-section">...</div>
```

**Шаблон report_page должен условно показывать ОСП-кнопки.** Передать параметр `dept_slug` в template и через JS:

```javascript
var deptSlug = '{{ dept_slug }}';
if (deptSlug === 'osp') {
  document.getElementById('ospButtons').style.display = 'grid';
}
```

---

## Отчёт (добавить к Наряду №15)

```
### Дополнение

16. Строка "Важные замечания": [✅/❌]
17. Журналист (ОСП): [✅/❌]
18. Погружение 4 уровня (ОСП): [✅/❌]
19. На контроль с частотой (ОСП): [✅/❌]
20. Контр-прогноз (ОСП): [✅/❌]
21. Условные кнопки по отделу: [✅/❌]
```
