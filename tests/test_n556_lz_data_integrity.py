#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #556: гварды источника — база знаний ЛЗ пишет то, что о ней заявлено.

Живые проверки — батарея test_n556v3.mlog (29 проверок, CI-джоба
«v3 battery»); этот файл держит инварианты ИСТОЧНИКА, чтобы регрессия
ловилась и на этапе pytest (конвенция test_n427_lz_clean_query.py).

A.1 — адресация артефактов по id (LIKE-обновления запрещены);
A.2 — стадия хайпа: код из 5 значений по первой строке STAGE:;
A.3 — скор прорыва: из ответа модели (SCORES:), не жёсткие нули;
A.4 — Gate 3 с настоящим id; устойчивые да/нет (LZYes/LZNone);
A.5 — идемпотентная миграция LZDataMaintain из InitDB, без удаления.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_a1_no_like_updates_on_artifacts():
    # UPDATE по подстроке названия одной командой менял все похожие записи.
    # SELECT-поиск по LIKE (LZArchiveSearch) легален — наряд запрещал только UPDATE.
    like_updates = [l for l in LZ.splitlines()
                    if "UPDATE " in l and "LIKE" in l
                    and ("knowledge_artifacts" in l or "tracked_technologies" in l)]
    assert not like_updates, f"LIKE-обновление артефактов вернулось: {like_updates}"
    # адресация — через LZArtifactId/LZTechRowId, строка tracked_technologies создаётся
    assert "pattern LZArtifactId(title: String, domain: String) -> Float" in LZ
    assert "pattern LZTechRowId(artifact_id: Float, technology: String) -> Float" in LZ
    assert "pattern LZNormTitle(title: String) -> String" in LZ
    # deep scan не вставляет слепо: INSERT только внутри LZArtifactId
    assert "INSERT INTO knowledge_artifacts" in LZ
    deep_body = LZ[LZ.index("pattern LZDeepScan"):]
    deep_body = deep_body[:deep_body.index("\n}")]
    assert "INSERT INTO knowledge_artifacts" not in deep_body, "LZDeepScan снова вставляет слепо"
    assert "LZArtifactId(query, domain)" in deep_body


def test_a2_stage_is_code_from_five_values():
    assert "pattern LZStageFromText(text: String) -> String" in LZ
    # требование формата — в промпте; смысловая часть не менялась
    assert "STAGE: <trigger|peak|trough|slope|plateau>" in LZ
    # в базе пишется только распознанный код, по id
    assert 'db_execute("UPDATE knowledge_artifacts SET hype_cycle_stage = ?, updated_at = datetime(\'now\') WHERE id = ?", [stage, aid])' in LZ
    # нераспознанный ответ — честная пометка владельцу
    assert "Стадия не распознана — значение в базе не менялось" in LZ


def test_a3_scores_from_model_not_zeros():
    assert "pattern LZScoreFor(text: String, horizon: String) -> Float" in LZ
    assert "SCORES: 1y=<0-100> 3y=<0-100> 5y=<0-100> 10y=<0-100>" in LZ
    # жёсткие нули в tracked_technologies удалены
    assert "[0.0, 0.0, 0.0, 0.0," not in LZ
    # скоры пишутся по id, disruption_score = горизонт 3y
    assert "UPDATE tracked_technologies SET disruption_1y = ?, disruption_3y = ?, disruption_5y = ?, disruption_10y = ?, updated_at = datetime('now') WHERE id = ?" in LZ
    assert "UPDATE knowledge_artifacts SET disruption_score = ?, last_scored_at = datetime('now'), updated_at = datetime('now') WHERE id = ?" in LZ
    assert "Скор прорыва не распознан — значения в базе не менялись" in LZ
    # мусорный ответ не роняет навык: to_float_or, не to_float (№514)
    assert "to_float_or(val_raw, -1.0)" in LZ


def test_a4_gate3_real_id_and_robust_yes_none():
    # Gate 3 вызывается с id артефакта, а не с нулём
    code_only = "\n".join(l for l in LZ.splitlines() if not l.strip().startswith("//"))
    assert "LZGateNegativeSignals(aid)" in code_only
    assert "LZGateNegativeSignals(0)" not in code_only
    # устойчивые да/нет на всех местах сравнения
    assert "pattern LZYes(text: String) -> Bool" in LZ
    assert "pattern LZNone(text: String) -> Bool" in LZ
    code_only = "\n".join(l for l in LZ.splitlines() if not l.strip().startswith("//"))
    assert '== "YES"' not in code_only
    assert '== "NONE"' not in code_only
    assert "LZYes(check)" in LZ and "LZYes(result)" in LZ
    assert LZ.count("LZNone(") >= 4  # gate3 + gate7 + gate8 + определение


def test_a5_migration_in_initdb_idempotent_no_delete():
    assert "pattern LZDataMaintain() -> String" in LZ
    # InitDB вызывает миграцию на каждом старте
    assert "let _ = LZDataMaintain()" in APP
    # разбор STAGE-строк в SQL, длинный мусор — NULL
    assert "upper(substr(hype_cycle_stage, 1, 6)) = 'STAGE:'" in LZ
    assert "UPDATE knowledge_artifacts SET hype_cycle_stage = NULL WHERE length(hype_cycle_stage) > 12" in LZ
    # дубли — keeper с минимальным id, остальные archived, БЕЗ удаления
    assert "SET status = 'archived' WHERE id = ?" in LZ
    assert "SET updated_at = MAX(COALESCE(updated_at, ''), ?) WHERE id = ?" in LZ
    assert "DELETE FROM knowledge_artifacts" not in LZ
    # повторный запуск не растит счётчик: archived-строки исключены
    assert "WHERE status != 'archived' ORDER BY id" in LZ


def test_llm_seam_lives_in_app_layer():
    # шов определён в app.mlog (прод-замыкание), в lz.mlog — только вызовы:
    # импортированные определения сильнее локальных, стаб батареи иначе не работает
    assert "pattern LZLlm(prompt: String) -> String" in APP
    assert "pattern LZLlm" not in LZ
    assert "LZLlm(" in LZ


def test_battery_in_ci_loop():
    # батарея #556 не копит долг молча (конвенция #519)
    assert "test_n556v3.mlog" in CI
    # #553: цикл расширен test_n553v3.mlog
    assert "for f in test_forge{1..9}v3.mlog test_narad{1..3}v3.mlog test_n550v3.mlog test_n553v3.mlog test_n556v3.mlog" in CI
