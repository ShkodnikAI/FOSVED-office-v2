"""Гвард наряда #429: досье закупок — все 10 площадок, человеческие статусы,
прогрев каталога Onliner.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/429
A.1 — caption показывает все площадки (было [:5] — остальные пропадали).
A.2 — supply_pending и source_disabled формулируются человечески; пустая
      деталь не печатается.
A.3 — фоновый прогрев каталога схем Onliner: onliner_warm_catalog +
      /cron/onliner-warm (CRON_SECRET) + фон при старте (entrypoint.sh)
      + слот onliner-warm в реестре (enabled: false по протоколу №419).
Запуск: python -m pytest tests/test_n429_shop_dossier.py -v
"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from proxy.shop_dossier import (  # noqa: E402
    SOURCE_KIND_LABELS,
    humanize_source_status,
    render_caption,
)

DOSSIER = (REPO_ROOT / "proxy" / "shop_dossier.py").read_text(encoding="utf-8")
COLLECTORS = (REPO_ROOT / "proxy" / "shop_collectors.py").read_text(encoding="utf-8")
TAIL = (REPO_ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
SCHEDULES = (REPO_ROOT / "dept" / "schedules.mlog").read_text(encoding="utf-8")
ENTRYPOINT = (REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8")


# ── A.2: человеческие статусы ────────────────────────────────────────────────

def test_supply_pending_is_human(monkeypatch):
    """№598 A.2: supply_pending — живой статус связи со снабженцем.
    Детерминизм: связи не было (supplier_last_seen → None) → честное
    «недоступен», не старое статичное «ждёт выполнения» (наряд #598)."""
    monkeypatch.setattr("proxy.shop_supply.supplier_last_seen", lambda: None)
    out = humanize_source_status({"ok": False, "kind": "supply_pending",
                                  "task_id": "T1", "error": ""})
    assert "снабженец недоступен" in out, out
    assert "задание ждёт его" in out, out


def test_source_disabled_wording():
    out = humanize_source_status({"ok": False, "kind": "source_disabled"})
    assert out == "выключено в настройках", out


def test_empty_detail_not_printed():
    # сырой вид «kind: » с хвостовым двоеточием больше не возникает
    out = humanize_source_status({"ok": False, "kind": "brandnew_kind", "error": ""})
    assert not out.endswith(": "), out
    assert out == "brandnew_kind", out


def test_error_detail_still_shown():
    out = humanize_source_status({"ok": False, "kind": "transport",
                                  "error": "timeout after 10s"})
    assert "timeout after 10s" in out, out


# ── A.1: все площадки в карточке ────────────────────────────────────────────

def _snapshot(sources):
    return {
        "product": {"title": "Тест"},
        "verdict": {"score": 50, "text": "ок", "best_offer_id": None},
        "offers": [],
        "sources_display": sources,
        "badges": [],
    }


def test_caption_lists_all_sources():
    n = 10
    srcs = [{"platform": f"p{i}", "status": f"статус {i}"} for i in range(n)]
    cap = render_caption(_snapshot(srcs))
    for i in range(n):
        assert f"p{i}" in cap, f"площадка p{i} пропала из карточки"


def test_no_slice_five_left_in_caption():
    assert "sources_display\"][:5]" not in DOSSIER and "sources_display'][:5]" not in DOSSIER


# ── A.3: прогрев каталога Onliner ───────────────────────────────────────────

def test_warm_function_exists_and_persistent():
    assert "def onliner_warm_catalog(max_pages=None)" in COLLECTORS
    assert "ONLINER_SCHEMAS_TTL" in COLLECTORS.split("def onliner_warm_catalog")[1].split("def onliner_resolve_category")[0]
    # idempotent fast path: свежий полный каталог — no-op без сети
    assert '"fresh": True' in COLLECTORS


def test_warm_route_with_auth():
    assert "@app.route(\"/cron/onliner-warm\"" in TAIL
    block = TAIL.split("def cron_onliner_warm")[1][:800]
    assert "cron_secret_ok()" in block, "роут прогрева без CRON_SECRET-auth"
    assert "onliner_warm_catalog()" in block


def test_entrypoint_warms_on_start():
    assert "/cron/onliner-warm" in ENTRYPOINT
    assert "nohup" in ENTRYPOINT.split("/cron/onliner-warm")[0][-400:], \
        "прогрев при старте должен быть фоновым — бут не ждёт 240с"
    assert "--data-urlencode" in ENTRYPOINT.split("/cron/onliner-warm")[1][:200], \
        "секрет через --data-urlencode (урок №425)"


def test_registry_slot_disabled_by_protocol():
    assert "pattern OnlinerWarmSlot()" in SCHED, "слот-паттерн отсутствует в scheduler.mlog"
    assert 'name: "onliner-warm"' in SCHEDULES
    line = next(l for l in SCHEDULES.splitlines() if 'name: "onliner-warm"' in l)
    assert "enabled: false" in line, "новая запись реестра обязана быть выключенной (протокол №419)"
    assert "catch_up: \"skip\"" in line
