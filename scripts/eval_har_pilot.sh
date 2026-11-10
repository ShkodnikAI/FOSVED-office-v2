#!/usr/bin/env bash
# eval_har_pilot.sh — #697 (REA-4): повторяемый рецепт «HAR-сессия своего
# веб-приложения → агентная среда для evals/QA без живого продакшна».
#
# Две ветки (наряд A.1 — пилот; контраст двух веток = главная находка):
#   demo   — самодостаточный контур: REST-демо приложение (scripts/eval_har_demo_app.py)
#            → HAR (eval_har_recorder.py) → rea environment-build →
#            rea environment-serve + MCP smoke. Ожидание: read ИЗ STATE,
#            write SERVED (create подтверждён позже прочитанным списком).
#   office — сессия стенда офиса (serve_stack.sh или его рецепт; base-URL
#            передаётся аргументом): /schedules list→create→list. Ожидание
#            (честное, из пилота 10.11.2026): read recorded (fields-differ),
#            write withheld (no-state-target) — RPC-поверхность офиса даёт
#            replay-only среду. Это ожидание-находка, НЕ провал прогона.
#
# Docker в песочнице может отсутствовать: agent-env run требует Docker,
# environment-serve — НЕ требует (README бандла: контейнер запускает ровно
# этот сервер). Прогон проверяет environment-serve; недоступность Docker
# фиксируется в выводе честной пометкой.
#
# Использование:
#   scripts/eval_har_pilot.sh demo                     # самодостаточный контур
#   scripts/eval_har_pilot.sh office http://127.0.0.1:10001   # живой стенд офиса
#
# Выход: 0 — гейты ветки пройдены; 1 — рецепт сломан (диагностика в выводе).
set -euo pipefail

MODE="${1:-demo}"
OFFICE_BASE="${2:-http://127.0.0.1:10001}"
REA_VERSION="6.8.0"   # пин обязателен (конвенция нарядов #694–#696: апгрейд — осознанным коммитом)
REPO=$(cd "$(dirname "$0")/.." && pwd)
W="/tmp/eval_har_pilot_${MODE}"
mkdir -p "$W"

# ── Гейты ─────────────────────────────────────────────────────────────────
command -v node >/dev/null 2>&1 || { echo "FAIL: node не установлен"; exit 1; }
node -e '
// Гейт версии node — требование README rea-agents (22.23.4+ / 24.22.1+ / 26.12.1+)
const v = process.versions.node.split(".").map(Number);
const req = [[22, 23, 4], [24, 22, 1], [26, 12, 1]];
const ge = (a, b) => a[0] > b[0] || (a[0] === b[0] &&
  (a[1] > b[1] || (a[1] === b[1] && a[2] >= b[2])));
const ok = v[0] > 26 || req.some(r => v[0] === r[0] && ge(v, r));
if (!ok) { console.error(`FAIL: node ${v.join(".")} ниже требуемого (README rea-agents)`); process.exit(1); }
'
command -v docker >/dev/null 2>&1 \
  && echo "[gate] docker: доступен — agent-env run возможен отдельным шагом (вне этого прогона)" \
  || echo "[gate] docker: НЕДОСТУПЕН — agent-env run пропущен (наряд #697: честная пометка, не провал); проверяем environment-serve — тот же сервер, что в контейнере"
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 не установлен"; exit 1; }

rea() { timeout 300 npx -y "rea-agents@${REA_VERSION}" "$@"; }

parse_coverage() {  # <build.json> — читает coverage в плоский вывод
  python3 - "$1" << 'PY'
import json, sys
d = json.load(open(sys.argv[1]))
cov = d.get("coverage", {})
reads = cov.get("reads", {})
writes = cov.get("writes", {})
print(f"reads.state={reads.get('state', 0)} reads.recorded={reads.get('recorded', 0)} "
      f"recorded_reasons={json.dumps(reads.get('recorded_reasons', {}), ensure_ascii=False)}")
print(f"writes.served={[w.get('tool') + ':' + str(w.get('effect')) for w in writes.get('served', [])]}")
for w in writes.get("withheld", []):
    print(f"writes.withheld={w.get('tool')} reason={w.get('reason')}")
PY
}

serve_and_smoke() {  # <bundle-envs-dir> <port> <extra smoke args...>
  local ENVDIR="$1"; shift
  local PORT="$1"; shift
  setsid npx -y "rea-agents@${REA_VERSION}" environment-serve \
    "$ENVDIR/manifest.json" --evidence "$ENVDIR/evidence.json" \
    --host 127.0.0.1 --port "$PORT" > "$W/serve.log" 2>&1 &
  local NPX_PID=$!
  local UP=0
  for i in $(seq 1 60); do
    sleep 1
    curl -s --max-time 2 -o /dev/null "http://127.0.0.1:${PORT}/.well-known/agent-env.json" 2>/dev/null && { UP=1; break; }
  done
  if [ "$UP" != "1" ]; then
    echo "FAIL: environment-serve не поднялся за 60с (лог: $W/serve.log)"
    kill -TERM -- -"$NPX_PID" 2>/dev/null || true
    return 1
  fi
  timeout 90 python3 "$REPO/scripts/eval_har_mcp_smoke.py" --url "http://127.0.0.1:${PORT}" "$@"
  local RC=$?
  kill -TERM -- -"$NPX_PID" 2>/dev/null || true
  sleep 2
  grep -o '"served": *[a-z]*' "$W/serve.log" | tail -1 | sed 's/^/[serve] state /' || true
  return $RC
}

echo "=== [1/4] HAR-запись сессии ($MODE) ==="
if [ "$MODE" = "demo" ]; then
  python3 "$REPO/scripts/eval_har_demo_app.py" --port 18766 > "$W/demo_app.log" 2>&1 &
  DEMO_PID=$!
  sleep 2
  python3 "$REPO/scripts/eval_har_recorder.py" \
    --scenario "$REPO/scripts/eval_har_scenario_demo.json" --out "$W/demo.har" || {
      kill "$DEMO_PID" 2>/dev/null || true; exit 1; }
  kill "$DEMO_PID" 2>/dev/null || true
  HAR="$W/demo.har"; ENVDIR="$W/env_demo/envs/rest-demo-items"; NAME="rest-demo-items"
elif [ "$MODE" = "office" ]; then
  curl -s --max-time 5 "$OFFICE_BASE/health" >/dev/null 2>&1 \
    || { echo "FAIL: стенд офиса не отвечает на $OFFICE_BASE/health — подними по рецепту serve_stack.sh"; exit 1; }
  python3 "$REPO/scripts/eval_har_recorder.py" \
    --scenario "$REPO/scripts/eval_har_scenario_schedules.json" --base "$OFFICE_BASE" \
    --out "$W/office.har" || exit 1
  HAR="$W/office.har"; ENVDIR="$W/env_office/envs/fosved-office-schedules"; NAME="fosved-office-schedules"
else
  echo "FAIL: неизвестный режим $MODE (demo|office)"; exit 1
fi

echo "=== [2/4] rea environment-build ($NAME) ==="
rm -rf "$W/env_${MODE}" 2>/dev/null || true
rea environment-build "$HAR" "$W/env_${MODE}" --name "$NAME" --json > "$W/build.json" 2>"$W/build.err"
python3 -c "
import json, sys
d = json.load(open('$W/build.json'))
assert d.get('status') == 'built', f\"status={d.get('status')} (см. $W/build.err)\"
print('built:', d['directory'], '| tool_count:', d.get('tool_count'))
"
echo "--- coverage ---"
parse_coverage "$W/build.json"

echo "=== [3/4] environment-serve + MCP smoke (Docker-free путь; в контейнере — тот же сервер) ==="
if [ "$MODE" = "demo" ]; then
  serve_and_smoke "$ENVDIR" 18767 \
    --call 'get_items' \
    --call 'post_items {"body":{"title":"pilot-verify-697"}}' \
    --call 'get_items'
  RC=$?
else
  serve_and_smoke "$ENVDIR" 18767 --call 'get_schedules_list'
  RC=$?
fi

echo "=== [4/4] Находки (гейты ветки) ==="
python3 - "$W/build.json" "$MODE" << 'PY'
import json, sys
d = json.load(open(sys.argv[1]))
mode = sys.argv[2]
cov = d.get("coverage", {})
reads, writes = cov.get("reads", {}), cov.get("writes", {})
if mode == "demo":
    ok = reads.get("state", 0) >= 1 and any(w.get("tool") == "post_items" for w in writes.get("served", []))
    print(f"[demo] read из state: {reads.get('state', 0)} ≥ 1: {reads.get('state', 0) >= 1}; "
          f"write post_items served: {any(w.get('tool') == 'post_items' for w in writes.get('served', []))}")
    print("[demo] ВЕРДИКТ: " + ("ГОТОВО — state-ветка рецепта работает" if ok else "FAIL — state-ветка сломана"))
    sys.exit(0 if ok else 1)
else:
    withheld = {w.get("tool"): w.get("reason") for w in writes.get("withheld", [])}
    ok = reads.get("recorded", 0) >= 1 and withheld.get("post_schedules_create") == "no-state-target"
    print(f"[office] read recorded (fields-differ): {reads.get('recorded_reasons', {}).get('fields-differ', 0) >= 1}; "
          f"write withheld no-state-target: {withheld.get('post_schedules_create') == 'no-state-target'}")
    print("[office] ВЕРДИКТ: " + ("ГОТОВО — среда replay-only, как предсказано (RPC-поверхность)" if ok else "ИЗМЕНИЛОСЬ — сверить с docs/eval-har-env.md"))
    sys.exit(0 if ok else 1)
PY
RC2=$?
echo "артефакты: $W"
[ "$RC" = "0" ] && [ "$RC2" = "0" ] || exit 1
exit 0
