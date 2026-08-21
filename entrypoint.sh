#!/bin/bash
echo "=== Fosved Office v2 Starting ==="
export DATABASE_URL="${DATABASE_URL:-sqlite:${DATABASE_PATH:-./data}/fosved.db}"

# Log source file checksums
echo "--- Source checksums ---"
echo "app.mlog:       $(md5sum app.mlog 2>/dev/null | cut -d' ' -f1)"
echo "dept/yana.mlog: $(md5sum dept/yana.mlog 2>/dev/null | cut -d' ' -f1)"
echo "llm_proxy.py:   $(md5sum llm_proxy.py 2>/dev/null | cut -d' ' -f1)"
echo "miniapp.mlog:   $(md5sum dept/miniapp.mlog 2>/dev/null | cut -d' ' -f1)"
echo "osp.mlog:       $(md5sum dept/osp.mlog 2>/dev/null | cut -d' ' -f1)"
echo "expert.mlog:    $(md5sum dept/expert.mlog 2>/dev/null | cut -d' ' -f1)"

if grep -q "КРИТИЧЕСКОЕ ПРАВИЛО ФОРМАТА" dept/yana.mlog 2>/dev/null; then
  echo "!!! WARNING: dept/yana.mlog still has anti-format code !!!"
else
  echo "dept/yana.mlog: clean (no anti-format)"
fi

# ---------------------------------------------------------------------------
# HOTFIX 2026-08-21: mlog 0.17.0 — imported patterns from dept/osp and
# dept/expert are NOT visible at runtime (same class of bug as HandleYana).
#
# Restore FULL native functionality by inlining both files into app.mlog
# at boot (Yana pattern). Subcommands restored:
#   Expert: auto, compare, residual, cost, chart, briefing, quick/deep
#   OSP:    native gates, Brier, deep/full analysis paths
# ---------------------------------------------------------------------------
echo "--- HOTFIX: inline native OSP + Expert (full handlers) ---"
# Clean bytecode caches BEFORE serve
find . -path './dept/*.mbc' -delete 2>/dev/null || true
find /office/dept -name '*.mbc' -delete 2>/dev/null || true
echo "  Cleaned stale .mbc files"

# Comment broken imports (idempotent)
sed -i 's|^import dept/osp$|// import dept/osp  # inlined below — mlog-0.17 import regression|g' app.mlog
sed -i 's|^import dept/expert$|// import dept/expert  # inlined below — mlog-0.17 import regression|g' app.mlog
# Drop thin fallback import if present from previous hotfix
sed -i '/import dept\/handlers_fallback/d' app.mlog

if ! grep -q 'INLINED_DEPT_OSP_EXPERT' app.mlog; then
  if [ -f dept/osp.mlog ] && [ -f dept/expert.mlog ]; then
    {
      echo ""
      echo "// === INLINED_DEPT_OSP_EXPERT ==="
      echo "// Boot-time inline of dept/osp.mlog + dept/expert.mlog"
      echo "// Bypasses mlog 0.17 cross-file pattern export regression."
      echo "// Source of truth remains dept/osp.mlog and dept/expert.mlog."
      echo ""
      cat dept/osp.mlog
      echo ""
      cat dept/expert.mlog
      echo ""
      echo "// === END INLINED_DEPT_OSP_EXPERT ==="
    } >> app.mlog
    echo "  Inlined full dept/osp.mlog + dept/expert.mlog into app.mlog"
    echo "  app.mlog size after inline: $(wc -c < app.mlog) bytes"
  else
    echo "  FATAL: dept/osp.mlog or dept/expert.mlog missing — cannot restore handlers"
  fi
else
  echo "  Already inlined (marker INLINED_DEPT_OSP_EXPERT present)"
fi

grep -n 'INLINED_DEPT_OSP_EXPERT\|import dept/osp\|import dept/expert\|import dept/handlers_fallback' app.mlog | head -30 || true

if [ ! -f data/memory.db ]; then
  echo "--- Seeding FosvedMemory ---"
  python3 scripts/seed_memory.py data/memory.db
fi

python3 scripts/migrate_schema.py "${DATABASE_PATH:-./data}/fosved.db"

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

# 2. Metalogos
if ./bin/mlog check app.mlog 2>&1 | grep -q "parse error"; then
  echo "WARNING: mlog check found parse errors (mlog serve may still work — interpreter is more lenient)"
  ./bin/mlog check app.mlog 2>&1 | head -5
fi
./bin/mlog audit app.mlog 2>&1 | tail -3
PORT=10001 ./bin/mlog serve app.mlog &
MLOG_PID=$!
echo "Metalogos started (PID: $MLOG_PID)"
sleep 3

for i in {1..10}; do
  curl -sf http://127.0.0.1:10001/ && break
  echo "Waiting for Metalogos... ($i)"
  sleep 2
done

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

wait $LLM_PID $MLOG_PID $PROXY_PID
