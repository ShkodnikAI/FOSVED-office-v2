#!/bin/bash
echo "=== Fosved Office v2 Starting ==="
export DATABASE_URL="${DATABASE_URL:-sqlite:${DATABASE_PATH:-./data}/fosved.db}"

# Metalogos 0.19.0: VERSION file written from RENDER_GIT_COMMIT for /version route.
echo "${RENDER_GIT_COMMIT:-unknown}" > VERSION
echo "--- VERSION file updated: $(cat VERSION) ---"

# Log source file checksums
echo "--- Source checksums ---"
echo "app.mlog:       $(md5sum app.mlog 2>/dev/null | cut -d' ' -f1)"
echo "dept/yana.mlog: $(md5sum dept/yana.mlog 2>/dev/null | cut -d' ' -f1)"
echo "llm_proxy.py:   $(md5sum llm_proxy.py 2>/dev/null | cut -d' ' -f1)"
echo "skills-manifest: $(md5sum skills-manifest.json 2>/dev/null | cut -d' ' -f1)"
echo "miniapp.mlog:   $(md5sum dept/miniapp.mlog 2>/dev/null | cut -d' ' -f1)"
echo "osp.mlog:       $(md5sum dept/osp.mlog 2>/dev/null | cut -d' ' -f1)"
echo "expert.mlog:    $(md5sum dept/expert.mlog 2>/dev/null | cut -d' ' -f1)"

if grep -q "КРИТИЧЕСКОЕ ПРАВИЛО ФОРМАТА" dept/yana.mlog 2>/dev/null; then
  echo "!!! WARNING: dept/yana.mlog still has anti-format code !!!"
else
  echo "dept/yana.mlog: clean (no anti-format)"
fi

# ── Skills bootstrap (FO-012) ────────────────────────────────────────────────
# Скиллы не лежат в git — восстанавливаем из релиз-артефакта (skills-manifest.json).
bash scripts/bootstrap_skills.sh 2>&1 | sed 's/^/[entrypoint] /'

# ── DB Restore check (FO-001) ──────────────────────────────────────────────
# If main DB is missing or corrupt, try to restore from latest backup.
DB_DIR="${DATABASE_PATH:-./data}"
DB_FILE="${DB_DIR}/fosved.db"
if [ ! -f "$DB_FILE" ] || ! python3 -c "import sqlite3; c=sqlite3.connect('$DB_FILE'); c.execute('PRAGMA integrity_check').fetchone(); c.close()" 2>/dev/null; then
  echo "--- DB missing or corrupt — attempting restore from backup ---"
  if [ -d "${DB_DIR}/backups" ]; then
    python3 scripts/backup_db.py restore --latest 2>&1
  else
    echo "WARNING: No backup directory found. Starting with empty DB."
  fi
fi

if [ ! -f data/memory.db ]; then
  echo "--- Seeding FosvedMemory ---"
  python3 scripts/seed_memory.py data/memory.db 2>/dev/null || echo "seed_memory.py not found — memory.db will be created on first use"
fi

python3 scripts/migrate_schema.py "${DATABASE_PATH:-./data}/fosved.db" 2>/dev/null || echo "migrate_schema.py not found — skipping schema migration"

# ── Startup backup (FO-001) ─────────────────────────────────────────────────
# Create a backup at startup so we always have a recent snapshot.
echo "--- Startup backup ---"
python3 scripts/backup_db.py backup 2>&1 | tail -5

# 0. Prisma migrate deploy (PostgreSQL OSP schema)
if echo "$DATABASE_URL" | grep -q "^postgres"; then
  echo "--- Prisma migrate deploy (PostgreSQL) ---"
  npx prisma migrate deploy 2>&1 || echo "Prisma migrate failed (may already be up-to-date)"
else
  echo "--- Skipping Prisma (DATABASE_URL is not PostgreSQL) ---"
fi

# 1. LLM Proxy
if ! python3 -c "import llm_proxy" 2>/tmp/llm_import_err.log; then
  echo "FATAL: llm_proxy import error"; cat /tmp/llm_import_err.log | tail -10; exit 1
fi
python3 llm_proxy.py &
LLM_PID=$!
echo "LLM Proxy started (PID: $LLM_PID)"
sleep 2

for i in {1..10}; do
  curl -sf http://127.0.0.1:4000/health && break
  echo "Waiting for LLM proxy... ($i)"
  sleep 2
done

# FO-035 E.1: двухзонная инициализация FORGE — персистентный mount (форж-репо)
# + scratch зона; sweep хвостов scratch после падения процесса
FORGE_REPOS_DIR="${FORGE_REPOS_DIR:-/var/forge/repos}"
mkdir -p "${FORGE_REPOS_DIR}/forge/repos" /office/forge-tmp 2>/dev/null || mkdir -p /office/forge-tmp
rm -rf /office/forge-tmp/* 2>/dev/null
echo "--- FORGE: repos dir=${FORGE_REPOS_DIR}/forge/repos, scratch swept ---"

# 2. Metalogos
# FO-014: песочница документов filesystem-MCP + каталог subprocess-аудита ядра
# Наряд №395 (PR #191): бинарь и входной файл env-изированы для стейджинга.
# Стейджинг VM-пилота (FO-050): MLOG_BIN=./bin/mlog-020, MLOG_ENTRY=dogfood_staging.mlog
#   (или ./bin/mlog-021 + METALOGOS_SERVE_BACKEND=interpreter — наряд №419).
#
# Наряд №419 (Metalogos gh#572): guard-переход на 0.21.0.
# Прод-кандидат — mlog-021; перед стартом идёт ПРОБА: "$MLOG_CANDIDATE" audit
# $MLOG_ENTRY. 0.21-аудит Category A блокирует бут офиса (долг №327
# UNTRUSTED_DECISION ~430 сайтов диалогового контура + 33 деструктивных сайта
# без грант-контура — ценз в отчёте №419) ⇒ проба громко откатывает прод на
# легаси-бинарь. Переход произойдёт АВТОМАТИЧЕСКИ той же пробой, когда
# миграционный наряд (объём №395) прочистит аудит. Явный MLOG_BIN из env
# пробу не отменяет, но откат не трогает (оператор сказал — так и едем).
MLOG_CANDIDATE="${MLOG_BIN:-./bin/mlog-021}"
MLOG_LEGACY="./bin/mlog"
MLOG_ENTRY="${MLOG_ENTRY:-app.mlog}"
MLOG_BIN="$MLOG_CANDIDATE"
if [ -x "$MLOG_CANDIDATE" ] && "$MLOG_CANDIDATE" audit "$MLOG_ENTRY" >/dev/null 2>&1; then
  echo "--- Metalogos: 0.21 candidate PASSED the Category A audit probe — serving on $MLOG_CANDIDATE"
  # Гейты №259 (env в роутах) и exec: паритет с 0.19 — офис читает служебные
  # env (CRON_SECRET, OWNER_TELEGRAM_ID, ...); список = ценз env( по app.mlog
  # и dept/*.mlog (наряд №419). Скомпрометированные значения ротируются в
  # дашборде Render (см. docs/render-dashboard.md, секция native cron).
  export METALOGOS_ENV_ALLOWLIST="${METALOGOS_ENV_ALLOWLIST:-CEREBRAS_API_KEY,CRON_SECRET,DATABASE_URL,DEEPSEEK_API_KEY,FNP_CUSTOMER,FNP_GOAL,FNP_NAME,FNP_SLUG,FNP_TYPE,FORGE_GITHUB_OWNER,FORGE_REPOS_DIR,FORGE_RUN_ENABLED,FORGE_RUN_VLIMIT_KB,GROQ_API_KEY,INTERNAL_API_TOKEN,KIMI_API_KEY,LOCKDOWN_PASSWORD,METALOGOS_EXEC_TIMEOUT_SECS,OWNER_TELEGRAM_ID,RENDER_URL,SAKANA_API_KEY,SHOP_ENABLED,TAVILY_API_KEY,TELEGRAM_ARCHIVE_CHANNEL_ID,TELEGRAM_BOT_TOKEN,ZAI_API_KEY}"
  export METALOGOS_SERVE_ALLOW_EXEC="${METALOGOS_SERVE_ALLOW_EXEC:-1}"
  # ADR-0171 дефолт — VM, но VM-хендлеры 0.21 не видят db-соединение (db_decl):
  # office-путь держим на интерпретаторе до починки апстрима (находка №419).
  export METALOGOS_SERVE_BACKEND="${METALOGOS_SERVE_BACKEND:-interpreter}"
else
  if [ -x "$MLOG_CANDIDATE" ]; then
    echo "!!! Metalogos №419: 0.21 candidate ($MLOG_CANDIDATE) FAILED the audit probe — Category A blocks the office boot (№327 debt, см. отчёт №419)"
    echo "!!! GRADUAL CUTOVER: falling back to legacy $MLOG_LEGACY (0.19). External cron-job.org keeps firing /cron/* routes; native schedules activate after the migration naryad."
    "$MLOG_CANDIDATE" audit "$MLOG_ENTRY" 2>&1 | grep -m3 "ERROR" || true
  else
    echo "!!! Metalogos №419: candidate $MLOG_CANDIDATE not found — falling back to legacy $MLOG_LEGACY"
  fi
  if [ -n "${MLOG_BIN_FORCE:-}" ]; then
    MLOG_BIN="$MLOG_CANDIDATE"
    echo "!!! MLOG_BIN_FORCE set — serving on the FAILED candidate anyway (operator override)"
  else
    MLOG_BIN="$MLOG_LEGACY"
  fi
fi
mkdir -p "${DATABASE_PATH:-./data}/documents" "${DATABASE_PATH:-./data}/logs"
if "$MLOG_BIN" check "$MLOG_ENTRY" 2>&1 | grep -q "parse error"; then
  echo "WARNING: mlog check found parse errors (mlog serve may still work — interpreter is more lenient)"
  "$MLOG_BIN" check "$MLOG_ENTRY" 2>&1 | head -5
fi
"$MLOG_BIN" audit "$MLOG_ENTRY" 2>&1 | tail -3
PORT=10001 "$MLOG_BIN" serve "$MLOG_ENTRY" &
MLOG_PID=$!
echo "Metalogos started (PID: $MLOG_PID, bin: $MLOG_BIN, entry: $MLOG_ENTRY)"
sleep 3

for i in {1..10}; do
  curl -sf http://127.0.0.1:10001/ && break
  echo "Waiting for Metalogos... ($i)"
  sleep 2
done

# ── Наряд №419: бутстрап реестра заданий (только на 0.21-пути) ─────────────
# Реестр dept/schedules.mlog → нативный стор cron (идемпотентно по target).
# На легаси-пути бутстрап не запускается: 4-аргументный cron_add/TZ — контракт
# 0.21; внешние cron-job.org продолжают дёргать /cron/*-роуты как раньше.
if [ "$MLOG_BIN" = "$MLOG_CANDIDATE" ] && [ -n "$CRON_SECRET" ]; then
  echo "--- №419: bootstrapping native schedules (dept/schedules.mlog -> cron store)"
  BOOT_REPORT=$(curl -sf "http://127.0.0.1:10001/schedules/bootstrap?secret=${CRON_SECRET}" 2>/dev/null || echo "")
  if [ -n "$BOOT_REPORT" ]; then
    echo "  bootstrap: ${BOOT_REPORT}"
    case "$BOOT_REPORT" in
      *"FAIL("*) echo "  !!! SCHEDULES BOOTSTRAP HAS FAILURES (loud per naryad №419) — fix dept/schedules.mlog and redeploy" ;;
      *) echo "  native schedules OK" ;;
    esac
  else
    echo "  !!! schedules/bootstrap did not answer — native schedules NOT registered (external crons remain the executor)"
  fi
fi

echo "--- Version check ---"
curl -sf http://127.0.0.1:10001/version 2>/dev/null || echo "version endpoint not available"

echo "--- Department import validation ---"
for DEPT_ROUTE in "/health" "/version"; do
  curl -sf "http://127.0.0.1:10001${DEPT_ROUTE}" > /dev/null 2>&1 && echo "  ${DEPT_ROUTE}: OK" || echo "  ${DEPT_ROUTE}: FAIL"
done
echo "  Testing handler resolution via /webhook/telegram dry-run..."
TEST_RESULT=$(curl -s -X POST http://127.0.0.1:10001/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"update_id":-1,"message":{"message_id":-1,"chat":{"id":0},"text":"/status","from":{"id":0}}}' 2>&1)
echo "  /status response: ${TEST_RESULT}"
echo "--- Department validation complete ---"

# 3. Reverse Proxy
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

# 4. LZ Telegram Monitor (MON-1, #171)
# Kill-switch: TG_MONITOR_ENABLED != "1" → процесс логает и завершается сам.
# Полный чеклист владельца (api_id/hash, отдельный аккаунт) — issue #171.
python3 telegram_monitor.py &
TG_MONITOR_PID=$!
echo "LZ Telegram monitor started (PID: $TG_MONITOR_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID $TG_MONITOR_PID
