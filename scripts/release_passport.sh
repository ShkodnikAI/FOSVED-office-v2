#!/usr/bin/env bash
# #695 REA-2 A.1: скрипт «паспорта релиза» — факты hardening/сертификатов/
# подписей нативного артефакта до публикации, статически, без исполнения.
#
# На каждый артефакт:
#   ELF — inspect-binary-layout (hardening: image_type/PIE, PT_GNU_RELRO,
#         PT_GNU_STACK/NX — факты Evidence, флаги производные от них)
#         + inspect-elf-notes;
#   PE  — inspect-pe-certificates + inspect-pe-imports (+ inspect-pe-load-config);
#   APK — inspect-apk-signature.
# Выход — md-паспорт в /tmp с Evidence-id и sha256 артефактов.
#
# Пин rea-agents (наряды #694/#695: авто-обновление запрещено). Для hardening
# нужен внешний Python: REA_PWNTOOLS_PYTHON → venv с pwntools 4.15.0,
# pyelftools 0.33, Unicorn 2.1.2 (REA сам Python не ставит — remediation
# инструмента). Без переменной hardening-секция пропускается с пометкой.
# REA_PWNTOOLS_MAX_INPUT_BYTES поднят до 128 МиБ (дефолт 32 МиБ < бинари офиса;
# ремедиация инструмента — «поднять параметр»).
#
# Usage: scripts/release_passport.sh <артефакт> [ещё артефакты…]
set -euo pipefail

REA_VERSION="6.8.0"
export REA_PWNTOOLS_MAX_INPUT_BYTES="${REA_PWNTOOLS_MAX_INPUT_BYTES:-134217728}"

[ $# -ge 1 ] || { echo "usage: $0 <артефакт> [ещё артефакты…]" >&2; exit 2; }

command -v node >/dev/null 2>&1 || { echo "FAIL: node не установлен" >&2; exit 1; }
node -e '
const v = process.versions.node.split(".").map(Number);
const req = [[22, 23, 4], [24, 22, 1], [26, 12, 1]];
const ge = (a, b) => a[0] > b[0] || (a[0] === b[0] &&
  (a[1] > b[1] || (a[1] === b[1] && a[2] >= b[2])));
const ok = v[0] > 26 || req.some(r => v[0] === r[0] && ge(v, r));
if (!ok) { console.error(`FAIL: node ${v.join(".")} ниже требуемого (README rea-agents: 22.23.4+ / 24.22.1+ / 26.12.1+)`); process.exit(1); }
'

STAMP=$(date -u +%Y%m%d-%H%M%S)
PASSPORT="/tmp/release_passport_${STAMP}.md"
RAW_DIR="/tmp/release_passport_${STAMP}_raw"
mkdir -p "$RAW_DIR"

echo "# Паспорт релиза (REA, non-blocking) — ${STAMP} UTC" > "$PASSPORT"
echo >> "$PASSPORT"
echo "- Инструмент: rea-agents@${REA_VERSION} (пин; статический разбор, без исполнения)" >> "$PASSPORT"
if [ -n "${REA_PWNTOOLS_PYTHON:-}" ]; then
  echo "- hardening-провайдер: pwntools-адаптер (\$REA_PWNTOOLS_PYTHON=${REA_PWNTOOLS_PYTHON})" >> "$PASSPORT"
else
  echo "- hardening-провайдер: недоступен — REA_PWNTOOLS_PYTHON не задан (нужен venv: pwntools 4.15.0, pyelftools 0.33, Unicorn 2.1.2); секции hardening пропущены с пометкой" >> "$PASSPORT"
fi
echo >> "$PASSPORT"
echo "| Артефакт | sha256 | Тип | Evidence |" >> "$PASSPORT"
echo "|---|---|---|---|" >> "$PASSPORT"

SUMMARY_ROWS=()

run_rea() {  # run_rea <команда> <артефакт> <файл-тег> — md+json в RAW_DIR
  local cmd="$1" art="$2" tag="$3"
  npx -y "rea-agents@${REA_VERSION}" "$cmd" "$art" --format md > "$RAW_DIR/${tag}.md" 2>"$RAW_DIR/${tag}.err"
  npx -y "rea-agents@${REA_VERSION}" "$cmd" "$art" --format json > "$RAW_DIR/${tag}.json" 2>>"$RAW_DIR/${tag}.err"
}

ev_of() {  # evidence-id из json-конверта (первое поле evidence_id)
  python3 - "$1" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f: d = json.load(f)
except Exception:
    sys.exit(0)
print(d.get("evidence_id", ""))
PY
}

for ART in "$@"; do
  [ -e "$ART" ] || { echo "FAIL: артефакт не найден: $ART" >&2; exit 1; }
  SHA=$(sha256sum "$ART" | cut -d' ' -f1)
  FT=$(file -b "$ART")
  TAG=$(basename "$ART" | tr -c 'A-Za-z0-9._-' '_')

  if echo "$FT" | grep -q "ELF"; then KIND="elf";
  elif echo "$FT" | grep -qiE "PE32|MS Windows|COFF"; then KIND="pe";
  elif echo "$FT" | grep -qiE "Android|APK|Zip"; then KIND="apk";
  else KIND="unknown"; fi

  EVIDENCE=""
  {
    echo
    echo "## ${ART}"
    echo
    echo "- file: \`${FT}\`"
    echo "- sha256: \`${SHA}\`"
  } >> "$PASSPORT"

  if [ "$KIND" = "elf" ]; then
    if [ -n "${REA_PWNTOOLS_PYTHON:-}" ]; then
      run_rea inspect-binary-layout "$ART" "${TAG}_layout" || true
      EV=$(ev_of "$RAW_DIR/${TAG}_layout.json")
      EVIDENCE="${EVIDENCE} layout:${EV}"
      {
        echo
        echo "### hardening (inspect-binary-layout; Evidence \`${EV}\`)"
        echo
        python3 - "$RAW_DIR/${TAG}_layout.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f: d = json.load(f)
nr = d.get("normalized_result", {})
it = nr.get("image_type")
segs = nr.get("segments") or []
relro = [s for s in segs if "GNU_RELRO" in str(s.get("type", ""))]
stack = [s for s in segs if "GNU_STACK" in str(s.get("type", ""))]
print(f"- PIE: image_type={it}" + (" → позиционно-независимый (ET_DYN)" if it == "ET_DYN" else " → фиксированный образ (ET_EXEC)"))
if relro:
    f = relro[0].get("permissions") or {}
    print(f"- RELRO: PT_GNU_RELRO присутствует (read={f.get('read')}, write={f.get('write')}, execute={f.get('execute')})")
else:
    print("- RELRO: сегмент PT_GNU_RELRO НЕ найден")
if stack:
    f = stack[0].get("permissions") or {}
    nx = "стек не исполняемый (NX)" if not f.get("execute") else "⚠ ВЫПОЛНЯЕМЫЙ СТЕК (NX отключён)"
    print(f"- NX: PT_GNU_STACK execute={f.get('execute')} → {nx}")
else:
    print("- NX: сегмент PT_GNU_STACK НЕ найден (флаг платформы по умолчанию)")
print()
print("Флаги — производные от фактов Evidence (image_type, сегменты); сырые факты — в json рядом с паспортом.")
PY
      } >> "$PASSPORT"
    else
      {
        echo
        echo "### hardening — ПРОПУЩЕНО: REA_PWNTOOLS_PYTHON не задан"
        echo "(remediation инструмента: venv с pwntools 4.15.0, pyelftools 0.33, Unicorn 2.1.2)"
      } >> "$PASSPORT"
    fi
    run_rea inspect-elf-notes "$ART" "${TAG}_elfnotes" || true
    EV=$(grep -m1 '^ev_' "$RAW_DIR/${TAG}_elfnotes.md" || true)
    [ -z "$EV" ] && EV=$(ev_of "$RAW_DIR/${TAG}_elfnotes.json")
    EVIDENCE="${EVIDENCE} elf-notes:${EV}"
    {
      echo
      echo "### ELF notes (Evidence \`${EV}\`)"
      echo
      sed -n '1,80p' "$RAW_DIR/${TAG}_elfnotes.md"
    } >> "$PASSPORT"

  elif [ "$KIND" = "pe" ]; then
    run_rea inspect-pe-certificates "$ART" "${TAG}_pecert" || true
    EV=$(grep -m1 '^ev_' "$RAW_DIR/${TAG}_pecert.md" || true)
    [ -z "$EV" ] && EV=$(ev_of "$RAW_DIR/${TAG}_pecert.json")
    EVIDENCE="${EVIDENCE} pe-cert:${EV}"
    { echo; echo "### Authenticode-сертификаты (Evidence \`${EV}\`)"; echo; sed -n '1,80p' "$RAW_DIR/${TAG}_pecert.md"; } >> "$PASSPORT"
    run_rea inspect-pe-imports "$ART" "${TAG}_peimp" || true
    EV=$(grep -m1 '^ev_' "$RAW_DIR/${TAG}_peimp.md" || true)
    [ -z "$EV" ] && EV=$(ev_of "$RAW_DIR/${TAG}_peimp.json")
    EVIDENCE="${EVIDENCE} pe-imports:${EV}"
    { echo; echo "### Импорты PE (Evidence \`${EV}\`)"; echo; sed -n '1,80p' "$RAW_DIR/${TAG}_peimp.md"; } >> "$PASSPORT"
    run_rea inspect-pe-load-config "$ART" "${TAG}_peload" || true
    EV=$(grep -m1 '^ev_' "$RAW_DIR/${TAG}_peload.md" || true)
    [ -z "$EV" ] && EV=$(ev_of "$RAW_DIR/${TAG}_peload.json")
    EVIDENCE="${EVIDENCE} pe-load-config:${EV}"
    { echo; echo "### Load configuration/TLS (Evidence \`${EV}\`)"; echo; sed -n '1,60p' "$RAW_DIR/${TAG}_peload.md"; } >> "$PASSPORT"

  elif [ "$KIND" = "apk" ]; then
    run_rea inspect-apk-signature "$ART" "${TAG}_apksig" || true
    EV=$(grep -m1 '^ev_' "$RAW_DIR/${TAG}_apksig.md" || true)
    [ -z "$EV" ] && EV=$(ev_of "$RAW_DIR/${TAG}_apksig.json")
    EVIDENCE="${EVIDENCE} apk-sig:${EV}"
    { echo; echo "### Подписи APK (Evidence \`${EV}\`)"; echo; sed -n '1,80p' "$RAW_DIR/${TAG}_apksig.md"; } >> "$PASSPORT"

  else
    { echo; echo "### Тип не распознан (file: \`${FT}\`) — паспорт неполный, разбор вручную"; } >> "$PASSPORT"
  fi

  SUMMARY_ROWS+=("| ${ART} | \`${SHA:0:16}…\` | ${KIND} |${EVIDENCE} |")
done

# Сводку вставляем после заголовочной таблицы
python3 - "$PASSPORT" "${SUMMARY_ROWS[@]+"${SUMMARY_ROWS[@]}"}" <<'PY'
import sys
path, rows = sys.argv[1], sys.argv[2:]
with open(path) as f: text = f.read()
header = "| Артефакт | sha256 | Тип | Evidence |\n|---|---|---|---|\n"
head, _, rest = text.partition(header)
insert = ("\n".join(rows) + "\n") if rows else ""
with open(path, "w") as f: f.write(head + header + insert + rest)
PY

echo
echo "Паспорт: ${PASSPORT}"
echo "Сырые Evidence (json/md): ${RAW_DIR}/"
echo
cat "$PASSPORT"
