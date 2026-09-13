# FO-014: MCP-инструменты офиса (github + filesystem)

## Что это

Офис — потребитель MCP (Model Context Protocol) через `mcp_call`/`mcp_list_tools`
из Metalogos №268 (ADR-0132 v1, stdio-транспорт, taint-контур). Allowlist v1:
**github + filesystem, только эти два** (решение владельца, SG-F3). Оба сервера —
office-owned (этот репозиторий, `mcp_servers/`), stdio, legacy-диалект MCP
(контракт зеркалит `tests/fixtures/mcp_echo_server.py` из Metalogos).

```
Telegram /issue /ci /docs
  → app.mlog (mlogserver, route bodies)
    → dept/dev.mlog: McpGithubCall / McpFsCall
      → mcp_call (bin/mlog, Metalogos №268)
        → mcp_servers/github | mcp_servers/filesystem (subprocess, stdio)
          → GitHub REST | песочница data/documents
```

## Гейты (безопасность)

| Гейт | Значение | Где |
|------|----------|-----|
| exec-гейт тел роутов | `METALOGOS_SERVE_ALLOW_EXEC=1` | render.yaml (осознанное расширение — нужно именно для `mcp_call`) |
| MCP-allowlist | `METALOGOS_MCP_ALLOWLIST="mcp_servers/github,mcp_servers/filesystem"` | render.yaml, конфиг не код; изменение — отдельный коммит |
| Таймаут фазы | `METALOGOS_MCP_TIMEOUT_SECS=30` (кламп 1..300) | render.yaml |
| Subprocess-аудит ядра | `METALOGOS_AUDIT_LOG_PATH=/office/data/logs/metalogos_audit.log` | render.yaml |
| Office-аудит | каждый вызов → `audit_log` (`action='mcp_call'`, actor=dev, статус attempt/ok/refused/error) | dept/dev.mlog `McpAudit` |
| Taint | вывод тулз = недоверенные данные (UserInput, №268); наружу — только после `redact(_, "secrets")`; `reflex_train` с taint-входом отвергается статикой ядра | `McpGithubCall`/`McpFsCall` |
| Песочница fs | `FOSVED_MCP_FS_ROOT=/office/data/documents`, realpath-контейнмент, выход — громкий отказ | mcp_servers/filesystem |
| Токен | `GITHUB_TOKEN` → `GH_TOKEN` → `GITHUB_TOKEN_METALOGOS` (переиспользование существующего секрета) | mcp_servers/github |

## Инцидент-политика

- Сбой ядра (spawn/таймаут/протокол): `try mcp_call(...)` → `()` → департамент
  **не падает**, ответ содержит диагностику и fallback «сделать руками».
- Отказ тулзы (REST 4xx/5xx, traversal): сервер возвращает `{"ok": false,
  "error": "..."}` (isError=false) — детали диагностики не теряются в `try`.
- `mcp_list_tools` доступен для диагностики реестра тулз сервера.

## Команды dev-департамента

| Команда | Действие |
|---|---|
| `/issue <owner/repo> <заголовок и текст>` | создать issue через GitHub-MCP |
| `/ci <owner/repo> [ветка]` | CI-статус (check-runs) по ref |
| `/docs list [path]` | список песочницы документов |
| `/docs read <path>` | прочитать файл (redact перед выводом) |
| `/docs write <path> <текст>` | записать файл в песочницу (вне git) |

## Тесты

`tests/test_fo014_mcp_tools.py` — протокол обоих серверов (initialize /
notifications/initialized / tools/list / tools/call / unknown tool −32602),
github против stub-REST (ok/отказ/404/без токена), песочница fs (traversal,
absolute path), гейты ядра (allowlist miss → `MCP_NOT_ALLOWLISTED`, spawn
в audit-файле, deny-by-default тел роутов без `METALOGOS_SERVE_ALLOW_EXEC`).
