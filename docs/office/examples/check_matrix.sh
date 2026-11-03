#!/bin/bash
# Матрица верификации примеров §2.6. Запуск: bash deliverable-review/examples/check_matrix.sh
# Считает ОТДЕЛЬНО артефакты режима проверки и реальные находки (см. VERIFICATION.md, «Протокол check»).
cd "$(dirname "$0")/../.."
export DATABASE_URL="sqlite::memory:"
printf "%-22s %-8s %6s %6s %6s %6s %6s %6s %s\n" файл runtime dup undf sinkDB exp warn прочее тесты
for f in deliverable-review/examples/[0-9c]*.mlog; do
  b=$(basename "$f")
  for rt in "work/mlog-038|0.38.0" "work/o2/bin/mlog|0.34.1"; do
    bin="${rt%%|*}"; ver="${rt##*|}"
    root=$("$bin" check "$f" --root "$f" 2>&1 | grep -v GLIBC | grep -E "^ +[0-9]+: ")
    plain=$("$bin" check "$f" 2>&1 | grep -v GLIBC | grep -E "^ +[0-9]+: ")
    all="$root
$plain"
    tot=$(echo "$all" | grep -c .)
    dup=$(echo "$all"  | grep -c "duplicate pattern")
    undf=$(echo "$all" | grep -c "undefined:")
    sink=$(echo "$all" | grep -cE "SQL_DYNAMIC|SEC_|INJECTION|SINK")
    exp=$(echo "$all"  | grep -c "BUILTIN_EXPERIMENTAL")
    warn=$(echo "$all" | grep -c "declared-return")
    other=$(( tot - dup - undf - sink - exp - warn ))
    t=$("$bin" test "$f" 2>&1 | grep -v GLIBC | grep -oE "[0-9]+/[0-9]+ tests passed" | tail -1)
    printf "%-22s %-8s %6s %6s %6s %6s %6s %6s %s\n" "$b" "$ver" "$dup" "$undf" "$sink" "$exp" "$warn" "$other" "$t"
  done
done
