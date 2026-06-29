# Наряд — Слой 1: Унификация DB-схем и рантайм-фиксы

**Проект:** FOSVED Office V2
**Дата:** 2026-06-27
**Версия:** 1.0
**Слой:** 1 (рантайм-баги)

## Цель прохода

Устранить расхождение схем SQLite между `llm_proxy.py` (Python) и `app.mlog` (Metalogos), из-за которого все SQL-запросы из mlog-слоя к совместным таблицам падают с ошибкой несуществующих колонок. Параллельно — починить два мёртвых пути: загрузку скиллов и ссылку на несуществующую таблицу `archive`.

## Запреты прохода

- Не трогать .mlog файлы кроме `dept/context.mlog` (задача E.1) и `dept/scheduler.mlog` (задача D.1-D.3)
- Не менять бизнес-логику LLM-вызовов, фейловера, Telegram-интеграции
- Не переименовывать файлы и папки в `skills/`, `library/`, `config/`
- Не удалять данные из существующей БД — только миграция схемы
- Не менять `app.mlog`, `dept/admin.mlog`, `dept/utils.mlog`, `dept/miniapp.mlog`, `dept/lz.mlog`
- Не заниматься содержанием скиллов — только починка путей загрузки

## Перед началом

Создать файл `LAYER1_REPORT.md` в корне проекта:

```markdown
# Layer 1 Report — DB Schema Unification
Date: <дата>
## Блок A — Миграция
## Блок B — CREATE TABLE
## Блок C — Python-запросы
## Блок D — scheduler.mlog
## Блок E — context.mlog
## Smoke-test
## Чек-лист сдачи
```

**Правило при затруднении:** если какой-либо шаг невыполним (например, `ALTER TABLE RENAME COLUMN` не поддерживается), записать в `LAYER1_REPORT.md` что именно не получилось, пометить `BLOCKED`, перейти к следующей задаче.

---

## Блок A. Миграция существующей БД

Суть: на Render уже есть `fosved.db` со старой Python-схемой. `CREATE TABLE IF NOT EXISTS` не обновит её. Нужен скрипт миграции.

### A.1. Создать скрипт `scripts/migrate_schema.py`

Где: новый файл `scripts/migrate_schema.py`
Что сделать: создать скрипт, который при запуске:

1. Проверяет, нужна ли миграция (есть ли колонка `created` в `dialog_history` — если да, нужна)
2. Для каждой таблицы из списка ниже — переименовывает старые колонки и добавляет недостающие
3. Логирует каждое действие в stdout

Таблица переименований (старое → новое):

| Таблица | Переименовать | Добавить |
|---|---|---|
| `dialog_history` | `created` → `created_at` | — |
| `adapt_corrections` | `original` → `original_query`, `corrected` → `correction`, `created` → `created_at` | `original_response TEXT` |
| `error_patterns` | `context` → `query_text`, `created` → `created_at` | `correction TEXT` |
| `token_usage` | `tokens_in` → `input_tokens`, `tokens_out` → `output_tokens`, `cost` → `cost_usd`, `created` → `created_at` | `request_type TEXT` |
| `audit_log` | `created` → `timestamp` | `actor TEXT`, `dept TEXT`, `status TEXT` |
| `dept_metrics` | `rating` → `metric_value`, `created` → `created_at` | `metric_name TEXT DEFAULT 'satisfaction'`, `period TEXT` |
| `miniapp_responses` | `created` → `created_at` | `query TEXT`, `confidence TEXT` |
| `miniapp_notes` | `created` → `created_at` | — |
| `system_settings` | `updated` → удалить нельзя, оставить | — |

Скрипт должен использовать `ALTER TABLE <t> RENAME COLUMN <old> TO <new>` (поддерживается SQLite ≥ 3.25, на Ubuntu 24.04 — версия 3.45).

Для добавления колонок: `ALTER TABLE <t> ADD COLUMN <col> <type>`.

Каждую операцию обернуть в try/except: если колонка уже переименована — пропустить без ошибки.

В начале скрипта:

```python
import sqlite3, sys, os
DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'data', 'fosved.db')
```

Как проверить:
```bash
# Создать тестовую БД со старой схемой, запустить миграцию, проверить
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/test_migrate.db')
c.executescript('''
CREATE TABLE dialog_history (id INTEGER PRIMARY KEY, dept TEXT, chat_id TEXT, role TEXT, content TEXT, created TEXT);
CREATE TABLE token_usage (id INTEGER PRIMARY KEY, provider TEXT, model TEXT, tokens_in INT, tokens_out INT, cost REAL, dept TEXT, created TEXT);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, action TEXT, details TEXT, created TEXT);
INSERT INTO dialog_history (dept, created) VALUES ('osp', '2025-01-01');
INSERT INTO token_usage (tokens_in, cost, created) VALUES (100, 0.5, '2025-01-01');
''')
c.commit(); c.close()
"
python3 scripts/migrate_schema.py /tmp/test_migrate.db
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/test_migrate.db')
# Проверка: колонка created_at должна существовать
r = c.execute('SELECT created_at FROM dialog_history').fetchone()
print('dialog_history created_at:', r)
# Проверка: колонка input_tokens
r = c.execute('SELECT input_tokens, cost_usd FROM token_usage').fetchone()
print('token_usage:', r)
# Проверка: колонка timestamp в audit_log
r = c.execute('PRAGMA table_info(audit_log)').fetchall()
cols = [x[1] for x in r]
print('audit_log columns:', cols)
assert 'timestamp' in cols, 'FAIL: timestamp missing'
assert 'actor' in cols, 'FAIL: actor missing'
assert 'dept' in cols, 'FAIL: dept missing'
print('ALL OK')
"
```
Ожидаемый результат: `ALL OK`, без ошибок.

### A.2. Добавить вызов миграции в `entrypoint.sh`

Где: `entrypoint.sh`, после блока `if [ ! -f data/memory.db ]` (строка ~16), перед запуском `llm_proxy.py`
Что сделать: добавить строку:

```bash
# Migrate DB schema if needed
python3 scripts/migrate_schema.py data/fosved.db
```

Как проверить:
```bash
grep "migrate_schema" entrypoint.sh
```
Ожидаемый результат: одна строка с `python3 scripts/migrate_schema.py`.

---

## Блок B. Обновление CREATE TABLE в `llm_proxy.py`

### B.1. Заменить блок CREATE TABLE

Где: `llm_proxy.py`, функция `init_db()`. Найти блок:
```bash
grep -n "CREATE TABLE" llm_proxy.py | head -12
```

Что сделать: заменить весь `executescript("""...""")` блок (строки 247-257 на момент аудита) на:

```python
        c.executescript("""
        CREATE TABLE IF NOT EXISTS miniapp_responses (id TEXT PRIMARY KEY, dept TEXT, title TEXT, query TEXT, raw_text TEXT DEFAULT '', html TEXT, confidence TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS miniapp_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, note_text TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS dept_metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, metric_name TEXT, metric_value TEXT, period TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS token_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, provider TEXT, model TEXT, input_tokens TEXT, output_tokens TEXT, cost_usd TEXT, request_type TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT DEFAULT (datetime('now')), action TEXT, actor TEXT, dept TEXT, details TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS dialog_history (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, dept TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS adapt_corrections (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, original_query TEXT, original_response TEXT, correction TEXT, corr_type TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS error_patterns (id INTEGER PRIMARY KEY AUTOINCREMENT, dept TEXT, error_type TEXT, query_text TEXT, correction TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS channel_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, dept TEXT, title TEXT, channel_message_id TEXT, archived_at TEXT DEFAULT (datetime('now')));
        """)
```

Как проверить:
```bash
python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)" && echo "SYNTAX OK"
```
Ожидаемый результат: `SYNTAX OK`

---

## Блок C. Обновление Python-запросов в `llm_proxy.py`

Принцип: все `INSERT`/`SELECT`/`WHERE` по переименованным колонкам — обновить. Ниже — список замен. Каждую замену искать `grep -n`, менять, проверять синтаксис.

### C.1. dialog_history: `created` → `created_at`

Найти и заменить все вхождения:
```bash
grep -n "dialog_history" llm_proxy.py
```

Конкретные замены (8 штук):

| Что найти (grep) | Что заменить |
|---|---|
| `INSERT INTO dialog_history (dept, chat_id, role, content, created)` | `INSERT INTO dialog_history (dept, chat_id, role, content, created_at)` |
| `SELECT COUNT(*) as c FROM dialog_history WHERE dept=? AND created>=?` | `...WHERE dept=? AND created_at>=?` |
| `SELECT role,content,created FROM dialog_history` | `SELECT role,content,created_at FROM dialog_history` |
| `SELECT dept, COUNT(*) as c FROM dialog_history WHERE created>=?` | `...WHERE created_at>=?` |
| `SELECT COUNT(*) as c FROM dialog_history WHERE created>=?` | `...WHERE created_at>=?` |
| `SELECT content, created FROM dialog_history` | `SELECT content, created_at FROM dialog_history` |

Проверка после всех замен:
```bash
grep -n "dialog_history.*\bcreated\b" llm_proxy.py | grep -v "created_at"
```
Ожидаемый результат: пусто (ни одного `created` без `_at`).

### C.2. adapt_corrections: `original` → `original_query`, `corrected` → `correction`, `created` → `created_at`

Найти:
```bash
grep -n "adapt_corrections" llm_proxy.py
```

Замены (14 вхождений):

| Что найти | Что заменить |
|---|---|
| `INSERT INTO adapt_corrections (dept, original, corrected, created, corr_type)` | `INSERT INTO adapt_corrections (dept, original_query, correction, created_at, corr_type)` |
| `SELECT original,corrected,created FROM adapt_corrections` | `SELECT original_query,correction,created_at FROM adapt_corrections` |
| `SELECT dept, original, corrected, created FROM adapt_corrections` | `SELECT dept, original_query, correction, created_at FROM adapt_corrections` |
| `SELECT original, corrected, corr_type, created FROM adapt_corrections` | `SELECT original_query, correction, corr_type, created_at FROM adapt_corrections` |
| `SELECT original, corrected, created FROM adapt_corrections` | `SELECT original_query, correction, created_at FROM adapt_corrections` |
| `WHERE created>=?` в контексте adapt_corrections | `WHERE created_at>=?` |

**Важно:** код, который читает результат, обращается к `r["original"]`, `r["corrected"]`, `r["created"]`. Эти обращения тоже надо обновить на `r["original_query"]`, `r["correction"]`, `r["created_at"]`.

Найти обращения к результатам:
```bash
grep -n '"original"\|"corrected"\|"created"' llm_proxy.py | grep -v "CREATE TABLE\|INSERT\|SELECT\|#\|TODO"
```

Проверка:
```bash
grep -n "adapt_corrections" llm_proxy.py | grep -E "\boriginal\b|\bcorrected\b|\bcreated\b" | grep -v "created_at\|original_query\|original_response\|correction"
```
Ожидаемый результат: пусто.

### C.3. error_patterns: `context` → `query_text`, `created` → `created_at`

Найти:
```bash
grep -n "error_patterns" llm_proxy.py
```

Замены (5 вхождений):

| Что найти | Что заменить |
|---|---|
| `INSERT INTO error_patterns (dept, error_type, context, created)` | `INSERT INTO error_patterns (dept, error_type, query_text, created_at)` |
| `SELECT dept, error_type, context, created FROM error_patterns` | `SELECT dept, error_type, query_text, created_at FROM error_patterns` |
| `WHERE created>=?` | `WHERE created_at>=?` (если в контексте error_patterns) |

Обращения к результатам: `r["context"]` → `r["query_text"]`, `r["created"]` → `r["created_at"]`.

Проверка:
```bash
grep -n "error_patterns" llm_proxy.py | grep -E "\bcontext\b|\bcreated\b" | grep -v "created_at\|query_text"
```
Ожидаемый результат: пусто.

### C.4. token_usage: `tokens_in` → `input_tokens`, `tokens_out` → `output_tokens`, `cost` → `cost_usd`, `created` → `created_at`

Это самая объёмная таблица — 25 вхождений.

Найти:
```bash
grep -n "token_usage" llm_proxy.py
```

Замены INSERT (2 штуки, одинаковые):
```
INSERT INTO token_usage (provider,model,tokens_in,tokens_out,cost,dept,created) VALUES (?,?,?,?,?,?,?)
→
INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)
```

Замены SELECT — паттерн: заменить в каждом SELECT-запросе:
- `SUM(tokens_in)` → `SUM(input_tokens)`
- `SUM(tokens_out)` → `SUM(output_tokens)`
- `SUM(cost)` → `SUM(cost_usd)`
- `WHERE created>=?` → `WHERE created_at>=?`
- `WHERE created>=?` → `WHERE created_at>=?` (во всех вхождениях)

Также в `_collect_metrics_for_period()` (функция ~строка 990):
```python
conditions = "created >= ?"
→
conditions = "created_at >= ?"
```
и
```python
conditions += " AND created < ?"
→
conditions += " AND created_at < ?"
```

**Внимание:** `_collect_metrics_for_period` использует переменную `conditions` для НЕСКОЛЬКИХ таблиц (`dialog_history`, `miniapp_responses`, `adapt_corrections`, `dept_metrics`, `token_usage`). После замены `created` → `created_at` в `conditions`, все эти таблицы будут работать корректно, т.к. все теперь используют `created_at`.

Проверка:
```bash
grep -n "token_usage" llm_proxy.py | grep -E "\btokens_in\b|\btokens_out\b|\bcost[^_]\b|\bcreated[^_]\b" | grep -v "created_at\|input_tokens\|output_tokens\|cost_usd"
```
Ожидаемый результат: пусто.

### C.5. audit_log: `created` → `timestamp`, добавить `actor`, `dept`, `status`

Найти:
```bash
grep -n "audit_log" llm_proxy.py
```

Замены INSERT (2 штуки, одинаковые):
```
INSERT INTO audit_log (action,details,created) VALUES (?,?,?)
→
INSERT INTO audit_log (action,actor,dept,details,status) VALUES (?,'proxy','system',?,'ok')
```
Убрать третий параметр (datetime) из кортежа — колонка `timestamp` имеет DEFAULT.

То есть:
```python
_query("INSERT INTO audit_log (action,details,created) VALUES (?,?,?)",
       ("llm_call", json.dumps({...}), now))
→
_query("INSERT INTO audit_log (action,actor,dept,details,status) VALUES (?,'proxy',?,?,'ok')",
       ("llm_call", dept, json.dumps({...})))
```

Замены SELECT (3 штуки):
```
SELECT action,details,created FROM audit_log
→
SELECT action,details,timestamp FROM audit_log

SELECT id, action, details, created FROM audit_log
→
SELECT id, action, details, timestamp FROM audit_log
```

Обращения к результатам: `r["created"]` → `r["timestamp"]`.

Проверка:
```bash
grep -n "audit_log" llm_proxy.py | grep -E "\bcreated\b" | grep -v "timestamp"
```
Ожидаемый результат: пусто.

### C.6. dept_metrics: `rating` → `metric_value`, `created` → `created_at`, добавить `metric_name`, `period`

Найти:
```bash
grep -n "dept_metrics" llm_proxy.py
```

Замена INSERT (1 штука):
```python
_query("INSERT INTO dept_metrics (dept,rating,created) VALUES (?,?,?)", (dept, rating, datetime.utcnow().isoformat()))
→
_query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES (?,'satisfaction',?,?,?)", (dept, str(rating), 'daily', datetime.utcnow().isoformat()))
```

Замены SELECT (6 штук):
```
AVG(rating)   →   AVG(CAST(metric_value AS REAL))
WHERE created>=?   →   WHERE created_at>=?
```

В `_collect_metrics_for_period`:
```python
ratings = _query(f"SELECT dept, COALESCE(AVG(rating),0) as avg_r, COUNT(*) as c FROM dept_metrics WHERE {conditions} GROUP BY dept", ...)
→
ratings = _query(f"SELECT dept, COALESCE(AVG(CAST(metric_value AS REAL)),0) as avg_r, COUNT(*) as c FROM dept_metrics WHERE {conditions} AND metric_name='satisfaction' GROUP BY dept", ...)
```

Аналогично все остальные SELECT с `AVG(rating)`:
```
COALESCE(AVG(rating),0) as avg_r  →  COALESCE(AVG(CAST(metric_value AS REAL)),0) as avg_r
COALESCE(AVG(rating),0) as a      →  COALESCE(AVG(CAST(metric_value AS REAL)),0) as a
```

Обращения к результатам: оставить `r["avg_r"]` / `r["a"]` — алиасы в SELECT не меняются.

Проверка:
```bash
grep -n "dept_metrics" llm_proxy.py | grep -E "\brating\b|\bcreated[^_]\b"
```
Ожидаемый результат: пусто.

### C.7. miniapp_responses: `created` → `created_at`

Найти:
```bash
grep -n "miniapp_responses" llm_proxy.py
```

Замены: в каждом SELECT/INSERT заменить `created` → `created_at`. 11 вхождений, все — замена одного слова.

Проверка:
```bash
grep -n "miniapp_responses" llm_proxy.py | grep -E "\bcreated\b" | grep -v "created_at"
```
Ожидаемый результат: пусто.

### C.8. miniapp_notes: `created` → `created_at`

```bash
grep -n "miniapp_notes" llm_proxy.py
```

Одна замена в INSERT.

Проверка: аналогично C.7.

### C.9. Финальная проверка синтаксиса

```bash
python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)" && echo "SYNTAX OK"
```
Ожидаемый результат: `SYNTAX OK`

---

## Блок D. Починка `archive` → `channel_archive` в `scheduler.mlog`

### D.1. Строка 113

Где: `dept/scheduler.mlog`, строка 113
Найти: `grep -n "FROM archive" dept/scheduler.mlog`
Что не так: запрос к таблице `archive`, которой не существует. Реальная таблица — `channel_archive`.
Что сделать: заменить `FROM archive` → `FROM channel_archive` в трёх местах:

```
Строка 113: FROM archive WHERE created_at → FROM channel_archive WHERE archived_at
Строка 116: FROM archive WHERE created_at → FROM channel_archive WHERE archived_at
Строка 171: FROM archive WHERE dept = ? AND created_at → FROM channel_archive WHERE dept = ? AND archived_at
```

**Внимание:** таблица `channel_archive` использует колонку `archived_at`, не `created_at`.

Как проверить:
```bash
grep -n "FROM archive" dept/scheduler.mlog
```
Ожидаемый результат: пусто (ни одной ссылки на `archive`; все — `channel_archive`).

---

## Блок E. Починка пути загрузки скиллов

### E.1. Исправить путь в `context.mlog`

Где: `dept/context.mlog`, строка 55 (функция `SelectSkillsByKeywords`)
Что не так: код ищет `skills/fosved/<dept>/<skill>/SKILL.md` — директория `skills/fosved/` не существует. Скиллы на диске лежат в `skills/<skill-name>/SKILL.md` (плоская структура, без dept-подпапок).

Найти:
```bash
grep -n "skills/fosved/" dept/context.mlog
```

Заменить:
```
let skill_content = read_file("skills/fosved/" + dept + "/" + trim(skill) + "/SKILL.md")
→
let skill_content = read_file("skills/" + trim(skill) + "/SKILL.md")
```

**Важно:** даже после этого фикса большинство скиллов из `skills_index/*.txt` не найдутся на диске (потому что имена в индексе и имена папок — разные). Но те, что совпадут, будут загружаться. Полная синхронизация индекса с диском — это Слой 2, не сейчас.

Как проверить:
```bash
grep "skills/fosved/" dept/context.mlog
```
Ожидаемый результат: пусто.

---

## Smoke-test после всего

### S.1. Python компилируется

```bash
python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)" && echo "OK"
```
Ожидаемый результат: `OK`

### S.2. Миграция работает на чистой старой БД

```bash
rm -f /tmp/smoke_test.db
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/smoke_test.db')
c.executescript('''
CREATE TABLE dialog_history (id INTEGER PRIMARY KEY, dept TEXT, chat_id TEXT, role TEXT, content TEXT, created TEXT);
CREATE TABLE adapt_corrections (id INTEGER PRIMARY KEY, dept TEXT, original TEXT, corrected TEXT, created TEXT, corr_type TEXT DEFAULT '');
CREATE TABLE error_patterns (id INTEGER PRIMARY KEY, dept TEXT, error_type TEXT, context TEXT, created TEXT);
CREATE TABLE token_usage (id INTEGER PRIMARY KEY, provider TEXT, model TEXT, tokens_in INT, tokens_out INT, cost REAL, dept TEXT, created TEXT);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, action TEXT, details TEXT, created TEXT);
CREATE TABLE dept_metrics (id INTEGER PRIMARY KEY, dept TEXT, rating INT, created TEXT);
CREATE TABLE miniapp_responses (id TEXT PRIMARY KEY, dept TEXT, html TEXT, created TEXT, title TEXT, raw_text TEXT DEFAULT '');
CREATE TABLE miniapp_notes (id INTEGER PRIMARY KEY, doc_id TEXT, note_text TEXT, created TEXT);
INSERT INTO dialog_history (dept, chat_id, role, content, created) VALUES ('osp', '123', 'user', 'test', '2025-01-01');
INSERT INTO token_usage (provider, model, tokens_in, tokens_out, cost, dept, created) VALUES ('zai', 'glm-4', 100, 200, 0.05, 'osp', '2025-01-01');
INSERT INTO audit_log (action, details, created) VALUES ('test', '{}', '2025-01-01');
''')
c.commit(); c.close()
"
python3 scripts/migrate_schema.py /tmp/smoke_test.db
python3 -c "
import sqlite3
c = sqlite3.connect('/tmp/smoke_test.db')
# Проверяем все переименованные колонки
r = c.execute('SELECT created_at FROM dialog_history LIMIT 1').fetchone()
assert r[0] == '2025-01-01', f'dialog_history: {r}'
r = c.execute('SELECT input_tokens, output_tokens, cost_usd, created_at FROM token_usage LIMIT 1').fetchone()
assert r == (100, 200, 0.05, '2025-01-01'), f'token_usage: {r}'
r = c.execute('SELECT timestamp FROM audit_log LIMIT 1').fetchone()
assert r[0] == '2025-01-01', f'audit_log: {r}'
cols = [x[1] for x in c.execute('PRAGMA table_info(audit_log)').fetchall()]
assert 'actor' in cols and 'dept' in cols and 'status' in cols, f'audit_log cols: {cols}'
cols = [x[1] for x in c.execute('PRAGMA table_info(dept_metrics)').fetchall()]
assert 'metric_name' in cols and 'metric_value' in cols, f'dept_metrics cols: {cols}'
cols = [x[1] for x in c.execute('PRAGMA table_info(adapt_corrections)').fetchall()]
assert 'original_query' in cols and 'correction' in cols, f'adapt_corrections cols: {cols}'
print('SMOKE TEST PASSED')
"
```
Ожидаемый результат: `SMOKE TEST PASSED`

### S.3. Миграция идемпотентна

```bash
python3 scripts/migrate_schema.py /tmp/smoke_test.db
python3 scripts/migrate_schema.py /tmp/smoke_test.db
echo "Idempotent: OK"
```
Ожидаемый результат: без ошибок, `Idempotent: OK`.

### S.4. Новая чистая БД создаётся корректно

```bash
rm -f /tmp/fresh_test.db
python3 -c "
import sys; sys.path.insert(0, 'lib')
# Имитируем init_db()
import sqlite3
c = sqlite3.connect('/tmp/fresh_test.db')
# Скопировать новый executescript из llm_proxy.py
exec(open('llm_proxy.py').read().split('def init_db')[1].split('def ')[0].split('c.executescript')[1].split('c.commit')[0])
# Проверить колонки
for tbl in ['dialog_history','token_usage','audit_log','dept_metrics','adapt_corrections','error_patterns']:
    cols = [x[1] for x in c.execute(f'PRAGMA table_info({tbl})').fetchall()]
    print(f'{tbl}: {cols}')
"
```
Ожидаемый результат: все таблицы с новыми именами колонок.

### S.5. Нет ссылок на старые имена

```bash
# В llm_proxy.py не должно быть старых имён (кроме комментариев)
grep -nE "\btokens_in\b|\btokens_out\b" llm_proxy.py | grep -v "^#\|#.*tokens_in\|input_tokens\|output_tokens" | wc -l
grep -nE "\bcost[,) ]" llm_proxy.py | grep -v "cost_usd\|TOKEN_COSTS\|#\|cost_today\|cost_month\|cost\"" | wc -l
grep -nE "\"created\"|\bcreated[>=<]|,created\)" llm_proxy.py | grep -v "created_at\|#" | wc -l
# В scheduler.mlog не должно быть FROM archive
grep "FROM archive[^_]" dept/scheduler.mlog | wc -l
# В context.mlog не должно быть skills/fosved/
grep "skills/fosved/" dept/context.mlog | wc -l
```
Ожидаемый результат: все пять команд выдают `0`.

---

## Структура финального отчёта исполнителя

Файл `LAYER1_REPORT.md`:

```markdown
# Layer 1 Report — DB Schema Unification
Date: <дата>

## Блок A — Миграция
- A.1: scripts/migrate_schema.py создан: да/нет
- A.2: entrypoint.sh обновлён: да/нет
- Smoke-test миграции: PASSED/FAILED

## Блок B — CREATE TABLE
- B.1: Все 10 CREATE TABLE обновлены: да/нет
- Синтаксис-проверка: PASSED/FAILED

## Блок C — Python-запросы
- C.1 dialog_history: <N> замен, 0 остатков старых имён
- C.2 adapt_corrections: <N> замен, 0 остатков
- C.3 error_patterns: <N> замен, 0 остатков
- C.4 token_usage: <N> замен, 0 остатков
- C.5 audit_log: <N> замен, 0 остатков
- C.6 dept_metrics: <N> замен, 0 остатков
- C.7 miniapp_responses: <N> замен, 0 остатков
- C.8 miniapp_notes: <N> замен, 0 остатков
- C.9 финальный синтаксис: PASSED/FAILED

## Блок D — scheduler.mlog
- D.1: 3 замены archive → channel_archive: да/нет
- created_at → archived_at: да/нет

## Блок E — context.mlog
- E.1: skills/fosved/ → skills/: да/нет

## Smoke-test
- S.1 py_compile: PASSED/FAILED
- S.2 миграция старой БД: PASSED/FAILED
- S.3 идемпотентность: PASSED/FAILED
- S.4 свежая БД: PASSED/FAILED
- S.5 нет старых имён: PASSED/FAILED

## Примечания
<любые проблемы, находки, блокеры>
```

---

## Чек-лист сдачи

- [ ] `scripts/migrate_schema.py` существует и исполняем
- [ ] `entrypoint.sh` вызывает миграцию перед стартом
- [ ] В `llm_proxy.py` все 10 CREATE TABLE совпадают с app.mlog
- [ ] В `llm_proxy.py` нет ни одной ссылки на `tokens_in`, `tokens_out`, `cost` (без `_usd`), `rating` (в контексте dept_metrics), `original` / `corrected` (в контексте adapt_corrections), `context` (в контексте error_patterns)
- [ ] В `llm_proxy.py` нет `created` без `_at` в SQL-запросах (кроме `audit_log` где используется `timestamp`)
- [ ] `python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)"` — без ошибок
- [ ] `dept/scheduler.mlog` не содержит `FROM archive` (только `FROM channel_archive`)
- [ ] `dept/context.mlog` не содержит `skills/fosved/`
- [ ] Smoke-test S.2 — PASSED
- [ ] Smoke-test S.3 — PASSED
- [ ] `LAYER1_REPORT.md` заполнен полностью
