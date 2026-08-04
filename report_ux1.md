# Отчёт: UX-1

**Дата:** 2026-08-01  
**Ветка:** `feat/ux1-authorship`  
**Хеш коммита:** `3e950ec`  
**База:** main `fe29292`  
**Файлы:** 16 файлов изменено

## Подтверждение публикации

```
$ git ls-remote origin | grep ux1
3e950ec6c116e9690986c0ef580c6be4250b06f5	refs/heads/feat/ux1-authorship
```

## A.1: Статика Mini App

Убран `@require_telegram` с роута `miniapp_spa_static`. Добавлена защита от выхода за каталог через `.resolve()` + `startswith()`. Документирующий комментарий в docstring.

Проверка (с `TELEGRAM_BOT_TOKEN="123:TEST"`):

```
css: 200 text/css; charset=utf-8
индекс без подписи: 200 прихожая: True
выход за каталог: 404
```

- css → `200` + `text/css` ✅
- индекс без подписи → прихожая (защита сохранена) ✅
- выход за каталог → `404` ✅

`py_compile` OK.

## B.1: Провайдер/модель из обработчиков отделов

Добавлено в 14 обработчиков (13 файлов):

| Файл | Обработчик | Кол-во `last_model_` |
|------|-----------|---------------------|
| dept/osp.mlog | HandleOSP | 1 |
| dept/design.mlog | HandleDesign | 1 |
| dept/dev.mlog | HandleDev | 1 |
| dept/engineering.mlog | HandleEngineering | 1 |
| dept/expert.mlog | HandleExpert | 1 |
| dept/finance.mlog | HandleFinance | 1 |
| dept/kavalnya.mlog | HandleKavalnya | 1 |
| dept/legal.mlog | HandleLegal | 1 |
| dept/lz.mlog | HandleLZ + LZDeepScan | 2 |
| dept/marketing.mlog | HandleMarketing | 1 |
| dept/qa.mlog | HandleQA | 1 |
| dept/visual.mlog | HandleVisual | 1 |
| dept/admin.mlog | HandleAdmin | 1 |

Добавленные строки (после `let reply = json_get(...)`):
```
  let used_model = to_string(json_get(parse_json(proxy_result), "model", ""))
  let used_provider = to_string(json_get(parse_json(proxy_result), "provider", ""))
  kv_set("last_model_" + dept, used_provider + " / " + used_model)
```

## B.2: Модель в шапке отчёта

В `dept/miniapp.mlog`, `SendReport` — блок `meta`:

**До:**
```
    let mut meta = "<div class=\"report-meta\"><span>ID: " + doc_id + "</span>"
    meta = meta + "<span>" + date_str + "</span>"
    meta = meta + "<span>Confidence: " + confidence + "/4</span></div>"
```

**После:**
```
    let mut meta = "<div class=\"report-meta\"><span>ID: " + doc_id + "</span>"
    meta = meta + "<span>" + date_str + "</span>"
    meta = meta + "<span>Confidence: " + confidence + "/4</span>"
    let model_info = to_string(kv_get("last_model_" + dept))
    if model_info == "" then { let model_info = "не определена" }
    meta = meta + "<span>Модель: " + model_info + "</span></div>"
```

`grep -c "Модель:" dept/miniapp.mlog` → 1 ✅

## C.1: Префикс отдела в чате

В `dept/miniapp.mlog`, `SendReport` — добавлен блок `dept_title` с 13 названиями отделов + `short_with_dept`:

```
    let dept_title = dept
    if dept == "osp" then { let dept_title = "ОСП · Стратегическое планирование" }
    if dept == "lz" then { let dept_title = "ЛЗ · Лаборатория знаний" }
    ... (13 отделов)
    let short_with_dept = dept_title + "\n\n" + short
```

`grep -c "dept_title" dept/miniapp.mlog` → 15 ✅

## C.2: Подпись Яны

В `app.mlog:2231` — текст ответа Яны в чате:

**До:**
```
        let text_body = json_encode({chat_id: chat_id, text: reply})
```

**После:**
```
        let text_body = json_encode({chat_id: chat_id, text: "Яна\n\n" + reply})
```

Служебные команды обрабатываются ДО ветки `dept == "yana"`, поэтому подпись попадает только на содержательные ответы.

## Smoke (после деплоя — проверяет владелец)

1. Mini App → экраны загружаются: видны стили, работает навигация.
2. Запрос в отдел → перед текстом видно имя отдела; в отчёте строка `Модель: kimi / kimi-k3`.
3. Обычное сообщение Яне → ответ подписан «Яна».
4. `/status` → служебный ответ без лишней подписи.
5. Обычный браузер: `/miniapp-spa` → прихожая, `/archive/browse` → «только из Telegram».
6. `/health` → ok, traceback = 0.

## Затруднения

Нет.
