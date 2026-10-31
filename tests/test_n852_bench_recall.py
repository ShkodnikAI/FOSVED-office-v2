#!/usr/bin/env python3
"""Наряд №852 (Metalogos gh#1676, волна 73 — W-M): тесты бенчмарка recall.

Проверяются швы измерительного харнесса (scripts/bench_recall.py):
- детерминированная экстракция корпуса из реальных артефактов репо;
- целостность golden-набора: 62 запроса, виды валидны, каждая игла
  {file, needle} разрешается ровно в запись корпуса (fail-closed разметка);
- метрики hit@k/MRR@k/empty_share на синтетических прогонах (по выдаче);
- контуры like/morph на мини-БД через прод-поверхность FosvedMemory.

Контур vec (sqlite-vec + локальная эмбеддинг-модель) в CI не запускается
(зависимости опциональны, скачивание модели в CI запрещено) — он замеряется
вручную в среде с зависимостями (см. docs/bench-recall.md), здесь только
skip-гвард с честной причиной.

Запуск: python -m pytest tests/test_n852_bench_recall.py -v (cwd = корень репо).
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bench_recall as br  # noqa: E402
from lib.fosved_memory import FosvedMemory  # noqa: E402

GOLDEN = json.loads(
    (REPO_ROOT / "tests" / "golden" / "recall_golden.json").read_text(encoding="utf-8")
)


# ── корпус: детерминированная экстракция реальных артефактов ─────────────

def test_corpus_extracts_real_artifacts():
    records = br.extract_corpus()
    assert len(records) > 500, f"корпус подозрительно мал: {len(records)}"
    for rec in records[:50]:
        # fail-closed source-атрибуция (№849): без явного источника записи нет
        assert rec["source"].startswith("doc:")
        assert rec["type"] in FosvedMemory.TYPES
        assert rec["content"] == rec["content"].strip()
    keys = {r["key"] for r in records}
    assert len(keys) == len(records), "ключи записей не уникальны"


def test_corpus_extraction_is_deterministic():
    a = [r["key"] for r in br.extract_corpus()]
    b = [r["key"] for r in br.extract_corpus()]
    assert a == b


# ── golden-набор: схема и fail-closed разметка ───────────────────────────

def test_golden_schema_valid():
    queries = GOLDEN["queries"]
    assert 50 <= len(queries) <= 100, f"golden вне коридора наряда (50–100): {len(queries)}"
    kinds = {"keyword", "question", "paraphrase"}
    ids = [q["id"] for q in queries]
    assert len(set(ids)) == len(ids), "id запросов не уникальны"
    for q in queries:
        assert q["kind"] in kinds, f"{q['id']}: неизвестный вид {q['kind']}"
        assert q["query"].strip() == q["query"]
        assert q["relevant"], f"{q['id']}: пустая разметка"
        for ref in q["relevant"]:
            assert (REPO_ROOT / ref["file"]).exists(), f"{q['id']}: файла нет {ref['file']}"
            assert ref["needle"].strip()


def test_golden_needles_resolve_deterministically():
    records = br.extract_corpus()
    relevant = br.resolve_golden(GOLDEN["queries"], records)
    assert len(relevant) == len(GOLDEN["queries"])
    for qid, keys in relevant.items():
        assert keys, f"{qid}: разметка не разрешилась"
        assert all(k in {r["key"] for r in records} for k in keys)


# ── метрики: считаются по фактической выдаче ─────────────────────────────

def _rec(key: str, content: str) -> dict:
    return {"key": key, "content": content, "type": "fact",
            "confidence": 0.9, "source": "doc:test", "created_at": 0.0}


def test_metrics_hit_mrr_empty_by_output():
    q1 = {"id": "q1", "kind": "keyword", "query": "x", "relevant": [{"file": "f", "needle": "n"}]}
    q2 = {"id": "q2", "kind": "question", "query": "y", "relevant": [{"file": "f", "needle": "n"}]}
    rel = {"q1": ["aaa"], "q2": ["bbb"]}
    # q1: релевантная на 2-й позиции → hit, RR 0.5; q2: пустая выдача → miss
    runs = [
        (q1, [{"rec": _rec("zzz", "чужая запись")}, {"rec": _rec("aaa", "целевая запись")}]),
        (q2, []),
    ]
    m = br.metrics(runs, rel, k=5)
    assert m["n"] == 2
    assert m["hit@5"] == 0.5
    assert m["mrr@5"] == 0.25
    assert m["empty_share"] == 0.5


def test_metrics_relevant_beyond_k_not_a_hit():
    q = {"id": "q1", "kind": "keyword", "query": "x", "relevant": [{"file": "f", "needle": "n"}]}
    rel = {"q1": ["aaa"]}
    runs = [(q, [{"rec": _rec(f"r{i}", "шум")}, {"rec": _rec("aaa", "цель")}]) for i in range(1)]
    m = br.metrics(runs, rel, k=1)
    assert m["hit@1"] == 0.0 and m["mrr@1"] == 0.0


# ── стеммер: детерминированная морфология RU/EN ──────────────────────────

def test_stemmer_russian_forms_converge():
    assert br.stem("деплоя") == br.stem("деплой") or br._stem_eq(br.stem("деплоя"), br.stem("деплой"))
    assert br._stem_eq(br.stem("ветки"), br.stem("ветка"))
    assert br._stem_eq(br.stem("запросов"), br.stem("запрос"))
    assert br._stem_eq(br.stem("testing"), br.stem("tests"))


# ── контуры like/morph на мини-БД через прод-поверхность ─────────────────

def _seed_mini(db_path: str):
    records = [
        {"key": "k1", "content": "Деплой мини аппа на Render происходит автоматически после мержа в main",
         "type": "fact", "confidence": 0.9, "source": "doc:test-mini"},
        {"key": "k2", "content": "Ветка живёт не дольше 30 дней с момента последнего коммита, если не влитая",
         "type": "instruction", "confidence": 0.9, "source": "doc:test-mini"},
        {"key": "k3", "content": "Снапшот скиллов хранится как GitHub Release с проверкой sha256",
         "type": "fact", "confidence": 0.9, "source": "doc:test-mini"},
    ]
    mem = FosvedMemory(db_path=db_path)
    id_map = {}
    for rec in records:
        rid = mem.remember(rec["content"], rec["type"], rec["confidence"], rec["source"])
        id_map[rid] = rec
    return mem, id_map, records


def test_like_contour_hits_verbatim_substring():
    with tempfile.TemporaryDirectory() as tmp:
        mem, id_map, records = _seed_mini(str(Path(tmp) / "m.db"))
        res = br.recall_like(mem, "render", id_map)
        assert res, "LIKE не нашёл дословный подстрочный токен"
        assert res[0]["rec"]["key"] == "k1"


def test_like_contour_empty_on_morphological_variant():
    with tempfile.TemporaryDirectory() as tmp:
        mem, id_map, records = _seed_mini(str(Path(tmp) / "m.db"))
        # «деплою» — словоформа; whole-phrase LIKE на многословном запросе пуст
        assert br.recall_like(mem, "деплой мини аппа", id_map) == []


def test_morph_contour_finds_variant_and_ranks_top():
    with tempfile.TemporaryDirectory() as tmp:
        mem, id_map, records = _seed_mini(str(Path(tmp) / "m.db"))
        res = br.recall_morph(mem, "деплой мини аппа", id_map)
        assert res, "morph не нашёл ни одного стема"
        assert res[0]["rec"]["key"] == "k1"
        assert all("score" in x for x in res)
        assert len(res) <= 5


def test_morph_visibility_mirrors_production():
    """Паритет видимости №849/№850: purged-записи не видны контуру morph."""
    with tempfile.TemporaryDirectory() as tmp:
        mem, id_map, records = _seed_mini(str(Path(tmp) / "m.db"))
        mem.db.execute("UPDATE typed_memories SET purged_at = 1 WHERE content LIKE '%Render%'")
        mem.db.commit()
        assert br.recall_morph(mem, "деплой мини аппа", id_map) == []


# ── контур vec: только гвард зависимостей (CI без модели — честный skip) ──

def test_vec_contour_requires_optional_deps():
    pytest.importorskip("sqlite_vec", reason="sqlite-vec недоступен — контур (в) замеряется вручную (docs/bench-recall.md)")
    pytest.importorskip("model2vec", reason="model2vec недоступен — контур (в) замеряется вручную (docs/bench-recall.md)")
    try:
        from model2vec import StaticModel  # noqa: F401
        StaticModel.from_pretrained("minishlab/potion-multilingual-128M")
    except Exception as e:  # noqa: BLE001 — честный skip без подмены результата
        pytest.skip(f"локальная эмбеддинг-модель недоступна: {e}")
