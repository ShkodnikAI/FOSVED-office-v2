"""Наряд #638 (A5): размеченный набор маршрутизации — сбор кодом на проде,
утверждение кнопками, freeze версии с ~30% holdout.

Структурные гвардии; поведенческие проверки — mlog-тесты dept/route_eval.mlog
и python-тесты detect_dept_ranking.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_EVAL = (REPO_ROOT / "dept" / "route_eval.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
CORE = (REPO_ROOT / "proxy" / "core.py").read_text(encoding="utf-8")
ROUTES = (REPO_ROOT / "proxy" / "routes_core.py").read_text(encoding="utf-8")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _block(src: str, start_marker: str) -> str:
    start = src.index(start_marker)
    nxt = src.find("\npattern ", start + 10)
    nxt2 = src.find("\ntest ", start + 10)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return src[start:min(ends)] if ends else src[start:]


def test_table_schema_exact():
    """A.1: таблица route_eval_set — колонки по букве наряда."""
    assert "CREATE TABLE IF NOT EXISTS route_eval_set" in ROUTE_EVAL
    for col in ("text_hash", "text_redacted", "dept_proposed", "dept_expected",
                "status", "version", "holdout", "created_at", "decided_at"):
        assert re.search(rf"\b{col}\b", ROUTE_EVAL[: ROUTE_EVAL.index("route_eval_hash")]), \
            f"нет колонки {col}"
    assert "candidate" in ROUTE_EVAL and "corrected" in ROUTE_EVAL and "rejected" in ROUTE_EVAL


def test_collection_owner_only_source():
    """A.2: источник — dialog_history role='user' (сообщения владельца по chat_id)."""
    sel = _block(ROUTE_EVAL, "pattern RouteSelectBatch(")
    assert "role = 'user'" in sel and "chat_id = ?1" in sel


def test_redact_pipeline():
    """A.2: text_redacted = redact «all» + маскирование телефонов и почты."""
    assert "pattern RouteMaskPII(" in ROUTE_EVAL
    red = _block(ROUTE_EVAL, "pattern RouteRedactText(")
    assert "RouteMaskPII(" in red and 'redact(text, "all")' in red
    # маска: токен с @ → email; 10+ цифр → phone
    mask = _block(ROUTE_EVAL, "pattern RouteMaskPII(")
    assert '"<email>"' in mask and '"<phone>"' in mask
    assert "RouteDigitsOnly(" in mask


def test_dept_proposed_battle_routing():
    """A.2: dept_proposed — боевой маршрутизатор DetectDepartment."""
    prop = _block(ROUTE_EVAL, "pattern RouteProposed(")
    assert "DetectDepartment(" in prop
    # дефолт честно: пустой ответ боевого маршрутизатора → yana
    assert '"yana"' in prop


def test_python_ranking_endpoint():
    """A.2: /detect-dept/scores — тот же боевой скоринг с полным рейтингом."""
    assert "def detect_dept_ranking(" in CORE
    assert "def detect_dept(text):\n    return detect_dept_ranking(text)[0]" in CORE
    assert '"/detect-dept/scores"' in ROUTES
    assert "detect_dept_ranking(text)" in ROUTES


def test_review_buttons():
    """A.3: кнопки — подтверждение, 3 альтернативы, «другой…», «убрать»."""
    review = APP[APP.index("starts_with(text, \"/route-review\")"): APP.index("starts_with(text, \"/route-dept \")")]
    assert 'callback_data: "rq:" + id_s + ":ok"' in review
    assert '"другой…"' in review and '"убрать"' in review
    # 3 альтернативы из одного источника
    assert "RouteAlternatives(proposed)" in review
    alts = _block(ROUTE_EVAL, "pattern RouteAlternatives(")
    assert "RouteDepts()" in alts
    # запись решения — один писатель
    assert "pattern RouteWriteDecision(" in ROUTE_EVAL


def test_callback_owner_gate():
    """A.3: нажатие rq: — только владелец (та же проверка, что у rt:)."""
    cb = APP[APP.index('starts_with(cb_data, "rq:")'):]
    cb = cb[: cb.index("return respond") + 20]
    assert "OWNER_TELEGRAM_ID" in cb
    assert "callback_query.from.id" in cb


def test_freeze_gate_and_holdout():
    """A.4: freeze — от 100 утверждённых; holdout ~30% по text_hash; неизменяемость."""
    fz = _block(ROUTE_EVAL, "pattern RouteFreeze(")
    assert "n < 100.0" in fz
    assert "ORDER BY text_hash ASC" in fz
    assert "уже зафиксирована" in fz
    # доля holdout — около 30%
    assert "0.3" in fz
    wd = _block(ROUTE_EVAL, "pattern RouteWriteDecision(")
    assert '"frozen"' in wd


def test_one_off_slot_self_removing():
    """A.2: сбор — разовым заданием планировщика, самоснимающимся, вебхук сразу."""
    slot = _block(APP, "pattern RouteCandidatesSlot()")
    assert "cron_remove(" in slot
    assert "RouteSelectBatch(" in slot
    ensure = _block(APP, "pattern RouteCronEnsure()")
    assert '"RouteCandidatesSlot"' in ensure and "cron_add(" in ensure
    assert "Сбор кандидатов запущен" in APP


def test_docs_mention_route_eval():
    """/help и README перечисляют команды разметки."""
    assert "/route-candidates" in APP and "/route-review" in APP
    assert "/route-candidates" in README and "/route-review" in README and "freeze v1" in README
