# Отчёт: SEC-4

**Дата:** 2026-08-01  
**Ветка:** `fix/sec4-initdata-bootstrap`  
**Хеш коммита:** `d440c28`  
**База:** main `70dbbd3`  
**Файл:** `llm_proxy.py` — 47 строк добавлено, 7 изменено

## Подтверждение публикации

```
$ git ls-remote origin | grep sec4
d440c28f4fcf472cd411ccf6fd70c17f5d7d86d9	refs/heads/fix/sec4-initdata-bootstrap
```

## A.1: Шаблон страницы-прихожей

Добавлена константа `_TG_BOOTSTRAP_PAGE` перед `def require_telegram` (строка 138). Содержимое — минимальная HTML-страница с:
- `<script src="https://telegram.org/js/telegram-web-app.js">` — загрузка Telegram WebApp SDK
- JS-скрипт, который берёт `Telegram.WebApp.initData`, делает `fetch` того же URL с заголовком `X-Telegram-Init-Data` и подставляет полученный HTML через `document.write`
- Если `initData` пуст — показывает «Эта страница открывается только из Telegram.»

```
$ grep -c "_TG_BOOTSTRAP_PAGE" llm_proxy.py
2
```

## A.2: Разделение логики отказа

Заменён блок `if not _verify_init_data(init_data)` в `require_telegram`:

- **Подпись отсутствует** (`not init_data`) → `200` + прихожая (`_TG_BOOTSTRAP_PAGE`)
- **Подпись есть, но не прошла проверку** → `log.warning("SEC-4: initData present but rejected")` + `403` + страница «Доступ закрыт»

```
$ grep -c "SEC-4: initData present but rejected" llm_proxy.py
1

$ python3 -m py_compile llm_proxy.py
(py_compile OK — без ошибок)
```

## A.3: Проверка логики до деплоя

Запуск с `TELEGRAM_BOT_TOKEN="test-bot-token-for-sec4" OWNER_TELEGRAM_ID="2044005421"`:

```
без подписи: 200 | прихожая: True
подпись неверная: 403 | отказ: True
```

Обе строки совпали с ожидаемыми. Содержимое страниц при неудачной проверке не отдаётся ни в одном случае.

## Smoke (после деплоя — проверяет владелец)

1. Запрос с длинным ответом → кнопка «Открыть отчёт» → отчёт открывается (кратко мелькнёт «Загрузка…»).
2. `/archive list` → ссылка → листалка открывается; переходы год → месяц → отдел → отчёт работают.
3. Кнопки нижней панели в отчёте → не 404 и не 403.
4. `/status` или дашборд отдела → открывается.
5. `https://fosved-office-v2.onrender.com/archive/browse` в обычном браузере → «Эта страница открывается только из Telegram», содержимого архива не видно.
6. Render-лог: 403 на страницах нет, traceback = 0.

## Затруднения

Нет.
