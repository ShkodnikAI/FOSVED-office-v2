#!/usr/bin/env bash
# #696 REA-3 A.1: ЛЗ-сенсор WebMCP — еженедельное пассивное обнаружение
# page-declared WebMCP-инструментов по фиксированному списку доменов.
#
# Сенсор = поставщик ФАКТОВ «страница декларирует WebMCP-инструменты»
# (URL + дата + Evidence-id) для watchlist-категории #566 «тонкие скиллы
# против жирных tool-слоёв (MCP)». Триаж подтверждений — по уставу ЛЗ
# (library/lz.md:31, ≥3 независимых подтверждений; сенсор НЕ вердикт и
# НЕ disruption alert).
#
# Механика: rea-agents discover-webmcp-tools (пассивное наблюдение через
# CDP-домен WebMCP браузера; invokeTool НИКОГДА не вызывается — метаданные
# тулов недоверенные, page-declared-untrusted).
#
# Требования к браузеру: CDP-домен WebMCP есть в Chrome 146+ (DevTrial,
# origin trial с 149; chrome://flags/#enable-webmcp-testing). Проверено в
# песочнице 10.11.2026: Chrome for Testing 157.0.8103.50 — домен есть,
# декларативные тула (form toolname/tooldescription) обнаруживаются;
# playwright chromium-1200 (v143) — домена НЕТ («provider_unavailable»).
# Путь к браузеру: LZ_WEBMCP_BROWSER (по умолчанию — chromium из playwright,
# см. сообщение сенсора при недоступности домена).
#
# Пин rea-agents (наряды #694/#695/#696: авто-обновление запрещено).
# Требование к node — по README rea-agents: 22.23.4+ / 24.22.1+ / 26.12.1+.
#
# Робо-этика (наряд #696 «Что НЕ делаем»): только публичные входные
# страницы, 1 запрос на домен за прогон (без перехода по ссылкам), пауза
# ≥10 c между доменами (LZ_WEBMCP_DELAY), без авторизации/сабмитов форм,
# честный headless-UA (без подмены). robots.txt не проверяется: это не
# краулер — единичный визит входной страницы, как у любого браузера.
#
# A.2 (периодичность): окно еженедельное, ручной запуск (процедура —
# в шапке lz_webmcp_sensor.py и в отчёте наряда #696). Автономизация
# (cron/Actions-lane) — отдельный наряд: config/waker_windows.txt удалён
# (a2293d1, #604), start_crons.py гоняет только HTTP-эндпоинты приложения.
#
# Usage:
#   bash scripts/lz_webmcp_sensor.sh                     # 10 доменов по умолчанию
#   bash scripts/lz_webmcp_sensor.sh --domains a.com,b.com
#   bash scripts/lz_webmcp_sensor.sh --self-test         # локальная страница с
#                                                        # декларацией — проверка
#                                                        # сенсора без внешней сети
set -euo pipefail

REA_VERSION="6.8.0"

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

command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 не установлен" >&2; exit 1; }

# Playwright — внешний драйвер браузера (в requirements.txt офиса его НЕТ:
# сенсор — инструмент ЛЗ-стенда, не зависимость прода; как REA_PWNTOOLS_PYTHON
# в #695, внешние зависимости задаются окружением стенда)
if [ -z "${LZ_WEBMCP_BROWSER:-}" ]; then
  python3 -c "import playwright" 2>/dev/null || {
    echo "FAIL: python-модуль playwright не установлен (pip install playwright && python3 -m playwright install chromium) либо задайте LZ_WEBMCP_BROWSER=<путь к chrome 146+>" >&2
    exit 1
  }
fi

# rea-agents доступен? (npx качает при первом запуске; проверяем версию пина)
npx -y "rea-agents@${REA_VERSION}" --version >/dev/null 2>&1 \
  || { echo "FAIL: rea-agents@${REA_VERSION} недоступен (npx)" >&2; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "${DIR}/lz_webmcp_sensor.py" "$@"
