#!/bin/bash
echo "=== Fosved Office v2 Starting ==="

# Show build SHA to verify deploy
echo "--- Build ---"
if [ -f /office/build_sha.txt ]; then
  cat /office/build_sha.txt
else
  echo "WARNING: no build_sha.txt — old image cached!"
fi

# Log source file checksums to verify deploy picked up new code
echo ""
echo "--- Source checksums ---"
echo "app.mlog:       $(md5sum app.mlog 2>/dev/null | cut -d' ' -f1)"
echo "dept/yana.mlog: $(md5sum dept/yana.mlog 2>/dev/null | cut -d' ' -f1)"
echo "llm_proxy.py:   $(md5sum llm_proxy.py 2>/dev/null | cut -d' ' -f1)"
echo "miniapp.mlog:   $(md5sum dept/miniapp.mlog 2>/dev/null | cut -d' ' -f1)"

# Verify yana.mlog does NOT contain anti-format code
echo ""
if grep -q "КРИТИЧЕСКОЕ ПРАВИЛО ФОРМАТА" dept/yana.mlog 2>/dev/null; then
  echo "!!! WARNING: dept/yana.mlog still has anti-format code !!!"
else
  echo "dept/yana.mlog: clean (no anti-format)"
fi

# Verify llm_proxy.py has _NO_FORMAT_DEPTS
echo ""
if grep -q '_NO_FORMAT_DEPTS.*yana' llm_proxy.py 2>/dev/null; then
  echo "llm_proxy.py: yana excluded from FORMAT_INSTRUCTION ✓"
else
  echo "!!! WARNING: llm_proxy.py missing _NO_FORMAT_DEPTS yana exclusion !!!"
fi

# Verify app.mlog HandleYana uses /tts and /tg-send (not SendReport)
echo ""
if grep -q 'tg-send' app.mlog 2>/dev/null; then
  echo "app.mlog: HandleYana uses /tg-send ✓"
else
  echo "!!! WARNING: app.mlog HandleYana missing /tg-send !!!"
fi

echo ""
echo "--- Starting services ---"

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
echo ""
echo "--- Version check ---"
curl -sf http://127.0.0.1:10001/version 2>/dev/null || echo "version endpoint not available"

# 3. Reverse Proxy (port $PORT, default 10000)
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID