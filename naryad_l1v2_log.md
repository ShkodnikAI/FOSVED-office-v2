# Лог исполнения: Наряд L1 v2 — FOSVED Office mlog 0.8.9

## A.1: bin/mlog → 0.8.9
- Файл: bin/mlog
- До: `mlog 0.7.10`, BuildID bdbcf888, 12072696 bytes
- После: `mlog 0.8.9`, BuildID 0c6128cb, 12582600 bytes
- Источник: CI run #28728313073 (commit 78c7f9b), artifact 8087969617, `mlog-linux-x86_64`
- Команда: `./bin/mlog --version` → `mlog 0.8.9` ✓

## B.1: if-выражение в ArchiveSearch
- Файл: app.mlog:506-514
- До: `let rows = if filter_text != "" then {...} else {...}` (if-выражение со statement-блоками)
- После: `let rows = ""` + `if ... then { let rows = ... } else { let rows = ... }` (if-инструкция)
- Проверка: `grep -c 'let rows = if' app.mlog` → 0 ✓
- Проверка: `./bin/mlog check app.mlog 2>&1 | grep -c "parse error"` → 0 ✓

## B.2: && → and в utils
- Файл: dept/utils.mlog:184
- До: `if dept != "yana" && dept != "admin" && len(text) > 1000.0 then {`
- После: `if dept != "yana" and dept != "admin" and len(text) > 1000.0 then {`
- Проверка: `grep -c '&&' dept/utils.mlog` → 0 ✓
- Проверка: `./bin/mlog check dept/utils.mlog 2>&1 | grep -c "parse error"` → 0 ✓

## C.1: db-блок в app.mlog
- Файл: app.mlog:4 (вставлена между строкой 2 и import)
- До: db-блок отсутствовал
- После: `db { url: env("DATABASE_URL") }`
- Проверка: `grep -n 'db { url' app.mlog` → `4:db { url: env("DATABASE_URL") }` (в диапазоне 1-6) ✓

## C.2: DATABASE_URL fallback в entrypoint.sh
- Файл: entrypoint.sh:3
- До: отсутствовал
- После: `export DATABASE_URL="${DATABASE_URL:-sqlite:data/fosved.db}"`
- Проверка: `bash -n entrypoint.sh` → OK ✓
- Проверка: `grep -n DATABASE_URL entrypoint.sh` → `3:export DATABASE_URL=...` ✓

## C.3: DATABASE_URL в .env.example
- Файл: .env.example:7
- До: отсутствовал
- После: `DATABASE_URL=sqlite:data/fosved.db`
- Проверка: `grep -c DATABASE_URL .env.example` → 1 ✓

## D.1: Парс-гейт в entrypoint.sh
- Файл: entrypoint.sh:38-40
- До: отсутствовал
- После: 3 строки (if grep parse error → FATAL + head -8 + exit 1)
- Проверка: `bash -n entrypoint.sh` → OK ✓
- Проверка (порча): вставка `&& BAD PARSE` → гейт сработал: `FATAL: app.mlog parse error`, парсинг показал ошибку, откат ✓

## D.2: Security-audit в entrypoint.sh
- Файл: entrypoint.sh:41
- До: отсутствовал
- После: `./bin/mlog audit app.mlog 2>&1 | tail -3` (не блокирующий)
- Проверка: `bash -n entrypoint.sh` → OK ✓

## Smoke-test
- `./bin/mlog --version` → `mlog 0.8.9` ✓
- 23 mlog-файла, check по каждому → 0 парс-ошибок (итого 0) ✓
- `DATABASE_URL="sqlite:data/fosved.db" PORT=10001 ./bin/mlog serve app.mlog` → `[db] Connected: sqlite:data/fosved.db` ✓
- `curl -s http://127.0.0.1:10001/health` → `ok e1c8b5a` ✓
- `curl -s http://127.0.0.1:10001/version` → `version=e1c8b5a anti_format=0` ✓
- `curl -s "http://127.0.0.1:10001/cron/morning?secret=WRONG"` → `Forbidden` ✓
- `curl -s http://127.0.0.1:10001/` → `Fosved Office v2 alive [e1c8b5a]` ✓