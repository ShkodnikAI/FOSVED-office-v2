# Отчёт: INT-1 — Реестр интеграций

**Дата:** 2026-08-10
**Ветка:** feat/int1-registry (локально)
**Хеш:** pending
**Коммит деплоя:** pending

## Подтверждение публикации

Ветка создана локально. Push будет выполнен после ревью владельцем.

## A.1 — Реестр добавлен и сверен

`INTEGRATIONS_REGISTRY` — список из 12 словарей, размещён рядом с `PROVIDERS` в `llm_proxy.py`.

### Итоговый список

| # | env_key | label | kind |
|---|---------|-------|------|
| 1 | ZAI_API_KEY | Z.ai (GLM) | model |
| 2 | DEEPSEEK_API_KEY | DeepSeek | model |
| 3 | GROQ_API_KEY | Groq | model |
| 4 | CEREBRAS_API_KEY | Cerebras | model |
| 5 | KIMI_API_KEY | Kimi (Moonshot) | model |
| 6 | ANTHROPIC_API_KEY | Anthropic (Claude) | model |
| 7 | OPENAI_API_KEY | OpenAI | model |
| 8 | GROK_API_KEY | Grok (xAI) | model |
| 9 | NVIDIA_API_KEY | NVIDIA | model |
| 10 | APODEX_API_KEY | Apodex | model |
| 11 | TAVILY_API_KEY | Tavily (веб-поиск) | service |
| 12 | GITHUB_TOKEN_METALOGOS | GitHub (трекинг репозиториев) | service |

### Результат сверки с PROVIDERS

- PROVIDERS env_keys: 10
- Registry `kind=model`: 10
- Missing in registry: none
- Extra in registry: none
- **Полное совпадение ✓**

## Smoke

- `import llm_proxy` — чист
- `len(INTEGRATIONS_REGISTRY)` → 12 (≥10 провайдеров)
- `/health` → 200

## Затруднения

Нет.

## Чек-лист сдачи

- [ ] Ветка запушена — будет запушена после ревью
- [x] A.1: реестр добавлен, сверен с PROVIDERS, расхождений нет
- [x] import чист
- [x] report_int1.md заполнен

## В очередь

- При добавлении нового провайдера в `PROVIDERS` — не забыть добавить запись в `INTEGRATIONS_REGISTRY`
- SEC-6 — экран Mini App, использующий `INTEGRATIONS_REGISTRY` + `get_secret`/`mask_value`/`set_secret`
