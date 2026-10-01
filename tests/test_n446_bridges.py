#!/usr/bin/env python3
"""#446: 12 мёртвых межотдельных мостов — решения владельца исполнены (2026-10-02).

Решение владельца по классам (бриф #446, аудит 2026-09-30):
  A — ПОСТРОИТЬ (3): /lz/telegram, /osp/inflection-alert, /archive/save —
      перенесены на живые механизмы (mlog-роут /lz/telegram :10001 по
      контракту №318; /osp/analyze :10001; SendReport → архив miniapp_responses).
  B — УБРАТЬ (3): /dept/finance/cross-check, /osp/cantillon, /osp/disruption-confirmed
      (носители вычищены вместе с вызовами).
  C — УБРАТЬ (6): /dept/expert/briefing, /dept/lz/assess, /dept/legal/regulatory,
      /finance/vc-signal, /osp/quarterly-intel, /kk/arsenal-input (двойной труп).

Гварды:
  1. Убранные URL не возвращаются в некомментарный код mlog.
  2. Построенные мосты идут на живые роуты и несут hash-form секрета (№318).
  3. Детектор мёртвых вызовов (scripts/deadcall_detector.py): 0 мёртвых,
     кроме известного префиксного ложняка /cron/ (роуты /cron/* живы).
"""
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPT_FILES = {f.name: f.read_text(encoding="utf-8") for f in (REPO_ROOT / "dept").glob("*.mlog")}
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
OSP = DEPT_FILES["osp.mlog"]
LZ = DEPT_FILES["lz.mlog"]
EXPERT = DEPT_FILES["expert.mlog"]


def _code_lines(src: str) -> str:
    """Некомментарные строки (упоминания в комментариях не считаются)."""
    return "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))


# ── 1. Убранные мосты не возвращаются ───────────────────────────────────────

REMOVED = [
    "4000/dept/finance/cross-check",
    "4000/dept/expert/briefing",
    "4000/dept/lz/assess",
    "4000/dept/legal/regulatory",
    "4000/osp/cantillon",
    "4000/osp/disruption-confirmed",
    "4000/finance/vc-signal",
    "4000/osp/quarterly-intel",
    "4000/kk/arsenal-input",
    "4000/archive/save",
    "4000/lz/telegram",
    "4000/osp/inflection-alert",
]


@pytest.mark.parametrize("dead", REMOVED)
def test_removed_bridges_stay_removed(dead):
    for name, src in dict(DEPT_FILES, app=APP).items():
        assert dead not in _code_lines(src), f"мёртвый мост {dead} вернулся в {name}"


def test_removed_carrier_patterns_gone():
    for pat in (
        "pattern OSPRouteToFinance",
        "pattern OSPRouteToExpert",
        "pattern OSPRouteToLZ(",
        "pattern OSPRouteToLegal",
        "pattern LZGateEmissionCheck",
        "pattern LZVCTracking",
        "pattern LZLifecycleTransition",
        "pattern LZQuarterlyReport",
    ):
        assert pat not in _code_lines(APP + "\n" + "\n".join(DEPT_FILES.values())), (
            f"носитель {pat} удалён по #446 (классы B+C) — не возвращать без решения владельца"
        )


# ── 2. Построенные мосты — на живые роуты ──────────────────────────────────

def test_a1_lz_telegram_route_exists():
    """Живой mlog-роут /lz/telegram (:10001) по секрет-контракту №318."""
    assert 'route "/lz/telegram" method=POST' in APP
    seg = APP[APP.index('route "/lz/telegram"'):]
    seg = seg[:seg.index("\n  route ", 10)] if "\n  route " in seg[10:] else seg
    assert "LZTelegramSearch(" in seg, "роут должен вызывать живой LZTelegramSearch"
    assert "hash_only" in seg, "секрет — по контракту №318 (hash-form)"


def test_a1_osp_tg_uses_live_route():
    """OSPTelegramSearch вызывает /lz/telegram на :10001, не мёртвый :4000."""
    seg = OSP[OSP.index("pattern OSPTelegramSearch"):]
    seg = seg[:seg.index("\npattern ", 10)]
    assert "10001/lz/telegram?secret=" in seg
    assert 'redact(env("CRON_SECRET"), "hash_only")' in seg
    assert "json_get(parse_json(result)" in seg, "ответ роута должен разбираться (JSON response)"


def test_a2_inflection_alert_via_osp_analyze():
    """LZInflectionDetect шлёт алерт в живой /osp/analyze (:10001), fire-and-forget."""
    seg = LZ[LZ.index("pattern LZInflectionDetect"):]
    seg = seg[:seg.index("\npattern ", 10)]
    assert "10001/osp/analyze?secret=" in seg
    assert '"inflection_alert"' in seg, "тип алерта должен быть маркирован в payload"
    assert "5.0)" in seg, "fire-and-forget: короткий таймаут (прецедент LZGateOSPReferral)"


def test_a3_expert_compare_uses_send_report():
    """ExpertCompareVehicles сохраняет сравнение через SendReport (архив
    miniapp_responses), не через мёртвый /archive/save."""
    seg = EXPERT[EXPERT.index("pattern ExpertCompareVehicles"):]
    seg = seg[:seg.index("\npattern ", 10)]
    code = _code_lines(seg)
    assert "SendReport(" in code, "сравнение должно уходить в общий исходящий путь SendReport"
    assert "4000/archive/save" not in code


# ── 3. Детектор мёртвых вызовов ─────────────────────────────────────────────

def test_deadcall_detector_zero_dead_bridges():
    """Детектор (base = рабочее дерево): из мёртвых допустим только /cron/ —
    известный ложняк на префиксный вызов (роуты /cron/* живы, вне наряда)."""
    out = subprocess.run(
        ["python3", "scripts/deadcall_detector.py"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    ).stdout
    dead_lines = [
        line.strip().split("<-")[0].strip()
        for line in out.splitlines()
        if "МЁРТВЫЕ ВЫЗОВЫ" in line or (line.strip().startswith("/") and "Flask" not in line)
    ]
    dead_lines = [d for d in dead_lines if d.startswith("/")]
    # после маркера остаются только пути с источниками
    dead_lines = [d for d in out.splitlines() if d.strip().startswith("/") and "←" in d]
    paths = [d.split("←")[0].strip() for d in dead_lines]
    unexpected = [p for p in paths if p != "/cron/"]
    assert not unexpected, f"мёртвые вызовы вернулись: {unexpected}"
    assert "/cron/" in paths, "ложняк /cron/ должен остаться единственным (префиксный матч)"
