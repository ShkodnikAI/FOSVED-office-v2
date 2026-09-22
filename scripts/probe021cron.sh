#!/bin/bash
# №423: проба auth-блока /cron/morning на реальном mlog-021 (Metalogos 0.21.0).
# Диагноз 403 из бут-лога 2026-09-22: какая именно ветка отдаёт отказ.
# Матрица: (A) env задан + CRON_SECRET в METALOGOS_ENV_ALLOWLIST,
#          (B) env задан, но CRON_SECRET НЕТ в allowlist (env-гейт №259),
#          (C) env не задан вовсе.
# Ожидания: A-верный=200 ok / A-неверный=403 mismatch / B=500 ENV_NOT_PERMITTED /
#           C=403 empty-env (см. docs/render-dashboard.md, §№423).
set -u
cd "$(dirname "$0")/.."

[ -x bin/mlog-021 ] || chmod +x bin/mlog-021
SECRET="probe-cron-secret-42"
PROBE=scripts/probe021cron.mlog
OUT=$(mktemp -d)

run_case () {
  local LABEL="$1"; shift
  pkill -f "mlog-021 serve ${PROBE}" 2>/dev/null; sleep 0.5
  env "$@" ./bin/mlog-021 serve "$PROBE" > "${OUT}/serve_${LABEL}.log" 2>&1 &
  local PID=$!
  for _ in $(seq 1 15); do
    curl -sf http://127.0.0.1:10001/ >/dev/null 2>&1 && break
    sleep 1
  done
  echo "=== ${LABEL} ==="
  echo -n "  верный секрет    : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/cron/morning?secret=${SECRET}"; echo
  echo -n "  неверный секрет  : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/cron/morning?secret=WRONG"; echo
  echo -n "  без секрета      : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/cron/morning"; echo
  kill $PID 2>/dev/null
}

run_case A_env_ok METALOGOS_ENV_ALLOWLIST="CRON_SECRET" CRON_SECRET="${SECRET}"
run_case B_allowlist_no_cron METALOGOS_ENV_ALLOWLIST="OTHER_VAR" CRON_SECRET="${SECRET}"
run_case C_env_unset METALOGOS_ENV_ALLOWLIST="CRON_SECRET"
pkill -f "mlog-021 serve ${PROBE}" 2>/dev/null
rm -rf "$OUT"
echo "ГОТОВО (ожидания — в шапке файла и docs/render-dashboard.md §№423)"
