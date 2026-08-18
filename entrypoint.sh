#!/bin/bash
echo "=== Fosved Office v2 Starting ==="
export DATABASE_URL="${DATABASE_URL:-sqlite:${DATABASE_PATH:-./data}/fosved.db}"

# Log source file checksums
echo "--- Source checksums ---"
echo "app.mlog:       $(md5sum app.mlog 2>/dev/null | cut -d' ' -f1)"
echo "dept/yana.mlog: $(md5sum dept/yana.mlog 2>/dev/null | cut -d' ' -f1)"
echo "llm_proxy.py:   $(md5sum llm_proxy.py 2>/dev/null | cut -d' ' -f1)"
echo "miniapp.mlog:   $(md5sum dept/miniapp.mlog 2>/dev/null | cut -d' ' -f1)"

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

# 0. Prisma migrate deploy (PostgreSQL OSP schema) — runs only if DATABASE_URL is a PG connection string
if echo "$DATABASE_URL" | grep -q "^postgres"; then
  echo "--- Prisma migrate deploy (PostgreSQL) ---"
  npx prisma migrate deploy 2>&1 || echo "Prisma migrate failed (may already be up-to-date)"
else
  echo "--- Skipping Prisma (DATABASE_URL is not PostgreSQL) ---"
fi

# 1. LLM Proxy (native circuit breaker + combo chains + compression)
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
# NOTE: mlog check uses stricter parsing than mlog serve (rejects 'fn' and top-level 'let').
# mlog serve interpreter supports these fine. Log warnings but don't exit.
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

# 3. Reverse Proxy
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID