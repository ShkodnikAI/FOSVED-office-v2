#!/usr/bin/env bash
# scripts/measure_prod.sh — Замер конкурентности release-сборки
#
# Использование:  bash scripts/measure_prod.sh <BASE_URL>
# Пример:         bash scripts/measure_prod.sh http://localhost:8080
#
# Что делает:
#   1. Baseline: одиночный запрос к /ask (медленный LLM-маршрут)
#   2. Два параллельных запроса к /ask + периодические /health
#   3. Замеряет время каждого запроса через curl -w
#
# Маршруты:
#   /ask   — медленный (LLM-вызов, ~5-30s)
#   /health — быстрый (JSON-ответ, <0.01s)
#
# НЕ дёргает: /webhook/telegram, /tg-send (секретные)
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

BASE="${1:?Usage: $0 <BASE_URL>}"
BASE="${BASE%/}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══ Замер конкурентности release-сборки mlog ═══${NC}"
echo -e "Целевой адрес: ${YELLOW}${BASE}${NC}"
echo ""

# ── 0. Проверяем доступность ──
echo -e "${CYAN}[0/4] Проверка доступности...${NC}"
HEALTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health" --max-time 5)
if [ "$HEALTH_CODE" != "200" ]; then
    echo -e "${RED}Сервер недоступен: /health вернул ${HEALTH_CODE}${NC}"
    exit 1
fi
echo -e "${GREEN}  /health -> 200 OK${NC}"
echo ""

# ── 1. Baseline: одиночный /ask ──
echo -e "${CYAN}[1/4] Baseline: одиночный /ask...${NC}"
T_BASELINE=$(curl -s -w "%{time_total}" -o /dev/null \
    --max-time 120 \
    -X POST "${BASE}/ask" \
    -H "Content-Type: application/json" \
    -d '{"dept":"yana","messages":[{"role":"user","content":"Привет"}]}')
echo -e "${GREEN}  Baseline /ask: ${T_BASELINE}s${NC}"
echo ""

# ── 2. Два параллельных /ask + 3x /health ──
echo -e "${CYAN}[2/4] Конкурентность: 2 x /ask + 3 x /health...${NC}"

ASK1_OUT=$(mktemp)
ASK2_OUT=$(mktemp)

# Параллельные /ask
curl -s -w "%{time_total}" -o /dev/null \
    --max-time 120 \
    -X POST "${BASE}/ask" \
    -H "Content-Type: application/json" \
    -d '{"dept":"yana","messages":[{"role":"user","content":"Скажи число от 1 до 10"}]}' \
    > "$ASK1_OUT" 2>/dev/null &
PID_ASK1=$!

curl -s -w "%{time_total}" -o /dev/null \
    --max-time 120 \
    -X POST "${BASE}/ask" \
    -H "Content-Type: application/json" \
    -d '{"dept":"yana","messages":[{"role":"user","content":"Какой сегодня день недели?"}]}' \
    > "$ASK2_OUT" 2>/dev/null &
PID_ASK2=$!

echo -e "  PID: ask1=${PID_ASK1} ask2=${PID_ASK2}"

# Три /health с задержками
for i in 1 2 3; do
    sleep 2
    T_H=$(curl -s -w "%{time_total}" -o /dev/null "${BASE}/health" --max-time 5)
    echo -e "  ${YELLOW}/health #${i}: ${T_H}s${NC}"
done

wait $PID_ASK1 2>/dev/null || true
wait $PID_ASK2 2>/dev/null || true

T_ASK1=$(cat "$ASK1_OUT" 2>/dev/null || echo "FAIL")
T_ASK2=$(cat "$ASK2_OUT" 2>/dev/null || echo "FAIL")
rm -f "$ASK1_OUT" "$ASK2_OUT"

echo ""
echo -e "${CYAN}[3/4] Результаты /ask:${NC}"
echo -e "  ${YELLOW}ask1: ${T_ASK1}s${NC}"
echo -e "  ${YELLOW}ask2: ${T_ASK2}s${NC}"
echo ""

# ── 4. Итог ──
echo -e "${CYAN}═══ Итог ═══${NC}"
echo -e "  Baseline /ask (1x):  ${T_BASELINE}s"
echo -e "  /ask #1 (2x параллель): ${T_ASK1}s"
echo -e "  /ask #2 (2x параллель): ${T_ASK2}s"
echo ""
echo -e "  Если ask1+ask2 ~= baseline -> блокировка (ожидаем concurrency)"
echo -e "  Если ask1+ask2 < baseline*2 -> частичная блокировка"
echo -e "  Если /health > 0.5s под нагрузкой -> event loop блокируется"
echo ""
echo -e "${CYAN}dev-сборку не замеряем — бессмысленно (60MB, debug)${NC}"
echo -e "${CYAN}release-сборка (21MB): baseline=${T_BASELINE}s${NC}"
