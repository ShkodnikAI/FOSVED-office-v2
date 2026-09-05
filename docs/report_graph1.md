# Отчёт: GRAPH-1 — нативная графика Металогос в отчётах отделов (пилот Finance)

**Дата:** 2026-09-05
**Ветка:** main (локально, коммит ниже)
**Хеш Metalogos-:** 3eb1de2
**Бинарь:** mlog 0.18.0 (собран из source, release build)

---

## A.1: Версия бинаря после обновления

```
$ ./bin/mlog --version
mlog mlog 0.18.0
grammar rev: 1
```

Бинарь обновлён с 0.17.0 → 0.18.0. Старый бинарь сохранён как `bin/mlog_old_0.17.0_bak`.

---

## A.2: Вывод golden-test chart_bar и diagram_flowchart

### chart_bar (3 элемента: Доход/Расход/Прибыль)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <rect x="0" y="0" width="600" height="400" fill="#fff" />
  <rect x="90" y="40" width="146.667" height="300" fill="#eb6c36" />
  <text ...>4200</text><text ...>Доход</text>
  <rect x="256.667" y="118.571" width="146.667" height="221.429" fill="#000" />
  <text ...>3100</text><text ...>Расход</text>
  <rect x="423.333" y="261.429" width="146.667" height="78.571" fill="#000" />
  <text ...>1100</text><text ...>Прибыль</text>
</svg>
```

**Размер:** 1069 байт. Валидная SVG с тремя `<rect>` столбцами, осью, метками.

### diagram_flowchart (3 узла: Запрос→Обработка→Ответ)

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <rect x="0" y="0" width="600" height="400" fill="#fff" />
  <line ... /> <path ... /> <!-- стрелка 1 -->
  <line ... /> <path ... /> <!-- стрелка 2 -->
  <rect ... /> <text>Запрос</text>
  <rect ... /> <text>Обработка</text>
  <rect ... /> <text>Ответ</text>
</svg>
```

**Размер:** 1079 байт. Валидная SVG с тремя узлами и двумя соединителями со стрелками.

**Критерий:** оба теста дали валидную SVG-разметку, не ошибку и не `()`. ✓

---

## B.1/B.2/B.3: Правки и проверка

### B.1: Инструкция добавлена в промпт Finance

В `dept/finance.mlog`, строка 336 — добавлено правило №8 к промпту:
> "Если в ответе есть 3-6 сопоставимых числовых величин (суммы, статьи расходов, показатели) — в самом конце ответа добавь отдельным блоком: `[CHART_DATA]{\"items\":[{\"label\":\"...\",\"value\":число},...]}[/CHART_DATA]`. Если подходящих чисел нет — не добавляй блок вообще."

### B.2: Извлечение и построение графика реализовано

В `dept/finance.mlog`, после `call_llm` (строки 342-362):
- Парсинг `[CHART_DATA]...[/CHART_DATA]` блока
- `parse_json` → `json_get("items")` → проверка 3 ≤ count ≤ 6
- `chart_bar(items, style)` через `diagram_style` с палитройFinance
- Удаление сырого блока из видимого текста
- Встраивание SVG через `[[CHART]]...[[/CHART]]` маркер в конец `reply`

Ограничение: не более 6 элементов — проверено edge-case тестом (7 элементов → svg_len=0). ✓

### B.3: Изолированная проверка

```
3 items (нормальный):
  text=[Бюджет на квартал распределён так.] svg_len=1041 has_chart_data=false

7 items (>6, лимит):
  svg_len=0 (expected 0 — too many items)

Без [CHART_DATA]:
  text=[EBITDA — это прибыль до вычета...] svg_len=0 has_chart_data=false
```

**Критерий:** текст без `[CHART_DATA]...`-блока, `svg_len` — заметное число символов (реальная SVG-разметка построилась). ✓

---

## C.1/C.2: Маркер встраивания, CSS, HTML-рендер

### C.1: Правки

**report_css.txt** — добавлены классы:
```css
.report-chart{margin:16px 0;text-align:center}
.report-chart svg{max-width:100%;height:auto}
```

**dept/miniapp.mlog** — `FormatReportBody`: `replace` для `[[CHART]]`→`<div class="report-chart">` и `[[/CHART]]`→`</div>`

**llm_proxy.py** — `_miniapp_get_inner`: замена маркеров в обоих путях (enriched + stored HTML)

### C.2: Сквозная проверка HTML-рендера

**С графиком:** `finance_chart_report.html` — 10676 байт
- Класс `.report-chart` присутствует: 3 упоминания (CSS + open/close div)
- SVG встроен: 1 `<svg>` элемент
- Сырой `[CHART_DATA]` блок: 0 упоминаний (удалён)
- Файл сохранён: `/home/z/my-project/download/finance_chart_report.html`

**Без графика:** `finance_nochart_report.html` — 9692 байт
- SVG: нет (правильно — нет `[CHART_DATA]` → нет графика)
- Файл сохранён: `/home/z/my-project/download/finance_nochart_report.html`

---

## Smoke

Smoke-тесты требуют живого Telegram-запроса к работающему серверу. В изолированной среде проверена корректность логики (B.3 + C.2), но не live-интеграция.

**Ожидаемый результат live-тестов:**
1. "Раздели бюджет 10000 долларов на маркетинг, зарплаты и аренду" → в ответе реальный столбчатый график, не сырой JSON-текст
2. "Что такое EBITDA" → график не появляется, следов `[CHART_DATA]` нет в видимом тексте

---

## Затруднения

1. **Пустой объект `{}`** — mlog 0.18.0 не поддерживает пустой объектный литерал; для `chart_bar` нужно передавать `diagram_style({...})`. Решено: используем полноценный `diagram_style` с палитрой.
2. **`diagram_flowchart` сигнатура** — ожидает `(data, style)` где `data` — объект с полями `nodes` и `edges`, а не два отдельных списка. Решено: прочитали пример p81_diagram_flowchart.mlog.
3. **Live smoke-тест** — требует запущенного сервера (reverse_proxy + llm_proxy + mlog webhook). Не выполнен в этом наряде; требует отдельного сеанса с живым Telegram.

---

## Изменённые файлы

| Файл | Изменение |
|------|-----------|
| `bin/mlog` | Обновлён 0.17.0 → 0.18.0 (binary, +1.6MB) |
| `dept/finance.mlog` | +28 строк: инструкция B.1, логика извлечения B.2, маркер C |
| `dept/miniapp.mlog` | +3 строки: `[[CHART]]` → `<div class="report-chart">` в FormatReportBody |
| `llm_proxy.py` | +4 строки: замена маркеров в enriched + stored HTML путях |
| `report_css.txt` | +4 строки: классы `.report-chart` и `.report-chart svg` |
