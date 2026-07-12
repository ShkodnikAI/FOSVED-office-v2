#!/usr/bin/env bash
# L4.18 Block B — 10-point dual test via curl-emulation
#
# Sends emulated Telegram Update JSON to localhost:10002/webhook/telegram
# Each request triggers real mlog processing -> real Telegram API call
# Owner sees responses in test bot chat (Telegram) and compares visually.
#
# Prerequisite: scripts/start_test_bot.sh completed successfully
#   /tmp/mlog_test_chat_id.txt contains the owner's chat_id for test bot
#
set -euo pipefail

cd /home/z/my-project/FOSVED-office-v2

WEBHOOK_URL="http://localhost:10002/webhook/telegram"
LOG_FILE="/tmp/mlog_dual_test_results.txt"
REPORT_FILE="test_results_dual.md"

if [ ! -f /tmp/mlog_test_chat_id.txt ]; then
  echo "ERROR: /tmp/mlog_test_chat_id.txt not found. Run start_test_bot.sh first."
  exit 1
fi

CHAT_ID=$(cat /tmp/mlog_test_chat_id.txt)
OWNER_ID="${OWNER_TELEGRAM_ID:?OWNER_TELEGRAM_ID not set}"

echo "=== L4.18 Block B — Dual Test (10 points) ==="
echo "Chat ID: $CHAT_ID"
echo "Webhook: $WEBHOOK_URL"
echo ""

# ── Helper: send emulated Telegram Update and log result ───────
send_update() {
  local test_num="$1"
  local description="$2"
  local json_payload="$3"

  echo "-------------------------------------------"
  echo "TEST $test_num: $description"
  echo "Sending to $WEBHOOK_URL ..."
  echo ""

  local start_ts
  start_ts=$(date +%s%N)

  local http_code
  local http_body
  http_body=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d "$json_payload" \
    "$WEBHOOK_URL" 2>&1) || http_body="CURL_FAIL"

  local end_ts
  end_ts=$(date +%s%N)
  local elapsed_ms=$(( (end_ts - start_ts) / 1000000 ))

  echo "  HTTP status: $http_body"
  echo "  Time: ${elapsed_ms}ms"
  echo "  Payload: ${json_payload:0:120}..."
  echo ""
  echo "  >>> Check Telegram (test bot chat) for the response <<<"
  echo ""

  # Append to log
  echo "TEST $test_num: $description" >> "$LOG_FILE"
  echo "  HTTP: $http_body, Time: ${elapsed_ms}ms" >> "$LOG_FILE"
  echo "  Payload: $json_payload" >> "$LOG_FILE"
  echo "  Response: SEE TELEGRAM (visual check required)" >> "$LOG_FILE"
  echo "" >> "$LOG_FILE"

  # Pause between tests so owner can read the response
  echo "  Waiting 5s before next test..."
  sleep 5
}

# ── Build base Update JSON structure ───────────────────────────
# This matches Telegram's Update format that the webhook handler expects:
#   data.message.chat.id  -> chat_id (extracted by handler)
#   data.message.from.id  -> user_id (owner check)
#   data.message.text     -> text (command/message content)

# Clear previous log
> "$LOG_FILE"

echo "# L4.18 Block B — Dual Test Results" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "**Date:** $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$REPORT_FILE"
echo "**Variant:** 2 (separate process, port 10002)" >> "$REPORT_FILE"
echo "**Production code diff since Block A:** 0 lines" >> "$REPORT_FILE"
echo "**DB:** shared (fosved.db)" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "---" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# ══════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  OWNER: Open test bot chat in Telegram NOW.     ║"
echo "║  Each response will appear there for comparison. ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
sleep 3

# ── TEST 1: /start ────────────────────────────────────────────
send_update "1" "/start — greeting message" \
  "{\"update_id\":1,\"message\":{\"message_id\":1,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/start\"}}"

# ── TEST 2: /status ───────────────────────────────────────────
send_update "2" "/status — department list + voice/archive state" \
  "{\"update_id\":2,\"message\":{\"message_id\":2,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/status\"}}"

# ── TEST 3: Regular message (routed to yana by default) ───────
send_update "3" "Plain message — auto-routed to yana dept (check MarkdownV2: bold/italic)" \
  "{\"update_id\":3,\"message\":{\"message_id\":3,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"Расскажи кратко про макроэкономическую ситуацию в РФ на сегодня\"}}"

# ── TEST 4: Explicit /yana message (MarkdownV2 formatting) ────
send_update "4" "/yana — explicit yana command (check bold/italic in MarkdownV2)" \
  "{\"update_id\":4,\"message\":{\"message_id\":4,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/yana Сделай краткий обзор ключевых рисков для портфеля на ближайший месяц\"}}"

# ── TEST 5: /cost ─────────────────────────────────────────────
send_update "5" "/cost — LLM usage statistics (SQL aggregate, comparable with production)" \
  "{\"update_id\":5,\"message\":{\"message_id\":5,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/cost\"}}"

# ── TEST 6: /good ─────────────────────────────────────────────
send_update "6" "/good — positive feedback learning" \
  "{\"update_id\":6,\"message\":{\"message_id\":6,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/good\"}}"

# ── TEST 7: Voice message (STT via Python proxy) ──────────────
# NOTE: This will try to call http://127.0.0.1:4000/stt — if STT proxy
# is running, it will transcribe; if not, mlog returns an error message.
# Either way, the TEST is: does the error path work correctly?
send_update "7" "Voice message — STT via Python proxy on port 4000" \
  "{\"update_id\":7,\"message\":{\"message_id\":7,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"voice\":{\"duration\":3,\"file_id\":\"FAKE_VOICE_FILE_ID_FOR_TEST\",\"mime_type\":\"audio/ogg\"}}}"

# ── TEST 8: Long response trigger (>800 chars -> miniapp card) ─
# Use /osp with a broad query to trigger a long analytical response
send_update "8" "/osp — long analytical response (check if miniapp card appears for >800 chars)" \
  "{\"update_id\":8,\"message\":{\"message_id\":8,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/osp Проведи полный анализ последствий скачков цен на нефть для российской экономики в контексте бюджетного правила\"}}"

# ── TEST 9: /admin subcommand ─────────────────────────────────
send_update "9" "/admin report — night cycle report (admin dept)" \
  "{\"update_id\":9,\"message\":{\"message_id\":9,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/admin report\"}}"

# ── TEST 10: /rate 8 ──────────────────────────────────────────
send_update "10" "/rate 8 — rating feedback" \
  "{\"update_id\":10,\"message\":{\"message_id\":10,\"from\":{\"id\":$OWNER_ID,\"is_bot\":false,\"first_name\":\"Test\"},\"chat\":{\"id\":$CHAT_ID,\"type\":\"private\"},\"date\":$(date +%s),\"text\":\"/rate 8\"}}"

# ══════════════════════════════════════════════════════════════
echo ""
echo "=== All 10 tests sent ==="
echo ""
echo "Full log: $LOG_FILE"
echo "Mlog process log: /tmp/mlog_test_10002.log"
echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  OWNER: Check test bot chat in Telegram.            ║"
echo "║  Compare each response with production bot behavior. ║"
echo "║  Key checks:                                         ║"
echo "║    - Test 3/4: Bold/italic rendered (MarkdownV2)?    ║"
echo "║    - Test 5: /cost numbers match production?          ║"
echo "║    - Test 8: Miniapp card for long response?          ║"
echo "║    - Test 7: Voice error or transcription?            ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "After visual review, owner should report results back to the agent."
echo "Agent will fill test_results_dual.md with expected vs actual per point."