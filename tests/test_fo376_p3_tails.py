"""Наряд №376 (P3): гварды хвостов — expert API, маршрутизация /api/lz/,
quickexpert/deepexpert, честный /status, dept-циклы в schedules, промпт-гигиена.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
PROXY = (REPO_ROOT / "reverse_proxy.py").read_text(encoding="utf-8")
SCHED = (REPO_ROOT / "dept" / "schedules.mlog").read_text(encoding="utf-8")
SCHEDULER = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")

EXPERT_ROUTES = [
    ('route "/api/expert/automotive" method=GET', "ExpertAutomotiveLookup"),
    ('route "/api/expert/compare" method=GET', "ExpertCompareVehicles"),
    ('route "/api/expert/residual-value" method=GET', "ExpertResidualValueData"),
    ('route "/api/expert/operation-cost" method=GET', "ExpertOperationCostData"),
    ('route "/api/expert/chart" method=POST', "ExpertGenerateChart"),
    ('route "/api/expert/briefings" method=GET', "ExpertListBriefings"),
    ('route "/api/expert/briefing" method=POST', "ExpertCreateBriefing"),
]


def test_expert_api_routes_restored():
    """7 обёрток /api/expert/* живут в mlogserver-блоке app.mlog (TODO :804 закрыт)."""
    for decl, handler in EXPERT_ROUTES:
        assert decl in APP, f"нет {decl}"
        assert handler in APP, f"нет вызова {handler}"


def test_reverse_proxy_api_lz_routes_to_python():
    """/api/lz/* — Python-слой (routes_admin.py); форвардинг в mlog заслонял живые эндпоинты."""
    def _list_block(src, name):
        seg = src[src.index(name + " = ["):]
        seg = seg[:seg.index("]")]
        # только некомментарные строки — упоминания в # №376-комментариях не считаются
        return "\n".join(l for l in seg.splitlines() if not l.strip().startswith("#"))
    mlog_block = _list_block(PROXY, "MLOG_ROUTES_PREFIXES")
    llm_block = _list_block(PROXY, "LLM_ROUTES_PREFIXES")
    assert '"/api/lz/"' not in mlog_block, "/api/lz/ не должен форвардиться в mlog"
    assert '"/api/lz/"' in llm_block, "/api/lz/ должен идти на Python-слой (:4000)"
    assert '"/api/expert/"' in mlog_block, "/api/expert/ остаётся mlog-префиксом"


def test_quickexpert_deepexpert_dispatch():
    """Диспетчер мапит /quickexpert и /deepexpert в эксперт-трек (dept/expert.mlog парсит оба)."""
    start = APP.index("pattern DetectDepartment")
    block = APP[start:APP.index("\npattern ", start + 10)]
    assert 'starts_with(text, "/quickexpert")' in block
    assert 'starts_with(text, "/deepexpert")' in block


def test_status_no_hardcoded_all_online():
    assert 'Departments: yana, osp\nAll 14 online' not in APP and "All 14 online.\nVoice" not in APP, \
        "/status не должен утверждать ложный статус (упоминание в комментарии №376 допустимо)"


def test_dept_cycle_slots_registered_disabled():
    """13 dept-слотов в schedules.mlog — enabled: false до решения владельца (№419)."""
    expected = [
        "finance-daily", "finance-monthly", "finance-quarterly",
        "legal-daily", "legal-monthly", "legal-quarterly",
        "engineering-weekly", "engineering-monthly", "engineering-quarterly",
        "marketing-daily", "marketing-monthly", "marketing-quarterly",
        "lz-digest-native",
    ]
    for name in expected:
        m = re.search(r'\{ name: "%s".*?enabled: (\w+)' % name, SCHED)
        assert m, f"нет слота {name} в schedules.mlog"
        assert m.group(1) == "false", f"слот {name} должен быть enabled: false"
        # target-паттерн существует в scheduler.mlog
        tm = re.search(r'target: "(\w+)".*?enabled: false \}', SCHED[SCHED.index(f'name: "{name}"'):SCHED.index(f'name: "{name}"') + 220])
        assert tm, f"не распарсить target слота {name}"
        assert f"pattern {tm.group(1)}()" in SCHEDULER, \
            f"нет паттерна {tm.group(1)} в scheduler.mlog"


def test_no_dead_yana_notify_endpoint():
    """:4000/yana/notify — эндпоинт никогда не существовал (класс №1).
    (Вызов в dept/kavalnya.mlog:473 — мёртвый мост KKRouteToYana — территория #382.)
    """
    lz_code = "\n".join(l for l in (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8").splitlines() if not l.strip().startswith("//"))
    assert "yana/notify" not in lz_code, "lz.mlog всё ещё зовёт мёртвый :4000/yana/notify"


def test_prompt_hygiene():
    """upravlenie.md удалён (мёртвый дубль Яны); JS-фантом archive-publisher вычищен."""
    assert not (REPO_ROOT / "library" / "upravlenie.md").exists()
    fin = (REPO_ROOT / "library" / "finance.md").read_text(encoding="utf-8")
    assert "archive-publisher.js" not in fin
    assert "FinancialForecast" not in fin
