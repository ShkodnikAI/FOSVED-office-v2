#!/usr/bin/env bash
# ── rc_stand_check.sh — воскресная проверка кандидата Metalogos на стенде офиса ──
# Наряд FOSVED-office-v2#655 (решение владельца 04.11, календарный релизный
# поезд Metalogos-#1793 / ADR-0189): каждое воскресенье после субботнего
# кандидата vX.Y.0-rc.N стенд офиса — контрольная точка релиза языка.
#
# Использование:
#   scripts/rc_stand_check.sh <tag>                 # полный прогон
#   scripts/rc_stand_check.sh <tag> --logs-only     # повторный скан журнала Render
#                                                   # (окно 2 ч) + возврат staging на main
#
# Что делает:
#   1. Пин стенда на ассет rc: релиз <tag> обязан иметь ассеты
#      mlog-linux-x86_64 и SHA256SUMS; sha256 сверяется — НЕ сошёлся →
#      громкий отказ (мутационный гард: подменённый ассет не проходит).
#   2. Ценз #633: MLOG_BIN=кандидат mlog check app.mlog --root app.mlog
#      против эталона docs/office/BASELINE_app_mlog.txt.
#   3. e2e-батарея (office_e2e_baseline): v3-батарея test_*v3 как в CI +
#      mlog test app.mlog с моком Bot API и гвардом «❌».
#   4. Деплой на staging (опционально, при RENDER_API_KEY+RENDER_SERVICE_ID):
#      ветка stand/rc-<tag> с кандидатом в bin/mlog → Render деплой → /health.
#      Без реквизитов — печатает точные действия владельца.
#   5. Smoke owner-команд по одной на отдел (scripts/smoke.py SMOKE_DEPTS=1,
#      при BOT_TOKEN/OWNER_ID) — против staging с кандидатом.
#   6. Журнал Render на маркеры IRREVERSIBLE_NO_GRANT / [ROUTE_HANDLER_ERROR] /
#      падения старта — окно 2 ч (повторный прогон --logs-only через 2 ч).
#   7. Отчёт в release-issue Metalogos: rc=<tag> · check: N/базовая · e2e: x/y ·
#      smoke: x/y · логи: OK|список + вердикт GO / NO-GO.
#      NO-GO → issue в Metalogos с воспроизведением (отключить: NO_ISSUE=1);
#      прод офиса НЕ трогается.
#
# Реквизиты (все опциональны, недостающее честно помечается «не проверено»):
#   GITHUB_TOKEN_METALOGOS / GITHUB_TOKEN / GH_TOKEN — API Metalogos- и постинг отчёта
#   RC_ASSET_DIR       — готовые ассеты (мутационный/офлайн режим, без скачивания)
#   STAGING_URL        — default https://fosved-office-v2-staging.onrender.com
#   BOT_TOKEN/OWNER_ID/WEBHOOK_SECRET — smoke через вебхук
#   RENDER_API_KEY/RENDER_SERVICE_ID  — деплой и журнал Render
#   RC_SKIP_E2E=1 / RC_SKIP_DEPLOY=1  — отладочные пропуски
#
# Коды выхода: 0 = GO · 1 = NO-GO · 2 = шаг невыполним (релиз/ассеты) · 3 = SHA не сошёлся.
# Вызовы api.render.com не проверялись из песочницы (egress) — при отсутствии
# сети скрипт отказывает громко, не молча.

set -u -o pipefail
cd "$(dirname "$0")/.." || exit 2

TAG="${1:-}"
LOGS_ONLY="${2:-}"
[ -z "$TAG" ] && { echo "usage: scripts/rc_stand_check.sh <tag> [--logs-only]"; exit 2; }

REPO_API="https://api.github.com/repos/ShkodnikAI/Metalogos-"
WORK="${RC_WORK_DIR:-/tmp/rc-stand-$TAG}"
STAGING_URL="${STAGING_URL:-https://fosved-office-v2-staging.onrender.com}"
STATE="$WORK/state.env"
mkdir -p "$WORK"

say()  { echo "[rc] $*"; }
pass() { echo "[rc]   OK: $*"; }
fail() { echo "[rc]   FAIL: $*"; }
die()  { echo "[rc] ОТКАЗ: $*" >&2; exit "${2:-2}"; }

GH_TOK=""
for t in "${GITHUB_TOKEN_METALOGOS:-}" "${GITHUB_TOKEN:-}" "${GH_TOKEN:-}"; do
  [ -n "$t" ] && { GH_TOK="$t"; break; }
done

api() { # api <METHOD> <path> [json-body] — GitHub API Metalogos-
  local method="$1" path="$2" body="${3:-}" auth=() out
  [ -n "$GH_TOK" ] && auth=(-H "Authorization: Bearer $GH_TOK")
  if [ "$method" = "GET" ]; then
    curl -sS --max-time 60 "${auth[@]}" -H "Accept: application/vnd.github+json" "$REPO_API$path"
  else
    curl -sS --max-time 60 "${auth[@]}" -H "Accept: application/vnd.github+json" \
      -H "Content-Type: application/json" -X "$method" -d "$body" "$REPO_API$path"
  fi
}

# ── --logs-only: скан журнала Render за окно + возврат staging на main ──────
if [ "$LOGS_ONLY" = "--logs-only" ]; then
  [ -n "${RENDER_API_KEY:-}" ] && [ -n "${RENDER_SERVICE_ID:-}" ] \
    || die "--logs-only требует RENDER_API_KEY и RENDER_SERVICE_ID" 2
  [ -f "$STATE" ] && . "$STATE"
  SINCE="${DEPLOY_TS:-}"
  [ -z "$SINCE" ] && die "нет $STATE с DEPLOY_TS — сначала полный прогон" 2
  say "скан журнала Render с $SINCE (окно 2 ч, сервис $RENDER_SERVICE_ID)"
  LOGS_OUT="$WORK/logs_2h.txt"
  : > "$LOGS_OUT"
  for PAGE in 1 2 3 4 5; do
    curl -sS --max-time 60 -H "Authorization: Bearer $RENDER_API_KEY" \
      -H "Accept: application/json" \
      "https://api.render.com/v1/logs?service=$RENDER_SERVICE_ID&startTime=$SINCE&limit=100&offset=$(( (PAGE-1)*100 ))" \
      >> "$LOGS_OUT" 2>>"$LOGS_OUT" || true
  done
  BAD=$(grep -cE "IRREVERSIBLE_NO_GRANT|\[ROUTE_HANDLER_ERROR\]|panicked at|bootstrap.*failed=[1-9]" "$LOGS_OUT" || true)
  say "окно журнала: $(wc -c < "$LOGS_OUT") байт, маркеров отказов: $BAD"
  # возврат staging на main (если гнали rc-ветку)
  if [ "${BRANCH_SWITCHED:-0}" = "1" ] && [ "${RC_KEEP_BRANCH:-0}" != "1" ]; then
    say "возврат staging на ветку main"
    curl -sS --max-time 60 -X PATCH "https://api.render.com/v1/services/$RENDER_SERVICE_ID" \
      -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" \
      -H "Accept: application/json" -d '{"branch":"main"}' >/dev/null \
      && say "staging снова на main (автодеплой вернёт боевой пин)" \
      || say "ВНИМАНИЕ: возврат ветки не удался — верни staging на main в дашборде Render"
  fi
  if [ "$BAD" -eq 0 ]; then
    say "ЛОГИ: OK — маркеров отказов нет"
    exit 0
  fi
  grep -nE "IRREVERSIBLE_NO_GRANT|\[ROUTE_HANDLER_ERROR\]|panicked at|bootstrap.*failed=[1-9]" "$LOGS_OUT" | head -10
  say "ЛОГИ: СПИСОК ОТКАЗОВ выше — NO-GO, см. issue в Metalogos"
  exit 1
fi

# ── Шаг 1. Релиз и ассеты ───────────────────────────────────────────────────
say "шаг 1: релиз $TAG"
case "$TAG" in
  v[0-9]*.[0-9]*.[0-9]*-rc*) : ;;
  *) say "ВНИМАНИЕ: $TAG не вида vX.Y.Z-rc.N — валидационный прогон, отчёт будет помечен" ;;
esac

if [ -n "${RC_ASSET_DIR:-}" ]; then
  # офлайн/мутационный режим: ассеты из каталога, запрос релиза не нужен
  say "RC_ASSET_DIR=$RC_ASSET_DIR — ассеты из каталога (мутационный/офлайн режим)"
  cp "$RC_ASSET_DIR/mlog-linux-x86_64" "$RC_ASSET_DIR/SHA256SUMS" "$WORK/" \
    || die "в RC_ASSET_DIR нет mlog-linux-x86_64 и/или SHA256SUMS" 2
else
  REL=$(api GET "/releases/tags/$TAG")
  echo "$REL" | python3 -c '
import json, sys
r = json.load(sys.stdin)
if not isinstance(r, dict) or "assets" not in r:
    print("ERR:" + str(r)[:300]); sys.exit(1)
m = {a["name"]: a["browser_download_url"] for a in r["assets"]}
for k in ("mlog-linux-x86_64", "SHA256SUMS"):
    if k not in m:
        print("MISSING:" + k); sys.exit(1)
print(m["mlog-linux-x86_64"])
print(m["SHA256SUMS"])
' > "$WORK/rel.txt" 2>"$WORK/rel.err" \
    || die "релиз $TAG не читается: $(tail -2 "$WORK/rel.err" | head -1)"
  grep -q "^MISSING:" "$WORK/rel.txt" \
    && die "в релизе $TAG нет ассета $(grep '^MISSING:' "$WORK/rel.txt" | cut -d: -f2) — шаг невыполним, не начинать (шаг 0 наряда)" 2

  BIN_URL=$(sed -n 1p "$WORK/rel.txt")
  SUMS_URL=$(sed -n 2p "$WORK/rel.txt")
  say "скачивание ассетов"
  curl -sSL --retry 4 --max-time 300 -o "$WORK/mlog-linux-x86_64" "$BIN_URL" \
    || die "скачивание бинаря не удалось" 2
  curl -sSL --retry 4 --max-time 60 -o "$WORK/SHA256SUMS" "$SUMS_URL" \
    || die "скачивание SHA256SUMS не удалось" 2
fi

WANT=$(awk '$2=="mlog-linux-x86_64"{print $1}' "$WORK/SHA256SUMS")
GOT=$(sha256sum "$WORK/mlog-linux-x86_64" | awk '{print $1}')
[ -n "$WANT" ] || die "в SHA256SUMS нет строки mlog-linux-x86_64" 2
if [ "$WANT" != "$GOT" ]; then
  echo "[rc]   ожидалось (SHA256SUMS): $WANT"
  echo "[rc]   фактически:              $GOT"
  die "SHA не сходится — ассет подменён или битый; продолжение невозможно" 3
fi
pass "sha256 сошёлся: $GOT"

chmod +x "$WORK/mlog-linux-x86_64"
CAND="$WORK/mlog-linux-x86_64"
VOUT=$("$CAND" --version 2>&1) || die "кандидат не запускается: $VOUT" 2
say "кандидат: $VOUT"
echo "$VOUT" > "$WORK/version.txt"
cp "$WORK/SHA256SUMS" "$WORK/SHA256SUMS.used"

# ── Шаг 2. Ценз #633 на кандидате ──────────────────────────────────────────
say "шаг 2: ценз #633 (mlog check app.mlog --root app.mlog) на кандидате"
CHECK_OK=0; CHECK_N="?"; CHECK_BASELINE="37"
if MLOG_BIN="$CAND" python3 scripts/mlog_baseline_gate.py > "$WORK/check.txt" 2>&1; then
  CHECK_OK=1
  CHECK_N=$(grep -oE "итого содержательных: [0-9]+" "$WORK/check.txt" | tail -1 | grep -oE "[0-9]+")
  pass "GATE GREEN, ${CHECK_N}/${CHECK_BASELINE}"
else
  fail "ценз красный:"
  tail -6 "$WORK/check.txt" | sed 's/^/        /'
fi

# ── Шаг 3. e2e-батарея (office_e2e_baseline) ───────────────────────────────
E2E_OK=0; E2E_PASS=0; E2E_TOTAL=0; E2E_FAILED=""
if [ "${RC_SKIP_E2E:-0}" != "1" ]; then
  say "шаг 3: e2e-батарея на кандидате (v3 + mlog test)"
  # env — как в CI (джоба v3 battery, наряд #519); значения фиктивные тестовые
  export METALOGOS_ALLOW_EXEC="1" FORGE_RUN_ENABLED="1" FORGE_RUN_VLIMIT_KB="64"
  export METALOGOS_EXEC_TIMEOUT_SECS="30" OWNER_TELEGRAM_ID="99999"
  export TELEGRAM_BOT_TOKEN="test-bot-token-123456" TELEGRAM_WEBHOOK_SECRET="wh-secret-12345678"
  export API_SECRET="api-token-123456" CRON_SECRET="cron-token-123456"
  export GITHUB_TOKEN_METALOGOS="gh-token-12345678"
  export DEEPSEEK_API_KEY="deepseek-token-12345" ZAI_API_KEY="zai-token-12345678"
  export KIMI_API_KEY="kimi-token-12345678" GROQ_API_KEY="groq-token-12345678"
  export GROK_API_KEY="grok-token-12345678" ANTHROPIC_API_KEY="anth-token-12345678"
  export OPENAI_API_KEY="oai-token-12345678" CEREBRAS_API_KEY="cerebras-12345678"
  export NVIDIA_API_KEY="nvidia-token-1234567" TAVILY_API_KEY="tavily-token-1234567"
  export YANDEX_MARKET_API_KEY="yandex-market-123456" SAKANA_API_KEY="sakana-token-1234567"
  export LOCKDOWN_PASSWORD="lockdown-pass-123456" TELEGRAM_ARCHIVE_CHANNEL_ID="-1"
  export SHOP_ENABLED="0" FORGE_GITHUB_OWNER="test-owner" RENDER_URL="http://127.0.0.1:9999"

  mkdir -p forge-tmp
  for d in $(grep -ho 'sqlite:/tmp/[^"]*' test_*v3.mlog test_n588_night.mlog | sed -E 's#^sqlite:##; s#/[^/]*$##' | sort -u); do
    rm -rf "$d" && mkdir -p "$d"
  done
  python3 -c "import pytest" 2>/dev/null || python3 -m pip install --quiet --break-system-packages pytest

  # список батареи — как в CI (джоба v3 battery, наряд #519); RC_E2E_FILES —
  # подмножество для валидации скрипта (полный список — на воскресном прогоне)
  E2E_LIST="${RC_E2E_FILES:-test_forge1v3.mlog test_forge2v3.mlog test_forge3v3.mlog test_forge4v3.mlog test_forge5v3.mlog test_forge6v3.mlog test_forge7v3.mlog test_forge8v3.mlog test_forge9v3.mlog test_narad1v3.mlog test_narad2v3.mlog test_narad3v3.mlog test_n550v3.mlog test_n553v3.mlog test_n556v3.mlog test_n565v3.mlog test_n566v3.mlog test_n559v3.mlog test_n588_night.mlog}"
  for f in $E2E_LIST; do
    N=$(echo "$f" | sed -E 's/test_(forge|narad)([0-9]+)v3/\2/')
    D=/tmp/n519-$N; rm -rf "$D" && mkdir -p "$D"
    export FORGE_REPOS_DIR="$D"
    out=$(timeout 180 "$CAND" run "$f" 2>&1 | grep -vE "REDACT\[|audit-event")
    rc=$?
    E2E_TOTAL=$((E2E_TOTAL+1))
    if [ $rc -eq 0 ] && echo "$out" | grep -q "ALL PASS"; then
      pass "battery $f"
      E2E_PASS=$((E2E_PASS+1))
    else
      fail "battery $f (rc=$rc)"; echo "$out" | grep -E "error|FAIL " | head -4 | sed 's/^/        /'
      E2E_FAILED="$E2E_FAILED $f"
      echo "$out" > "$WORK/fail_$f.log"
    fi
  done

  # mlog test app.mlog — с моком Bot API и гвардом «❌» (джоба CI naryad #644)
  rm -rf /tmp/mlogtest && mkdir -p /tmp/mlogtest
  M455_NAMES="app.mlog,consensus.mlog"
  for M455_F in dept/*.mlog library/*.mlog memories/*.mlog; do
    [ -e "$M455_F" ] || continue
    M455_NAMES="${M455_NAMES},$(basename "$M455_F")"
  done
  python3 tests/mock_telegram.py 18801 & MOCK_PID=$!
  sleep 1
  set +e
  DATABASE_URL=sqlite:/tmp/mlogtest/office.db METALOGOS_DATA_DIR=. \
  METALOGOS_HTTP_ALLOW_PRIVATE=1 METALOGOS_SENSITIVE_PATH_ALLOWLIST="$M455_NAMES" \
  METALOGOS_TELEGRAM_API_BASE=http://127.0.0.1:18801 OWNER_TELEGRAM_ID=000000000 \
  TELEGRAM_BOT_TOKEN=fake-token-n644 CRON_SECRET=fake-cron-n644 \
    "$CAND" test app.mlog > "$WORK/mlogtest.txt" 2>&1
  MTEST_RC=$?
  set -e
  kill $MOCK_PID 2>/dev/null
  E2E_TOTAL=$((E2E_TOTAL+1))
  if [ $MTEST_RC -eq 0 ] && ! grep -q "❌" "$WORK/mlogtest.txt"; then
    MTEST_N=$(grep -oE "[0-9]+/[0-9]+ tests passed" "$WORK/mlogtest.txt" | tail -1)
    pass "mlog test app.mlog: ${MTEST_N:-rc=0}"
    E2E_PASS=$((E2E_PASS+1))
  else
    fail "mlog test app.mlog (rc=$MTEST_RC, ❌-гвард)"; grep "❌" "$WORK/mlogtest.txt" | head -3 | sed 's/^/        /'
    E2E_FAILED="$E2E_FAILED mlog-test"
  fi

  [ $E2E_PASS -eq $E2E_TOTAL ] && E2E_OK=1
  say "e2e: $E2E_PASS/$E2E_TOTAL${E2E_FAILED:+ (упали:$E2E_FAILED)}"
else
  say "шаг 3 ПРОПУЩЕН (RC_SKIP_E2E=1) — валидационный прогон"
fi

# ── Шаг 4. Деплой на staging (опционально) ─────────────────────────────────
DEPLOY_NOTE="не проверено — нужны RENDER_API_KEY и RENDER_SERVICE_ID (действие владельца: ветка stand/rc-$TAG + деплой staging)"
if [ "${RC_SKIP_DEPLOY:-0}" = "1" ]; then
  say "шаг 4 ПРОПУЩЕН (RC_SKIP_DEPLOY=1)"
elif [ -n "${RENDER_API_KEY:-}" ] && [ -n "${RENDER_SERVICE_ID:-}" ]; then
  say "шаг 4: деплой staging на кандидата (ветка stand/rc-$TAG)"
  BRANCH="stand/rc-$TAG"
  git fetch origin main --force >/dev/null 2>&1 || true
  git worktree remove --force "$WORK/repo-rc" >/dev/null 2>&1 || true
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git worktree add --force "$WORK/repo-rc" "$BRANCH" >/dev/null 2>&1 || die "worktree ветки $BRANCH не создан" 2
  else
    git worktree add --force "$WORK/repo-rc" -b "$BRANCH" origin/main >/dev/null 2>&1 || die "worktree ветки $BRANCH не создан" 2
  fi
  cp "$CAND" "$WORK/repo-rc/bin/mlog"
  git -C "$WORK/repo-rc" add bin/mlog
  git -C "$WORK/repo-rc" -c user.email="agent@fosved.office" -c user.name="Fosved Agent" \
    commit -m "rc-stand: кандидат $TAG (sha256 ${GOT:0:8}, проверка наряда #655)" >/dev/null \
    || die "коммит rc-ветки не создан" 2
  git -C "$WORK/repo-rc" push --force "origin" "$BRANCH" >/dev/null 2>&1 \
    || die "пуш ветки $BRANCH не удался — нужны git-реквизиты" 2
  git worktree remove --force "$WORK/repo-rc" >/dev/null 2>&1 || true
  pass "ветка $BRANCH запушена с кандидатом"

  say "переключение staging на $BRANCH и деплой"
  PATCH=$(curl -sS --max-time 60 -X PATCH "https://api.render.com/v1/services/$RENDER_SERVICE_ID" \
    -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" \
    -H "Accept: application/json" -d "{\"branch\":\"$BRANCH\"}")
  echo "$PATCH" | grep -q '"id"' || die "PATCH ветки Render не удался: $(echo "$PATCH" | head -c 200)" 1
  DEP=$(curl -sS --max-time 60 -X POST "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys" \
    -H "Authorization: Bearer $RENDER_API_KEY" -H "Content-Type: application/json" \
    -H "Accept: application/json" -d '{"clearCache":"no"}')
  DEPLOY_ID=$(echo "$DEP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null)
  [ -n "$DEPLOY_ID" ] || die "деплой Render не запустился: $(echo "$DEP" | head -c 200)" 1
  DEPLOY_TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  printf 'DEPLOY_TS=%s\nBRANCH_SWITCHED=1\nRENDER_SERVICE_ID=%s\n' "$DEPLOY_TS" "$RENDER_SERVICE_ID" > "$STATE"
  say "деплой $DEPLOY_ID запущен ($DEPLOY_TS), жду статус live (до 15 мин)"
  DEPLOY_LIVE=0
  for i in $(seq 1 30); do
    sleep 30
    DS=$(curl -sS --max-time 60 "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys/$DEPLOY_ID" \
      -H "Authorization: Bearer $RENDER_API_KEY" -H "Accept: application/json" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
    case "$DS" in
      live) DEPLOY_LIVE=1; break ;;
      build_failed|update_failed|canceled|deactivated) break ;;
    esac
  done
  if [ "$DEPLOY_LIVE" != "1" ]; then
    fail "деплой staging не дошёл до live (статус: ${DS:-?}) — NO-GO"
    DEPLOY_NOTE="FAIL: деплой не дошёл до live (статус ${DS:-?}); журнал: см. дашборд Render"
    VERDICT_FAIL=1
  else
    pass "деплой live; возврат ветки — скриптом --logs-only через 2 ч (или RC_KEEP_BRANCH=1)"
    DEPLOY_NOTE="OK: деплой $DEPLOY_ID live ($DEPLOY_TS), staging на $BRANCH"
  fi
else
  say "шаг 4: реквизитов Render нет — деплой за владельцем:"
  say "  git worktree add /tmp/rc-$TAG-stand -b stand/rc-$TAG origin/main"
  say "  cp $CAND /tmp/rc-$TAG-stand/bin/mlog && (cd /tmp/rc-$TAG-stand && git add bin/mlog && git commit -m 'rc-stand: $TAG' && git push --force origin stand/rc-$TAG)"
  say "  дашборд Render: staging service → Settings → Branch = stand/rc-$TAG → Manual Deploy"
fi

# ── Шаг 5. Smoke owner-команд (по одной на отдел) ──────────────────────────
SMOKE_NOTE="не проверено — нужны BOT_TOKEN/OWNER_ID (действие владельца)"
SMOKE_OK=0
if [ "${RC_SKIP_SMOKE:-0}" = "1" ]; then
  say "шаг 5 ПРОПУЩЕН (RC_SKIP_SMOKE=1)"
elif [ -n "${BOT_TOKEN:-}" ] && [ -n "${OWNER_ID:-}" ]; then
  say "шаг 5: smoke owner-команд против $STAGING_URL"
  if BASE_URL="$STAGING_URL" SMOKE_DEPTS=1 python3 scripts/smoke.py > "$WORK/smoke.txt" 2>&1; then
    SMOKE_OK=1
    SMOKE_NOTE="OK: $(grep 'ИТОГ' "$WORK/smoke.txt" | tail -1)"
    pass "$SMOKE_NOTE"
  else
    SMOKE_NOTE="FAIL: $(grep 'ИТОГ' "$WORK/smoke.txt" | tail -1)"
    fail "$SMOKE_NOTE"; grep "^  - " "$WORK/smoke.txt" | head -5 | sed 's/^/        /'
  fi
else
  say "шаг 5: реквизитов смока нет — $SMOKE_NOTE"
fi

# ── Шаг 6. Журнал Render: первичный скан (окно добирается --logs-only) ─────
LOGS_NOTE="скан через 2 ч: scripts/rc_stand_check.sh $TAG --logs-only"
if [ -n "${RENDER_API_KEY:-}" ] && [ -n "${RENDER_SERVICE_ID:-}" ] && [ -f "$STATE" ]; then
  . "$STATE"
  say "шаг 6: первичный скан журнала с $DEPLOY_TS"
  curl -sS --max-time 60 -H "Authorization: Bearer $RENDER_API_KEY" -H "Accept: application/json" \
    "https://api.render.com/v1/logs?service=$RENDER_SERVICE_ID&startTime=$DEPLOY_TS&limit=100" \
    > "$WORK/logs_now.txt" 2>&1 || true
  BAD_NOW=$(grep -cE "IRREVERSIBLE_NO_GRANT|\[ROUTE_HANDLER_ERROR\]|panicked at" "$WORK/logs_now.txt" || true)
  if [ "$BAD_NOW" -eq 0 ]; then
    LOGS_NOTE="первичный скан чист (полное окно 2 ч — --logs-only)"
    pass "логи: первичный скан без маркеров"
  else
    LOGS_NOTE="СПИСОК: маркеры отказов уже в журнале ($BAD_NOW)"
    fail "$LOGS_NOTE"; grep -oE "IRREVERSIBLE_NO_GRANT[^\"]{0,80}|\[ROUTE_HANDLER_ERROR\][^\"]{0,80}" "$WORK/logs_now.txt" | head -5 | sed 's/^/        /'
  fi
else
  say "шаг 6: $LOGS_NOTE (реквизитов Render нет — журнал за владельцем)"
fi

# ── Вердикт и отчёт ────────────────────────────────────────────────────────
# короткие токены строки отчёта (формат наряда: smoke: x/y · логи: OK|список)
SMOKE_SHORT="не проверено"
case "$SMOKE_NOTE" in
  OK:*)   SMOKE_SHORT="OK $(grep 'ИТОГ' "$WORK/smoke.txt" 2>/dev/null | tail -1 | grep -oE '[0-9]+ из [0-9]+' || echo '')" ;;
  FAIL:*) SMOKE_SHORT="FAIL $(grep 'ИТОГ' "$WORK/smoke.txt" 2>/dev/null | tail -1 | grep -oE '[0-9]+ из [0-9]+' || echo '')" ;;
esac
LOGS_SHORT="не проверено"
case "$LOGS_NOTE" in
  "первичный скан чист"*) LOGS_SHORT="OK (первичный скан; окно 2 ч — --logs-only)" ;;
  "скан через 2 ч"*)      LOGS_SHORT="скан через 2 ч (--logs-only)" ;;
  СПИСОК*)                LOGS_SHORT="СПИСОК ОТКАЗОВ" ;;
esac

VERDICT="GO"; REASONS=""
[ "$CHECK_OK" = "1" ] || { VERDICT="NO-GO"; REASONS="$REASONS
- ценз #633 красный (${CHECK_N:-?}/$CHECK_BASELINE)"; }
[ "$E2E_OK" = "1" ] || [ "${RC_SKIP_E2E:-0}" = "1" ] || { VERDICT="NO-GO"; REASONS="$REASONS
- e2e-батарея: $E2E_PASS/$E2E_TOTAL ($E2E_FAILED )"; }
case "$SMOKE_NOTE" in
  FAIL:*) VERDICT="NO-GO"; REASONS="$REASONS
- smoke: $SMOKE_NOTE" ;;
esac
[ "${VERDICT_FAIL:-0}" = "1" ] && VERDICT="NO-GO"
case "$LOGS_NOTE" in СПИСОК*) VERDICT="NO-GO"; REASONS="$REASONS
- журнал Render: маркеры отказов" ;; esac

GAPS=""
case "$DEPLOY_NOTE" in OK:*) : ;; *) GAPS="$GAPS
- деплой staging: $DEPLOY_NOTE" ;; esac
case "$SMOKE_NOTE" in OK:*|FAIL:*) : ;; *) GAPS="$GAPS
- smoke: $SMOKE_NOTE" ;; esac
case "$LOGS_SHORT" in OK*|СПИСОК*) : ;; *) GAPS="$GAPS
- логи Render: $LOGS_SHORT" ;; esac

REPORT=$(cat <<EOF
**Стенд офиса (наряд FOSVED-office-v2#655)** — воскресная проверка кандидата

\`rc=$TAG · check: ${CHECK_N}/${CHECK_BASELINE} · e2e: ${E2E_PASS}/${E2E_TOTAL} · smoke: ${SMOKE_SHORT} · логи: ${LOGS_SHORT}\`

Вердикт: **$VERDICT**
${REASONS}

- sha256 кандидата: \`$GOT\` (SHA256SUMS релиза сверен; \`$(cat "$WORK/version.txt" | head -1)\`)
- деплой staging: $DEPLOY_NOTE
- smoke: $SMOKE_NOTE
- логи: $LOGS_NOTE
- прод офиса НЕ тронут (пин прод меняется только по команде владельца после понедельничной публикации)
EOF
)
if [ -n "$GAPS" ] && [ "$VERDICT" != "NO-GO" ]; then
  REPORT="$REPORT

Пробелы (вердикт локального контура; до понедельника закрываются владельцем):$GAPS"
fi

say "ОТЧЁТ:"
echo "$REPORT"

# постинг в release-issue Metalogos (issue с $TAG в заголовке)
POSTED=0
ISSUES=$(api GET "/issues?state=all&per_page=100")
ISS_NUM=$(echo "$ISSUES" | python3 -c '
import json, sys
tag = sys.argv[1]
try:
    issues = json.load(sys.stdin)
except Exception:
    issues = []
for i in issues:
    if isinstance(i, dict) and tag in (i.get("title") or ""):
        print(i["number"]); break
' "$TAG" 2>/dev/null)
if [ -n "$ISS_NUM" ] && [ -n "$GH_TOK" ]; then
  say "постинг отчёта в release-issue #$ISS_NUM"
  PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"body": sys.stdin.read()}))' <<< "$REPORT")
  RESP=$(api POST "/issues/$ISS_NUM/comments" "$PAYLOAD")
  echo "$RESP" | grep -q '"html_url"' && { POSTED=1; pass "отчёт опубликован"; } || fail "постинг не удался: $(echo "$RESP" | head -c 200) — опубликуй отчёт выше вручную"
else
  [ -z "$GH_TOK" ] && say "GITHUB-токена нет — опубликуй отчёт выше в release-issue Metalogos вручную"
  [ -z "$ISS_NUM" ] && say "release-issue с $TAG в заголовке не найден — опубликуй отчёт выше вручную"
fi

# NO-GO → issue в Metalogos с воспроизведением
if [ "$VERDICT" = "NO-GO" ] && [ "${NO_ISSUE:-0}" != "1" ] && [ -n "$GH_TOK" ]; then
  say "NO-GO: создаю issue в Metalogos с воспроизведением"
  REPRO=""
  [ -f "$WORK/check.txt" ] && REPRO="$REPRO\n<details><summary>ценз #633 (хвост)</summary>\n\n$(tail -15 "$WORK/check.txt")\n\n</details>"
  for LF in "$WORK"/fail_*.log; do
    [ -f "$LF" ] && REPRO="$REPRO\n<details><summary>$(basename "$LF")</summary>\n\n\`\`\`\n$(tail -25 "$LF")\n\`\`\`\n\n</details>"
  done
  ISSUE_BODY=$(printf '## NO-GO со стенда офиса (FOSVED-office-v2#655)\n\nКандидат `%s`, sha256 `%s`.\nПричины:%b\n\nВоспроизведение:%b\n\nСтенд: v3-батарея + ценз + mlog test как в CI офиса; скрипт `scripts/rc_stand_check.sh`.' \
    "$TAG" "$GOT" "$REASONS" "$REPRO")
  PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"title": "NO-GO rc-кандидата со стенда офиса: "+sys.argv[1], "body": sys.stdin.read(), "labels": ["rc-no-go"]}))' "$TAG" <<< "$ISSUE_BODY")
  RESP=$(api POST "/issues" "$PAYLOAD")
  echo "$RESP" | grep -q '"html_url"' && pass "issue NO-GO создан" || fail "issue не создан: $(echo "$RESP" | head -c 200) — создай вручную"
fi

[ "$VERDICT" = "GO" ] && exit 0 || exit 1
