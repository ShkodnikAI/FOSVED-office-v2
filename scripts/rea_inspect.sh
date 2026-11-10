#!/usr/bin/env bash
# #694 REA-1 A.2: обёртка статического разбора сторонних артефактов
# через rea-agents (Reverse Engineer Anything, MIT; npm `rea-agents`).
#
# Пин версии обязателен (наряд #694 «Что НЕ делаем»): авто-обновления
# запрещены — апгрейд осознанным коммитом. 6.8.0 — версия, проверенная
# в песочнице 10.11.2026 (`npx -y rea-agents@6.8.0 --version` → 6.8.0;
# doctor → 175 CLI-команд / 229 MCP-инструментов).
#
# Требование к node — по README rea-agents §What you can analyze:
# 22.23.4+ / 24.22.1+ / 26.12.1+.
#
# Usage: scripts/rea_inspect.sh <rea-команда> <путь-к-артефакту> [доп. аргументы]
#   Примеры (рецепты и критерии — docs/dependency-acceptance-rea.md):
#     scripts/rea_inspect.sh analyze-javascript-application node_modules/@prisma/client \
#       --detail summary --evidence_output /tmp/prisma_client.bundle
#     scripts/rea_inspect.sh inspect-elf-notes bin/mlog
#   Выход — Evidence-JSON в /tmp с именем артефакта и датой (UTC).
set -euo pipefail

REA_VERSION="6.8.0"

usage() {
  echo "usage: $0 <rea-команда> <путь-к-артефакту> [доп. аргументы rea]" >&2
  exit 2
}
[ $# -ge 2 ] || usage
CMD="$1"; ART="$2"; shift 2
[ -e "$ART" ] || { echo "FAIL: артефакт не найден: $ART" >&2; exit 1; }

command -v node >/dev/null 2>&1 || { echo "FAIL: node не установлен" >&2; exit 1; }
node -e '
// Гейт версии node — требование README rea-agents (22.23.4+ / 24.22.1+ / 26.12.1+)
const v = process.versions.node.split(".").map(Number);
const req = [[22, 23, 4], [24, 22, 1], [26, 12, 1]];
const ge = (a, b) => a[0] > b[0] || (a[0] === b[0] &&
  (a[1] > b[1] || (a[1] === b[1] && a[2] >= b[2])));
const ok = v[0] > 26 || req.some(r => v[0] === r[0] && ge(v, r));
if (!ok) { console.error(`FAIL: node ${v.join(".")} ниже требуемого (README rea-agents: 22.23.4+ / 24.22.1+ / 26.12.1+)`); process.exit(1); }
'

BASE=$(basename "$ART" | tr -c 'A-Za-z0-9._-' '_')
STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="/tmp/rea_${BASE}_${STAMP}.json"

# Тока артефакта в вывод не подаём: rea читает только локальный путь.
npx -y "rea-agents@${REA_VERSION}" "$CMD" "$ART" --format json "$@" > "$OUT"

echo "Evidence JSON: ${OUT} ($(wc -c < "$OUT" | tr -d ' ') bytes)"
echo "Вердикт и критерии — docs/dependency-acceptance-rea.md (наряд #694)."
