#!/bin/bash
echo "=== Fosved Office v2 Starting ==="

# Log source file checksums to verify deploy picked up new code
echo "--- Source checksums ---"
echo "app.mlog:       $(md5sum app.mlog 2>/dev/null | cut -d' ' -f1)"
echo "dept/yana.mlog: $(md5sum dept/yana.mlog 2>/dev/null | cut -d' ' -f1)"
echo "llm_proxy.py:   $(md5sum llm_proxy.py 2>/dev/null | cut -d' ' -f1)"
echo "miniapp.mlog:   $(md5sum dept/miniapp.mlog 2>/dev/null | cut -d' ' -f1)"

# Verify yana.mlog does NOT contain anti-format code
if grep -q "КРИТИЧЕСКОЕ ПРАВИЛО ФОРМАТА" dept/yana.mlog 2>/dev/null; then
  echo "!!! WARNING: dept/yana.mlog still has anti-format code !!!"
else
  echo "dept/yana.mlog: clean (no anti-format)"
fi

# 0. Seed memory on first deploy
if [ ! -f data/memory.db ]; then
    echo "--- Seeding FosvedMemory ---"
    python3 scripts/seed_memory.py data/memory.db
fi

# 1. LLM Proxy (port 4000)
python3 llm_proxy.py &
LLM_PID=$!
echo "LLM Proxy started (PID: $LLM_PID)"
sleep 2

# Healthcheck proxy
for i in {1..10}; do
  curl -sf http://127.0.0.1:4000/health && break
  echo "Waiting for LLM proxy... ($i)"
  sleep 2
done

# 2. Metalogos (port 10001)
PORT=10001 mlog serve app.mlog &
MLOG_PID=$!
echo "Metalogos started (PID: $MLOG_PID)"
sleep 3

# Healthcheck mlog
for i in {1..10}; do
  curl -sf http://127.0.0.1:10001/ && break
  echo "Waiting for Metalogos... ($i)"
  sleep 2
done

# Verify version endpoint
echo "--- Version check ---"
curl -sf http://127.0.0.1:10001/version 2>/dev/null || echo "version endpoint not available"

# 3. Reverse Proxy (port $PORT, default 10000)
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID