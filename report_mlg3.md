# Отчёт: MLG-3

- **Дата**: 2026-08-21
- **Ветка**: `feat/mlg3-smartrouter-binary`
- **База**: `b5f9032` (main)
- **Бинарь**: mlog 0.17.0 (был 0.12.0)
- **Источник артефакта**: GitHub Actions run `32367437966`, artifact `9405838291`, коммит `c8d286c`, digest `sha256:2ce737b5f1ffc0f6d5226475ebfe2ec4f747c80113dbf695d533250b1a78f144`

## A.1/A.2: Бинарь

- Скачан через GitHub API (`archive_download_url`), 8.9 МБ zip → 24 МБ ELF 64-bit PIE
- `file bin/mlog`: `ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), dynamically linked, interpreter /lib64/ld-linux-x86-64.so-2, for GNU/Linux 3.2.0, BuildID=619d13a51fb6886368159f3e1838779115dac09f, not stripped`
- `./bin/mlog --version` → `mlog 0.17.0`
- Старый бинарь (0.12.0) сохранён как `bin/mlog_old_0.12.0`
- `./bin/mlog check app.mlog` — нет panic, нет segmentation fault

## B.1: Ложные undefined

- Всего: **49** ложных `undefined`
  - `AuditLog`: 44 (межфайловый импорт из dept/*, check не резолвит cross-file patterns)
  - `GetRecentDialog`: 2
  - `GetCorrections`: 2
  - `EscapeMarkdownV2Simple`: 1
- Ранее (из контекста сессии) было 7 ложных `AuditLog` в quest.mlog — рост до 44 объясняется тем, что verifier wiring из предыдущего наряда добавил вызовы `AuditLog` в app.mlog (Yana self-verify, Expert best-of-N)
- **Вывод**: это старое известное поведение `mlog check`, не новая регрессия
- `parse error`: **0**

## B.2: Golden-test SmartRouter

Тестовый файл `mlg3_golden.mlog` с провайдером指向 `127.0.0.1:19999` (мёртвый порт).

**Вывод дословно:**
```
error: All LLM providers failed. Last error: openai_compatible request failed: error sending request for url (http://127.0.0.1:19999/v1/chat/completions)
```

**Критерий пройден**: реальная попытка HTTP-запроса через SmartRouter к мёртвому порту. **Не** `[MOCK: ...]`.

### Важное открытие: реальный синтаксис `llm {}`

Синтаксис блока `llm {}` вMetalogos 0.17.0 отличается от предполагаемого в наряде:

| Поле | Наряд (неверно) | Реальность |
|------|----------------|------------|
| `alias` | Строка в кавычках: `"dead"` | Идентификатор без кавычек: `dead` |
| `provider` | `"openai-compatible"` | `openai_compatible` (подчёркивание, без кавычек) |
| `timeout` | На уровне блока | Не поддерживается (нет в грамматике) |
| `failover` | На уровне блока | На уровне блока ✅ |
| `circuit_breaker` | На уровне блока | На уровне блока ✅ |
| `default_model` | Не указан | Обязательное поле (если providers заданы) |

Корректный минимальный пример:
```mlog
llm {
  providers: [
    { alias: myprov, provider: openai_compatible, key: env("KEY"), url: "https://..." }
  ],
  default_model: "model-name",
  failover: auto,
  circuit_breaker: 3
}
```

## C.1: Блок `llm {}` в app.mlog

Добавлен после `db { url: env("DATABASE_URL") }`, перед `import dept/utils`.

Провайдеры (5, все `openai_compatible`):
- **kimi** — `api.moonshot.ai` (KIMI_API_KEY)
- **deepseek** — `api.deepseek.com` (DEEPSEEK_API_KEY)
- **zai** — `api.z.ai` (ZAI_API_KEY)
- **groq** — `api.groq.com` (GROQ_API_KEY)
- **cerebras** — `api.cerebras.ai` (CEREBRAS_API_KEY)

Проверка санкций:
- `anthropic` — **не включён** ✅
- `openai` (как провайдер) — **не включён** ✅
- `openai_compatible` используется только как протокол для не-санкционных провайдеров
- `credential_manager.py` подтверждает: `sanctions_ok: False` для anthropic и openai
- `mlog check app.mlog` → `parse error: 0`

## D.1: Три вызова в dept/miniapp.mlog

Переписаны с `call_llm(model, messages, temperature, max_tokens)` на `call_llm(prompt, input)`:

1. **Журналист** (строка ~396): `call_llm(ctx + "\n\n" + jprompt, raw)`
2. **Deepen** (строка ~415): `call_llm(ctx + "\n\n" + instr, "Углуби предыдущий анализ:\n" + raw)`
3. **Контр-прогноз** (строка ~441): `call_llm(ctx + "\n\n" + cprompt, raw)`

Убрано: 3 строки `let model = MiniappSelectModel()`, 3 строки `let messages = json_encode(...)`, 3 вызова с 4 аргументами.

Проверки:
- `grep -c 'call_llm(model, messages' dept/miniapp.mlog` → **0** ✅
- `grep -c 'json_encode([{role:' dept/miniapp.mlog` → **0** ✅
- `./bin/mlog check dept/miniapp.mlog` → `parse error: 0` ✅

## D.2: MiniappSelectModel — пометка

Добавлен TODO-комментарий на строку перед объявлением:
```
// TODO: мёртвый код после MLG-3 — выбор модели теперь делает SmartRouter. Удалить отдельным нарядом по чистке.
```

- `grep -c 'мёртвый код после MLG-3' dept/miniapp.mlog` → **1** ✅
- Функция `MiniappSelectModel()` **не удалена** (требование наряда) ✅

## Smoke

- Дейcтвие «журналист» требует деплоя на Render для проверки живьём — не может быть выполнено в песочнице
- `mlog check` на обоих файлах чист от parse errors
- Остальные 19 отделов продолжают использовать старую сигнатуру `call_llm(model, messages, temperature, max_tokens)` — ожидаемо, не входит в этот наряд

## Затруднения

1. **Синтаксис `llm {}`** — наряд предполагал строковые значения для `alias` и `provider` с дефисами. Реальная грамматика 0.17.0 требует:
   - `alias`: bare identifier (без кавычек)
   - `provider`: bare identifier с подчёркиванием (`openai_compatible`, не `"openai-compatible"`)
   - Обязательное поле `default_model` (не указано в наряде)
   - Поле `timeout` не существует на уровне блока `llm {}`
   Методом проб выяснена корректная грамматика.

2. **Артефакт GitHub Actions** — прямая ссылка `runs/{id}/artifacts/{id}/zip` даёт 404; правильный URL: `actions/artifacts/{id}/zip`. CLI `gh` не установлен, использован `curl` с PAT.

3. **Smoke-test** — действие «журналист» из Mini App невозможно проверить без деплоя на Render (требует работающий Telegram бот + БД + API ключи).
