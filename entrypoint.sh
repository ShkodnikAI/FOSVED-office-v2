#!/bin/bash
# ── #450: сброс привилегий — замечание 1 аудита 2026-10-01 (#451) ───────────
# Постоянный диск Render монтируется ПОВЕРХ /var/data при запуске: chown в
# Dockerfile действует только на слой образа, а база на диске создана
# процессами от root → под office запись в базу не гарантирована
# (attempt to write a readonly database / Permission denied).
# Контейнер стартует от root: разово выравниваем владельца персистентных
# путей и сбрасываем привилегии — ВСЕ процессы офиса (bootstrap, seed,
# backup, LLM-прокси, mlog, reverse_proxy, tg-monitor) работают от office.
if [ "$(id -u)" = "0" ]; then
  echo "--- #450: root-bootstrap: chown persistent disk, drop privileges -> office ---"
  chown -R office:office "${DATABASE_PATH:-/var/data}" /var/forge /office/data 2>/dev/null || true
  exec gosu office bash "$0" "$@"
fi

echo "=== Fosved Office v2 Starting ==="
echo "--- running as $(id -u):$(id -gn) ---"
export DATABASE_URL="${DATABASE_URL:-sqlite:${DATABASE_PATH:-./data}/fosved.db}"

# Metalogos: VERSION file written from RENDER_GIT_COMMIT for /version route.
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
# Стейджинг VM-пилота (FO-050): MLOG_BIN=./bin/mlog (0.30.0, наряд FO-050-R #503 — пин mlog-020 снят: dept/team.mlog не парсится 0.20.0), MLOG_ENTRY=dogfood_staging.mlog
#
# Наряд №349 (2026-09-24): переход 0.19→0.22 (ADR-0005). Наряд N023 (2026-09-24):
# 0.23.0 (ADR-0006). Наряд N024 (2026-09-25, прямое указание владельца):
# 0.24.0 (ADR-0007). Наряд №372 (2026-09-25, office-параллель Волны 15):
# 0.25.0 (ADR-0008). Наряд №494-office (2026-09-27, прямое указание владельца
# «переходим на 0.27.0»): боевой бинарь — bin/mlog = 0.27.0 (ADR-0009; бинарь
# из CI-артефакта тегового коммита 0d1cce9 — unfreeze-релиз: В17-фиксы памяти
# + security-волна 0.26.0 №454-№459, включая file-ingest gate №455 — офисная
# адаптация в блоке ниже); 0.25 вендорен как bin/mlog-025 (прошлый-хороший,
# тест-гвард), mlog-024 выведен из репо (история git сохраняет).
# Guard-проба №419 сохранена: перед стартом "$MLOG_CANDIDATE" audit
# аугментированной копии (мост №421); 0.27-аудит на app.mlog без моста —
# те же 42 строки [ERROR] долга №327 (0 Category A), с мостом — чисто;
# check/audit/27-гвард dept/serve-батарея/.mbc-кросс 4/4 — 0.27 ≡ 0.25
# байт-идентичны (проверено, ADR-0009 B.2–B.4).
# Явный MLOG_BIN из env пробу не отменяет, но откат не трогает.
# Фолбэк — mlog-020 (0.20.0): последний бинарь с корректным try-контрактом И
# lax-аудитом (грузит сырой app.mlog без моста). 0.21/0.19/0.22/0.23 выведены из ротации.
MLOG_CANDIDATE="${MLOG_BIN:-./bin/mlog}"
MLOG_LEGACY="./bin/mlog-020"
MLOG_ENTRY="${MLOG_ENTRY:-app.mlog}"
MLOG_BIN="$MLOG_CANDIDATE"
# №421: проба принимает exit 0 (чисто) и exit 2 (только предупреждения —
# известный ложняк эвристики SECRETS: "sk_" совпадает внутри "task_id"/
# "risk_level", апстрим-баг word-boundary; ошибок Category A нет).
# Exit 1 (ошибки Category A) по-прежнему блокирует бут на кандидате.
# №424-ценз и гейты — ОБЩИЕ для обеих ветвей (кандидат и фолбэк).
# №427 (инцидент 2026-09-24): на фолбэк-пути allowlist не экспортировался —
# env() в хендлерах 0.19 denied → /version 500 ENV_NOT_PERMITTED.
METALOGOS_ENV_ALLOWLIST_CENSUS="CEREBRAS_API_KEY,CRON_SECRET,DATABASE_URL,DEEPSEEK_API_KEY,FNP_CUSTOMER,FNP_GOAL,FNP_NAME,FNP_SLUG,FNP_TYPE,FORGE_GITHUB_OWNER,FORGE_REPOS_DIR,FORGE_RUN_ENABLED,FORGE_RUN_VLIMIT_KB,GROQ_API_KEY,INTERNAL_API_TOKEN,KIMI_API_KEY,LOCKDOWN_PASSWORD,METALOGOS_EXEC_TIMEOUT_SECS,OWNER_TELEGRAM_ID,RENDER_URL,SAKANA_API_KEY,SHOP_ENABLED,TAVILY_API_KEY,TELEGRAM_ARCHIVE_CHANNEL_ID,TELEGRAM_BOT_TOKEN,ZAI_API_KEY,ALPHAVANTAGE_API_KEY,OSP_TAVILY_DAILY_BUDGET,OSP_TAVILY_CACHE_MIN,TEAM_MAX_CONSULTS,TEAM_MAX_LLM_CALLS"
# BEGIN №424 env-allowlist guard (extract-тест: tests/test_env_allowlist_guard.py)
export METALOGOS_ENV_ALLOWLIST="${METALOGOS_ENV_ALLOWLIST:-$METALOGOS_ENV_ALLOWLIST_CENSUS}"
# №424: оверрайд из дашборда Render затирал дефолт ЦЕЛИКОМ — живой пробой
# 2026-09-22: CRON_SECRET читался (403-ветка), а env("INTERNAL_API_TOKEN")
# давал 500 ENV_NOT_PERMITTED → /version лежала. Политика теперь: ценз —
# нижняя граница; дашборд может только ДОБАВЛЯТЬ имена, не убирать.
for ALLOWLIST_NAME in $(printf '%s' "$METALOGOS_ENV_ALLOWLIST_CENSUS" | tr ',' ' '); do
  case ",${METALOGOS_ENV_ALLOWLIST}," in
    *",${ALLOWLIST_NAME},"*) ;;
    *) METALOGOS_ENV_ALLOWLIST="${METALOGOS_ENV_ALLOWLIST:+${METALOGOS_ENV_ALLOWLIST},}${ALLOWLIST_NAME}" ;;
  esac
done
# END №424 env-allowlist guard
echo "--- env-allowlist effective (names only): ${METALOGOS_ENV_ALLOWLIST}"
export METALOGOS_SERVE_ALLOW_EXEC="${METALOGOS_SERVE_ALLOW_EXEC:-1}"
# №422: SSRF-гвард (с 0.21) по умолчанию режет http_get/http_post на 127.0.0.1 —
# а это ШТАТНЫЙ внутренний канал офиса (mlog -> свой LLM-прокси на :4000,
# ~40 сайтов вызовов: /ask, news, tts, /cron/*-цепочки). Без флага офис на
# 0.21 отвечает только на команды без LLM — репродукция в отчёте №422.
# Публичная поверхность не меняется: наружу смотрит только reverse-прокси.
export METALOGOS_HTTP_ALLOW_PRIVATE="${METALOGOS_HTTP_ALLOW_PRIVATE:-1}"
# ADR-0171 дефолт — VM, но VM-хендлеры 0.21+ не видят db-соединение (db_decl):
# office-путь держим на интерпретаторе до починки апстрима (находка №419).
# №349/B.1: пин ЯВНЫЙ и здесь, и в render.yaml — VM-дефолт 0.21+ не подхватывается.
export METALOGOS_SERVE_BACKEND="${METALOGOS_SERVE_BACKEND:-interpreter}"
# #445 A.3: rate-limit по реальному клиенту. Доверенный пир mlog — только
# reverse_proxy (127.0.0.1), XFF от него ПЕРЕЗАПИСЫВАЕТСЯ клиентским адресом
# (контракт №263, reverse_proxy.py:_upstream_headers). До наряда: peer 127.0.0.1
# был лимит-ключом для всего внешнего трафика — один общий лимит на всех.
export METALOGOS_TRUSTED_PROXIES="${METALOGOS_TRUSTED_PROXIES:-127.0.0.1}"

# ── №455 (0.26.0): file-ingest gate — офисная адаптация (ADR-0009) ──────────
# Serve-чтения файлов содержатся в METALOGOS_DATA_DIR (дефолт ./data).
# Офисный корпус читает ~100 ресурсов приложения из корня (skills/,
# library/, config/, VERSION, METHODOLOGY.md) — снапшотить их всё в data/
# = миграция ~100 сайтов чтения. Осознанное решение (ADR-0009): корень
# containment = корень приложения; layer-1 deny-list (.env*, *.db,
# *.sqlite*, .git/**, metalogos.toml) сохранён ПОЛНОСТЬЮ и теперь закрывает
# чтения, которые 0.25 разрешала. Чтения *.mlog (снапшоты исходников:
# app/dept/library/memories) снимаются с deny-list загрузочным allowlist'ом
# имён; контент помечается Secret движком меток и на каждом сайте обёрнут
# в redact(..., "all"). Рантайм-записи (config/priority_*.txt,
# memories/consensus.mlog) гейту №455 не подчиняются — поведение как в 0.25.
export METALOGOS_DATA_DIR="${METALOGOS_DATA_DIR:-.}"
M455_NAMES="app.mlog,consensus.mlog"
for M455_F in dept/*.mlog library/*.mlog memories/*.mlog; do
  [ -e "$M455_F" ] || continue
  M455_NAMES="${M455_NAMES},$(basename "$M455_F")"
done
export METALOGOS_SENSITIVE_PATH_ALLOWLIST="${METALOGOS_SENSITIVE_PATH_ALLOWLIST:-$M455_NAMES}"
echo "--- №455: DATA_DIR=app-root, sensitive-allowlist(names): ${M455_NAMES}"

# №427 (инцидент 2026-09-24, продолжение): один app.mlog на два бинаря
# невозможен — мост `profile legacy { egress: permissive_with_audit }`
# (№421) делает пробу кандидата зелёной, но 0.19 эту строку НЕ парсит
# (инцидент #333: boot break). История #333/#427 привела к №349: кандидат
# теперь 0.22.0 в bin/mlog. Механика сохранена: пробуем и сервервим
# АУГМЕНТИРОВАННУЮ копию (мост добавляется скриптом) на кандидате;
# фолбэк получает оригинал без моста (0.20 мост тоже парсит, но сырой
# файл проще и достаточно).
MLOG_SERVE_FILE="$MLOG_ENTRY"
MLOG_PROBE_RC=9
if [ -x "$MLOG_CANDIDATE" ]; then
  MLOG_AUG="${TMPDIR:-/tmp}/app_serve_candidate.mlog"
  if grep -q "^profile legacy" "$MLOG_ENTRY"; then
    cp "$MLOG_ENTRY" "$MLOG_AUG"
  else
    { printf '%s\n' "profile legacy { egress: permissive_with_audit }"; cat "$MLOG_ENTRY"; } > "$MLOG_AUG"
  fi
  "$MLOG_CANDIDATE" audit "$MLOG_AUG" >/dev/null 2>&1 && MLOG_PROBE_RC=0 || MLOG_PROBE_RC=$?
  if [ "$MLOG_PROBE_RC" = "0" ] || [ "$MLOG_PROBE_RC" = "2" ]; then
    MLOG_SERVE_FILE="$MLOG_AUG"
  fi
fi
if [ "$MLOG_PROBE_RC" = "0" ] || [ "$MLOG_PROBE_RC" = "2" ]; then
  echo "--- Metalogos: candidate PASSED the Category A audit probe — serving on $MLOG_CANDIDATE (file: $MLOG_SERVE_FILE)"
else
  if [ -x "$MLOG_CANDIDATE" ]; then
    echo "!!! Metalogos №419/№349: candidate ($MLOG_CANDIDATE) FAILED the audit probe — Category A blocks the office boot (№327 debt, см. отчёт №419)"
    echo "!!! GRADUAL CUTOVER: falling back to legacy $MLOG_LEGACY (0.20.0). External cron-job.org keeps firing /cron/* routes; native schedules activate after the migration naryad."
    "$MLOG_CANDIDATE" audit "$MLOG_ENTRY" 2>&1 | grep -m3 "ERROR" || true
  else
    echo "!!! Metalogos №419/№349: candidate $MLOG_CANDIDATE not found — falling back to legacy $MLOG_LEGACY"
  fi
  if [ -n "${MLOG_BIN_FORCE:-}" ]; then
    MLOG_BIN="$MLOG_CANDIDATE"
    echo "!!! MLOG_BIN_FORCE set — serving on the FAILED candidate anyway (operator override)"
  else
    MLOG_BIN="$MLOG_LEGACY"
  fi
fi
# ── #399 A.2 + #505 A.3: фолбэк-патч фич Metalogos-#757 и timeout ────────────
# app.mlog несёт llm { max_tokens: 8192, timeout: 150 } и SendReport вызывает
# llm_last_finish_reason() — эти фичи понимает линия 0.27.1+ (вкл. боевой
# 0.30.0, ADR-0018; исторические пробы: 0.20/0.25/0.27.0 дают parse-ошибку
# "expected llm_providers, COMMA, or RBRACE" / "undefined: function").
# Фолбэк-ветка (кандидат не прошёл пробу — редкий crash-сценарий) служит
# 0.20, поэтому вырезает фичи из serve-копии; граница — до вывода 0.20
# из ротации (ADR-0009).
if [ "$MLOG_BIN" = "$MLOG_LEGACY" ]; then
  sed -i '/max_tokens: 8192,/d' "$MLOG_SERVE_FILE"
  sed -i '/^  timeout: 150,$/d' "$MLOG_SERVE_FILE"
  sed -i 's/llm_last_finish_reason()/""/g' "$MLOG_SERVE_FILE"
  echo "#399 A.2 + #505 A.3: fallback $MLOG_LEGACY — фича #757 (max_tokens + пометка обрезки) и timeout вырезаны из serve-копии"
fi
mkdir -p "${DATABASE_PATH:-./data}/documents" "${DATABASE_PATH:-./data}/logs" "${DATABASE_PATH:-./data}"

# ── №428 A.5: KV-стор Metalogos на постоянный диск ──────────────────────────
# Декларация memory persist в app.mlog допускает только строковый литерал
# ("data/metalogos_kv.db"): env-выражение грамматикой не разрешено (проверено
# прогоном 0.27.0), отдельной env-переменной пути kv-стора у бинаря нет.
# На проде data/ — эфемерный слой контейнера: стор нативных расписаний
# (ключ cron_jobs) и KV-память терялись при каждом деплое/рестарте.
# DATABASE_PATH задаёт постоянный диск (Render: /var/data) — направляем
# файл туда симлинком; существующий эфемерный файл переносится разово.
KV_DISK_PATH="${DATABASE_PATH:-}/metalogos_kv.db"
if [ -n "${DATABASE_PATH:-}" ] && [ "$DATABASE_PATH" != "./data" ]; then
  if [ -f "data/metalogos_kv.db" ] && [ ! -L "data/metalogos_kv.db" ] && [ ! -e "$KV_DISK_PATH" ]; then
    if mv data/metalogos_kv.db "$KV_DISK_PATH" 2>/dev/null; then
      echo "KV store migrated: data/metalogos_kv.db -> $KV_DISK_PATH"
    fi
  fi
  if [ ! -e "data/metalogos_kv.db" ]; then
    if ln -s "$KV_DISK_PATH" data/metalogos_kv.db 2>/dev/null; then
      echo "KV store: data/metalogos_kv.db -> $KV_DISK_PATH (persistent disk)"
    fi
  fi
  if [ ! -e "data/metalogos_kv.db" ]; then
    echo "WARNING: KV store symlink was not created — native cron state stays ephemeral"
  fi
fi
# naryad-361: каталог артефактов Визуала — html_to_pdf пишет туда относительными
# путями (visuals/*.pdf); без mkdir запись падала ENOENT в рантайме
mkdir -p visuals
if "$MLOG_BIN" check "$MLOG_SERVE_FILE" 2>&1 | grep -q "parse error"; then
  echo "WARNING: mlog check found parse errors (mlog serve may still work — interpreter is more lenient)"
  "$MLOG_BIN" check "$MLOG_SERVE_FILE" 2>&1 | head -5
fi
"$MLOG_BIN" audit "$MLOG_SERVE_FILE" 2>&1 | tail -3
PORT=10001 "$MLOG_BIN" serve "$MLOG_SERVE_FILE" &
MLOG_PID=$!
echo "Metalogos started (PID: $MLOG_PID, bin: $MLOG_BIN, entry: $MLOG_SERVE_FILE)"
sleep 3

# ── Наряд #520: ожидание готовности mlog serve до /health (200) ────────────
# На 0.32.0 старт занимает ~57 с (прод-лог 16.10: первый запрос 02:59:24,
# «listening» 03:00:21), прежнее окно 10×2 с = 20 с гарантированно рвало
# бут: bootstrap расписаний получал conn-fail ×3 («native schedules NOT
# registered»), стартовые проверки печатали FAIL без причины. Ждём до
# готовности /health; попытки/интервал/граница — в переменных; таймаут —
# громкий выход (§445 A.2): полумёртвый бут без расписаний хуже рестарта.
MLOG_BOOT_WAIT_SECS="${MLOG_BOOT_WAIT_SECS:-180}"
MLOG_BOOT_POLL_SECS="${MLOG_BOOT_POLL_SECS:-2}"
MLOG_BOOT_DEADLINE=$(( $(date +%s) + MLOG_BOOT_WAIT_SECS ))
MLOG_BOOT_READY=0
while [ "$(date +%s)" -lt "$MLOG_BOOT_DEADLINE" ]; do
  if curl -sf --max-time 5 "http://127.0.0.1:10001/health" >/dev/null 2>&1; then
    MLOG_BOOT_READY=1
    break
  fi
  echo "Waiting for Metalogos /health... (deadline ${MLOG_BOOT_WAIT_SECS}s)"
  sleep "$MLOG_BOOT_POLL_SECS"
done
if [ "$MLOG_BOOT_READY" != "1" ]; then
  echo "!!! Metalogos did not become healthy within ${MLOG_BOOT_WAIT_SECS}s (naryad #520) — aborting boot (§445 A.2), Render restarts the container"
  kill "$MLOG_PID" 2>/dev/null || true
  exit 1
fi
echo "Metalogos healthy — /health 200 (naryad #520 wait loop done)"

# ── Наряд #536 A.0: диагностика расхождения секретов ────────────────────────
# Прод-mlog отклоняет оба секрета из того же контейнерного env (стартовый лог
# dep-db9f48jrjlhs73ejcnn0: bootstrap 403 key_mismatch, /version FAIL).
# Печатаем ТОЛЬКО длины (shell-сторона) и флаг пробелов/переводов строк —
# значения не выводятся. Ответ маршрута /internal/envcheck (mlog-сторона env)
# — рядом; маршрут временный и будет удалён после A.3 (по тексту наряда),
# shell-строки остаются постоянной диагностикой.
echo "envcheck shell: cron=${#CRON_SECRET} internal=${#INTERNAL_API_TOKEN}"
case "${CRON_SECRET}" in
  *[[:space:]]*) echo "envcheck spaces: cron=yes" ;;
  *) echo "envcheck spaces: cron=no" ;;
esac
case "${INTERNAL_API_TOKEN}" in
  *[[:space:]]*) echo "envcheck spaces: internal=yes" ;;
  *) echo "envcheck spaces: internal=no" ;;
esac
# #536 A.0: mlog-сторона (без XFF — только loopback, см. маршрут в app.mlog)
EC_RESP=$(curl -s --max-time 5 "http://127.0.0.1:10001/internal/envcheck" 2>/dev/null || true)
echo "envcheck route: ${EC_RESP:-no-answer}"

# ── Наряд №419: бутстрап реестра заданий (только на пути кандидата) ────────
# Реестр dept/schedules.mlog → нативный стор cron (идемпотентно по target).
# На легаси-пути бутстрап не запускается: 4-аргументный cron_add/TZ — контракт
# 0.21+; внешние cron-job.org продолжают дёргать /cron/*-роуты как раньше.
if [ "$MLOG_BIN" = "$MLOG_CANDIDATE" ] && [ -n "$CRON_SECRET" ]; then
  echo "--- №419: bootstrapping native schedules (dept/schedules.mlog -> cron store)"
  # №422: на холодном старте 0.21 serve может не успеть ответить на первый запрос
  # (гонка инициализации kv/БД — в бут-логе 2026-09-22 бутстрап отпал через 160 мс
  # после «listening»). Три попытки с паузой 2 с; секрет в URL не печатаем.
  BOOT_REPORT=""
  BOOT_CODE=""
  for BOOT_ATTEMPT in 1 2 3; do
    # №425: 0.21 percent-декодирует query ('+' → пробел, %XX → байты,
    # url_decode_fallback server.rs) — сырая вставка секрета с '+' честно
    # даёт 403 (проба scripts/probe021qp.sh: raw=403, enc=200 KEEP×7).
    # Секрет только в URL внутреннего curl, в лог не печатаем.
    # №426: -w добавляет HTTP-код отдельной строкой — прежнее «no answer»
    # сливало 403/404/conn-refused/таймаут (бут 2026-09-23T07:29Z: причина
    # из лога не видна). С №428 тело не-2xx печатается в лог (причина отказа),
    # в отчёт не попадает — отчётный путь ждёт только 2xx.
    BOOT_RAW=$(curl -s --max-time 90 -G "http://127.0.0.1:10001/schedules/bootstrap" --data-urlencode "secret=${CRON_SECRET}" -w $'\n%{http_code}' 2>/dev/null || true)
    BOOT_CODE="${BOOT_RAW##*$'\n'}"
    BOOT_REPORT="${BOOT_RAW%$'\n'*}"
    case "$BOOT_CODE" in
      2*) : ;;
      000|"") BOOT_CODE="conn-fail"; BOOT_REPORT="" ;;
      *)
        # №428 A.2: тело не-2xx печатаем в бут-лог — иначе причина отказа
        # не устанавливается (бут 2026-09-29: три попытки 403 без причины).
        # Роут /schedules/bootstrap отвечает литералами cron_key_unset /
        # key_mismatch — значение секрета в теле не присутствует.
        # В BOOT_REPORT не возвращаем: отчётный путь ниже ждёт только 2xx.
        echo "  bootstrap attempt ${BOOT_ATTEMPT}: HTTP ${BOOT_CODE} body: ${BOOT_REPORT}"
        BOOT_REPORT=""
        ;;
    esac
    if [ -n "$BOOT_REPORT" ]; then break; fi
    if [ "$BOOT_ATTEMPT" != "3" ]; then
      echo "  bootstrap attempt ${BOOT_ATTEMPT}: no answer (HTTP ${BOOT_CODE:-conn-fail}) — retry in 2s"
      sleep 2
    fi
  done
  if [ -n "$BOOT_REPORT" ]; then
    echo "  bootstrap: ${BOOT_REPORT}"
    case "$BOOT_REPORT" in
      *"FAIL("*) echo "  !!! SCHEDULES BOOTSTRAP HAS FAILURES (loud per naryad №419) — fix dept/schedules.mlog and redeploy" ;;
      *) echo "  native schedules OK" ;;
    esac
  else
    echo "  !!! schedules/bootstrap did not answer after 3 attempts (last HTTP: ${BOOT_CODE:-conn-fail}) — native schedules NOT registered (external crons remain the executor)"
  fi
fi

# ── #429 A.3: фоновый прогрев каталога схем Onliner ──────────────────────
# Дозагрузка словаря /schemas до complete (худший случай ~80×3с ≈ 240с);
# свежий полный кэш — мгновенный no-op (TTL 7 дней). Фон (nohup) — бут
# не ждёт; секрет в URL внутреннего запроса, в лог не печатаем (№425).
# Регулярный пере-прогрев — слот onliner-warm (dept/schedules.mlog,
# включается владельцем).
if [ -n "$CRON_SECRET" ]; then
  nohup curl -s --max-time 300 -G "http://127.0.0.1:4000/cron/onliner-warm" \
    --data-urlencode "secret=${CRON_SECRET}" >/dev/null 2>&1 &
  echo "Onliner catalog warm-up started in background (#429 A.3)"
fi

echo "--- Version check ---"
# №422: /version за RequireInternalAuth — без token-параметра роут честно отвечает
# 401 и проверка всегда падала («version endpoint not available» в бут-логе).
# №425: token — через --data-urlencode (0.21 декодирует query, см. бутстрап выше).
curl -sf --max-time 30 -G "http://127.0.0.1:10001/version" --data-urlencode "token=${INTERNAL_API_TOKEN:-}" 2>/dev/null || echo "version endpoint not available"

echo "--- Department import validation ---"
for DEPT_ROUTE in "/health" "/version"; do
  # №422: /version требует token; №425: токен — через --data-urlencode
  # (сырая вставка в query ломается о декодирование 0.21), в лог не печатаем
  if [ "$DEPT_ROUTE" = "/version" ] && [ -n "${INTERNAL_API_TOKEN:-}" ]; then
    curl -sf --max-time 30 -G "http://127.0.0.1:10001/version" --data-urlencode "token=${INTERNAL_API_TOKEN}" > /dev/null 2>&1 && echo "  ${DEPT_ROUTE}: OK" || echo "  ${DEPT_ROUTE}: FAIL"
  else
    curl -sf --max-time 30 "http://127.0.0.1:10001${DEPT_ROUTE}" > /dev/null 2>&1 && echo "  ${DEPT_ROUTE}: OK" || echo "  ${DEPT_ROUTE}: FAIL"
  fi
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

# #445 A.2: супервизия — падение ЛЮБОГО критичного процесса (LLM-прокси,
# mlog serve, reverse_proxy) завершает контейнер с ненулевым кодом, Render
# перезапускает сервис целиком (раньше: wait всех — при падении mlog офис
# жил полумёртвым, Render считал сервис живым). tg-monitor НЕ критичен —
# его смерть офис не роняет (kill-switch TG_MONITOR_ENABLED остаётся).
wait -n $LLM_PID $MLOG_PID $PROXY_PID
SUP_EXIT=$?
echo "!!! CRITICAL PROCESS DIED (wait exit=${SUP_EXIT}) — shutting down for container restart (naryad #445 A.2)"
kill $LLM_PID $MLOG_PID $PROXY_PID 2>/dev/null || true
sleep 2
exit "${SUP_EXIT:-1}"
