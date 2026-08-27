# Отчёт: MEM-1.2

Дата: 2026-08-03
Ветка: `fix/mem1-2-unit-concat` (запушена)
Хеш коммита: `4b2a2a0`
Коммит деплоя: `6b2d209` (merge), `4c33d4c` (re-trigger) — **Render не подхватил**

## Подтверждение публикации

```
git ls-remote origin | grep mem1-2
4b2a2a02387d80de385247cfaacf42a285ae7a36	refs/heads/fix/mem1-2-unit-concat
```

## A.1: YanaRecallMemories — всегда строка на выходе

**До (строки 783–785):**
```
  let mem_text = try FormatMemoryResults(results)
  if to_string(mem_text) == "()" then { return "" }
  return mem_text
```

**После:**
```
  let mem_raw = try FormatMemoryResults(results)
  let mem_text = to_string(mem_raw)
  if mem_text == "()" then { return "" }
  return mem_text
```

`try` возвращает Unit → `to_string()` конвертирует в `"()"` → проверка и замена на `""`.

**Grep-счётчики:**
- `grep -c "to_string(mem_raw)" app.mlog` → **1**
- `./bin/mlog check app.mlog 2>&1 | grep -c "parse error"` → **0**

## A.2: Все семь источников контекста приведены к строке

**HandleYana (строки 711–726):**
```
  let s_memories = to_string(memories)
  if s_memories == "()" then { let s_memories = "" }
  let s_calendar = to_string(calendar)
  if s_calendar == "()" then { let s_calendar = "" }
  let s_weather = to_string(weather)
  if s_weather == "()" then { let s_weather = "" }
  let s_skills = to_string(skills)
  if s_skills == "()" then { let s_skills = "" }
  let s_corrections = to_string(corrections)
  if s_corrections == "()" then { let s_corrections = "" }
  let s_dialog = to_string(dialog)
  if s_dialog == "()" then { let s_dialog = "" }
  let s_now = to_string(now_info)
  if s_now == "()" then { let s_now = "" }
```

Строка `context` обновлена: `now_info` → `s_now`, `weather` → `s_weather`, `calendar` → `s_calendar`, `memories` → `s_memories`, `skills` → `s_skills`, `corrections` → `s_corrections`, `dialog` → `s_dialog`. Переменные `profile` и `anti_format` не тронуты.

Аналогичные guards добавлены в общий обработчик отделов (строки 330–341).

**Grep-счётчики:**
- `grep -c "s_memories" app.mlog` → **6** (HandleYana + общий обработчик)
- `grep -c 'let context = profile + anti_format + "' app.mlog` → **1**
- `./bin/mlog check app.mlog 2>&1 | grep -c "parse error"` → **0**

## B.1: Тело ответа логируется

**До (строки 472–475):**
```python
    except Exception as e:
        _breaker.record_failure(provider_name)
        log.warning(f"LLM fail: provider={provider_name} model={model} err={e}")
        return None
```

**После:**
```python
    except Exception as e:
        _breaker.record_failure(provider_name)
        detail = ""
        resp_obj = getattr(e, "response", None)
        if resp_obj is not None:
            try:
                detail = f" body={resp_obj.text[:300]}"
            except Exception:
                pass
        log.warning(f"LLM fail: provider={provider_name} model={model} err={e}{detail}")
        return None
```

**Grep-счётчики:**
- `grep -c "body={resp_obj.text" llm_proxy.py` → **1**
- `python3 -c "import ast; ast.parse(open('llm_proxy.py').read()); print('OK')"` → **OK**

## B.2: Причина отказа Kimi

**Не получена** — Render не подхватил деплой. После деплоя: любой запрос в отдел → строка `LLM fail: provider=kimi ... body=...` в логе.

## Smoke: требует деплоя

- 500 в логе: проверить после деплоя
- Ответ с памятью: проверить после деплоя
- Напоминание «через 2 минуты»: проверить после деплоя

## Затруднения

1. **Render не подхватывает деплой** — 2 пустых коммита запушены, `/version` всё ещё `436f863`. Возможна необходимость ручного деплоя через Render Dashboard.
2. **localhost bypass уже существовал** — в `auth_middleware` (строка 58) уже был обход для `/memory/` с localhost. Не потребовалось изменений в `_check_bearer()`.
