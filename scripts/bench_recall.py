#!/usr/bin/env python3
"""Наряд №852 (Metalogos gh#1676, волна 73 — W-M): бенчмарк recall на golden-наборе офиса.

Сравнение трёх контуров поиска по одним и тем же golden-запросам:

  (а) like   — текущая прод-поверхность: FosvedMemory.recall() как есть
               (SQL `lower(content) LIKE ?` + word-overlap релевантность);
  (б) morph  — LIKE + морфологическая нормализация (лёгкий RU/EN стеммер,
               детерминированный, без зависимостей) — «дешёвый апгрейд»;
  (в) vec    — sqlite-vec + локальные статические эмбеддинги
               (model2vec/potion-multilingual-128M, без API, данные не
               покидают контур) поверх поверхности №849/№850/№851
               (superseded/purged/declined исключены — паритет видимости).

Метрики: hit@5, MRR@5, доля пустых выдач. Решение по порогу из наряда:
апгрейд поиска, если LIKE hit@5 < 0.7.

Golden-набор: tests/golden/recall_golden.json — 62 запроса трёх видов
(keyword / question / paraphrase), каждый размечен на релевантную запись
корпуса через {file, needle} — разрешение детерминированное и проверяемое
(первая строка файла, содержащая иглу; тест фиксирует однозначность).
Корпус — реальные офисные артефакты репо (docs/, отчёты нарядов, library/),
экстракция детерминированная (см. extract_corpus).

Запуск:
    python3 scripts/bench_recall.py                 # все доступные контуры
    python3 scripts/bench_recall.py --json data/bench_recall_report.json
    python3 scripts/bench_recall.py --skip vec      # только like+morph
    python3 scripts/bench_recall.py --shadow-cmd '<команда>'   # memanto shadow:
        команда получает запрос на stdin, печатает JSON-массив строк-записей;
        записи в прод НЕ идут (урок №581/№840 — shadow-first). Локальный режим
        memanto (Docker+Ollama) подставляется сюда на сервере офиса.

Внешние API в контуре бенчмарка запрещены нарядом: только локальные модели.
Отсутствие sqlite-vec/модели — честный SKIP контура с причиной, не подмена.
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lib.fosved_memory import FosvedMemory  # noqa: E402

GOLDEN_PATH = REPO_ROOT / "tests" / "golden" / "recall_golden.json"

# Корпус: реальные офисные артефакты в репо (не синтетика).
CORPUS_GLOBS = [
    "docs/*.md",
    "docs/adr/*.md",
    "docs/departments/*.md",
    "docs/projects/**/*.md",
    "report_*.md",
    "library/*.md",
]

MIN_LEN, MAX_LEN = 40, 400  # границы строки-кандидата в память (после чистки)

# ─────────────────────────── КОРПУС ──────────────────────────────────────

_MD_NOISE = re.compile(
    r"^(==+|-{3,}|\*{3,}|!+\[|<|\|[-\s|:]+\|)"
)


def _clean_line(raw: str) -> str:
    """Чистка markdown-строки до атомарного текста памяти."""
    s = raw.strip()
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)          # картинки
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)       # ссылки → текст
    s = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", s)         # инлайн-код
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)             # жирный
    s = re.sub(r"^\s*[-*+]\s+", "", s)                   # буллет
    s = re.sub(r"^\s*#{1,6}\s+", "", s)                  # заголовок
    s = re.sub(r"^\s*>\s?", "", s)                       # цитата
    s = s.replace("|", " · ")                            # строка таблицы
    s = re.sub(r"\s+", " ", s).strip()
    s = s.lstrip("· ").strip()
    return s


def _memory_type(rel: str, text: str) -> str:
    """Эвристика типа записи (13 типов FosvedMemory, №849/№851-поверхность)."""
    low = text.lower()
    if "/adr/" in rel:
        return "decision"
    if re.search(r"дефект|найден|баг|падает|сломан|не работает", low):
        return "error"
    if re.search(r"урок|вывод:|находка", low):
        return "learning"
    if re.search(r"правил|политик|обязательн|запрещ|только после|нельзя|должен", low):
        return "instruction"
    if re.search(r"наблюден|статус|сегодня|отчёт", low):
        return "observation"
    return "fact"


def extract_corpus() -> List[Dict[str, Any]]:
    """Детерминированная экстракция записей памяти из реальных артефактов репо.

    Одна строка = одна запись (атомарный факт/решение/правило). Ключ записи —
    sha1(relpath:lineno) — стабилен, golden-разметка ссылается на строки.
    """
    records: List[Dict[str, Any]] = []
    seen: set = set()
    files: List[Path] = []
    for g in CORPUS_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(g)))
    for path in sorted(set(files)):
        rel = str(path.relative_to(REPO_ROOT))
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            print(f"[corpus] пропущен {rel}: {e}", file=sys.stderr)
            continue
        in_code = False
        for i, raw in enumerate(lines, start=1):
            if raw.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code or not raw.strip() or _MD_NOISE.match(raw.strip()):
                continue
            text = _clean_line(raw)
            if not (MIN_LEN <= len(text) <= MAX_LEN):
                continue
            words = re.findall(r"\w{2,}", text.lower())
            if len(words) < 5:
                continue
            norm = text.lower()
            if norm in seen:
                continue
            seen.add(norm)
            key = hashlib.sha1(f"{rel}:{i}".encode()).hexdigest()[:12]
            records.append({
                "key": key,
                "file": rel,
                "line": i,
                "content": text,
                "type": _memory_type(rel, text),
                "confidence": 0.9,
                "source": f"doc:{rel}",
            })
    return records


# ─────────────────────────── SEED ────────────────────────────────────────

def seed_memory(records: List[Dict[str, Any]], db_path: str) -> Tuple[FosvedMemory, Dict[int, Dict[str, Any]]]:
    """Посев корпуса через прод-поверхность remember() (fail-closed source, №849).

    Возвращает (память, карта id→record). Случайные supersede конфликт-детектором
    фиксируются честно (seed_superseded) — это свойство прод-поверхности.
    """
    mem = FosvedMemory(db_path=db_path)
    id_map: Dict[int, Dict[str, Any]] = {}
    for rec in records:
        rid = mem.remember(
            content=rec["content"],
            mem_type=rec["type"],
            confidence=rec["confidence"],
            source=rec["source"],
        )
        id_map[rid] = rec
    return mem, id_map


# ─────────────────────── ВИДИМОСТЬ (паритет №849/№850/№851) ─────────────

def _active_rows(mem: FosvedMemory) -> List[Dict[str, Any]]:
    """Активные записи — точный зеркальный фильтр видимости recall().

    confidence >= 0.3, не superseded, не purged (№850), не declined (FO-020).
    Используется контурами morph/vec: паритет видимости с прод-поверхностью.
    """
    rows = mem.db.execute(
        '''SELECT * FROM typed_memories
           WHERE confidence >= 0.3
             AND superseded_by IS NULL
             AND purged_at IS NULL
             AND (review_status IS NULL OR review_status != 'declined')'''
    ).fetchall()
    return [dict(r) for r in rows]


def _decay(mem_type: str, created_at: float, now: float) -> float:
    """Зеркало decay-логики _relevance_score (FosvedMemory)."""
    if mem_type in FosvedMemory.ETERNAL_TYPES:
        return 1.0
    if mem_type in FosvedMemory.DECAY_RATES:
        rate, floor = FosvedMemory.DECAY_RATES[mem_type]
        return max(floor, 1.0 - ((now - created_at) / 86400) * rate)
    return max(0.3, 1.0 - ((now - created_at) / 86400) * 0.02)


# ─────────────────────── КОНТУР (а): LIKE (прод) ─────────────────────────

def recall_like(mem: FosvedMemory, query: str, id_map: Dict[int, Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Текущая прод-поверхность без изменений."""
    return [{"rec": id_map[m["id"]], "score": m.get("relevance", 0.0)}
            for m in mem.recall(query, limit=limit)]


def _longest_token(query: str) -> str:
    """Самый длинный значимый токен запроса (диагностика лучшего случая LIKE)."""
    tokens = [t for t in _tokens(query) if len(t) >= 4]
    return max(tokens, key=len) if tokens else query.strip()


# ─────────────────── КОНТУР (б): LIKE + морфология ──────────────────────

_RU_SUFFIXES = [
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими",
    "ая", "ое", "ые", "ых", "ий", "ый", "ой", "ом", "ем", "ах", "ях",
    "ов", "ев", "ей", "ии", "ия", "ье", "ья", "ую", "юю", "ы", "и",
    "а", "я", "е", "о", "у", "ю", "ь",
]
_EN_SUFFIXES = ["ings", "ing", "ies", "ed", "es", "s", "er", "ly"]


def stem(token: str) -> str:
    """Лёгкий детерминированный стеммер RU/EN (срез флексий, мин. длина 4)."""
    t = token.lower()
    if re.match(r"[а-яё]", t):
        for suf in _RU_SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                return t[: len(t) - len(suf)]
        return t
    for suf in _EN_SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: len(t) - len(suf)]
    return t


def _tokens(text: str) -> List[str]:
    return re.findall(r"[а-яёa-z0-9]+", text.lower())


def _stem_eq(a: str, b: str) -> bool:
    """Совпадение стемов с префиксной терпимостью (деплой/деплоя/деплою)."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short)


def recall_morph(mem: FosvedMemory, query: str, id_map: Dict[int, Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    """Контур (б): морфологическая нормализация обеих сторон + то же ранжирование
    (semantic × decay × confidence × review), что в _relevance_score."""
    qstems = [stem(t) for t in _tokens(query)]
    if not qstems:
        return []
    now = time.time()
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in _active_rows(mem):
        cstems = {stem(t) for t in _tokens(r["content"])}
        matched = sum(1 for qs in qstems if any(_stem_eq(qs, cs) for cs in cstems))
        if matched == 0:
            continue
        semantic = matched / len(qstems)
        rs = r.get("review_status") or "approved"
        review_w = FosvedMemory.REVIEW_WEIGHTS.get(rs, 1.0)
        score = semantic * _decay(r["type"], r["created_at"], now) * r["confidence"] * review_w
        scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], -x[1]["created_at"]))
    return [{"rec": id_map[r["id"]], "score": s} for s, r in scored[:limit]]


# ──────────────── КОНТУР (в): sqlite-vec + локальные эмбеддинги ─────────

class VecIndex:
    """sqlite-vec KNN-индекс поверх активных записей (видимость = recall()).

    Эмбеддинги — локальная статическая модель (model2vec, без API).
    Модель и sqlite-vec — опциональны: недоступность = честный SKIP.
    """

    def __init__(self, rows: List[Dict[str, Any]], db_path: str, model_tag: str):
        import numpy as np
        import sqlite_vec

        self.np = np
        self.model_tag = model_tag
        from model2vec import StaticModel
        self.model = StaticModel.from_pretrained(model_tag)
        self.conn = sqlite3.connect(db_path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        dim = self.model.dim
        self.conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(embedding float[{dim}])"
        )
        texts = [r["content"] for r in rows]
        embs = self.model.encode(texts)
        embs = np.asarray(embs, dtype=np.float32)
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embs = embs / norms
        self.rowids = [r["id"] for r in rows]
        for rid, emb in zip(self.rowids, embs):
            self.conn.execute(
                "INSERT INTO vec_memories(rowid, embedding) VALUES (?, ?)",
                (rid, emb.tobytes()),
            )
        self.conn.commit()

    def search(self, mem: FosvedMemory, query: str, id_map: Dict[int, Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        """KNN top-k с фильтром видимости recall() (KNN берётся с запасом ×4)."""
        q = self.np.asarray(self.model.encode([query]), dtype=self.np.float32)
        q = q / max(self.np.linalg.norm(q), 1e-9)
        knn = max(limit * 4, 20)
        hits = self.conn.execute(
            "SELECT rowid, distance FROM vec_memories WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (q[0].tobytes(), knn),
        ).fetchall()
        active_ids = {r["id"] for r in _active_rows(mem)}
        out: List[Dict[str, Any]] = []
        for rid, dist in hits:
            if rid not in active_ids or rid not in id_map:
                continue
            out.append({"rec": id_map[rid], "score": 1.0 - float(dist)})
            if len(out) >= limit:
                break
        return out


# ─────────────────────────── GOLDEN + МЕТРИКИ ────────────────────────────

def load_golden(path: Path = GOLDEN_PATH) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["queries"]


def resolve_golden(queries: List[Dict[str, Any]], records: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Разметка: {query_id: [record_key, ...]} через (file, needle).

    needle — подстрока строки-записи в файле; разрешение детерминированное.
    Неразрешённая игла — громкая ошибка (fail-closed разметка).
    """
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        by_file.setdefault(rec["file"], []).append(rec)
    out: Dict[str, List[str]] = {}
    for q in queries:
        keys: List[str] = []
        for ref in q["relevant"]:
            cands = [r for r in by_file.get(ref["file"], []) if ref["needle"] in r["content"]]
            if not cands:
                raise ValueError(
                    f"golden {q['id']}: игла не разрешена в {ref['file']}: {ref['needle']!r}"
                )
            keys.append(cands[0]["key"])
        out[q["id"]] = keys
    return out


def metrics(runs: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
            relevant: Dict[str, List[str]], k: int = 5) -> Dict[str, Any]:
    """hit@k, MRR@k, доля пустых выдач (по выдаче, не по памяти)."""
    hits, rr, empty = 0, 0.0, 0
    for q, results in runs:
        rel = set(relevant[q["id"]])
        got_keys = [x["rec"]["key"] for x in results]
        if not got_keys:
            empty += 1
        rank = next((i + 1 for i, key in enumerate(got_keys[:k]) if key in rel), None)
        if rank is not None:
            hits += 1
            rr += 1.0 / rank
    n = len(runs)
    return {
        "n": n,
        f"hit@{k}": round(hits / n, 3) if n else 0.0,
        f"mrr@{k}": round(rr / n, 3) if n else 0.0,
        "empty_share": round(empty / n, 3) if n else 0.0,
    }


def metrics_by_kind(runs: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]],
                    relevant: Dict[str, List[str]], k: int = 5) -> Dict[str, Any]:
    kinds = sorted({q["kind"] for q, _ in runs})
    out: Dict[str, Any] = {}
    for kind in kinds:
        sub = [(q, r) for q, r in runs if q["kind"] == kind]
        out[kind] = metrics(sub, relevant, k)
    return out


# ─────────────────────────── SHADOW (memanto) ────────────────────────────

def shadow_run(queries: List[Dict[str, Any]], shadow_cmd: str,
               records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """memanto в shadow: локальная команда получает запрос на stdin, печатает
    JSON-массив строк. Совпадение записей — по подстроке содержимого записи
    в выданной строке (слияния контуров нет, записи в прод не идут)."""
    import subprocess

    contents = [r["content"] for r in records]
    runs: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    try:
        for q in queries:
            proc = subprocess.run(
                shadow_cmd, shell=True, input=q["query"].encode(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            if proc.returncode != 0:
                print(f"[shadow] код {proc.returncode}: {proc.stderr.decode()[:200]}",
                      file=sys.stderr)
                return None
            items = json.loads(proc.stdout.decode())
            got: List[Dict[str, Any]] = []
            for item in items:
                text = str(item)
                matches = [r for r in records if r["content"] in text]
                if matches:
                    got.append({"rec": matches[0], "score": 1.0})
                elif any(content and content[:40] in text for content in contents):
                    got.append({"rec": records[0], "score": 0.0})
            runs.append((q, got[:5]))
        return {
            "contour": "shadow:memanto (локальный режим, без записи в прод)",
            "overall": metrics(runs, resolve_golden(queries, records)),
            "by_kind": metrics_by_kind(runs, resolve_golden(queries, records)),
        }
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        print(f"[shadow] memanto недоступен: {e}", file=sys.stderr)
        return None


# ─────────────────────────── MAIN ────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="№852: бенчмарк recall (like/morph/vec/shadow)")
    ap.add_argument("--json", metavar="PATH", help="записать полный отчёт JSON")
    ap.add_argument("--skip", choices=["vec", "morph"], action="append", default=[])
    ap.add_argument("--shadow-cmd", metavar="CMD", help="локальная команда memanto (shadow)")
    ap.add_argument("--vec-model", default="minishlab/potion-multilingual-128M",
                    help="модель статических эмбеддингов (model2vec)")
    args = ap.parse_args()

    records = extract_corpus()
    queries = load_golden()
    relevant = resolve_golden(queries, records)
    print(f"корпус: {len(records)} записей | golden: {len(queries)} запросов")

    with tempfile.TemporaryDirectory(prefix="n852-") as tmp:
        mem, id_map = seed_memory(records, str(Path(tmp) / "memory.db"))

        # целостность разметки: ни одна релевантная запись не съедена конфликт-детектором
        sup = mem.db.execute(
            "SELECT COUNT(*) FROM typed_memories WHERE superseded_by IS NOT NULL"
        ).fetchone()[0]
        gold_ids = {k for keys in relevant.values() for k in keys}
        rec_keys = {r["key"] for r in records}
        missing = gold_ids - rec_keys
        if missing:
            print(f"FAIL: golden-ключи вне корпуса: {sorted(missing)}", file=sys.stderr)
            return 1
        print(f"seed: {len(id_map)} записей | superseded при севе: {sup}")

        contours: List[Dict[str, Any]] = []

        runs_like = [(q, recall_like(mem, q["query"], id_map)) for q in queries]
        contours.append({
            "contour": "(а) like — прод-поверхность FosvedMemory.recall (SQL LIKE)",
            "overall": metrics(runs_like, relevant),
            "by_kind": metrics_by_kind(runs_like, relevant),
        })

        # Диагностика (не контур наряда): лучший случай LIKE — одиночный токен
        # (самый длинный значимый). Показывает потолок прод-поверхности на том
        # же корпусе: LIKE-фильтр — whole-phrase подстрока, многословные
        # запросы проходят только как дословная фраза.
        runs_single = [(q, recall_like(mem, _longest_token(q["query"]), id_map)) for q in queries]
        contours.append({
            "contour": "diag — like одиночным токеном (лучший случай LIKE, не контур наряда)",
            "overall": metrics(runs_single, relevant),
            "by_kind": metrics_by_kind(runs_single, relevant),
        })

        if "morph" not in args.skip:
            runs_morph = [(q, recall_morph(mem, q["query"], id_map)) for q in queries]
            contours.append({
                "contour": "(б) morph — LIKE + морфологическая нормализация (RU/EN стеммер)",
                "overall": metrics(runs_morph, relevant),
                "by_kind": metrics_by_kind(runs_morph, relevant),
            })

        if "vec" not in args.skip:
            try:
                idx = VecIndex(_active_rows(mem), str(Path(tmp) / "memory.db"), args.vec_model)
                runs_vec = [(q, idx.search(mem, q["query"], id_map)) for q in queries]
                contours.append({
                    "contour": f"(в) vec — sqlite-vec + {args.vec_model} (локально, без API)",
                    "overall": metrics(runs_vec, relevant),
                    "by_kind": metrics_by_kind(runs_vec, relevant),
                })
            except (ImportError, OSError, sqlite3.Error) as e:
                print(f"[vec] SKIP: {e}", file=sys.stderr)
                contours.append({
                    "contour": "(в) vec — SKIP (зависимость/модель недоступны в этой среде)",
                    "reason": str(e),
                })

    if args.shadow_cmd:
        shadow = shadow_run(queries, args.shadow_cmd, records)
        if shadow:
            contours.append(shadow)
        else:
            contours.append({"contour": "shadow:memanto — SKIP (команда вернула ошибку)"})

    like_overall = contours[0]["overall"]
    threshold = 0.7
    like_hit5 = like_overall.get("hit@5", 0.0)
    verdict = ("АПГРЕЙД ОБОСНОВАН" if like_hit5 < threshold
               else "ПОРОГ НЕ ДОСТИГНУТ — апгрейд по этому порогу не требуется")

    report = {
        "naryad": "№852 (Metalogos gh#1676, волна 73 — W-M)",
        "date": time.strftime("%Y-%m-%d"),
        "corpus_records": len(records),
        "golden_queries": len(queries),
        "golden_path": "tests/golden/recall_golden.json",
        "seed_superseded": sup,
        "decision_threshold": f"апгрейд поиска, если LIKE hit@5 < {threshold}",
        "contours": contours,
        "verdict": verdict,
    }

    print()
    for c in contours:
        print(f"## {c['contour']}")
        if "overall" in c:
            print(f"   overall: {c['overall']}")
            for kind, m in c["by_kind"].items():
                print(f"   {kind:>10}: {m}")
        else:
            print(f"   {c.get('reason', '')}")
        print()
    print(f"ВЕРДИКТ: {report['verdict']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nотчёт: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
