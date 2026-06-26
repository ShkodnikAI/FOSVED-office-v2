#!/bin/bash
echo "=== Fosved Office v2 Starting ==="

# Log source file checksums
echo "--- Source checksums ---"
echo "app.mlog:       $(md5sum app.mlog 2>/dev/null | cut -d' ' -f1)"
echo "dept/yana.mlog: $(md5sum dept/yana.mlog 2>/dev/null | cut -d' ' -f1)"
echo "llm_proxy.py:   $(md5sum llm_proxy.py 2>/dev/null | cut -d' ' -f1)"

# Verify critical files exist
echo ""
MISSING=0
for f in app.mlog llm_proxy.py reverse_proxy.py dept/miniapp.mlog dept/context.mlog library/yana.md report_css.txt config/priority_provider.txt config/priority_model.txt; do
  if [ ! -f "$f" ]; then
    echo "!!! MISSING: $f !!!"
    MISSING=1
  fi
done
if [ $MISSING -eq 0 ]; then
  echo "All critical files present ✓"
fi

# Verify yana.mlog clean
echo ""
if grep -q "КРИТИЧЕСКОЕ ПРАВИЛО ФОРМАТА" dept/yana.mlog 2>/dev/null; then
  echo "!!! dept/yana.mlog has anti-format code !!!"
else
  echo "dept/yana.mlog: clean ✓"
fi

# Verify llm_proxy.py excludes yana from FORMAT_INSTRUCTION
if grep -q '_NO_FORMAT_DEPTS.*yana' llm_proxy.py 2>/dev/null; then
  echo "llm_proxy.py: yana excluded from FORMAT_INSTRUCTION ✓"
else
  echo "!!! llm_proxy.py missing _NO_FORMAT_DEPTS !!!"
fi

# Verify app.mlog HandleYana uses /tg-send
if grep -q 'tg-send' app.mlog 2>/dev/null; then
  echo "app.mlog: HandleYana uses /tg-send ✓"
else
  echo "!!! app.mlog missing /tg-send !!!"
fi

echo ""
echo "--- Starting services ---"

# 1. LLM Proxy (port 4000)
python3 llm_proxy.py &
LLM_PID=$!
echo "LLM Proxy started (PID: $LLM_PID)"
sleep 2

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

for i in {1..10}; do
  curl -sf http://127.0.0.1:10001/ && break
  echo "Waiting for Metalogos... ($i)"
  sleep 2
done

echo ""
echo "--- Version check ---"
curl -sf http://127.0.0.1:10001/version 2>/dev/null || echo "version endpoint not available"

# 3. Reverse Proxy (port $PORT, default 10000)
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID