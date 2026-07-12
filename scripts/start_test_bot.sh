#!/usr/bin/env bash
# L4.18 Block B — start SECOND mlog serve process for dual-test
# Port 10002, test bot token, SAME DB as production
set -euo pipefail

cd /home/z/my-project/FOSVED-office-v2

# Test bot token MUST be in env
if [ -z "${TEST_TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "ERROR: TEST_TELEGRAM_BOT_TOKEN not set. Aborting."
  exit 1
fi

# Kill any previous test process on 10002
PREV_PID=$(lsof -ti :10002 2>/dev/null || true)
if [ -n "$PREV_PID" ]; then
  echo "Killing previous test process on port 10002 (PID: $PREV_PID)..."
  kill "$PREV_PID" 2>/dev/null || true
  sleep 1
fi

# Generate app_test.mlog if not exists or app.mlog is newer
if [ ! -f app_test.mlog ] || [ app.mlog -nt app_test.mlog ]; then
  echo "Generating app_test.mlog from app.mlog (port 10001 -> 10002)..."
  sed 's/^  port: 10001$/  port: 10002/' app.mlog > app_test.mlog
fi

# Override TELEGRAM_BOT_TOKEN to point at TEST bot for this process
export TELEGRAM_BOT_TOKEN="$TEST_TELEGRAM_BOT_TOKEN"

# Use SAME database as production (for comparable SQL aggregates)
export DATABASE_URL="file:/home/z/my-project/FOSVED-office-v2/data/fosved.db"

echo "Starting mlog serve on port 10002 (test bot)..."
echo "  TELEGRAM_BOT_TOKEN: ${TEST_TELEGRAM_BOT_TOKEN:0:10}..."
echo "  DATABASE_URL: $DATABASE_URL"
echo "  Port: 10002"

nohup ./bin/mlog serve app_test.mlog > /tmp/mlog_test_10002.log 2>&1 &
TEST_PID=$!
echo "PID: $TEST_PID"

# Wait and verify
sleep 2
if kill -0 "$TEST_PID" 2>/dev/null; then
  echo "OK: Test process running (PID $TEST_PID)"
  echo ""
  echo "Next step: set webhook for test bot:"
  echo "  curl 'https://api.telegram.org/bot${TEST_TELEGRAM_BOT_TOKEN}/setWebhook?url=https://YOUR_DOMAIN:10002/webhook/'"
else
  echo "FAIL: Process died. Check /tmp/mlog_test_10002.log"
  exit 1
fi