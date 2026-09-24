#!/bin/bash
# №349 финальный smoke: probe318qp (№425 секрет-контракт) + schedules/bootstrap
# на новом бинаре 0.22 из дерева naryad-349/mlog-022.
set -u
BIN=/home/z/my-project/FOSVED-office-v2/bin/mlog
RES=/home/z/my-project/n349-results
cd "$RES" || exit 1

"$BIN" --version

# ── 1. probe318qp: секрет с '+' (литерал и %2B) + selfcheck ──────────
METALOGOS_HTTP_ALLOW_PRIVATE=1 METALOGOS_SERVE_ALLOW_ENV=1 METALOGOS_SERVE_BACKEND=interpreter \
  CRON_SECRET='Shkod+probe42' \
  "$BIN" serve scripts_probe318qp.mlog > /tmp/smoke_qp.log 2>&1 &
MS=$!
for i in 1 2 3 4 5 6 7 8; do
  sleep 1
  A=$(curl -s --max-time 5 "http://127.0.0.1:10001/" 2>/dev/null)
  [ -n "$A" ] && break
done
echo "qp-probe alive: $A"
echo "raw '+' (ожидаем 403 mismatch): $(curl -s --max-time 10 'http://127.0.0.1:10001/qp?secret=Shkod+probe42')"
echo "%2B (ожидаем 200 match):        $(curl -s --max-time 10 'http://127.0.0.1:10001/qp?secret=Shkod%2Bprobe42')"
echo "неверный (ожидаем 403):         $(curl -s --max-time 10 'http://127.0.0.1:10001/qp?secret=wrong')"
echo "selfcheck (ожидаем selfcheck-match): $(curl -s --max-time 15 'http://127.0.0.1:10001/selfcheck')"
kill $MS 2>/dev/null; wait $MS 2>/dev/null

# ── 2. schedules/bootstrap: нативный cron_add 4-арг+TZ на 0.22 ──────
SM=/home/z/my-project/n349-serve/boot022
mkdir -p "$SM" && cd /home/z/my-project/FOSVED-office-v2 && git archive HEAD | tar -x -C "$SM" && cd "$SM" && mkdir -p data
export DATABASE_URL="sqlite:$SM/data/fosved.db" DATABASE_PATH="$SM/data"
export CRON_SECRET="n349-test-secret" OWNER_TELEGRAM_ID="0" TELEGRAM_BOT_TOKEN="" INTERNAL_API_TOKEN=""
export METALOGOS_SERVE_BACKEND="interpreter" METALOGOS_SERVE_ALLOW_EXEC="1" METALOGOS_HTTP_ALLOW_PRIVATE="1" TG_MONITOR_ENABLED="0" SHOP_ENABLED="0" PORT="10001"
export METALOGOS_ENV_ALLOWLIST="CRON_SECRET,INTERNAL_API_TOKEN,OWNER_TELEGRAM_ID,DATABASE_URL,RENDER_URL,TELEGRAM_BOT_TOKEN,TELEGRAM_ARCHIVE_CHANNEL_ID,LOCKDOWN_PASSWORD,METALOGOS_EXEC_TIMEOUT_SECS,SHOP_ENABLED,TAVILY_API_KEY,KIMI_API_KEY,DEEPSEEK_API_KEY,ZAI_API_KEY,GROQ_API_KEY,CEREBRAS_API_KEY,SAKANA_API_KEY,FORGE_GITHUB_OWNER,FORGE_REPOS_DIR,FORGE_RUN_ENABLED,FORGE_RUN_VLIMIT_KB,FNP_CUSTOMER,FNP_GOAL,FNP_NAME,FNP_SLUG,FNP_TYPE"
# подача как в entrypoint №427: аугментированная копия с мостом №421
AUG="/tmp/app_smoke022.mlog"
{ printf '%s\n' "profile legacy { egress: permissive_with_audit }"; cat app.mlog; } > "$AUG"
"$BIN" serve "$AUG" > /tmp/smoke_boot.log 2>&1 &
MB=$!
for i in $(seq 1 20); do
  sleep 1
  H=$(curl -s --max-time 5 "http://127.0.0.1:10001/health" 2>/dev/null)
  [ -n "$H" ] && break
done
echo "boot /health: $H"
BOOT=$(curl -s --max-time 60 -G "http://127.0.0.1:10001/schedules/bootstrap" --data-urlencode "secret=n349-test-secret")
echo "bootstrap: ${BOOT:-<no-answer>}"
case "$BOOT" in
  *"FAIL("*) echo "BOOTSTRAP: FAILURES — LOUD" ;;
  "") echo "BOOTSTRAP: no answer" ;;
  *) echo "BOOTSTRAP: native schedules OK" ;;
esac
LIST=$(curl -s --max-time 15 "http://127.0.0.1:10001/schedules/list?secret=n349-test-secret")
echo "jobs in store after bootstrap: $(echo "$LIST" | /home/z/.venv/bin/python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('jobs',[])), 'jobs')" 2>/dev/null || echo parse-fail)"
kill $MB 2>/dev/null; wait $MB 2>/dev/null
echo "smoke done"
