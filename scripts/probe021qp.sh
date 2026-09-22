#!/bin/bash
# №425: проба декодирования query 0.21 на реальном бинаре + end-to-end
# /schedules/bootstrap с секретом, содержащим '+'.
# Ожидание: raw-вставка секрета с '+' -> 403 (декодирован в пробел);
# curl -G --data-urlencode -> 200 (кодирование сохраняет литеральный '+').
set -u
cd /home/z/my-project/FOSVED-office-v2

chmod +x bin/mlog-021 2>/dev/null
OUT=/tmp/probe021qp
mkdir -p "$OUT"
QP=/home/z/my-project/scripts/probe021qp.mlog

echo "=== Часть 1: echo-роут (декодирование query) ==="
pkill -f "mlog-021 serve ${QP}" 2>/dev/null; sleep 0.5
env METALOGOS_ENV_ALLOWLIST="CRON_SECRET" CRON_SECRET="x" PORT=10011 \
  ./bin/mlog-021 serve "$QP" > "$OUT/serve_echo.log" 2>&1 &
PID=$!
for i in $(seq 1 15); do
  curl -sf http://127.0.0.1:10011/ >/dev/null 2>&1 && break
  sleep 1
done
echo -n "  raw  '?secret=abc+def%20ghi' : "
curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10011/echo?secret=abc+def%20ghi"; echo
echo -n "  enc  -G --data-urlencode      : "
curl -s -w " [HTTP %{http_code}]" -G "http://127.0.0.1:10011/echo" --data-urlencode "secret=abc+def%20ghi"; echo
kill $PID 2>/dev/null

echo "=== Часть 2: /schedules/bootstrap на app.mlog, секрет с '+' ==="
# app.mlog пинчит порт 10001 в mlogserver-блоке (env PORT не переопределяет)
SECRET='Shkodnik+probe-vto'
pkill -f "mlog-021 serve app.mlog" 2>/dev/null; sleep 0.5
env METALOGOS_ENV_ALLOWLIST="CRON_SECRET" \
    METALOGOS_SERVE_BACKEND=interpreter \
    METALOGOS_SERVE_ALLOW_EXEC=1 \
    METALOGOS_HTTP_ALLOW_PRIVATE=1 \
    CRON_SECRET="${SECRET}" \
    DATABASE_URL="sqlite:${OUT}/probe.db" \
    DATABASE_PATH="${OUT}" \
  ./bin/mlog-021 serve app.mlog > "$OUT/serve_boot.log" 2>&1 &
PID=$!
UP=no
for i in $(seq 1 60); do
  curl -sf http://127.0.0.1:10001/ >/dev/null 2>&1 && { UP=yes; break; }
  sleep 1
done
echo "  server up: ${UP}"
echo -n "  raw   '?secret=Shkodnik+probe-vto' : "
curl -s -w " [HTTP %{http_code}]" "http://127.0.0.1:10001/schedules/bootstrap?secret=${SECRET}"; echo
echo -n "  enc   -G --data-urlencode          : "
curl -s -w " [HTTP %{http_code}]" -G "http://127.0.0.1:10001/schedules/bootstrap" --data-urlencode "secret=${SECRET}"; echo
kill $PID 2>/dev/null
pkill -f "mlog-021 serve app.mlog" 2>/dev/null
echo "ГОТОВО"
