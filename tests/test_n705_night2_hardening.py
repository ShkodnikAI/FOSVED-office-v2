#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #705 NIGHT-2 (P1): гварды hardening'а AdminNightCycle.

Прод-факт 11.11: ночная проверка partial — «Phase 3: недоступна (AdminNightCycle
упал — детали в audit_log)». Внутри AdminNightCycle фазы 3/4/5 (AdminMetricsAnalysis/
AdminAutoFix/AdminProposals) вызывались без try, их внутренние query/read_file/
db_execute/kv_set/AuditLog — без TryVal: одна ошибка (прод-класс «database is
locked») роняла весь цикл, а «детали в audit_log» не писались — крошек между
night_cycle_start и night_cycle_done не было.

Гварды (идиома test_n485 — структурные проверки кода, мутации обязаны краснеть):
- A.1: вызовы фаз 3/4/5 в AdminNightCycle — под try;
- A.2: крошки AuditLog("night_cycle_phase") для фаз 3/4/5 + гвард сохранения;
- A.3: kv_set("admin_last_health") между Phase 2 и Phase 3 (ранняя запись);
- A.4: в фазах-паттернах нет голых query/db_execute/read_file/kv_set/AuditLog;
      мёртвые let-фолбэки убраны; разбор плана — в AdminParseAutofixPlan.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")


def _code_lines(seg: str) -> list:
    """Некомментарные строки (упоминания в комментариях не считаются)."""
    return [l for l in seg.splitlines() if not l.strip().startswith("//")]


def _segment(src: str, pattern_decl: str) -> str:
    """Тело одного паттерна: от 'pattern NAME' до следующего 'pattern '."""
    start = src.index(pattern_decl)
    rest = src[start + len(pattern_decl):]
    nxt = rest.find("\npattern ")
    return rest[:nxt] if nxt != -1 else rest


def _check_phases_wrapped(admin_src: str) -> list:
    """A.1: вызовы AdminMetricsAnalysis/AdminAutoFix/AdminProposals в
    AdminNightCycle — только под try; честные строки 'недоступна ('."""
    v = []
    seg = "\n".join(_code_lines(_segment(admin_src, "pattern AdminNightCycle")))
    for call in ("AdminMetricsAnalysis()", "AdminAutoFix(", "AdminProposals()"):
        lines = [l for l in seg.splitlines() if call in l and "pattern " not in l]
        if not lines or not any(f"try {call}" in l for l in lines):
            v.append(f"A.1: вызов {call} не под try в AdminNightCycle")
    if "недоступна (" not in seg:
        v.append("A.1: нет честной строки о сбое фазы в AdminNightCycle")
    return v


def _check_phase_crumbs(admin_src: str) -> list:
    """A.2: крошки night_cycle_phase для фаз 3/4/5 — С ДИНАМИЧЕСКИМ статусом
    (pN_status, не статичная строка); аудит старта/финала и сохранения —
    под TryVal."""
    v = []
    seg = "\n".join(_code_lines(_segment(admin_src, "pattern AdminNightCycle")))
    for ph, var in (("phase=3", "p3_status"), ("phase=4", "p4_status"), ("phase=5", "p5_status")):
        if f'AuditLog("night_cycle_phase", "admin", "{ph}' not in seg:
            v.append(f"A.2: нет крошки {ph} в audit_log")
        elif f'" + {var})' not in seg:
            v.append(f"A.2: крошка {ph} без динамического статуса {var}")
    if 'TryVal(try AuditLog("night_cycle_start"' not in seg:
        v.append("A.2: night_cycle_start не под TryVal")
    if 'TryVal(try AuditLog("night_cycle_done"' not in seg:
        v.append("A.2: night_cycle_done не под TryVal")
    if 'TryVal(try db_execute("INSERT INTO admin_reports' not in seg:
        v.append("A.2: INSERT admin_reports не под TryVal")
    return v


def _check_health_early(admin_src: str) -> list:
    """A.3: первая запись admin_last_health — после Phase 2 (вычисление
    health_score) и до Phase 3; под TryVal."""
    v = []
    seg = _segment(admin_src, "pattern AdminNightCycle")
    code = "\n".join(_code_lines(seg))
    kv_pos = code.find('kv_set("admin_last_health"')
    h_pos = code.find('json_get(parse_json(review_ok), "health_score"')
    p3_pos = code.find("try AdminMetricsAnalysis()")
    if kv_pos == -1:
        v.append("A.3: kv_set admin_last_health исчез из AdminNightCycle")
    elif not (h_pos != -1 and h_pos < kv_pos < p3_pos):
        v.append("A.3: kv_set admin_last_health не между Phase 2 и Phase 3")
    if 'TryVal(try kv_set("admin_last_health"' not in code:
        v.append("A.3: ранняя kv_set admin_last_health не под TryVal")
    return v


_DBOPS = ("query(", "db_execute(", "read_file(", "kv_set(", "AuditLog(")


def _check_no_naked_dbops(admin_src: str) -> list:
    """A.4: в фазах-паттернах небазовые операции — только под try/TryVal."""
    v = []
    for decl in ("pattern AdminMetricsAnalysis()",
                 "pattern AdminAutoFix(",
                 "pattern AdminProposals()"):
        seg = "\n".join(_code_lines(_segment(admin_src, decl)))
        for l in seg.splitlines():
            s = l.strip()
            for op in _DBOPS:
                if op in s and "try " + op not in s and "TryVal(try " not in s:
                    v.append(f"A.4: голый {op} в {decl.split()[1]}: {s[:70]}")
    return v


def _check_dead_fallbacks_gone(admin_src: str) -> list:
    """A.4: мёртвые let-фолбэки убраны — В ГРАНИЦАХ НАРЯДА (фазы 3/4/5,
    AdminNightCycle, AdminParseAutofixPlan). Донарядные вхождения того же
    класса в других паттернах admin.mlog — вне границ, сигналом в отчёт."""
    v = []
    in_scope = []
    for decl in ("pattern AdminMetricsAnalysis()", "pattern AdminAutoFix(",
                 "pattern AdminProposals()", "pattern AdminNightCycle",
                 "pattern AdminParseAutofixPlan"):
        in_scope.extend(_code_lines(_segment(admin_src, decl)))
    for l in in_scope:
        if re.search(r"then\s*\{\s*let\s+\w+\s*=", l):
            v.append(f"A.4: let-присваивание внутри then-блока (затенение): {l.strip()[:70]}")
    return v


def _check_parse_extracted(admin_src: str) -> list:
    """A.4: разбор плана — AdminParseAutofixPlan; гейты внутри; SKIP-ветка."""
    v = []
    if "pattern AdminParseAutofixPlan" not in admin_src:
        v.append("A.4: нет паттерна AdminParseAutofixPlan")
        return v
    seg = "\n".join(_code_lines(_segment(admin_src, "pattern AdminParseAutofixPlan")))
    af = "\n".join(_code_lines(_segment(admin_src, "pattern AdminAutoFix(")))
    if "AdminParseAutofixPlan(plan)" not in af:
        v.append("A.4: AdminAutoFix не вызывает AdminParseAutofixPlan")
    if "AdminGateAutoFix" not in seg:
        v.append("A.4: DENY-гейты потеряны из разбора плана")
    if "SKIP (нет перевода строки)" not in seg:
        v.append("A.4: нет честного SKIP для сегмента без перевода строки")
    if '"No autofixes needed"' not in seg:
        v.append("A.4: ветка NONE потеряна")
    return v


ALL_CHECKS = (_check_phases_wrapped, _check_phase_crumbs, _check_health_early,
              _check_no_naked_dbops, _check_dead_fallbacks_gone, _check_parse_extracted)


def _violations(admin_src: str) -> list:
    out = []
    for chk in ALL_CHECKS:
        out.extend(chk(admin_src))
    return out


def test_n705_all_guards_green_on_main():
    """Все гварды зелёные на текущем dept/admin.mlog."""
    v = _violations(ADMIN)
    assert not v, "нарушения гвардов #705:\n" + "\n".join(v)


# ── мутационный самотест: каждая мутация обязана краснеть ──

def test_mutation_unwrapped_phase3():
    m = ADMIN.replace("let tr_metrics = try AdminMetricsAnalysis()",
                      "let tr_metrics = AdminMetricsAnalysis()", 1)
    assert m != ADMIN, "мутация не применилась"
    assert any("A.1" in x for x in _violations(m)), "мутация без try не поймана"


def test_mutation_crumbs_removed():
    m = ADMIN.replace('AuditLog("night_cycle_phase", "admin", "phase=3 metrics " + p3_status)',
                      'AuditLog("night_cycle_phase", "admin", "phase=3 metrics ok")', 1)
    assert m != ADMIN
    # крошка с реальным статусом важна: подменяем на статичную строку — гвард полноты
    assert any("A.2" in x for x in _violations(m)), "мутация крошки не поймана"


def test_mutation_health_kv_back_to_phase7():
    """Возврат kv_set в конец (после Phase 3) — гвард ранней записи краснеет.
    №707 A.2: рядом с записью здоровья теперь и admin_last_health_ts —
    мутация убирает ОБЕ строки ранней записи (после фазы 2)."""
    seg_old = ('  let _ = TryVal(try kv_set("admin_last_health", health))\n'
               '  let _ = TryVal(try kv_set("admin_last_health_ts", to_string(now())))\n'
               '\n  // Phase 3: Metrics Analysis')
    seg_new = '\n  // Phase 3: Metrics Analysis'
    m = ADMIN.replace(seg_old, seg_new, 1)
    assert m != ADMIN, "мутация не применилась"
    assert any("A.3" in x for x in _violations(m)), "мутация позднего kv_set не поймана"


def test_mutation_dead_let_fallback_returned():
    m = ADMIN.replace(
        'if to_string(llm_result) == "()" then { return "Сервис временно недоступен." }\n  let reply = to_string(llm_result)',
        'if to_string(llm_result) == "()" then { let llm_result = "[оценка недоступна — провайдеры модели не ответили]" }\n  if to_string(llm_result) == "()" then { return "Сервис временно недоступен." }\n  let reply = to_string(llm_result)',
        1)
    assert m != ADMIN, "мутация не применилась"
    assert any("A.4" in x for x in _violations(m)), "мутация мёртвого let-фолбэка не поймана"


def test_mutation_naked_query_returned():
    m = ADMIN.replace(
        'let tr_tasks = try query("SELECT dept, COUNT(*) as cnt FROM dialog_history',
        'let tr_tasks = query("SELECT dept, COUNT(*) as cnt FROM dialog_history', 1)
    assert m != ADMIN, "мутация не применилась"
    assert any("A.4" in x and "query" in x for x in _violations(m)), "мутация голого query не поймана"
