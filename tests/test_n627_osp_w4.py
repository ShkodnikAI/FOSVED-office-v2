#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #627 (ОСП W4) — структурные гвардии.
Platt (§5.2) + сжатие поправки 1 (то же правило включения), кривая §5.4,
методики как структуры §7.2, A/B §7.4, удаление мёртвого §7.3, слот 1-го числа,
профиль без несуществующих гейтов. Живая математика проверена mlog-тестами
(n627: 92/92 с БД, фикстуры из scripts/n627_platt_sim.py) и мутациями
(порог→0, обучение на отложке, пол A/B — каждая красит свой тест)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSP_MLOG = open(os.path.join(REPO_ROOT, "dept", "osp.mlog"), encoding="utf-8").read()
APP_MLOG = open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8").read()
SCHED = open(os.path.join(REPO_ROOT, "dept", "schedules.mlog"), encoding="utf-8").read()
PROFILE = open(os.path.join(REPO_ROOT, "library", "osp.md"), encoding="utf-8").read()
TESTS = open(os.path.join(REPO_ROOT, "tests", "test_n423_osp_live_search.py"), encoding="utf-8").read()
TESTS469 = open(os.path.join(REPO_ROOT, "tests", "test_n469_osp_scenario_gate.py"), encoding="utf-8").read()


def _pattern_body(source: str, name: str) -> str:
    start = source.index(f"pattern {name}")
    nxt = source.find("\npattern ", start + len(f"pattern {name}"))
    if nxt == -1:
        nxt = source.find("\n// ═", start + 10)
    return source[start:nxt]


def test_platt_patterns_exist():
    for name in ("OSPCalLogit", "OSPPlattFit", "OSPPlattApply", "OSPPriorWeight",
                 "OSPPriorFit", "OSPPriorApply", "OSPCalibrationCurve",
                 "OSPFmt4", "OSPSettingUpsert"):
        assert f"pattern {name}" in OSP_MLOG, name


def test_platt_inclusion_rule():
    body = _pattern_body(OSP_MLOG, "OSPPlattFit")
    # правило включения единственное: n_train≥60 AND n_hold≥30 AND gain≥0.005
    assert "if gain >= 0.005" in body, "порог выигрыша 0.005 (§5.2)"
    assert "< 60.0" in body and "< 30.0" in body, "пороги n_train≥60 / n_hold≥30 (if nt < 60 or nh < 30 → REJECTED)"
    assert "400.0" in body and "0.05" in body, "GD 400 итераций, lr 0.05"
    # отложка = хвост архива по времени (verified_at DESC), не случайно
    assert "ORDER BY verified_at DESC, id DESC LIMIT 30" in body
    # поправка 3: unfit-config строки не идут в owner-обучение
    assert "unfit-config" in body
    # вердикт и коэффициенты — system_settings
    for key in ("osp_cal_a", "osp_cal_b", "osp_cal_note"):
        assert f'"{key}"' in body, key


def test_platt_identity_when_rejected():
    apply_body = _pattern_body(OSP_MLOG, "OSPPlattApply")
    # при REJECTED (note не ADOPTED) — вход побитово, без пересчёта
    assert 'starts_with(note, "ADOPTED") == false then { return p }' in apply_body


def test_savecard_chain_blend_clip_platt():
    body = _pattern_body(OSP_MLOG, "OSPSaveCard")
    # порядок: сжатие (если ADOPTED) → clip → Platt
    i_blend = body.index("OSPPriorApply(id, p_base)")
    i_clip = body.index("OSPClip(p_blend)")
    i_platt = body.index("OSPPlattApply(pc)")
    assert i_blend < i_clip < i_platt, "сжатие → clip → Platt"
    # методики — структурный гейт с блокировкой дерева
    assert "OSPMethodsGate(" in body
    assert "assumptions_json" in body


def test_prior_same_inclusion_rule():
    body = _pattern_body(OSP_MLOG, "OSPPriorFit")
    assert "if gain >= 0.005" in body, "поправка 1: то же правило включения"
    assert "< 60.0" in body and "< 30.0" in body
    assert "osp_prior_note" in body
    # класс сравнения: строки с prior_n ≥ 10 (n<10 не применяется)
    assert "prior_n >= 10" in body


def test_curve_writes_monthly_and_svg():
    body = _pattern_body(OSP_MLOG, "OSPCalibrationCurve")
    assert "calibration_curve" in body, "писатель monthly_reviews.calibration_curve"
    assert "chart_line" in body, "картинка chart_line"
    assert "diagram_style" in body
    assert "write_file" in body
    assert ">= 5.0" in body, "пол бакета n≥5"
    assert "ok_n < 3.0" in body, "пол ≥3 бакета"


def test_methods_gates_seven():
    for name in ("OSPAssumptionsGate", "OSPDeceptionGate", "OSPCGGate",
                 "OSPMesiiGate", "OSPMatrixGate", "OSPTreeGate",
                 "OSPNarrativesGate", "OSPMethodsGate"):
        assert f"pattern {name}" in OSP_MLOG, name
    tree = _pattern_body(OSP_MLOG, "OSPTreeGate")
    assert "0.15" in tree, "расхождение дерева >0.15 — G-гейт"
    assert "1.02" in tree, "сумма терминальных ≤1 (+допуск)"
    matrix = _pattern_body(OSP_MLOG, "OSPMatrixGate")
    assert "OSPComputePotential" in matrix, "потенциал — программа из матрицы сил"
    narr = _pattern_body(OSP_MLOG, "OSPNarrativesGate")
    assert "INSERT INTO indicator" in narr, "нарративы → строки indicator"
    assert "confirms_what" in narr and "verify_date" in narr


def test_ab_method_runs():
    body = _pattern_body(OSP_MLOG, "OSPMethodAB")
    assert "osp_forecast_method_runs" in body
    assert "GROUP BY mr.method" in body, "GROUP BY method (§7.4)"
    assert "skill_reviews" in body, "результат — skill_reviews.success_rate"
    assert "OSPMinN()" in body, "пол n≥10"
    # писатели: ансамбль и bench
    apply_body = _pattern_body(OSP_MLOG, "OSPEnsembleApply")
    assert "INSERT INTO osp_forecast_method_runs" in apply_body
    bench = _pattern_body(OSP_MLOG, "OSPBenchForecastRow")
    assert "INSERT INTO osp_forecast_method_runs" in bench
    schema = _pattern_body(OSP_MLOG, "OSPFEnsureSchema")
    assert "CREATE TABLE IF NOT EXISTS osp_forecast_method_runs" in schema
    for col in ("forecast_id", "method", "p_i", "family"):
        assert col in schema.split("osp_forecast_method_runs")[1][:250]


def test_dead_code_removed():
    # §7.3 / п.6 наряда: мёртвый код удалён
    assert "pattern OSPComputeBrier" not in OSP_MLOG, "дубль Brier удалён (живой OSPBrier остался)"
    assert "pattern OSPValidateProbability" not in OSP_MLOG, "поиск слов удалён (замена — json_validate W1)"
    assert "pattern OSPCheckQualityGates" not in OSP_MLOG, "g1–g12 удалены"
    assert "pattern OSPBrier" in OSP_MLOG, "живой Brier W2 на месте"
    assert "pattern OSPFinalSafetyCheck" in OSP_MLOG, "safety на месте"


def test_profile_matches_reality():
    # слово BLOCKER обещало блокировку, которой не было; теперь профиль
    # описывает фактическую блокировку публикации карточки и живые гейты
    assert "OSPCheckQualityGates" not in PROFILE, "мёртвый гейт из профиля убран"
    assert "Блокируют публикацию карточки" in PROFILE
    assert "OSPScenarioGateCheck" in PROFILE
    assert "system_settings osp_cal_note" in PROFILE


def test_monthly_slot_and_route():
    body = _pattern_body(OSP_MLOG, "OSPMonthlySlot")
    assert "OSPMonthlyReview" in body and "OSPCalibrationCurve" in body
    assert "OutboxPut" in body, "доставка — механизм #550"
    # слот в реестре расписаний, включён прямым указанием наряда
    assert 'name: "osp-monthly"' in SCHED
    assert 'target: "OSPMonthlySlot"' in SCHED
    # роут — ручной триггер с CRON_SECRET-гвардом
    assert 'route "/cron/osp-monthly"' in APP_MLOG
    i_route = APP_MLOG.index('route "/cron/osp-monthly"')
    assert "SecretMatches" in APP_MLOG[i_route:i_route + 400]


def test_commands_registered():
    assert 'starts_with(t, "/osp curve")' in OSP_MLOG
    assert 'starts_with(t, "/osp methods")' in OSP_MLOG
    assert "OSPCurveCommand" in OSP_MLOG and "OSPMethodABCommand" in OSP_MLOG
    # /osp recalibrate — теперь fit Platt + сжатия перед обзором
    body = _pattern_body(OSP_MLOG, "OSPRecalibrate")
    assert 'OSPPlattFit("owner")' in body
    assert 'OSPPriorFit("owner")' in body


def test_card_schema_optional_methods():
    body = _pattern_body(OSP_MLOG, "OSPFCardSchema")
    assert '\\"methods\\":{\\"type\\":\\"object\\"}' in body
    assert '\\"assumptions\\":{\\"type\\":\\"array\\"}' in body
    # required не тронут — старые хвосты валидны
    assert '\\"required\\":[\\"p\\",\\"resolution_criteria\\",\\"resolve_by\\",\\"as_of\\"]' in body


def test_n627_mlog_tests_present():
    for frag in ("Platt ADOPTED", "Platt порог", "Platt утечка", "Platt нехватка",
                 "сжатие поправки 1", "кривая", "методики: assumptions",
                 "A/B методологий: пол", "гигиена: боевые настройки"):
        assert frag in OSP_MLOG, frag


def test_old_guards_updated_consistently():
    # гвардии n423/n469 переведены на новую реальность, а не удалены
    assert '_pattern_body(OSP_MLOG, "OSPCheckQualityGates")' not in TESTS, "старая гвардия g1–g12 заменена"
    assert '_pattern_body(OSP_MLOG, "OSPCheckQualityGates")' not in TESTS469
    assert "test_gates_untouched" in TESTS
    assert "test_sherman_kent_scale_untouched" in TESTS469
