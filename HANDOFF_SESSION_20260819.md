# HANDOFF — Сессия 2026-08-19

## Что сделано (коммит `c1fac8e`)

### 1. Yana metrics (app.mlog)
- **Таблицы** `yana_delegation_log` и `yana_forgetting_incidents` + 3 индекса (строки 90-95)
- **YanaRecordDelegation()** — вызывается из HandleYana при делегировании (строка 1022)
- **YanaRecordForgetting()** — вызывается из /fix когда recent_dept=="yana" (строки 1612-1617)
- **YanaGetMetrics()** — агрегация: точность делегирования %, забывчивость (всего/7д/память была vs нет), нарушения гейтов
- **/yana-metrics** — новая команда (строки 1657-1662), добавлена в /help

### 2. call_python bridge — Variant B (llm_proxy.py + app.mlog)
- **`/call-python`** endpoint в llm_proxy.py (строки 5758-5798)
- **`call_python(module, function, args_json)`** pattern в app.mlog (строки 1356-1361)
- **Whitelist**: `CALL_PYTHON_ALLOWED` — 12 модулей, ~40 функций
- **Безопасность**: двойной whitelist (модуль + функция), audit log для всех вызовов/блокировок

### 3. Yana v6.0 enrichment (уже было на origin — коммит `3a66621`)
- 8 hard gates + YanaEnforceGates + YanaWrapWithDisclaimer + native call_llm
- Это было запушено из предыдущей сессии, мы добавили только метрики и call_python поверх

---

## Архитектура системы

```
Telegram → Render (reverse_proxy.py :443)
                ↓
         Python (llm_proxy.py :4000) ←→ mlog (app.mlog :10001)
                ↓                         ↓
           LLM circuit breaker      SQLite, routing,
           TTS/STT, Telegram API     14 dept handlers,
           image gen, OSINT         scheduler, hard gates,
                                   call_python bridge
```

### Ключевые файлы
| Файл | Строки | Роль |
|------|--------|------|
| `app.mlog` | ~3100 | Главный диспетчер: роутинг, все dept, сервер :10001 |
| `llm_proxy.py` | ~5810 | Python-прокси: LLM, TTS/STT, Telegram, /call-python |
| `dept/utils.mlog` | — | Общие паттерны: AuditLog, ReadDeptProfile и т.д. |
| `bin/mlog` | 21MB ELF | Metalogos runtime v0.12.0 (246 builtins) |
| `entrypoint.sh` | — | Deploy: mlog check, .mbc cache, builtin check |
| `render.yaml` | — | Render.com конфигурация |

---

## СЛЕДУЮЩИЙ ШАГ: LLM-as-a-Verifier

### Что нужно сделать
1. **Создать `lib/llm_verifier.py`** с функциями:
   - `select(candidates, criteria, weights)` — best-of-N selection
   - `score(text, criteria)` — fine-grained reward scoring 0-1
   - `verify(claim, evidence)` — claim verification
   - `rank(candidates, scores)` — ranking by scores

2. **Добавить `"llm_verifier"` в whitelist** — уже есть в `CALL_PYTHON_ALLOWED`:
   ```python
   "llm_verifier": {"select", "score", "verify", "rank"},
   ```

3. **Интегрировать в Яну** (app.mlog HandleYana):
   - После call_llm: `let verify_result = call_python("llm_verifier", "score", json_encode({text: reply, criteria: [...]}) )`
   - Если score < 0.5: запросить повторную генерацию
   - Записывать score в yana_delegation_log как feedback

4. **Расширить на другие отделы**:
   - **Expert**: best-of-N выбор из 3 кандидатов
   - **OSP**: confidence scoring для прогнозов
   - **QA**: probabilistic gates вместо бинарных

### GitHub репозиторий верификатора
`llm-as-a-verifier/llm-as-a-verifier` — 4 ключевых концепции:
- Fine-grained reward scoring (не бинарный pass/fail)
- Best-of-N selection
- Self-verification (LLM проверяет сам себя)
- Pivot tournament (кандидаты соревнуются)

---

## Фоновой баг: unknown function HandleExpert/HandleOSP

- **Статус**: Probably resolved после redeploy
- **Причина**: stale `.mbc` bytecode cache на Render
- **Фиксы уже в коде** (коммиты `ef8ec72`, `371f0ed`, `0a7ddbf` из предыдущих сессий)
- **Что проверить после деплоя**: /osp test, /expert test — если ошибки остались, удалить `*.mbc` в entrypoint.sh

---

## Ключевые решения сессии

1. **Variant B реализован как HTTP bridge**, не PyO3 в бинарнике — исходников Rust нет, только скомпилированный bin/mlog
2. **Яна v6.0 уже была на origin** из предыдущей сессии (`3a66621`) — мы добавили только метрики и call_python
3. **55 коммитов дивергенции** между локальным и origin — решено через `git reset --hard origin/main` + точечные правки

---

## Вызовы из Metalogos

```mlog
// Вызов Python функции из .mlog:
let result = call_python("statistics", "mean", "[[1,2,3,4,5]]")

// Парсинг результата:
let parsed = parse_json(result)
let value = json_get(parsed, "result", "0")
```

```mlog
// LLM-as-a-Verifier (когда модуль будет создан):
let verify = call_python("llm_verifier", "score", json_encode({text: reply, criteria: ["accuracy", "completeness", "no_hallucination"]}))
```

## Расширение whitelist

В `llm_proxy.py` строка 5740 — `CALL_PYTHON_ALLOWED`:
```python
CALL_PYTHON_ALLOWED = {
    "llm_verifier": {"select", "score", "verify", "rank"},
    "json": {"dumps", "loads"},
    "statistics": {"mean", "median", "stdev", "variance"},
    "math": {"ceil", "floor", "log", "log10", "sqrt", "exp", "pow", "factorial", "gcd", "comb", "perm"},
    "datetime": {"datetime", "timedelta", "timezone"},
    "re": {"match", "search", "findall", "sub", "split"},
    "difflib": {"SequenceMatcher", "get_close_matches"},
    "csv": {"reader", "writer", "DictReader", "DictWriter"},
    "decimal": {"Decimal"},
    "fractions": {"Fraction"},
}
```

Чтобы добавить новый модуль — добавить запись в dict. Функции класса (напр. `datetime.datetime`) требуют импорта через importlib.
