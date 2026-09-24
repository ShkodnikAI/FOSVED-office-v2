#!/bin/bash
# №349: прогон всех try-фикстур на всех трёх бинарях через `mlog run`.
# Результат: /home/z/my-project/n349-results/tryrun_matrix.txt
set -u
RES=/home/z/my-project/n349-results
FIX=$RES/tryfix
python3 /home/z/my-project/scripts/gen_tryfixtures.py

echo "test-body-1234" > /tmp/ok.txt
python3 -m http.server 9911 --bind 127.0.0.1 --directory /tmp >/dev/null 2>&1 &
HS=$!
sleep 0.7

: > $RES/tryrun_matrix.txt
for BV in 019:/home/z/my-project/FOSVED-office-v2/bin/mlog \
          021:/home/z/my-project/FOSVED-office-v2/bin/mlog-021 \
          022:/home/z/my-project/mlog-build-v022/target/release/mlog; do
  VER="${BV%%:*}"; BIN="${BV#*:}"
  echo "=== binary $VER ===" >> $RES/tryrun_matrix.txt
  for FX in $FIX/*.mlog; do
    NAME=$(basename "$FX" .mlog)
    OUT=$(METALOGOS_HTTP_ALLOW_PRIVATE=1 METALOGOS_SERVE_ALLOW_ENV=1 timeout 30 "$BIN" run "$FX" 2>&1 | tr '\n' ' ' | head -c 300)
    echo "$NAME -> ${OUT:-<empty>}" >> $RES/tryrun_matrix.txt
  done
done

kill $HS 2>/dev/null
cat $RES/tryrun_matrix.txt
