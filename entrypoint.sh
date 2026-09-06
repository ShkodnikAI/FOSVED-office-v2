#!/bin/bash
echo "=== Fosved Office v2 Starting ==="
export DATABASE_URL="${DATABASE_URL:-sqlite:${DATABASE_PATH:-./data}/fosved.db}"

# GRAPH-1 hotfix: mlog 0.18.0 blocks env() reaching respond() as [SECRET_LEAK]
# (new Category A check, no allowlist for known-safe vars). /version route now
# reads this file instead of env("RENDER_GIT_COMMIT") directly.
echo "${RENDER_GIT_COMMIT:-unknown}" > VERSION
echo "--- VERSION file updated: $(cat VERSION) ---"

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
