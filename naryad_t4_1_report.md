# Отчёт: T4.1 action-bar верификация
**Дата:** 2026-07-06
**Хеш:** 8546909 (main)
**Env:** sandbox без Flask/Telegram/LLM. Все пробы — статическая верификация код-путей. e2e пробы — SKIP-BY-ENV.

## A: Базовые кнопки (3 пробы)

| ID | вердикт | метод |
|----|---------|-------|
| A.1 Копировать | PASS (код-путь) | `navigator.clipboard.writeText` — стандартный API. iOS WebApp caveat — не проверяемо. |
| A.2 PDF | PASS (код-путь) | `window.print()` + `@media print` скрывает action-bar. |
| A.3 Поделиться | PASS (код-путь) | Цепочка `navigator.share` → `tg.openTelegramLink` → `alert` фолбэк корректна. |

Все 3 базовые кнопки имеют корректные код-пути. e2e — SKIP-BY-ENV.

## B: Замечания (2 пробы)

| ID | вердикт | метод |
|----|---------|-------|
| B.1 Локальное добавление | PASS (код-путь) | innerHTML аппенд + fetch POST. |
| B.2 Сохранение при переоткрытии | PASS (код-путь) | INSERT miniapp_notes → SELECT при рендере → notes_html в _build_action_bar. Цепочка БД полная. |

e2e — SKIP-BY-ENV.

## C: ОСП-кнопки (4 пробы)

| ID | вердикт | детали |
|----|---------|--------|
| C.1 Журналист | **FAIL** (TG) / SKIP-BY-OWNER (HTTP) | Telegram: `HandleMiniAppAction` не обрабатывает `journalist` — молчаливый `return "ok"`. HTTP: `/webhook/miniapp-action` (llm_proxy.py:1233) — корректен, но нужен LLM-ключ. |
| C.2 Погружение | **FAIL** (TG) / SKIP-BY-OWNER (HTTP) | Telegram: `deepen_to_N` не обработан в mlog. HTTP: корректен (llm_proxy.py:1242). |
| C.3 На контроль | **FAIL** (TG) / SKIP-BY-ENV (HTTP) | Telegram: mlog ждёт `action=="watch"` + поля `{freq, topic}`, но кнопка шлёт `action: "control_weekly"` — **несоответствие имён**. HTTP: корректен (llm_proxy.py:1252). |
| C.4 Контр-прогноз | **FAIL** (TG) / SKIP-BY-OWNER (HTTP) | Telegram: `counter_forecast` не обработан в mlog. HTTP: корректен (llm_proxy.py:1258). |

**Корневая причина:** `dept/miniapp.mlog:HandleMiniAppAction` (стр. 251-289) реализует только 3 действия: `archive`, `note`, `watch`. Четыре ОСП-действия из action-bar (`journalist`, `deepen_to_N`, `control_N`, `counter_forecast`) не обработаны. Фолбэк `return "ok"` на стр. 288 — молчаливо проглатывает неизвестные действия без ошибки и без ответа пользователю.

**Дополнительный дефект C.3:** Даже если бы mlog обрабатывал `control_*`, имя не совпадает — mlog ждёт `action=="watch"` с отдельными полями `freq` и `topic`, а кнопка шлёт `action: "control_weekly"` с doc_id.

**HTTP-фолбэк (`/webhook/miniapp-action`):** Все 4 ОСП-действия корректно реализованы в llm_proxy.py:1233-1268. Этот путь работает в браузере (не через Telegram WebApp sendData). Однако он требует:
- C.1, C.4: `call_llm("osp", messages)` — нужен LLM API-ключ
- C.2: `call_llm("osp", messages)` — нужен LLM API-ключ
- C.3: только INSERT в БД — работал бы без LLM

## D: Условность по отделу (1 проба)

| ID | вердикт | метод |
|----|---------|-------|
| D.1 НЕ-osp без ОСП-кнопок | PASS (код-путь) | `_build_action_bar`: `if dept == "osp"` — gate на стр. 1059. Базовые 3 кнопки рендерятся всегда. |

## E: Ширина/вёрстка (1 проба)

| ID | вердикт | детали |
|----|---------|--------|
| E.1 Ширина на мобильном | PASS (телефон) / INFO (планшет) | `report_css.txt:1` → `max-width: 480px`. На телефоне (< 480px) — полная ширина. На планшете (≥ 481px) — контейнер 480px по центру, что может быть узковато. Серверный рендер использует свой `report_css.txt` (инлайн в HTML), не `css/*.css` из SPA — чинятся раздельно (наряд 4.0 не затрагивает). |

## FAIL/SKIP-BY-OWNER

- **FAIL (Telegram-путь):** C.1, C.2, C.3, C.4 — ОСП-действия не доходят от `tg.sendData` до обработки. `HandleMiniAppAction` в `dept/miniapp.mlog` не знает эти действия.
- **SKIP-BY-OWNER:** C.1, C.2, C.4 (HTTP-путь) — нужны LLM-ключи для `call_llm`.
- **SKIP-BY-ENV:** A.1-A.3, B.1-B.2, D.1, E.1 — нужны Telegram WebApp / браузер / мобильный клиент.

## Дефекты для наряда-фикса

1. **`dept/miniapp.mlog:251-288`** — `HandleMiniAppAction` не обрабатывает ОСП-действия (`journalist`, `deepen_to_N`, `control_N`, `counter_forecast`). Все 4 молча проглатываются (`return "ok"` на стр. 288 без обработки).
   - **Фикс-вариант A (рекомендуемый):** делегировать ОСП-действия в llm_proxy через `http_post( RENDER_URL + "/webhook/miniapp-action", payload )` — код уже написан в llm_proxy.py:1233-1268, не дублировать.
   - **Фикс-вариант B:** реализовать обработку непосредственно в mlog (требует LLM-вызовы из mlog — сложнее, дублирование).

2. **`dept/miniapp.mlog:278-286`** — обработчик `action == "watch"` ожидает JSON `{action:"watch", freq:"daily", topic:"..."}`, но кнопка «На контроль» шлёт `{action:"control_weekly", doc_id:"..."}`. Имя действия и структура payload не совпадают.
   - **Фикс:** либо переименовать в mlog `watch` → `control_*`, либо в JS `doControl` шлёт `action:"watch"` + поля `freq` и `topic`.

3. **`dept/miniapp.mlog:288`** — фолбэк `return "ok"` не логирует неизвестные действия и не сообщает пользователю. Рекомендация: добавить `send_message(chat_id, "Неизвестное действие: " + action)` перед return.