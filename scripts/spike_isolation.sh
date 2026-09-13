#!/usr/bin/env bash
# FO-044 (наряд #151): спайк изоляции прогонов FORGE — измерения исполнением.
# Проверяет под реальным окружением (где запущен скрипт):
#   A.1  ulimit -v (RLIMIT_AS) поверх env -i для python/node — работает ли,
#        при каком пороге, не ломает ли рантаймы с щедрой виртуальной памятью;
#   A.2  unshare -n / unshare -Urn — доступен ли, изолирует ли сеть;
#   A.3  матрица «что ограничиваемо сегодня / что только контейнером».
# Воспроизведение на Render: docker exec <svc> bash scripts/spike_isolation.sh
set -u

echo "=== FO-044 spike: изоляция прогонов ==="
echo "окружение: $(uname -sr), $(nproc) cpu, RAM avail: $(awk '/MemAvailable/ {printf "%.0f МБ", $2/1024}' /proc/meminfo)"
echo "CapEff: $(grep CapEff /proc/self/status | awk '{print $2}') (0000000000000000 = capabilities нет вовсе)"
echo

echo "── A.2 unshare (отсечь сеть прогону) ──"
UNSHARE="nogo"
if unshare -n true 2>/dev/null; then
    echo "  [ok] unshare -n доступен (CAP_SYS_ADMIN есть — не ждём на Render)"
    UNSHARE="go"
else
    echo "  [no] unshare -n отклонён (rc=$?) — ожидаемо без CAP_SYS_ADMIN"
fi
URN="nogo"
if unshare -Urn true 2>/dev/null; then
    echo "  [ok] unshare -Urn (user+net ns) доступен — обходной путь есть"
    URN="go"
else
    echo "  [no] unshare -Urn отклонён (rc=$?) — user namespaces недоступны"
fi
# верификация изоляции: внутри -Urn снаружи не достучаться, внутри — жить
if [ "$URN" = "go" ]; then
    inner_net=$(unshare -Urn bash -c '
        ip link set lo up 2>/dev/null || ifconfig lo up 2>/dev/null
        # снаружи недоступно: адреса новые, интерфейса с маршрутом нет
        (timeout 3 python3 -c "import urllib.request; urllib.request.urlopen(\"https://example.com\", timeout=2)" 2>/dev/null && echo "NET-ХОДИТ" || echo "NET-ОТСЕЧЕНА")
        # loopback внутри ns живёт
        (python3 -m http.server 8123 --bind 127.0.0.1 >/dev/null 2>&1 &
        sleep 1
        timeout 3 python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8123\", timeout=2).status)" 2>/dev/null || echo "LOOPBACK-МЁРТВ")
    ' 2>/dev/null)
    echo "  └─ верификация: $(echo "$inner_net" | tr '\n' ' ')"
fi
echo

echo "── A.1 ulimit -v (RLIMIT_AS) поверх env -i (рецепт ForgeRun) ──"
# probe <label> <limit_kb> <cmd...> — квотинг через bash -c ... "$@" scaffold
probe() {
    local label="$1"; shift; local limit="$1"; shift
    local out rc
    out=$(timeout 25 bash -c 'ulimit -v '"$limit"' 2>/dev/null || exit 97; timeout 18 env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp "$@"' probe_scaffold "$@" 2>&1); rc=$?
    case "$rc" in
        0)   echo "  [ok]   ${label}: rc=0 $(echo "$out" | head -1 | cut -c1-60)" ;;
        124) echo "  [ok*]  ${label}: работал до таймаута (сервер жив под лимитом)" ;;
        97)  echo "  [no]   ${label}: ulimit отклонён ядром" ;;
        *)   echo "  [kill] ${label}: rc=${rc} $(echo "$out" | head -1 | cut -c1-70)" ;;
    esac
}

# python: минимальный скрипт на разных порогах
probe "python print    @ 256МБ" 262144 python3 -c "print('py-ok')"
probe "python print    @ 128МБ" 131072 python3 -c "print('py-ok')"
probe "python print    @ 64МБ"  65536  python3 -c "print('py-ok')"
probe "python print    @ 32МБ"  32768  python3 -c "print('py-ok')"
# python: http.server (сценарий живого превью)
probe "http.server     @ 256МБ" 262144 python3 -m http.server 8199 --bind 127.0.0.1
# python: прожорливый — обязан упасть по лимиту (путь kill-а)
probe "python hog 512МБ @ 256МБ" 262144 python3 -c "b'x' * (512*1024*1024)"
# node: минимальный скрипт (резервирует VA щедро — порог по измерению)
probe "node minimal    @ 2ГБ"  2097152 node -e "console.log('node-ok')"
probe "node minimal    @ 1.5ГБ" 1572864 node -e "console.log('node-ok')"
probe "node minimal    @ 1.3ГБ" 1331200 node -e "console.log('node-ok')"
probe "node minimal    @ 1ГБ"  1048576 node -e "console.log('node-ok')"
# node: http.server (превью node-проекта)
probe "node http       @ 2ГБ"  2097152 node -e "require('http').createServer((q,s)=>s.end('ok')).listen(8198,'127.0.0.1',()=>console.log('listening'))" 
echo

echo "── фактическая VA без лимита ──"
node -e "const s=require('fs').readFileSync('/proc/self/status','utf8'); const m=s.match(/VmSize:\s+(\d+)/); console.log('  node   VmSize:', m?Math.round(m[1]/1024)+' МБ':'?')" 2>/dev/null || true
python3 -c "
s=open('/proc/self/status').read()
for l in s.splitlines():
    if l.startswith('VmSize'): print('  python VmSize:', round(int(l.split()[1])/1024), 'МБ')" 2>/dev/null || true
echo

echo "── вывод для матрицы (A.3) ──"
echo "UNSHARE_NET=${UNSHARE} UNSHARE_URN=${URN}"
