#!/bin/bash
# №349 Блок B.3/B.4: реальный подъём полного стека офиса на заданном бинаре.
# Песочница = git archive HEAD (чистые трекнутые файлы), sqlite в tmp,
# без реальных ключей. Suite: /health, /version, webhook /status, /osp/analyze
# (ping + боевой запрос), /cron/control, /schedules/list.
# Использование: serve_stack.sh <mlog-binary> <tag>
set -u
BIN="$1"; TAG="$2"
BASE=/home/z/my-project/n349-serve/$TAG
RES=/home/z/my-project/n349-results
mkdir -p "$BASE"

cd /home/z/my-project/FOSVED-office-v2
git archive HEAD | tar -x -C "$BASE"
cd "$BASE"
echo "n349-local-verify" > VERSION
mkdir -p data

export DATABASE_URL="sqlite:$BASE/data/fosved.db"
export DATABASE_PATH="$BASE/data"
export CRON_SECRET="n349-test-secret"
export OWNER_TELEGRAM_ID="0"
export TELEGRAM_BOT_TOKEN=""
export INTERNAL_API_TOKEN=""
export METALOGOS_SERVE_BACKEND="interpreter"
export METALOGOS_SERVE_ALLOW_EXEC="1"
export METALOGOS_HTTP_ALLOW_PRIVATE="1"
export METALOGOS_ENV_ALLOWLIST="CEREBRAS_API_KEY,CRON_SECRET,DATABASE_URL,DEEPSEEK_API_KEY,FNP_CUSTOMER,FNP_GOAL,FNP_NAME,FNP_SLUG,FNP_TYPE,FORGE_GITHUB_OWNER,FORGE_REPOS_DIR,FORGE_RUN_ENABLED,FORGE_RUN_VLIMIT_KB,GROQ_API_KEY,INTERNAL_API_TOKEN,KIMI_API_KEY,LOCKDOWN_PASSWORD,METALOGOS_EXEC_TIMEOUT_SECS,OWNER_TELEGRAM_ID,RENDER_URL,SAKANA_API_KEY,SHOP_ENABLED,TAVILY_API_KEY,TELEGRAM_ARCHIVE_CHANNEL_ID,TELEGRAM_BOT_TOKEN,ZAI_API_KEY"
export TG_MONITOR_ENABLED="0"
export SHOP_ENABLED="0"
export MLOG_BIN="$BIN"
export PORT="10001"

OUT=$RES/serve_$TAG.txt
: > "$OUT"

# ── файл подачи: как entrypoint №427 — аугментированная копия с мостом ──
AUG="/tmp/app_serve_$TAG.mlog"
if grep -q "^profile legacy" app.mlog; then
  cp app.mlog "$AUG"
else
  { printf '%s\n' "profile legacy { egress: permissive_with_audit }"; cat app.mlog; } > "$AUG"
fi
"$BIN" audit "$AUG" >/dev/null 2>&1 && PRC=0 || PRC=$?
if [ "$PRC" != "0" ] && [ "$PRC" != "2" ]; then AUG="app.mlog"; fi
echo "[stack] bin=$BIN serve_file=$AUG (probe rc=$PRC)" >> "$OUT"

# ── LLM proxy ──
python3 llm_proxy.py > /tmp/llm_$TAG.log 2>&1 &
LLM_PID=$!
for i in 1 2 3 4 5; do sleep 1; curl -sf http://127.0.0.1:4000/health >/dev/null 2>&1 && break; done

# ── Metalogos serve ──
"$BIN" serve "$AUG" > /tmp/mlog_$TAG.log 2>&1 &
MLOG_PID=$!
MH=""
for i in $(seq 1 20); do
  sleep 1
  MH=$(curl -s --max-time 5 "http://127.0.0.1:10001/health" 2>/dev/null)
  [ -n "$MH" ] && break
done
echo "boot /health: ${MH:-<no-answer>}" >> "$OUT"

# ── reverse proxy (:10000 → :10001); PORT задан явно — иначе подхватит 10001 ──
PORT=10000 python3 reverse_proxy.py > /tmp/rp_$TAG.log 2>&1 &
RP_PID=$!
sleep 2

suite() {
  echo "--- B.3: /health via reverse proxy :10000 ---" >> "$OUT"
  curl -s --max-time 30 "http://127.0.0.1:10000/health" >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- B.3: /health direct :10001 ---" >> "$OUT"
  curl -s --max-time 30 "http://127.0.0.1:10001/health" >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- /version (INTERNAL_API_TOKEN empty → ok) ---" >> "$OUT"
  curl -s --max-time 30 "http://127.0.0.1:10001/version" >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- B.4: webhook /status (HandleYana) ---" >> "$OUT"
  curl -s --max-time 30 -X POST "http://127.0.0.1:10001/webhook/telegram" \
    -H "Content-Type: application/json" \
    -d '{"update_id":-1,"message":{"message_id":-1,"chat":{"id":0},"text":"/status","from":{"id":0}}}' >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- B.4: /osp/analyze ping (детерминированный) ---" >> "$OUT"
  curl -s --max-time 30 -X POST "http://127.0.0.1:10001/osp/analyze?secret=n349-test-secret" \
    -H "Content-Type: application/json" \
    -d '{"query":"ping"}' >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- B.4: /osp/analyze боевой (LLM недоступен → graceful) ---" >> "$OUT"
  curl -s --max-time 60 -X POST "http://127.0.0.1:10001/osp/analyze?secret=n349-test-secret" \
    -H "Content-Type: application/json" \
    -d '{"query":"FRED: ставка ФРС и доходности","chat_id":"0"}' >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- B.4: webhook текст-запрос Эксперту (LLM недоступен → graceful) ---" >> "$OUT"
  curl -s --max-time 60 -X POST "http://127.0.0.1:10001/webhook/telegram" \
    -H "Content-Type: application/json" \
    -d '{"update_id":-2,"message":{"message_id":-2,"chat":{"id":0},"text":"эксперт: анализ рынка дронов","from":{"id":0}}}' >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- B.4: webhook /lz скан (детерминированная часть) ---" >> "$OUT"
  curl -s --max-time 60 -X POST "http://127.0.0.1:10001/webhook/telegram" \
    -H "Content-Type: application/json" \
    -d '{"update_id":-3,"message":{"message_id":-3,"chat":{"id":0},"text":"/lz","from":{"id":0}}}' >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- /cron/control?secret= (слот контрольного чека) ---" >> "$OUT"
  curl -s --max-time 60 "http://127.0.0.1:10001/cron/control?secret=n349-test-secret" >> "$OUT" 2>&1; echo >> "$OUT"
  echo "--- /schedules/list?secret= (нативные расписания) ---" >> "$OUT"
  curl -s --max-time 30 "http://127.0.0.1:10001/schedules/list?secret=n349-test-secret" >> "$OUT" 2>&1; echo >> "$OUT"
}

suite

echo "=== serve log: ошибки хендлеров (подсчёт) ===" >> "$OUT"
grep -c "Handler error" /tmp/mlog_$TAG.log >> "$OUT" 2>&1 || echo "0" >> "$OUT"
echo "=== serve log: уникальные классы ошибок ===" >> "$OUT"
grep -i "handler error\|\[try\] caught\|panic\|ERROR" /tmp/mlog_$TAG.log | sed 's/[0-9]\+/N/g' | sort -u | head -15 >> "$OUT"

kill $LLM_PID $MLOG_PID $RP_PID 2>/dev/null
wait $MLOG_PID 2>/dev/null
echo "[stack] done, report: $OUT"
