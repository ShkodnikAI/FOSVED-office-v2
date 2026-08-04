# Отчёт: PROD-1

**Дата:** 2026-07-30
**Ветка:** `fix/prod1-three-defects`
**Хеш:** `717c5e9`
**Коммит:** `fix(PROD-1): three defects from prod logs`

## Подтверждение публикации

```
717c5e9e961d57375b5753e3042222f9d7cae8f6	refs/heads/fix/prod1-three-defects
```

## A.1: Перенос __main__

**До:** строка 5057 (перед NEWS MONITORING — мёртвая зона)
**После:** строка 5273 (последняя строка файла)

**Проверка кода после __main__:**
```
Счётчик исполняемого кода после __main__: 0
```

**Проверка доступности функций:**
```
get_fresh_news: True
collect_rss: True
get_night_news_digest: True
```

**Роуты зарегистрированы:**
```
/cron/collect-news True
/news/fresh True
/news/stats True
/lz/news True
/extract-document True
```

## B.1/B.2: Таблица потолков и применение

**PROVIDER_MAX_TOKENS** (строка 117):
```python
PROVIDER_MAX_TOKENS = {
    "groq": 2048,
}
```

**Применение потолка** (строка 857):
```python
cap = PROVIDER_MAX_TOKENS.get(prov_name)
if cap:
    max_tok = min(max_tok, cap)
```

**Проверка:**
```
PROVIDER_MAX_TOKENS.get(prov_name): 1 вхождение
python3 -c "import llm_proxy": чист
```

## C.1: Диагностика длины ответа

**Строка лога** (строка 346):
```python
log.info(f"LLM ok: provider={provider_name} model={model} dept={dept} "
         f"t_in={t_in} t_out={t_out} reply_chars={len(reply)} reply_head={reply[:120]!r}")
```

**Проверка:**
```
reply_chars=: 1 вхождение
```

## py_compile: чист

## Smoke: шесть пунктов

Требует мерджа в main и деплоя. Владелец проверяет.

| # | Проверка | Ожидание | Статус |
|---|---|---|---|
| 1 | Обычное сообщение боту → ответ | Ответ приходит | ⏳ после деплоя |
| 2 | `/news/stats` → не 404 и не 500 | JSON с цифрами | ✅ код доступен (A.1) |
| 3 | `/cron/collect-news` → сбор | Число материалов | ✅ код доступен (A.1) |
| 4 | Сообщение Яне → groq без 413 | `reply_chars=` в логе | ⏳ после деплоя |
| 5 | Утренний бриф без ошибки | Нет `scheduler_morning_brief_error` | ⏳ после деплоя |
| 6 | `/health` → ok, traceback = 0 | 200 | ⏳ после деплоя |

## Лог

Будет заполнен владельцем после деплоя — 2–3 строки `LLM ok` с `reply_chars` и `reply_head`.

## Затруднения

Нет. Все три блока выполнены механически, без неожиданностей.
