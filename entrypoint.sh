#!/bin/bash
echo "=== Fosved Office v2 Starting ==="

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

python3 scripts/migrate_schema.py data/fosved.db

# 1. OmniRoute (порт 20128) — ПЕРВЫЙ
omniroute serve --port 20128 --no-open &
OMNI_PID=$!
echo "OmniRoute started (PID: $OMNI_PID)"
sleep 3

for i in {1..10}; do
  curl -sf http://127.0.0.1:20128/health && break
  echo "Waiting for OmniRoute... ($i)"
  sleep 2
done

# 2. LLM Proxy
python3 llm_proxy.py &
LLM_PID=$!
echo "LLM Proxy started (PID: $LLM_PID)"
sleep 2

for i in {1..10}; do
  curl -sf http://127.0.0.1:4000/health && break
  echo "Waiting for LLM proxy... ($i)"
  sleep 2
done

# 3. Metalogos
PORT=10001 mlog serve app.mlog &
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

# 4. Reverse Proxy
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

# 5. OmniRoute Watchdog
while true; do
  if ! curl -sf http://127.0.0.1:20128/health > /dev/null 2>&1; then
    echo "OmniRoute died, restarting..."
    omniroute serve --port 20128 --no-open &
  fi
  sleep 30
done &
WATCHDOG_PID=$!
echo "OmniRoute watchdog started (PID: $WATCHDOG_PID)"

wait $OMNI_PID $LLM_PID $MLOG_PID $PROXY_PID
