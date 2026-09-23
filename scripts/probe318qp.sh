#!/bin/bash
# №318: проба auth /osp/analyze (query_param hash-compare) на реальном mlog-021.
# Секрет с '+' — кейс владельца из №423/№425; selfcheck — конвейер lz.mlog.
# Матрица в probe318qp.mlog. Ожидания:
#   A: raw+'=403 / %2B=200 / wrong=403 / none=403 / selfcheck=200 selfcheck-match
#   B: selfcheck=200 selfcheck-match ('+' и пробел)
#   C: 403 empty-env; D: 500 ENV_NOT_PERMITTED (матрица №423)
set -u
cd "$(dirname "$0")/.."

[ -x bin/mlog-021 ] || chmod +x bin/mlog-021
PROBE=scripts/probe318qp.mlog
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
  echo "$PID" > "${OUT}/pid_${LABEL}"
}

echo "=== (A) env='Shkod+probe42' (литеральный '+') ==="
run_case A CRON_SECRET='Shkod+probe42' METALOGOS_ENV_ALLOWLIST="CRON_SECRET" METALOGOS_HTTP_ALLOW_PRIVATE=1
H=$(printf '%s' 'Shkod+probe42' | sha256sum | cut -c1-16)
echo -n "  raw '+'           : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp?secret=Shkod+probe42"; echo
echo -n "  %2B-энкодинг      : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp?secret=Shkod%2Bprobe42"; echo
echo -n "  redact-hash (hex) : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp?secret=%5BHASH%3A${H}%5D%20hex"; echo
echo -n "  неверный секрет   : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp?secret=WRONG"; echo
echo -n "  без секрета       : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp"; echo
echo -n "  selfcheck (mlang) : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/selfcheck"; echo

echo "=== (B) env='Shkod probe+42' ('+' и пробел, chained-replace) ==="
run_case B CRON_SECRET='Shkod probe+42' METALOGOS_ENV_ALLOWLIST="CRON_SECRET" METALOGOS_HTTP_ALLOW_PRIVATE=1
echo -n "  selfcheck (mlang) : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/selfcheck"; echo

echo "=== (C) env unset, allowlist задан ==="
run_case C METALOGOS_ENV_ALLOWLIST="CRON_SECRET" METALOGOS_HTTP_ALLOW_PRIVATE=1
echo -n "  любой секрет      : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp?secret=x"; echo

echo "=== (D) env unset, allowlist не задан ==="
run_case D
echo -n "  любой секрет      : "; curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/qp?secret=x"; echo

kill "$(cat "${OUT}/pid_A" 2>/dev/null)" 2>/dev/null
pkill -f "mlog-021 serve ${PROBE}" 2>/dev/null
echo "OUT dir: ${OUT}"
