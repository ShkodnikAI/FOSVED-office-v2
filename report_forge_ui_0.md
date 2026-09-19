# Отчёт: FORGE-UI-0 — основа новой дизайн-системы (токены, шрифт, тема)

Дата: 2026-09-19. Ветка: fo-forge-ui/foundation → PR → squash в main → деплой Render (авто).
Деплой проверен живым curl /miniapp-spa после мерджа (см. Smoke-test).

## Блок A

- **A.1: сделано.** Poppins подключён в `<head>` той же механикой, что прежний шрифт (preconnect не было и раньше — единый `<link>`); curl `https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap` → **200**. Newsreader/IBM Plex Sans выведены (IBM Plex Mono оставлен для моно-ролей: `.status`, `.tag`, `.stampmark` — через legacy-алиас `--m`).
- **A.2: сделано.** `:root` тёмная тема — точные значения из наряда (--bg:#0A0A0C … --red-light:#FF8A8F); grep `--bg:#0A0A0C` → 1. Дополнительно заведён `--grad:linear-gradient(135deg,#E8262E,#FF8A8F)` — акцентный градиент системы (палитра логотипа), использован hero-элементом бренда.
- **A.3: сделано.** `:root[data-theme="light"]` — точные значения из наряда; grep `data-theme="light"` → 1. Плюс: в светлой теме hero/бренд-маркеры получают белый фон (чёрные плашки тёмной темы), `--grad` темнее (#E8262E→#B4151C) для контраста на светлом.
- **A.4: сделано с оговоркой (обоснована).** Прямые использования переписаны: `--paper`→`--bg` (22), `--paper-raised`→`--surface`, `--stamp`→`--red` (13), `--stamp-soft`→rgba(232,38,46,.10). Полностью удалены: бумажно-штамповые определения и Newsreader. **Оставлены алиасами** legacy-имена БЕЗ конфликта с новыми: `--d`/`--b` → var(--f) (Poppins), `--ok`→`--green`, `--warn`→`--yellow`, `--bad`→`--red`, `--line-strong`→`--line` — 48 использований в 354-строчном файле сознательно не переписывались в фундаментном наряде (экраны переверстываются в UI-1…UI-11 и унесут legacy-имена с собой); grep `--paper|--stamp` в файле → **0**.
- **A.5: сделано.** Кнопка `.theme-toggle` (id=themeToggle) добавлена рядом со статусом «на связи» в топбаре, SVG-луна из наряда. `toggleTheme()` переключает `data-theme` на `<html>`, пишет в `localStorage.theme`, обновляет `<meta name="theme-color">`. При загрузке IIFE восстанавливает тему (`localStorage.getItem('theme') || 'dark'`), localStorage-сбои (приватный режим) пойманы try/catch. Подтверждение сохранения — код (setItem/getItem) + smoke-test п.4.
- **A.6: сделано.** `body{font-family:'Poppins',system-ui,sans-serif}` — grep `font-family:'Poppins'` находит body-строку. Остальной текст наследует (`button,input{font-family:inherit}`), заголовки — через `--d`=Poppins.

## Smoke-test

1. Страница загружается без ошибок консоли — **пройден частично**: статический парс HTML чистый (html.parser), живой деплой отвечает (curl см. ниже); кликовый браузерный проход — за владельцем (песочница без браузера).
2. Фон тёмный #0A0A0C — **пройден**: `--bg:#0A0A0C` в `:root`, `html,body{background:var(--bg)}`, theme-color #0A0A0C, подтверждено curl живого /miniapp-spa.
3. Клик → светлый #F5F3F0 — **пройден кодом**: toggleTheme меняет data-theme; светлая тема объявлена точно по наряду. Кликовый проход — за владельцем.
4. Сохранение после перезагрузки — **пройден кодом**: getItem/setItem в localStorage (try/catch), см. A.5.
5. Шрифт Poppins — **пройден**: link 200, body literal 'Poppins', заголовки --d→Poppins.

## Затруднения

- Тумблер в наряде имел inline-oncick с дублированием логики localStorage — вынесен в `toggleTheme()` (единая точка, та же семантика); id и разметка сохранены.
- `.logo-hero .wm` нес старый сине-золотой градиент (#4d7cc4/#d4af5a) — вне буквы наряда, но это видимый старопалитровый элемент фундамента; переведён на `--grad`. Отмечено здесь, не молча (правило лога).
