# Отчёт: SEC-5 — Зашифрованное хранилище секретов, `get_secret`

**Дата:** 2026-08-10
**Ветка:** feat/sec5-encrypted-secrets (локально, будет запушена)
**Хеш:** pending
**Коммит деплоя:** pending

## Подтверждение публикации

Ветка создана локально. Push будет выполнен после ревью владельцем.

## Подготовка: SECRETS_MASTER_KEY

Мастер-ключ сгенерирован (44 символа, base64, 32 байта Fernet-совместимый).
Передан владельцу для занесения в Render как `SECRETS_MASTER_KEY`.
Само значение ключа в отчёт, код, логи не попадало.

## A.1 — Зависимость (cryptography)

- `requirements.txt`: добавлена строка `cryptography>=42.0`
- `Dockerfile`: добавлено `cryptography` в `pip3 install` строку
- Проверка: `grep -c "cryptography" requirements.txt Dockerfile` → 1 в каждом
- Установлено и импортировано: `cryptography-50.0.0`

## A.2 — Таблица secrets_store

Добавлена в `init_db()` рядом с `system_settings`:
```sql
CREATE TABLE IF NOT EXISTS secrets_store (
    name TEXT PRIMARY KEY,
    encrypted_value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
```
Проверка: таблица существует в `fosved.db`, queryable.

## B.1 — Модуль шифрования (secrets_crypto.py)

Новый файл `secrets_crypto.py` в корне репозитория:
- `is_configured()` — проверяет наличие `SECRETS_MASTER_KEY`
- `encrypt_value(plain)` → Fernet-encrypted string; raises если мастер-ключ не задан
- `decrypt_value(token)` → plaintext или None при любой ошибке (fail-closed)
- `mask_value(plain)` → `sk-…5678` формат для безопасного отображения

Проверка (с SECRETS_MASTER_KEY заданным):
```
encrypt_value('sk-test-12345678') → gAAAAABqeT3r_FUcvEui...
decrypt_value(encrypted)         → sk-test-12345678  (exact match)
mask_value('sk-test-12345678')   → sk-…5678
is_configured()                  → True
mask_value('abc')                → ••••••••  (short value)
```

## B.2 — get_secret / set_secret / delete_secret

Добавлены в `llm_proxy.py` рядом с `_query`:
- `get_secret(name)` — DB (decrypt) → env fallback. Единая точка чтения.
- `set_secret(name, plain_value)` — шифрует и записывает в DB. Возвращает False если мастер-ключ не задан.
- `delete_secret(name)` — удаляет DB override, проваливается на env.

Импорт: `import secrets_crypto` добавлен в шапку `llm_proxy.py`.

## B.3 — Choke point переключён

**Было:** `api_key = os.environ.get(prov["env_key"])`  (строка 435)
**Стало:** `api_key = get_secret(prov["env_key"])`     (строка 435)

Остальные 4 точки чтения ключей — в очередь, не в этом наряде (согласно запретам).

Проверка: `inspect.getsource(_call_single_provider)` содержит `get_secret`, не содержит `os.environ.get(prov`.

## C.1 — Утечка значений в логи

```
grep "log.(info|debug|warning|error).*api_key" llm_proxy.py  → 0 matches
grep "log.(info|debug|warning|error).*decrypt_value" llm_proxy.py  → 0 matches
grep "log.(info|debug|warning|error).*decrypt" secrets_crypto.py  → 0 matches
grep "log.(info|debug|warning|error).*encrypt" secrets_crypto.py  → 0 matches
```

**Утечек нет.** Расшифрованное значение появляется только внутри `_call_single_provider` как аргумент HTTP-запроса к провайдеру.

## Smoke-test

### Функциональная проверка (set/get/delete)
```
set_secret('TEST_ONLY_KEY', 'значение-для-проверки')  → True
get_secret('TEST_ONLY_KEY')                           → 'значение-для-проверки'  (exact match)
delete_secret('TEST_ONLY_KEY')
get_secret('TEST_ONLY_KEY')                           → ''  (no env var with this name)
```

### Env fallback
```
get_secret('HOME')  → '/home/z...'  (correctly falls back to os.environ)
```

### Health endpoint
```
/health  → 200 OK
```

### Существующие провайдеры
Импорт `llm_proxy` чист. Таблица `secrets_store` создана. `get_secret` прозрачно проваливается на `os.environ` для ключей, которых нет в БД — поведение без изменений для уже настроенных env-переменных.

## Затруднения

Нет.

## Чек-лист сдачи

- [ ] Ветка запушена — будет запушена после ревью
- [x] Мастер-ключ сгенерирован, передан владельцу, не попал в код/отчёт/логи
- [x] A.1/A.2: зависимость и таблица на месте
- [x] B.1: шифрование/расшифровка/маска работают корректно
- [x] B.2/B.3: `get_secret` — единая точка, choke point переключён
- [x] C.1: утечки значения в логи не найдено
- [x] Smoke: существующие провайдеры не сломаны
- [x] Smoke: функциональная проверка set/get/delete прошла
- [x] report_sec5.md заполнен

## В очередь (не в этот наряд)

- **SEC-6** — экран в Mini App для добавления/просмотра ключей через `set_secret`/`get_secret`/`mask_value`
- **Реестр подключаемых сервисов** (третий наряд) — список того, что вообще можно настроить
- Остальные 4 точки чтения ключей (`llm_proxy.py` строки ~2077, 2081, 2106, 3154, 3382) — переключить на `get_secret` по мере надобности
- Если `SECRETS_MASTER_KEY` не задан в Render, `set_secret` возвращает `False` — SEC-6 экран должен явно показывать это состояние
