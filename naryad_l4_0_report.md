# Отчёт: L4.0 SPA wire
**Дата:** 2026-07-06
**Ветка:** fix/l4-0-spa-wire
**Хеш:** 8546909
**Коммит:** L4.0: wire SPA — remove inline placeholder, connect css + app.js module
**База:** main (2491ca9)

## A.1: id контейнера рендера

`js/app.js:41` → `document.getElementById('screen-container')`.
В старом index.html этого id не было. Добавлен `<div id="screen-container"></div>`.
Дополнительно: `js/components/nav.js` ожидает `data-route` на `.nav-item` (стр. 21) и `.sidebar-item` (стр. 25) — старый HTML использовал `data-screen` и `href` без `data-route`. Все навигационные элементы обновлены.

## A.2: вырезано

- **Инлайн `<style>`**: строки 12-459 (~450 строк CSS, дублирующие css/*.css)
- **Инлайн `<script>`**: строки 608-710 (102 строки: mock DEPARTMENTS, renderDepartments, placeholder hash routing, Telegram init)
- **Заглушечная разметка**: status-row, alerts (2 hardcoded), kpi-row (3 hardcoded), dept-list пустой контейнер, section-header "Отделы", admin-section с hardcoded stats
- **Phone topbar**: динамически рендерится экранами через app.js

**Grep-проверки:**
- `grep -c "placeholder — only" index.html` → 0 ✅
- `grep -c "renderDepartments" index.html` → 0 ✅

## A.3: подключено

В `<head>` добавлены 4 CSS в порядке каскада:
1. `<link rel="stylesheet" href="css/vars.css">`
2. `<link rel="stylesheet" href="css/components.css">`
3. `<link rel="stylesheet" href="css/screens.css">`
4. `<link rel="stylesheet" href="css/responsive.css">`

Перед `</body>`:
- `<script type="module" src="js/app.js"></script>`

**Grep-проверки:**
- `grep -c 'href="css/' index.html` → 4 ✅
- `grep -c 'type="module" src="js/app.js"' index.html` → 1 ✅

## A.4: отдача статики

**Роут:** llm_proxy.py:3546 — `@app.get("/miniapp-spa/<path:filepath>")`
- Вложенные пути: да (`<path:filepath>` захватывает `js/screens/dashboard.js` и т.д.)
- Content-Type для .js: `application/javascript` (стр. 3553) ✅
- Content-Type для .css: `text/css` ✅
- Нахожки: нет, отдача корректная

## Smoke

Локальный стенд не поднят (sandbox OOM). Проверены:
- Все 9 файлов `js/screens/*.js` существуют на диске
- Все 4 `css/*.css` существуют на диске
- `js/app.js` и `js/components/nav.js` существуют на диске
- `git diff --name-only` → только `miniapp/index.html`

Прод: после деплоя на Render — открыть `RENDER_URL/miniapp-spa`, должен рендериться дашборд (экран по умолчанию `/`).

## Затруднения

Нет. Передача навигации (sidebar + bottom-nav) потребовала замены `data-screen` → `data-route` чтобы соответствовать nav.js, но это чисто механическая правка в рамках задачи A.1.