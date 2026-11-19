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
"""
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

    #728 B.3: массовая запись — чанками по KG_CHUNK узлов, транзакция на чанк
    (одно соединение с busy_timeout на весь проход). Прежде kg_upsert на
    каждый узел открывал до 4 собственных соединений через _query — при
    ~6.1k узлов скана это тысячи мелких транзакций подряд, практически
    непрерывный write-лок общей БД (прод 19.11: Grapher ~11 мин).
    """
    now = _now()
    active = _query("SELECT * FROM knowledge_graph WHERE valid_to IS NULL", fetch=True) or []
    by_key = {}
    for r in active:
        by_key.setdefault((r["node_type"], r["node_name"]), []).append(r)

    # parent_count (FO-020) — один агрегатный запрос вместо запроса на узел
    parent_counts = {}
    try:
        rows = _query(
            "SELECT node_type, node_name, COUNT(DISTINCT file_path) AS n "
            "FROM knowledge_graph GROUP BY node_type, node_name", (), fetch=True) or []
        parent_counts = {(r["node_type"], r["node_name"]): max(int(r["n"]), 1) for r in rows}
    except Exception as e:
        _log_error(f"kg parent_count batch failed: {e}", source="kg", kind="db_read")

    # Планирование БЕЗ записи: noop / close_missing / upsert-очередь
    seen_keys = set()
    upsert_queue = []   # узлы, требующие kg_upsert (new/updated)
    inserted = updated = noop = 0
    for n in nodes:
        key = (n.get("node_type"), n.get("node_name"))
        seen_keys.add(key)
        rows = by_key.get(key) or []
        match = [r for r in rows if (r["file_path"] or "") == (n.get("file_path") or "")
                 and (r["description"] or "") == (n.get("description") or "")]
        if rows and match:
            noop += 1
            continue
        upsert_queue.append(n)

    # Чанковая запись: KG_CHUNK узлов → одна транзакция (свой conn с
    # busy_timeout; #728 B.3 — короткие транзакции вместо per-node коннектов)
    import sqlite3
    from proxy.core import DB_FILE
    conn = sqlite3.connect(str(DB_FILE), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        for i in range(0, len(upsert_queue), KG_CHUNK):
            chunk = upsert_queue[i:i + KG_CHUNK]
            try:
                for n in chunk:
                    key = (n.get("node_type"), n.get("node_name"))
                    node_id, action = _kg_upsert_conn(
                        n.get("node_type"), n.get("node_name"),
                        n.get("file_path"), n.get("description"), source=source,
                        inference=1, review_status="pending",
                        parent_count=parent_counts.get(key, 1),
                        now=now, conn=conn, active_rows=by_key.get(key) or [])
                    if action == "new":
                        inserted += 1
                    elif action == "updated":
                        updated += 1
                    else:
                        noop += 1
                conn.commit()  # граница чанка: write-лок снят
            except sqlite3.Error:
                conn.rollback()
                raise
    finally:
        conn.close()

    # узлы, исчезнувшие со скана, — закрыть (чанками той же транзакционной дисциплиной)
    closed_missing = 0
    missing = [key for key, rows in by_key.items() if key not in seen_keys]
    for i in range(0, len(missing), KG_CHUNK):
        chunk = missing[i:i + KG_CHUNK]
        _query("UPDATE knowledge_graph SET valid_to = ? WHERE valid_to IS NULL AND "
               "(node_type, node_name) IN (VALUES " + ",".join("(?,?)" for _ in chunk) + ")",
               tuple([now] + [v for key in chunk for v in key]))
        closed_missing += sum(len(by_key[key]) for key in chunk)
    return {"inserted": inserted, "updated": updated, "noop": noop, "closed_missing": closed_missing}
