#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #553: гварды источника — провенанс LLM-оценок КБ ЛЗ.

Живые проверки — батарея test_n553v3.mlog (24 проверки, CI-джоба
«v3 battery»); этот файл держит инварианты ИСТОЧНИКА, чтобы регрессия
ловилась и на этапе pytest (конвенция test_n556_lz_data_integrity.py).

A.1 — колонка provenance в knowledge_artifacts (inline-DDL + миграция InitDB);
A.1 — заполнение в момент записи: стадия, скор, статус (LLM) и домен (правило);
A.2 — устав: провенанс суждений модели, не замена [источник](URL) для фактов.
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
LZMD = (REPO_ROOT / "library" / "lz.md").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_a1_provenance_column_in_ddl_and_migration():
    # inline-DDL документирует колонку (AGENTS.md §1: inline-DDL и схема не расходятся)
    assert "provenance TEXT DEFAULT EMPTY_JSON" in LZ
    # миграция InitDB — по конвенции ALTER-миграций (TryVal+grant), без удаления данных
    assert 'grant_issue("db:alter:knowledge_artifacts", 3600.0, "once"), "ALTER TABLE knowledge_artifacts ADD COLUMN provenance TEXT DEFAULT' in APP


def test_a1_provenance_filled_at_write_time():
    # хелперы существуют и строят JSON на стороне SQL (json_object):
    # ключи-поля — зарезервированные слова mlog (проба 553b: двойное вложение)
    assert "pattern LZProvRecord(artifact_id: Float, field: String, via: String) -> String" in LZ
    assert "pattern LZProvRule(artifact_id: Float, field: String, rule_name: String) -> String" in LZ
    prov_body = LZ[LZ.index("pattern LZProvRecord"):]
    prov_body = prov_body[:prov_body.index("pattern LZProvRule")]
    assert "json_object('provider', ?, 'model', ?" in prov_body
    assert "json_object('temperature', 'unrecorded')" in prov_body
    # честные дефолты: незаданная модель — unrecorded, не выдуманное имя
    assert 'env_or("METALOGOS_LLM_MODEL", "unrecorded")' in prov_body
    assert 'env_or("METALOGOS_LLM_PROVIDER", "unrecorded")' in prov_body
    # места записи LLM-полей — в момент записи значения
    assert 'LZProvRecord(aid, "hype_cycle_stage", "LZLlm")' in LZ
    assert 'LZProvRecord(aid, "disruption_score", "LZLlm")' in LZ
    assert 'LZProvRecord(aid, "status", "LZInflectionDetect+LZYes")' in LZ
    # правило-значение: домен на создании артефакта и разбор стадии миграцией
    assert 'LZProvRule(new_id, "domain", "LZClassifyDomain")' in LZ
    assert "json_object('rule', 'LZDataMaintain:STAGE-parse')" in LZ


def test_a2_charter_provenance_paragraph():
    # дополнение раздела «Источники и ссылки (КРИТИЧЕСКОЕ)» — формулировка наряда
    assert "Суждение модели (оценка стадии, скор, вердикт гейта) сопровождается провенансом" in LZMD
    assert "Провенанс не заменяет ссылку на источник для фактов" in LZMD
    # формат фактов не тронут
    assert "в конце каждого факта/вывода — [источник](URL)" in LZMD


def test_battery_in_ci_loop():
    assert "test_n553v3.mlog" in CI
    assert "for f in test_forge{1..9}v3.mlog test_narad{1..3}v3.mlog test_n550v3.mlog test_n553v3.mlog test_n556v3.mlog test_n565v3.mlog test_n566v3.mlog test_n559v3.mlog" in CI
