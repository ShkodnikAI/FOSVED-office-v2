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

# Check mlog binary works
echo "--- mlog binary check ---"
which mlog 2>/dev/null && echo "mlog found in PATH" || echo "mlog NOT in PATH"
ls -la /usr/local/bin/mlog 2>/dev/null
mlog --version 2>&1 || echo "mlog --version failed"

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

# 2. Metalogos (port 10001) — with error capture
echo "--- Starting mlog serve ---"
PORT=10001 mlog serve app.mlog > /tmp/mlog_stdout.log 2> /tmp/mlog_stderr.log &
MLOG_PID=$!
echo "Metalogos started (PID: $MLOG_PID)"
sleep 3

# Check if mlog is still running
if kill -0 $MLOG_PID 2>/dev/null; then
  echo "mlog process is alive"
else
  echo "!!! mlog process DIED !!!"
  echo "--- mlog stderr ---"
  cat /tmp/mlog_stderr.log 2>/dev/null
  echo "--- mlog stdout ---"
  cat /tmp/mlog_stdout.log 2>/dev/null
fi

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

# Keep mlog logs visible
tail -f /tmp/mlog_stderr.log /tmp/mlog_stdout.log &

wait $LLM_PID $MLOG_PID $PROXY_PID