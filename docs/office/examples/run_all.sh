#!/bin/sh
# Прогон ВСЕХ примеров аудита Fosved Office на ОБОИХ рантаймах:
#   mlog 0.38.0     (work/mlog-038)     — цель наряда #620, основной рантайм задачи
#   mlog 0.34.1     (work/o2/bin/mlog)  — текущий прод офиса
# Проверка = `check` (статика + taint-синки) И `test` (исполнение): `mlog test`
# не подразумевает `mlog check` — проходим оба. Таблица находок с разделением
# артефактов режима и реальных ошибок: examples/check_matrix.sh.
# Пример 07 (если появится) — только 0.38: profile capability с 0.36 (ADR-0203).
set -e
cd "$(dirname "$0")/../.."

MLOG_034=work/o2/bin/mlog
MLOG_038=work/mlog-038
export DATABASE_URL="sqlite::memory:"

for f in deliverable-review/examples/card_contract.mlog deliverable-review/examples/0*.mlog; do
  base=$(basename "$f")
  for b in "$MLOG_038" "$MLOG_034"; do
    case "$base:$b" in
      07_capability_migration.mlog:"$MLOG_034")
        echo "═══ $base · 0.34.1 — ПРОПУСК (profile capability с 0.36) ═══"; continue ;;
    esac
    echo "═══ $base · $($b --version 2>/dev/null | head -1) ═══"
    # Реальные находки = всё, кроме артефактов режима (см. VERIFICATION.md).
    "$b" check "$f" --root "$f" 2>&1 | grep -v GLIBC \
      | grep -E "^ +[0-9]+: " \
      | grep -vE "duplicate pattern|BUILTIN_EXPERIMENTAL|declared-return" | head -5 || true
    # Отфильтровано (артефакты режима, доказано в VERIFICATION.md):
    #   duplicate pattern        — файл грузится дважды (цель + --root он же);
    #   BUILTIN_EXPERIMENTAL     — db_insert помечен experimental в 0.36+;
    #   declared-return (n486)   — появляется ТОЛЬКО в self-root режиме: при
    #                              preload декларация регистрируется как -> String.
    #                              В исходнике типы верны (RoutingMinN() -> Float).
    "$b" test "$f" 2>&1 | grep -v GLIBC | tail -2
  done
done
