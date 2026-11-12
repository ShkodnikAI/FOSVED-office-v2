#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #711 KK-1.1: живучесть отбора вопросов Кавальни, план дня по БД.

Гварды (mlog-тесты в dept/kk_training.mlog покрывают живое поведение
KKSelectValid/KKInsertPicked/KKDeptDetails; здесь — структурные гварды
app.mlog-частей, которые нельзя гнать живьём без LLM/сети):

- A.1: все преобразования полей вопроса в KKSelectValid — под TryVal;
  кривое поле → метка в kk_rej_flat, не бросок;
- A.2: KKAskForDept — сбой разбора генерации получает ту же одну
  регенерацию (с проверкой бюджета), итог «сбой разбора генерации →
  регенерация: N из плана»; стадия 1 вставляет одобренное ДО регенерации;
- A.3: план дня — по БД (KKAskedToday → kk_questions, date(asked_at));
  повторный прогон — audit «повторный прогон, добор N»; kv-накопители
  kk_acc_* не читаются и не пишутся; KKDayUtc — настоящая UTC-дата
  (эпоха-префикс менял ключ каждую секунду);
- A.4: маршрут /kk <dept> подробно → KKDeptDetails (текст, не карточка).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n711')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
KK = (REPO_ROOT / "dept" / "kk_training.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def _pattern_src(text: str, name: str) -> str:
    """Текст паттерна NAME — до следующего 'pattern '/'test ' на границе строки."""
    start = text.index(f"pattern {name}")
    for stop in ("\npattern ", "\ntest ", "\nflow "):
        nxt = text.find(stop, start + 1)
        if nxt != -1:
            return text[start:nxt]
    return text[start:]


# ─────────────────────────── A.1: отбор не падает ───────────────────────────

class TestA1TryValOnFields:
    def test_horizon_under_tryval(self):
        sel = _pattern_src(KK, "KKSelectValid")
        assert 'horizon_v = TryVal(try to_float(to_string(json_get(q, "horizon_days", "0"))))' in sel
        # мутация «убрать try»: голого to_float на horizon_days больше нет
        assert 'let horizon = to_float(to_string(json_get(q, "horizon_days"' not in sel

    def test_kind_text_url_under_tryval(self):
        sel = _pattern_src(KK, "KKSelectValid")
        for f in ("kind", "text", "source_url"):
            assert f'TryVal(try to_string(json_get(q, "{f}", ""))' in sel, f

    def test_reject_labels_present(self):
        sel = _pattern_src(KK, "KKSelectValid")
        assert '"horizon_days не число"' in sel
        assert '"поле не читается"' in sel
        reasons = _pattern_src(KK, "KKReasonsFrom")
        assert '"horizon_days не число"' in reasons
        assert '"поле не читается"' in reasons


# ─────────────────── A.2: регенерация после сбоя разбора ───────────────────

class TestA2RegenAfterParseFail:
    def test_parse_fail_flag_and_regen_condition(self):
        fn = _pattern_src(APP, "KKAskForDept")
        assert "parse_fail" in fn
        # регенерация: единое условие по БД (недобор ИЛИ сбой разбора —
        # при сбое вставлено 0, значит asked < план), не только missing > 0
        assert "if KKAskedToday(dept) < plan_today then {" in fn
        # старое условие «только недобор по missing» не возвращается
        assert "if missing > 0.0 then {" not in fn

    def test_summary_line_format(self):
        fn = _pattern_src(APP, "KKAskForDept")
        assert "сбой разбора генерации → регенерация: 0 из" in fn
        assert 'сбой разбора генерации → регенерация: " + to_string(asked)' in fn

    def test_regen_has_budget_check(self):
        fn = _pattern_src(APP, "KKAskForDept")
        i_regen = fn.index("if KKAskedToday(dept) < plan_today then {")
        i_budget = fn.index("KKBudgetOk(KKCallCost())", i_regen)
        i_call = fn.index("call_llm(", i_regen)
        assert i_regen < i_budget < i_call, "бюджет проверяется до второго вызова LLM"

    def test_stage1_inserts_before_regen(self):
        fn = _pattern_src(APP, "KKAskForDept")
        i_ins1 = fn.index("KKInsertPicked(")
        i_regen = fn.index("if KKAskedToday(dept) < plan_today then {")
        assert i_ins1 < i_regen, "стадия 1 вставляет одобренное ДО регенерации (БД-счётчик)"


# ─────────────────── A.3: план дня по БД, а не по kv ───────────────────

class TestA3PlanFromDb:
    def test_kkaskedtoday_counts_db(self):
        fn = _pattern_src(KK, "KKAskedToday")
        assert "kk_questions" in fn
        assert "date(asked_at) = date('now')" in fn
        assert "kv_get" not in fn

    def test_select_valid_no_kv_accumulators(self):
        sel = _pattern_src(KK, "KKSelectValid")
        # точечно: чтение/запись kv-накопителей (комментарий упоминает kk_acc — это история)
        assert 'kv_get("kk_acc' not in sel, "kv-накопители kk_acc_* не читаются (№711 A.3)"
        assert 'kv_set("kk_acc' not in sel, "kv-накопители kk_acc_* не пишутся (№711 A.3)"
        assert "date(asked_at) = date('now')" in sel

    def test_rerun_logged_and_capped(self):
        fn = _pattern_src(APP, "KKAskForDept")
        assert "повторный прогон, добор 0 — план" in fn
        assert 'повторный прогон, добор " + to_string' in fn
        # ранний выход: план выполнен — генерации нет вовсе
        i_check = fn.index("KKAskedToday(dept)")
        i_llm = fn.index("call_llm(")
        assert i_check < i_llm

    def test_kkdayutc_is_real_date(self):
        day = _pattern_src(KK, "KKDayUtc")
        assert "date('now')" in day
        # мутация «вернуть эпоху-префикс» — красный
        assert "substring(to_string(now())" not in day

    def test_insert_picked_returns_items_and_dups(self):
        ins = _pattern_src(KK, "KKInsertPicked")
        assert "KKInsertQuestion(" in ins
        assert "items:" in ins and "dups:" in ins
        # ответов отделов здесь нет — наряд C живёт в KKAskForDept
        assert "KKAnswerOne" not in ins


# ─────────────────── A.4: причины видны владельцу ───────────────────

class TestA4DetailsCommand:
    def test_route_present_near_kk(self):
        assert 'd_word == "подробно"' in APP
        assert "KKDeptDetails(d_dept)" in APP
        i_kk = APP.index('if text == "/kk" or starts_with(text, "/kk ")')
        i_route = APP.index('d_word == "подробно"')
        assert i_kk < i_route < i_kk + 4000, "маршрут — рядом с /kk"

    def test_usage_mentions_details(self):
        assert "/kk <dept> подробно — причины" in APP

    def test_details_sections(self):
        det = _pattern_src(KK, "KKDeptDetails")
        assert "Провалы формы" in det
        assert "Спорные исходы" in det
        assert "План дня" in det
        assert "За 4 недели" in det
        # провал формы: вопрос + note из kk_answers
        assert "trim(a.note) != ''" in det
        # спорный: вопрос, правило, evidence_url, причина
        assert "o.evidence_quote" in det
        assert "o.evidence_url" in det
        # числа сводки — из KKStats24h (подсчёт один), не свои COUNT
        assert "KKStatsRaw()" in det

    def test_details_no_own_aggregate_counts(self):
        det = _pattern_src(KK, "KKDeptDetails")
        assert "COUNT(*)" not in det, "агрегаты — из KKStatsRaw/KKDeptStats, не второй подсчёт"
