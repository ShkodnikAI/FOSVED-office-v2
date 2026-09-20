# Render Dashboard — инвентарь сервисов вне blueprint

**Канонический источник** конфигурации prod-службы и 11 cron-джоб — **Render Dashboard**
(workspace My Workspace), настроены вручную. `render.yaml` с 2026-09-20 управляет
только стейджингом FO-050 (blueprint): старая схема кронов была невалидной
(docker+startCommand, plan free у cron) и была отвергнута валидатором при первом
Apply — см. #182, #276.

**Правила:**
- Любое ручное изменение в дашборде → обновить этот файл тем же днём (иначе дрейф).
- Живость кронов («настроено ≠ работает») — проверяется по логам Render: наряд #255.
- Восстановление/пересоздание — сверять с этим инвентарём построчно.

## Prod: fosved-office-v2 (web, docker, plan free, region frankfurt)

- Runtime: Docker (Dockerfile, entrypoint.sh). Free tier: засыпает после 15 мин неактивности — держится кроном keep-alive (ниже).
- Env: группа `fosved-secrets` (см. ниже). `DATABASE_URL` в дашборде НЕ задаётся (#269):
  entrypoint.sh сам ставит sqlite-URL, Prisma-ветка недостижима.

## Env group: fosved-secrets (24 ключа)

`TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `TELEGRAM_ARCHIVE_CHANNEL_ID`,
`TELEGRAM_WEBHOOK_SECRET`, `CRON_SECRET`, `API_SECRET`, `DEEPSEEK_API_KEY`,
`GROQ_API_KEY`, `ZAI_API_KEY`, `GITHUB_TOKEN_METALOGOS`, `TAVILY_API_KEY`,
`BACKUP_UPLOAD_CMD`, `FORGE_MASTER_KEY`, `FORGE_GITHUB_OWNER` — sync (секреты);
`BACKUP_RETENTION=7`, `METALOGOS_SERVE_ALLOW_EXEC=1`, `METALOGOS_EXEC_TIMEOUT_SECS=60`,
`METALOGOS_MCP_TIMEOUT_SECS=30`, `SHOP_ENABLED=1`, `PORT=10000` — значения;
`METALOGOS_MCP_ALLOWLIST=mcp_servers/github,mcp_servers/filesystem,mcp_servers/markets,mcp_servers/web,mcp_servers/media`;
`METALOGOS_AUDIT_LOG_PATH=/office/data/logs/metalogos_audit.log`;
`FOSVED_MCP_FS_ROOT=/office/data/documents`; `FORGE_REPOS_DIR=/var/forge/repos`.

## Cron-джобы (11) — все docker? нет: curl-пингеры, web-вызовы prod API

| # | Имя | Расписание (UTC) | Вызов |
|---|-----|------------------|-------|
| 1 | collect-news | `0 * * * *` (ежечасно) | GET /cron/collect-news?secret=CRON_SECRET |
| 2 | lz-daily | `10 6 * * *` (06:10; после collect-news 06:00) | POST /scheduler/lz-daily `{"dry_run":false}` |
| 3 | tool-output-cleanup | `30 6 * * *` (FO-016, ретеншн data/tool_output) | GET /cron/cleanup-tool-output?secret= |
| 4 | morning-brief | `20 4 * * 1-5` (будни; бэкап+выгрузка до LLM) | POST /scheduler/morning-brief `{"owner_id":OWNER_TELEGRAM_ID}` |
| 5 | watch-sweep | `0 6 * * *` (SHOP-вотчи: deltas, lastCheckAt) | POST /scheduler/watch-sweep |
| 6 | indicator-pre-reminders | `0 3 * * *` (verifyDate ≤ 7 дней) | POST /scheduler/indicator-pre-reminders `{"days_ahead":7}` |
| 7 | db-backup | `0 2 * * *` (FO-001: VACUUM INTO + integrity + retention) | GET /cron/backup?secret= |
| 8 | golden-evals | `30 2 * * *` (FO-005; регрессия → алерт) | POST /scheduler/golden-evals?secret= `{}` |
| 9 | memory-consolidation | `30 3 * * *` (FO-006: dialog_history → факты) | GET /cron/consolidate-memory?secret= `{"days":1}` |
| 10 | keep-alive | `*/14 * * * *` (не даёт уснуть free-инстансу) | GET /health; GET /cron/narad-tick?secret= (FO-047); GET staging /health (FO-050) |
| 11 | shop-tick | `0 */6 * * *` (SHOP-4: WB/Ozon вотчи, kill-switch SHOP_ENABLED=0) | GET /cron/shop-tick?secret= |

База prod: `{prod-url}` = `https://fosved-office-v2.onrender.com`; стейджинг:
`https://fosved-office-v2-staging.onrender.com` (создаётся blueprint'ом из render.yaml).

## Staging (в blueprint, для сверки): fosved-office-v2-staging

web, docker, plan free, frankfurt; env: `fosved-secrets` + `MLOG_BIN=./bin/mlog-020`,
`MLOG_ENTRY=dogfood_staging.mlog`. VM-флип: `METALOGOS_SERVE_BACKEND=vm` после
апгрейда бинаря (FO-050).
