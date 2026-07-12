#!/usr/bin/env bash
# L4.18 Block B (Variant 2) — dual-test infrastructure
#
# Architecture:
#   - Second mlog serve on port 10002 with TEST_TELEGRAM_BOT_TOKEN
#   - NO real Telegram webhook (Render doesn't expose port 10002 externally)
#   - Input: curl-emulated Telegram Update JSON to localhost:10002/webhook/telegram
#   - Output: real Telegram API call from mlog -> test bot -> owner sees in Telegram
#   - Owner visually compares test bot response vs production bot response
#
# Usage:
#   Step 1: Owner adds TEST_TELEGRAM_BOT_TOKEN to Render env
#   Step 2: Owner opens test bot in Telegram, sends /start manually
#   Step 3: Run this script — it auto-detects chat_id via getUpdates
#   Step 4: Run scripts/run_dual_test.sh for 10-point test
#   Step 5: Owner checks Telegram (test bot chat) and compares visually
#
set -euo pipefail

cd /home/z/my-project/FOSVED-office-v2

# ── Preconditions ──────────────────────────────────────────────
if [ -z "${TEST_TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "ERROR: TEST_TELEGRAM_BOT_TOKEN not set in environment."
  echo "Add it to Render env, then re-run."
  exit 1
fi

if [ -z "${OWNER_TELEGRAM_ID:-}" ]; then
  echo "ERROR: OWNER_TELEGRAM_ID not set. Cannot pass owner check in mlog."
  exit 1
fi

echo "=== L4.18 Block B — Starting test bot process ==="
echo "TEST_TELEGRAM_BOT_TOKEN: ${TEST_TELEGRAM_BOT_TOKEN:0:10}..."
echo "OWNER_TELEGRAM_ID: $OWNER_TELEGRAM_ID"

# ── Step 1: Get owner's chat_id for test bot via getUpdates ────
echo ""
echo "--- Step 1: Detecting chat_id via getUpdates ---"

GETUPDATES_RESP=$(curl -s "https://api.telegram.org/bot${TEST_TELEGRAM_BOT_TOKEN}/getUpdates?offset=-1&timeout=0")
CHAT_ID=$(echo "$GETUPDATES_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data.get('ok'):
    results = data.get('result', [])
    if results:
        msg = results[-1].get('message', {})
        chat_id = msg.get('chat', {}).get('id')
        from_id = msg.get('from', {}).get('id')
        text = msg.get('text', '')
        print(f'{chat_id}|{from_id}|{text}')
        sys.exit(0)
print('NO_UPDATES')
" 2>/dev/null || echo "PARSE_ERROR")

if [[ "$CHAT_ID" == "NO_UPDATES" ]]; then
  echo "WARNING: No pending updates for test bot."
  echo "Using OWNER_TELEGRAM_ID as chat_id (private chat = user_id)."
  CHAT_ID="$OWNER_TELEGRAM_ID"
  TEST_FROM_ID="$OWNER_TELEGRAM_ID"
elif [[ "$CHAT_ID" == "PARSE_ERROR" ]]; then
  echo "WARNING: Failed to parse getUpdates response."
  echo "Using OWNER_TELEGRAM_ID as chat_id (private chat = user_id)."
  CHAT_ID="$OWNER_TELEGRAM_ID"
  TEST_FROM_ID="$OWNER_TELEGRAM_ID"
else
  TEST_CHAT_ID=$(echo "$CHAT_ID" | cut -d'|' -f1)
  TEST_FROM_ID=$(echo "$CHAT_ID" | cut -d'|' -f2)
  CHAT_ID="$TEST_CHAT_ID"
fi

echo "  chat_id for test bot: $CHAT_ID"
echo "  from.id: $TEST_FROM_ID"

if [ "$TEST_FROM_ID" != "$OWNER_TELEGRAM_ID" ]; then
  echo "WARNING: from.id ($TEST_FROM_ID) != OWNER_TELEGRAM_ID ($OWNER_TELEGRAM_ID)"
  echo "The test bot's owner check in mlog will REJECT this user."
fi

# ── Step 2: Kill previous test process on 10002 ────────────────
PREV_PID=$(lsof -ti :10002 2>/dev/null || true)
if [ -n "$PREV_PID" ]; then
  echo ""
  echo "--- Killing previous test process (PID: $PREV_PID) ---"
  kill "$PREV_PID" 2>/dev/null || true
  sleep 1
fi

# ── Step 3: Generate app_test.mlog ────────────────────────────
if [ ! -f app_test.mlog ] || [ app.mlog -nt app_test.mlog ]; then
  echo ""
  echo "--- Generating app_test.mlog (port 10001 -> 10002) ---"
  sed 's/^  port: 10001$/  port: 10002/' app.mlog > app_test.mlog
fi

# ── Step 4: Start second mlog serve ────────────────────────────
echo ""
echo "--- Starting mlog serve on port 10002 ---"

export TELEGRAM_BOT_TOKEN="$TEST_TELEGRAM_BOT_TOKEN"
export DATABASE_URL="file:/home/z/my-project/FOSVED-office-v2/data/fosved.db"
export OWNER_TELEGRAM_ID="$OWNER_TELEGRAM_ID"

nohup ./bin/mlog serve app_test.mlog > /tmp/mlog_test_10002.log 2>&1 &
TEST_PID=$!

sleep 3
if ! kill -0 "$TEST_PID" 2>/dev/null; then
  echo "FAIL: Test process died immediately. Log:"
  cat /tmp/mlog_test_10002.log
  exit 1
fi

echo "  PID: $TEST_PID"
echo "  Port: 10002"
echo "  DB: $DATABASE_URL"

# ── Step 5: Verify health ─────────────────────────────────────
HEALTH=$(curl -s http://localhost:10002/health 2>/dev/null || echo "UNREACHABLE")
echo "  Health check: $HEALTH"

if [[ "$HEALTH" != *"ok"* ]]; then
  echo "FAIL: Health check failed. Log:"
  tail -20 /tmp/mlog_test_10002.log
  exit 1
fi

# ── Step 6: Save chat_id for test runner ───────────────────────
echo "$CHAT_ID" > /tmp/mlog_test_chat_id.txt

echo ""
echo "=== Test bot process READY ==="
echo "  PID: $TEST_PID"
echo "  Log: /tmp/mlog_test_10002.log"
echo "  Chat ID: $CHAT_ID (saved to /tmp/mlog_test_chat_id.txt)"
echo ""
echo "Next: run scripts/run_dual_test.sh to execute 10-point test."
echo "Owner should have test bot chat open in Telegram to see responses."