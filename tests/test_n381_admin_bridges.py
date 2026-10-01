"""Наряд №381: гварды мёртвых мостов-пачка №2 — Admin → :10000/dept/* удалён,
AdminNotifyOwner → живая TG-доставка, регрессионный фильтр класса ошибок №1.

Класс ошибок №1 (анализ v1): HTTP-мосты к эндпоинтам, которые не существуют
(reverse_proxy не форвардит /dept/*; :4000/yana/notify никогда не существовал —
#376 P3). Гвард — grep-фильтр по dept/*.mlog и app.mlog.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")

DEPT_FILES = {f.name: f.read_text(encoding="utf-8") for f in (REPO_ROOT / "dept").glob("*.mlog")}
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")

# Известные мёртвые эндпоинты (полный запрет — эти классы были вычищены)
FORBIDDEN = [
    "10000/dept/",         # reverse_proxy не форвардит /dept/*
    ":4000/yana/notify",   # эндпоинт никогда не существовал (#376 P3; :4000/dept/yana/notify — отдельный allowlist ниже)
]

# Временно допущенные места: :4000/dept/* мосты в невызванных паттернах,
# исправляются своими нарядами (KKRoute* → #382, OSPRoute* → #446).
# #446 (2026-10-02): OSPRouteToFinance/Expert/LZ/Legal вычищены по решению
# владельца (классы B+C — убрать) — allowlist пуст, гвард ждёт только регрессий.
TEMP_ALLOW = {}


def _code_lines(src: str) -> list:
    """Некомментарные строки (упоминания в комментариях не считаются)."""
    return [l for l in src.splitlines() if not l.strip().startswith("//")]


def test_admin_dead_bridges_removed():
    """AdminRouteToScheduler удалён; :10000/dept/* больше нет в admin.mlog."""
    assert "pattern AdminRouteToScheduler" not in ADMIN
    assert '10000/dept/' not in "\n".join(_code_lines(ADMIN))
    # вызов в AdminNightCycle убран, KV-путь задокументирован как живой
    assert "AdminRouteToScheduler(substring" not in ADMIN
    assert 'kv_set("admin_night_summary", report)' in ADMIN, "живой механизм маршрутизации потерян"


def test_admin_notify_owner_live():
    """AdminNotifyOwner — прямая TG-доставка (SendAdminMessage), не мёртвый роут."""
    seg = ADMIN[ADMIN.index("pattern AdminNotifyOwner"):]
    seg = seg[:seg.index("\npattern ", 10)]
    assert "SendAdminMessage(chat_id, text)" in seg
    assert "http_post" not in seg, "AdminNotifyOwner не должен ходить по HTTP-мостам"


def test_class1_grep_guard():
    """Регрессионный фильтр класса №1: мёртвые эндпоинты не появляются в mlog-коде."""
    sources = dict(DEPT_FILES, app=APP)
    offenders = []
    for name, src in sources.items():
        code = "\n".join(_code_lines(src))
        for dead in FORBIDDEN:
            if dead in code:
                offenders.append(f"{name}: {dead}")
    assert not offenders, f"мёртвые эндпоинты вернулись в код: {offenders}"


def test_temp_allowlist_exact():
    """Допущенные :4000/dept/* мосты — строго в известном количестве, пока не исполнены
    их наряды (#382 для kavalnya; osp — тот же класс, хвост отчёта #381)."""
    for fname, expected in TEMP_ALLOW.items():
        code = "\n".join(_code_lines(DEPT_FILES[fname]))
        n = code.count("4000/dept/")
        assert n == expected, f"{fname}: ожидалось {expected} мостов :4000/dept/, найдено {n} — обнови allowlist после исполнения наряда"


def test_reverse_proxy_still_no_dept_forward():
    """Инвариант класса: reverse_proxy не должен внезапно начать форвардить /dept/*
    (если начнёт — мосты ожили в обход гвардов, обнови список)."""
    rp = (REPO_ROOT / "reverse_proxy.py").read_text(encoding="utf-8")
    m = re.search(r"(?:MLOG|LLM)_ROUTES_PREFIXES\s*=\s*\[(.*?)\]", rp, re.S)
    assert m, "списки форвард-префиксов не найдены"
    prefixes = "\n".join(l for l in m.group(1).splitlines() if not l.strip().startswith("#"))
    assert '"/dept/"' not in prefixes, "reverse_proxy теперь форвардит /dept/* — мосты класса №1 изменили статус"
