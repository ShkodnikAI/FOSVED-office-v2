#!/bin/sh
# Пробы ревью плана офиса (02.11.2026). Каждая проба — доказательство конкретного
# вердикта; прогон на ОБОИХ рантаймах: 0.38.0 (цель #620) и 0.34.1 (прод офиса).
#   probe_a2_sites     — 24 сайта db_execute("SELECT"): форма прода, замена, MySQL-диалект
#   probe_a2_cte       — quest.mlog:24 (CTE+INSERT) НЕ сломан: db_execute отказывает только на возврате строк
#   probe_a2_parsejson — наивная замена db_execute→query() даёт runtime TYPE_MISMATCH, check молчит
#   probe_d3_loader    — загрузчики ОСП: прод (25000/12000) vs проверка после vs ядро+приложения
#   probe_d3_ladder    — «лесенка секций»: L1..L4 на реальных 24 SKILL.md, бюджет по глубине
#   probe_d4_tail      — структурный хвост: извлечение программой + json_validate + артефакты
#   probe_number_format— формат числа владельцу (round до 2 знаков)
# ВНИМАНИЕ: probe_d3_* требуют cwd=work/osp_skills (реальные файлы skills/*/SKILL.md).
set -e
cd "$(dirname "$0")/../.."
export DATABASE_URL="sqlite::memory:"
B038=work/mlog-038
B034=work/o2/bin/mlog
P=deliverable-review/probes

for f in probe_a2_sites probe_a2_cte probe_a2_parsejson probe_d4_tail probe_number_format; do
  for b in "$B038" "$B034"; do
    echo "═══ $f · $($b --version 2>/dev/null | head -1) ═══"
    "$b" test "$P/$f.mlog" 2>&1 | grep -v GLIBC | tail -2
  done
done

cd work/osp_skills
for f in probe_d3_loader probe_d3_ladder; do
  for b in "../../$B038" "../../$B034"; do
    echo "═══ $f · $($b --version 2>/dev/null | head -1) ═══"
    DATABASE_URL="sqlite::memory:" "$b" test "../../$P/$f.mlog" 2>&1 | grep -v GLIBC | grep -vE "REDACT" | tail -3
  done
done
