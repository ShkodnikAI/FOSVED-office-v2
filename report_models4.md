# Отчёт: MODELS-4

**Дата:** 2026-08-01  
**Ветка:** `fix/models4-kimi-k3`  
**Хеш коммита:** `deefc98`  
**База:** main `70dbbd3`  
**Файл:** `llm_proxy.py` — 3 строки изменены

## Подтверждение публикации

```
$ git ls-remote origin | grep models4
deefc98c0ea51f41c5593b244f78a8b3f767fffd	refs/heads/fix/models4-kimi-k3
```

## A.1: Замена имени модели

**До:**
```
$ grep -c "kimi-k2-0711-preview" llm_proxy.py
3
```

**Замена:** во всех трёх вхождениях `COMBO_CHAINS`:
```python
# было:
("kimi", ["kimi-k2-0711-preview"]),
# стало:
("kimi", ["kimi-k3"]),
```

**После:**
```
$ grep -c "kimi-k2-0711-preview" llm_proxy.py
0

$ grep -c '"kimi-k3"' llm_proxy.py
3

$ python3 -m py_compile llm_proxy.py
(py_compile OK — без ошибок)
```

## A.2: Контроль цепочек

Чтение `llm_proxy.py` строки 245–273:

```
fosved-free: [
    ("groq", ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]),
    ("cerebras", ["gpt-oss-120b"]),
    ("deepseek", ["deepseek-chat"]),
]

fosved-standard: [
    ("kimi", ["kimi-k3"]),
    ("deepseek", ["deepseek-chat"]),
    ("zai", ["glm-4.6", "glm-4-plus"]),
    ("groq", ["llama-3.3-70b-versatile"]),
    ("cerebras", ["gpt-oss-120b"]),
]

fosved-deep: [
    ("kimi", ["kimi-k3"]),
    ("deepseek", ["deepseek-chat"]),
    ("zai", ["glm-4.6"]),
    ("groq", ["llama-3.3-70b-versatile"]),
    ("cerebras", ["gpt-oss-120b"]),
    ("anthropic", ["claude-sonnet-4-20250514"]),
]

fosved-fusion: [
    ("kimi", ["kimi-k3"]),
    ("deepseek", ["deepseek-chat"]),
    ("zai", ["glm-4.6"]),
    ("groq", ["llama-3.3-70b-versatile"]),
    ("cerebras", ["gpt-oss-120b"]),
    ("anthropic", ["claude-sonnet-4-20250514"]),
]
```

- `fosved-free` — без kimi ✅
- `fosved-standard` — первый элемент `('kimi', ['kimi-k3'])` ✅
- `fosved-deep` — первый элемент `('kimi', ['kimi-k3'])` ✅
- `fosved-fusion` — первый элемент `('kimi', ['kimi-k3'])` ✅
- Порядок провайдеров не изменён ✅
- Дубликатов нет ✅

## Smoke (после деплоя — проверяет владелец)

**Требуемые проверки:**
1. Запрос в любой отдел (ОСП / финансы) → ответ приходит.
2. В Render-логе строка `LLM ok: provider=kimi model=kimi-k3 dept=...`. Строки `LLM fail: provider=kimi` быть не должно.
3. Обычное сообщение Яне → отвечает groq или cerebras, не kimi.
4. `/api/economics` → по провайдеру kimi ненулевой расход.
5. `/health` → ok.

## Затруднения

Нет.
