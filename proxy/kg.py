"""FO-009: темпоральный knowledge_graph — версионирование узлов вместо перезаписи.

Наряд #69: узел валиден на интервале [valid_from, valid_to); NULL valid_to = актуально.
Обновление факта = закрытие старого узла (valid_to=now, superseded_by→новый id)
+ вставка новой версии. История не теряется; читается по умолчанию только актуальное.

Entity resolution (по наряду, простое правило): тот же (node_type, node_name) →
тот же субъект. Конфликт (несколько активных узлов ключа с разными file_path)
фиксируется в admin_findings и схлопывается в каноничную последнюю версию.

#728 B.3: массовые пути (kg_scan_rebuild) пишут чанками по KG_CHUNK узлов
одной транзакцией на старом соединении с busy_timeout — прежде каждый
апсерт открывал СВОЁ соединение через _query (прод 19.11: ~8.5k соединений
за прогон Grapher, минуты почти непрерывного write-лока). Одиночные вызовы
kg_upsert (живой API) сохраняют прежнюю семантику через _query.

#728 B.8 (вывод по аудиту 20.11 «почему попытка 1 дала +540 new /
~6026 updated при обычных ~800»): ключ узла (node_type, node_name) и
поля match (file_path, description) этим нарядом НЕ менялись → это НЕ
объявленная миграция формата. Числа — наследие состояния БД до B.3:
последний Grapher до ночи 20.11 работал СТАРЫМ per-node кодом (деплой
#730 — 19.11 07:53Z, после ночи 18.11), который закрывал и вставлял
версию ДВУМЯ отдельными _query-коммитами; падение между ними (OOM
512Mi — паттерн #712) оставляло ключи без активной версии → их
повторный скан честно дал «new» (540). «updated» 6026 ≈ накопленные
за мёртвые ночи 17/19 изменения (~800/ночь × 4 суток) + конфликтеые
ключи с несколькими активными версиями (каждая строка считается
отдельным закрытием). Доказательство с прода (после ночи 21.11):
SELECT node_name, COUNT(*) FROM knowledge_graph WHERE valid_to IS NULL
GROUP BY 1 HAVING COUNT(*)>1 — дубли конфликтных ключей; строки
valid_to IS NULL AND superseded_by IS NULL — сироты close-без-insert
старого кода. Новый чанковый путь атомарен (close+insert в одном
чанке) — тест test_b8_duplicate_actives_two_pass_stability.
"""
import time
from datetime import datetime, timezone

from proxy.core import _query, _log_error

# #728 B.3: узлов на транзакцию при массовом ребилде (замер на стенде:
# 500 апсерт-операций ≈ 30-60 мс — удержание лока на чанк с запасом ≤ 2 с).
KG_CHUNK = 500


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def kg_active(node_type=None, as_of=None):
    """Актуальные узлы (valid_to IS NULL) или срез на дату D.

    as_of: 'YYYY-MM-DD[ HH:MM:SS]' — узлы, действовавшие на момент D
    (valid_from <= D < valid_to). «Что было известно на дату D» из наряда.
    """
    where, params = [], []
    if as_of:
        where.append("valid_from <= ?")
        params.append(as_of)
        where.append("(valid_to IS NULL OR valid_to > ?)")
        params.append(as_of)
    else:
        where.append("valid_to IS NULL")
    if node_type:
        where.append("node_type = ?")
        params.append(node_type)
    sql = "SELECT * FROM knowledge_graph WHERE " + " AND ".join(where) + " ORDER BY node_type, node_name"
    return _query(sql, tuple(params), fetch=True) or []


def kg_history(node_type=None, node_name=None, limit=200):
    """Полная цепочка версий (новые сверху) — «обновлённый факт виден как цепочка версий»."""
    where, params = [], []
    if node_type:
        where.append("node_type = ?")
        params.append(node_type)
    if node_name:
        where.append("node_name = ?")
        params.append(node_name)
    sql = "SELECT * FROM knowledge_graph"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(valid_from, updated_at) DESC, id DESC LIMIT ?"
    params.append(limit)
    return _query(sql, tuple(params), fetch=True) or []


def kg_upsert(node_type, node_name, file_path, description, source="python",
              source_part_id=None, inference=0, review_status="approved",
              parent_count=1):
    """Вставить/обновить факт (живой API, одиночные вызовы). Возврат:
    (node_id, action) action ∈ new|updated|noop.

    - Активного узла ключа нет → новая версия (new).
    - Активный узел с тем же (file_path, description) → noop (чурлинг версий не нужен).
    - Активный узел с другим содержимым → закрыть (valid_to=now, superseded_by→новый id) + new.
    - Несколько активных узлов ключа с разными file_path → конфликт сущности:
      пишем в admin_findings, закрываем все, вставляем каноничную последнюю.

    #728 B.3: логика — в _kg_upsert_conn (одно соединение на вызов через
    _query-семантику); массовый путь kg_scan_rebuild переиспользует её же
    на чанковом соединении.
    """
    now = _now()
    active = _query(
        "SELECT * FROM knowledge_graph WHERE node_type = ? AND node_name = ? AND valid_to IS NULL",
        (node_type, node_name), fetch=True) or []

    if active:
        same = [r for r in active if r["file_path"] == file_path and (r["description"] or "") == (description or "")]
        if len(same) == len(active) and same:
            return same[0]["id"], "noop"  # факт не изменился
        if len({(r["file_path"] or "") for r in active}) > 1 and len(same) == 0:
            # конфликт сущности: одно имя — разные файлы; выносим на Admin
            try:
                _query(
                    "INSERT INTO admin_findings (severity, category, file, issue, fix, status) "
                    "VALUES ('medium', 'kg_entity_conflict', ?, ?, ?, 'open')",
                    (node_type + "/" + node_name,
                     f"{len(active)} активных узлов с разными file_path: "
                     + "; ".join(sorted({(r['file_path'] or '?') for r in active})),
                     "canonicalize: оставлена последняя версия (" + str(file_path) + ")"))
            except Exception as e:
                _log_error(f"kg conflict finding failed: {e}", source="kg", kind="data_loss")

    # закрыть все активные версии ключа
    closed_ids = []
    if active:
        _query("UPDATE knowledge_graph SET valid_to = ? WHERE node_type = ? AND node_name = ? AND valid_to IS NULL",
               (now, node_type, node_name))
        closed_ids = [r["id"] for r in active]

    _query(
        "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at, valid_from, valid_to, source_part_id, inference, review_status, parent_count) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
        (node_type, node_name, file_path, description, now, now,
         str(source_part_id) if source_part_id is not None else None,
         int(inference), review_status, int(parent_count)))
    row = _query("SELECT id FROM knowledge_graph WHERE node_type = ? AND node_name = ? AND valid_from = ? ORDER BY id DESC LIMIT 1",
                 (node_type, node_name, now), fetch=True)
    new_id = row[0]["id"] if row else None
    if closed_ids and new_id:
        _query("UPDATE knowledge_graph SET superseded_by = ? WHERE id IN (%s)" % ",".join("?" * len(closed_ids)),
               tuple([new_id] + closed_ids))
    return new_id, ("updated" if closed_ids else "new")


def _kg_upsert_conn(node_type, node_name, file_path, description, source,
                    inference, review_status, parent_count, now,
                    conn=None, active_rows=None):
    """#728 B.3: kg_upsert на ПЕРЕДАННОМ соединении (массовый путь ребилда).

    active_rows — уже прочитанные активные узлы ключа (кэш kg_scan_rebuild,
    по одному SELECT на ключ вместо четырёх запросов на узел). Управление
    транзакцией — у вызывающего (чанки): commit на границе чанка.

    #728 B.10: в массовом пути НЕ используется — kg_scan_rebuild пишет
    предвычисленными executemany-пакетами (см. ниже), этот путь — для
    одиночного живого kg_upsert (conn=None → _query) и наследуется им.
    """
    def _run(sql, params, fetch=False):
        if conn is None:
            return _query(sql, params, fetch=fetch)
        cur = conn.execute(sql, params)
        if fetch:
            return cur.fetchall()
        return None

    active = active_rows
    if active is None:
        active = _run(
            "SELECT * FROM knowledge_graph WHERE node_type = ? AND node_name = ? AND valid_to IS NULL",
            (node_type, node_name), fetch=True) or []

    if active:
        same = [r for r in active if r["file_path"] == file_path and (r["description"] or "") == (description or "")]
        if len(same) == len(active) and same:
            return same[0]["id"], "noop"  # факт не изменился
        if len({(r["file_path"] or "") for r in active}) > 1 and len(same) == 0:
            try:
                _run(
                    "INSERT INTO admin_findings (severity, category, file, issue, fix, status) "
                    "VALUES ('medium', 'kg_entity_conflict', ?, ?, ?, 'open')",
                    (node_type + "/" + node_name,
                     f"{len(active)} активных узлов с разными file_path: "
                     + "; ".join(sorted({(r['file_path'] or '?') for r in active})),
                     "canonicalize: оставлена последняя версия (" + str(file_path) + ")"))
            except Exception as e:
                _log_error(f"kg conflict finding failed: {e}", source="kg", kind="data_loss")

    closed_ids = []
    if active:
        _run("UPDATE knowledge_graph SET valid_to = ? WHERE node_type = ? AND node_name = ? AND valid_to IS NULL",
             (now, node_type, node_name))
        closed_ids = [r["id"] for r in active]

    _run(
        "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at, valid_from, valid_to, source_part_id, inference, review_status, parent_count) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
        (node_type, node_name, file_path, description, now, now,
         None, int(inference), review_status, int(parent_count)))
    row = _run("SELECT id FROM knowledge_graph WHERE node_type = ? AND node_name = ? AND valid_from = ? ORDER BY id DESC LIMIT 1",
               (node_type, node_name, now), fetch=True)
    new_id = row[0]["id"] if row else None
    if closed_ids and new_id:
        _run("UPDATE knowledge_graph SET superseded_by = ? WHERE id IN (%s)" % ",".join("?" * len(closed_ids)),
             tuple([new_id] + closed_ids))
    return new_id, ("updated" if closed_ids else "new")


def kg_scan_rebuild(nodes, source="scan"):
    """Перестройка графа со скана (админ-цикл) с сохранением истории.

    nodes: iterable of dict(node_type, node_name, file_path, description).
    Возврат: dict(inserted=, updated=, noop=, closed_missing=).

    Отличие от прежнего DELETE+INSERT: исчезнувшие со скана узлы закрываются
    (valid_to=now), а не стираются; неизменённые узлы не дублируются.

    #728 B.3: массовая запись — чанками по KG_CHUNK узлов, транзакция на чанк.
    #728 B.10 (аудит 21.11: kg_scan_rebuild держал запись 135–143 с —
    per-node SELECT id внутри чанковой транзакции, ~170 мс/узел): план
    записи строится ЦЕЛИКОМ в памяти по предпрочитанным активным строкам
    (один SELECT активных + один SELECT id до BEGIN), чанк = один
    executemany-пакет UPDATE + один INSERT-пакет без промежуточных
    SELECT'ов; commit на каждый чанк; [ua-tx] kg_chunk — held_ms чанка.
    #728 B.11 (аудит 21.11: ~815–855 updated каждую ночь при неизменных
    файлах): сущность узла — (node_type, node_name, file_path), НЕ
    (node_type, node_name). Прежний ключ схлопывал одноимённые паттерны
    разных файлов (Main1 ×30 файлов, _client ×28, main ×23 — расчёт по
    дереву 21.11: 917 «updated»/ночь без единого изменения) в один стек
    версий, перезаписываемый каждую ночь. Теперь одноимённые узлы разных
    файлов — самостоятельные сущности; сравнение содержимого — прежнее
    (file_path + description строкой): проверка на дереве 21.11 — новый
    ключ при идентичном скане даёт churn=0, нормализация не требуется.
    """
    now = _now()
    # ── предвычисление (ноль локов): активные строки по РАСШИРЕННОМУ ключу
    active = _query("SELECT * FROM knowledge_graph WHERE valid_to IS NULL", fetch=True) or []
    by_key = {}
    for r in active:
        # B.11: file_path — часть ключа сущности
        by_key.setdefault((r["node_type"], r["node_name"], (r["file_path"] or "")), []).append(r)

    parent_counts = {}
    try:
        rows = _query(
            "SELECT node_type, node_name, COUNT(DISTINCT file_path) AS n "
            "FROM knowledge_graph GROUP BY node_type, node_name", (), fetch=True) or []
        parent_counts = {(r["node_type"], r["node_name"]): max(int(r["n"]), 1) for r in rows}
    except Exception as e:
        _log_error(f"kg parent_count batch failed: {e}", source="kg", kind="db_read")

    # ── планирование БЕЗ записи (B.10): для каждого узла скана — решение
    # new / updated / noop и ГОТОВЫЕ пакеты строк; SELECT'ов в транзакции нет
    seen_keys = set()
    insert_rows = []      # (nt, nn, fp, desc, now, now, source_part_id, inference, review_status, parent_count)
    close_keys = []       # (node_type, node_name, file_path) — ключи со сменой содержимого
    inserted = updated = noop = 0
    from proxy.routes_admin import _ua_tx_log  # поздний импорт (цикл импортов)
    for n in nodes:
        key = (n.get("node_type"), n.get("node_name"), (n.get("file_path") or ""))
        seen_keys.add(key)
        rows = by_key.get(key) or []
        match = [r for r in rows
                 if (r["file_path"] or "") == (n.get("file_path") or "")
                 and (r["description"] or "") == (n.get("description") or "")]
        if rows and match:
            noop += 1
            continue
        if rows:
            close_keys.append(key)   # закрыть активные версии ключа
            updated += 1
        else:
            inserted += 1
        insert_rows.append(
            (n.get("node_type"), n.get("node_name"), n.get("file_path"),
             n.get("description"), now, now, None, 1, "pending",
             parent_counts.get((n.get("node_type"), n.get("node_name")), 1)))

    # ── запись чанками (B.10): executemany-пакеты, commit на чанк,
    #    ни одного SELECT внутри транзакции
    import sqlite3
    from proxy.core import DB_FILE
    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        for i in range(0, len(insert_rows), KG_CHUNK):
            _tc = time.monotonic()
            chunk_ins = insert_rows[i:i + KG_CHUNK]
            # ключи закрытия для этого чанка (по вхождениям close-ключей
            # узлов чанка — порядок параллелен insert_rows)
            chunk_close = close_keys[i:i + KG_CHUNK] if len(close_keys) == len(insert_rows) else []
            try:
                if chunk_close:
                    conn.executemany(
                        "UPDATE knowledge_graph SET valid_to = ? "
                        "WHERE node_type = ? AND node_name = ? AND file_path = ? AND valid_to IS NULL",
                        [(now, k[0], k[1], k[2]) for k in chunk_close])
                conn.executemany(
                    "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, "
                    "updated_at, valid_from, valid_to, source_part_id, inference, review_status, parent_count) "
                    "VALUES (?,?,?,?,?,?,NULL,?,?,?,?)",
                    chunk_ins)
                conn.commit()  # write-лок чанка снят
                try:
                    _ua_tx_log("kg_chunk", rows=len(chunk_ins),
                               held_ms=int((time.monotonic() - _tc) * 1000), source=source,
                               batch=i // KG_CHUNK,
                               closed=len(chunk_close))
                except Exception:
                    pass  # телеметрия не роняет запись
            except sqlite3.Error:
                conn.rollback()
                raise
    finally:
        conn.close()

    # superseded_by: одна связка «закрытые → новые» вне горячего пути —
    # INSERT'ы чанка имеют id > всех закрытых; по ключу, без SELECT на узел
    if close_keys:
        try:
            conn2 = sqlite3.connect(str(DB_FILE), timeout=5.0)
            try:
                conn2.execute("PRAGMA busy_timeout=5000")
                for i in range(0, len(close_keys), KG_CHUNK):
                    ck = close_keys[i:i + KG_CHUNK]
                    conn2.execute(
                        "UPDATE knowledge_graph SET superseded_by = ("
                        "  SELECT id FROM knowledge_graph n"
                        "  WHERE n.node_type = knowledge_graph.node_type"
                        "    AND n.node_name = knowledge_graph.node_name"
                        "    AND n.file_path = knowledge_graph.file_path"
                        "    AND n.valid_from = ? ORDER BY n.id DESC LIMIT 1)"
                        "WHERE valid_to = ? AND superseded_by IS NULL"
                        "  AND (node_type, node_name, file_path) IN (VALUES "
                        + ",".join("(?,?,?)" for _ in ck) + ")",
                        tuple([now, now] + [v for k in ck for v in k]))
                    conn2.commit()
            finally:
                conn2.close()
        except sqlite3.Error as e:
            # superseded_by — производная цепочка истории; сбой связки не
            # роняет ребилд (версии закрыты/вставлены), пишем в error_log
            _log_error(f"kg superseded_by link failed: {e}", source="kg", kind="db_write")

    # узлы, исчезнувшие со скана, — закрыть (чанками той же дисциплиной)
    closed_missing = 0
    missing = [key for key, rows in by_key.items() if key not in seen_keys]
    for i in range(0, len(missing), KG_CHUNK):
        chunk = missing[i:i + KG_CHUNK]
        _query("UPDATE knowledge_graph SET valid_to = ? WHERE valid_to IS NULL AND "
               "(node_type, node_name, file_path) IN (VALUES " + ",".join("(?,?,?)" for _ in chunk) + ")",
               tuple([now] + [v for key in chunk for v in key]))
        closed_missing += sum(len(by_key[key]) for key in chunk)
    return {"inserted": inserted, "updated": updated, "noop": noop, "closed_missing": closed_missing}
