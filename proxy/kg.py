"""FO-009: темпоральный knowledge_graph — версионирование узлов вместо перезаписи.

Наряд #69: узел валиден на интервале [valid_from, valid_to); NULL valid_to = актуально.
Обновление факта = закрытие старого узла (valid_to=now, superseded_by→новый id)
+ вставка новой версии. История не теряется; читается по умолчанию только актуальное.

Entity resolution (по наряду, простое правило): тот же (node_type, node_name) →
тот же субъект. Конфликт (несколько активных узлов ключа с разными file_path)
фиксируется в admin_findings и схлопывается в каноничную последнюю версию.
"""
from datetime import datetime, timezone

from proxy.core import _query, _log_error


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


def kg_upsert(node_type, node_name, file_path, description, source="python"):
    """Вставить/обновить факт. Возврат: (node_id, action) action ∈ new|updated|noop.

    - Активного узла ключа нет → новая версия (new).
    - Активный узел с тем же (file_path, description) → noop (чурлинг версий не нужен).
    - Активный узел с другим содержимым → закрыть (valid_to=now, superseded_by=новый id) + new.
    - Несколько активных узлов ключа с разными file_path → конфликт сущности:
      пишем в admin_findings, закрываем все, вставляем каноничную последнюю.
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
        "INSERT INTO knowledge_graph (node_type, node_name, file_path, description, updated_at, valid_from, valid_to) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (node_type, node_name, file_path, description, now, now))
    row = _query("SELECT id FROM knowledge_graph WHERE node_type = ? AND node_name = ? AND valid_from = ? ORDER BY id DESC LIMIT 1",
                 (node_type, node_name, now), fetch=True)
    new_id = row[0]["id"] if row else None
    if closed_ids and new_id:
        _query("UPDATE knowledge_graph SET superseded_by = ? WHERE id IN (%s)" % ",".join("?" * len(closed_ids)),
               tuple([new_id] + closed_ids))
    return new_id, ("updated" if closed_ids else "new")


def kg_scan_rebuild(nodes, source="scan"):
    """Перестройка графа со скана (админ-цикл) с сохранением истории.

    nodes: iterable of dict(node_type, node_name, file_path, description).
    Возврат: dict(inserted=, updated=, noop=, closed_missing=).

    Отличие от прежнего DELETE+INSERT: исчезнувшие со скана узлы закрываются
    (valid_to=now), а не стираются; неизменённые узлы не дублируются.
    """
    now = _now()
    active = _query("SELECT * FROM knowledge_graph WHERE valid_to IS NULL", fetch=True) or []
    by_key = {}
    for r in active:
        by_key.setdefault((r["node_type"], r["node_name"]), []).append(r)

    seen_keys = set()
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
        node_id, action = kg_upsert(n.get("node_type"), n.get("node_name"),
                                    n.get("file_path"), n.get("description"), source=source)
        if action == "new":
            inserted += 1
        elif action == "updated":
            updated += 1
        else:
            noop += 1

    # узлы, исчезнувшие со скана, — закрыть
    closed_missing = 0
    for key, rows in by_key.items():
        if key not in seen_keys:
            _query("UPDATE knowledge_graph SET valid_to = ? WHERE valid_to IS NULL AND node_type = ? AND node_name = ?",
                   tuple([now, key[0], key[1]]))
            closed_missing += len(rows)
    return {"inserted": inserted, "updated": updated, "noop": noop, "closed_missing": closed_missing}
