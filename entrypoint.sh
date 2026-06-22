#!/bin/bash
echo "Starting Fosved Office v2..."

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

# 3. Reverse Proxy (port $PORT, default 10000)
python3 reverse_proxy.py &
PROXY_PID=$!
echo "Reverse proxy started (PID: $PROXY_PID)"

wait $LLM_PID $MLOG_PID $PROXY_PID
