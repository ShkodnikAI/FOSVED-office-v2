# Отчёт: FORGE-UI-12 — форма создания проекта FORGE (#215)

## Блок A — форма

- Кнопка «+ Новый проект» в шапке списка Проектов (`#projAddBtn`) — открывает нижний лист, не пустой экран ✅
- Лист `#projNewSheet` — переиспользование существующего паттерна `.sheet`/`.box` из Интеграций (FORGE-UI-8), новый компонент не изобретался ✅
- Четыре поля наряда: название (`input`), цель одной фразой (`textarea`), заказчик (`input`), тип — `seg-3` Сайт/Android/ИИ-офис со значениями `site`/`android`/`ai_office` (как `project_type` в схеме) ✅
- «Полная форма» (модели, gate_policy, юрданные) — не делалась по наряду: она отдельная, открывается из настроек проекта после создания.

## HTTP-путь к созданию: тонкий route + mlog-мост

Прямого HTTP-пути к `ForgeCreateProject` не было. REST-обёртки в mlog удалены («несуществующий синтаксис serve» — TODO в dept/expert.mlog), python→mlog-вызова паттернов в офисе нет. Сделано по букве наряда («завести тонкий route, вызывающий существующий паттерн, не дублировать SQL в Python»):

- **Мост `dept/forge_create_bridge.mlog`** (новый): `import dept/forge` + `db { url: env("DATABASE_URL") }` + `flow Main` → `ForgeCreateProject(env(FNP_SLUG), env(FNP_NAME), "", env(FNP_GOAL), env(FNP_TYPE), env(FNP_TYPE), env(FNP_CUSTOMER), "key_stages", "fosved-standard", "dev")`. Значения по умолчанию повторяют Telegram-контур создания (dept/forge.mlog, форма диалога). SQL и валидация — ТОЛЬКО в существующем паттерне: проверка slug/типа, уникальность slug, вставка со `status='active'`, AuditLog.
- **`POST /api/forge/projects`** (proxy/routes_admin.py, за SEC-3 auth как все /api/*): HTTP-валидация формы (название обязательно, тип ∈ {site, android, ai_office} — дословная подсказка домена как в mlog-паттерне), генерация slug, запуск моста `subprocess.run(["./bin/mlog","run","dept/forge_create_bridge.mlog"], env=FNP_*, cwd=корень, timeout=90)`, парс stdout («Проект создан: …» → ok, «ОТКАЗ: …» → 409 с текстом отказа, timeout → 504). В python НЕТ INSERT — гвард-тестом.
- **Slug**: транслитерация кириллицы (ж→zh, ч→ch, я→ya, ё→yo; ъ/ь отбрасываются), `[^a-z0-9]+` → дефис; коллизии гасятся суффиксом `-2`, `-3` (чтение-проверка; финальный гарант — проверка уникальности внутри ForgeCreateProject, отказ 409).

## Блок B — отправка и переход

- «Создать проект» → POST → на ok: лист закрывается, список обновляется, **сразу открывается карточка именно нового проекта** (`loadProjects()` + `openProject(r.project.slug)`) ✅
- Отказы — честные тосты с текстом от моста (например «ОТКАЗ: проект … уже существует»).

## Живая верификация моста (локальная база, фикстура создана/удалена)

- `FNP_* ./bin/mlog run dept/forge_create_bridge.mlog` → stdout `Проект создан: ui12-probe-proj (site, гейты: key_stages)`, RC=0; строка в `forge_projects` (slug/name/type/status='active'/customer) подтверждена SELECT'ом, потом удалена.
- ОТКАЗ-путь: неверный тип → `ОТКАЗ: project_type ∈ {site, android, ai_office}` — SQL не выполняется.
- `mlog check` моста даёт 1 известный undefined (`ForgeCreateProject` через import — ограничение статического чекера, прецедент AuditLog из SHOP-7); рантайм подтверждён живыми прогонами. Мост живёт на бинаре 0.19 (прод), в 0.20-стейджинг не входит.

## Smoke-test — 5 пунктов

1. «+» открывает форму — гвард `test_form_plus_button_and_sheet` + живая структура листа ✅
2. Отправка создаёт реальную запись — поведенческий тест `test_post_creates_via_bridge_ok` (мок моста) + живой INSERT-прогон выше ✅
3. Slug корректен, без коллизий — `test_slugify_transliterates_and_hyphenates`, `test_slug_collision_gets_suffix` (kavaleriya → kavaleriya-2) + гарант в mlog-паттерне ✅
4. После создания открывается карточка нового проекта — гвард `test_form_submit_opens_card_of_new_project` ✅
5. Проект в общем списке сразу — `loadProjects()` перед `openProject()` в цепочке создания ✅
   Живой кликовый проход в миниаппе — за владельцем (initData-гейт SEC-4, прецедент всех UI-нарядов).

## Тесты

- `tests/test_forge_ui12_create_project.py` — 11 гвардов (форма 3, тонкий route/мост 2, slugify 2, POST-поведение 4).
- Suite: 597 → **608 passed**.

## Затруднения

- Ловля на собственном комментарии: первый вариант гварда «нет INSERT в python» поймал строку INSERT в моём же комментарии к роуту — переформулирован (прецедент CSS-гварда UI-0).
- `maketrans` не принимает многозначные замены (я→ya) — карта транслитерации на словаре.
- Первый прогон моста без `db`-декларации упал «no database connection» — добавлена та же `db { url: env("DATABASE_URL") }`, что в app.mlog; подключение к общей базе прод-инстанса безопасно: запись редкая, single-INSERT.
