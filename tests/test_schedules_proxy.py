"""№426: гварды — различимый HTTP-код бутстрапа (entrypoint) + санкционированный
passthrough /schedules/list|bootstrap (proxy).

Бут 2026-09-23T07:29Z: bootstrap «no answer»×3 — 403/404/таймаут слились в одну
строку, причина из лога не видна (гейт ① кутовера на нативный cron заблокирован).
Anti-copy-drift на источники: entrypoint.sh и proxy/routes_tail.py.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_entrypoint_bootstrap_logs_http_code():
    src = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    # №426: код ответа appended к каждой попытке и к финальному вердикту
    assert "-w $'\\n%{http_code}'" in src, "curl обязан добавлять HTTP-код (-w)"
    assert "HTTP ${BOOT_CODE:-conn-fail}" in src, "попытки/вердикт должны печатать код"
    # 2xx-фильтр: тело не-2xx не попадает в BOOT_REPORT (не путать с отчётом)
    assert "case \"$BOOT_CODE\" in" in src and "2*) : ;;" in src
    # Контракт №425 не тронут: -G + --data-urlencode, сырой вставки секрета нет
    assert '-G "http://127.0.0.1:10001/schedules/bootstrap"' in src
    assert re.search(r"schedules/bootstrap\?secret=", src) is None


def test_proxy_passthrough_guarded():
    src = (ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")
    assert '@app.get("/schedules/list")' in src
    assert '@app.get("/schedules/bootstrap")' in src
    # оба passthrough за cron_secret_ok (паттерн №425: decoded-OR-raw)
    for block in re.split(r'@app\.get\("/schedules/', src)[1:]:
        head = block.split("@app")[0]
        assert "cron_secret_ok()" in head, "passthrough обязан быть за cron_secret_ok()"
    # create/remove сознательно НЕ экспонируются (админ-домен, mlog-internal)
    assert '@app.get("/schedules/create")' not in src
    assert '@app.post("/schedules/create")' not in src
    assert '@app.get("/schedules/remove")' not in src
