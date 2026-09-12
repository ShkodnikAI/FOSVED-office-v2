"""FO-020: Review-очередь выведенных знаний — approve/decline/undo.

Наряд #86 (пакет G, волна G2). Эталон: supermemory inference review —
выведенное помечено isInference=true и понижено в весе выдачи, пока человек
не подтвердит. Догадки не должны «врать молча».

Источники выведенного:
- facts (FO-006, консолидация диалогов) — inference=1, review_status='pending',
  parent_count = число диалогов-источников (source_dialog_ids);
- knowledge_graph (FO-009, анализатор сканов) — inference=1, pending,
  parent_count = число различных file_path в истории узла.

Семантика решений:
- approve → review_status='approved'  — полный вес в ранжировании;
- decline → review_status='declined' + decline_reason (soft-delete —
  исключается из выдачи, строка остаётся);
- undo    → возврат в 'pending' (отмена последнего решения).

Все решения — в audit_log (FO-007). Очередь не блокирует работу офиса:
невыверенное просто легче (штраф веса в ранжировании, см. fosved_memory).
Авто-апрув не предусмотрен (владелец — единственный ревьюер в v1);
глубина очереди > 50 → уведомление владельцу в Telegram.
"""
import json

from proxy.core import log, _query, _get_setting, _log_audit

REVIEW_SOURCES = ("fact", "kg")
REVIEW_DECISIONS = ("approve", "decline", "undo")
QUEUE_OVERFLOW_THRESHOLD = 50


def _validate(source, decision):
    if source not in REVIEW_SOURCES:
        raise ValueError(f"unknown review source: {source!r} (v1: {REVIEW_SOURCES})")
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"unknown decision: {decision!r} (v1: {REVIEW_DECISIONS})")


def queue_depth():
    """Число невыверенных (pending) записей обоих источников."""
    f = _query("SELECT COUNT(*) AS n FROM facts WHERE status='active' AND review_status='pending'",
               fetch=True)
    k = _query("SELECT COUNT(*) AS n FROM knowledge_graph WHERE valid_to IS NULL AND review_status='pending'",
               fetch=True)
    return (f[0]["n"] if f else 0) + (k[0]["n"] if k else 0)


def get_review_queue(limit=50, source=None):
    """Очередь ревью, отсортированная по parent_count DESC (сильнейший
    сигнал — сколько источников поддерживают вывод — сверху).

    source: None | 'fact' | 'kg'. Каждый item несёт sources (идентификаторы
    источников: диалоги для facts, file_path для kg).
    """
    items = []
    if source in (None, "fact"):
        rows = _query(
            "SELECT id, dept, content, parent_count, source_dialog_ids, confidence, created_at "
            "FROM facts WHERE status='active' AND review_status='pending' "
            "ORDER BY parent_count DESC, created_at DESC LIMIT ?",
            (int(limit),), fetch=True) or []
        for r in rows:
            try:
                sources = json.loads(r["source_dialog_ids"] or "[]")
            except (ValueError, TypeError):
                sources = []
            items.append({"id": r["id"], "source": "fact", "dept": r["dept"] or "",
                          "content": r["content"], "parent_count": r["parent_count"] or 1,
                          "sources": sources, "confidence": r["confidence"],
                          "created_at": r["created_at"]})
    if source in (None, "kg"):
        rows = _query(
            "SELECT id, node_type, node_name, file_path, description, parent_count, valid_from "
            "FROM knowledge_graph WHERE valid_to IS NULL AND review_status='pending' "
            "ORDER BY parent_count DESC, valid_from DESC LIMIT ?",
            (int(limit),), fetch=True) or []
        for r in rows:
            content = (r["description"] or "").strip() or f"{r['node_type']}/{r['node_name']}"
            items.append({"id": r["id"], "source": "kg",
                          "dept": f"kg/{r['node_type']}",
                          "content": f"{r['node_name']}: {content}",
                          "parent_count": r["parent_count"] or 1,
                          "sources": [r["file_path"]] if r["file_path"] else [],
                          "confidence": None, "created_at": r["valid_from"]})
    items.sort(key=lambda x: str(x["created_at"] or ""), reverse=True)  # свежие вперёд
    items.sort(key=lambda x: x["parent_count"], reverse=True)            # затем по числу источников
    return items[:int(limit)]


def decide_review(item_id, source, decision, reason=None, actor="owner"):
    """Применить решение ревью. Все решения пишутся в audit_log.
    Возврат: dict статуса записи; ValueError при неверных аргументах."""
    _validate(source, decision)
    item_id = int(item_id)
    if source == "fact":
        row = _query("SELECT id, content, review_status FROM facts WHERE id = ?",
                     (item_id,), fetch=True)
    else:
        row = _query("SELECT id, node_name, review_status FROM knowledge_graph WHERE id = ?",
                     (item_id,), fetch=True)
    if not row:
        raise LookupError(f"{source}#{item_id} not found")
    prev = row[0]["review_status"] or "approved"

    if decision == "approve":
        new_status, note = "approved", None
    elif decision == "decline":
        new_status, note = "declined", (reason or "без причины")[:300]
    else:  # undo
        new_status, note = "pending", None

    if source == "fact":
        if decision == "decline":
            # soft-delete: строка остаётся, исключается из выдачи; content цел
            _query("UPDATE facts SET review_status='declined', decline_reason=?, updated_at=datetime('now') WHERE id=?",
                   (note, item_id))
        else:
            _query("UPDATE facts SET review_status=?, decline_reason=COALESCE(?, decline_reason) WHERE id=?",
                   (new_status, note, item_id))
        label = (row[0]["content"] or "")[:120]
    else:
        _query("UPDATE knowledge_graph SET review_status=? WHERE id=?", (new_status, item_id))
        label = (row[0]["node_name"] or "")[:120]

    _log_audit(f"review_{decision}", {
        "item_id": item_id, "source": source, "decision": decision,
        "prev_status": prev, "new_status": new_status,
        "reason": note, "content_head": label, "actor": actor,
    }, "memory")
    log.info(f"review: {source}#{item_id} {decision} ({prev} -> {new_status}) by {actor}")
    return {"id": item_id, "source": source, "review_status": new_status,
            "previous": prev, "decline_reason": note}


def notify_queue_overflow_if_needed(threshold=QUEUE_OVERFLOW_THRESHOLD):
    """Глубина очереди > threshold → уведомление владельцу в Telegram
    (вызывается после ночной консолидации). Возврат: dict|None."""
    depth = queue_depth()
    if depth <= threshold:
        return None
    owner = os_owner_id()
    if not owner:
        log.warning("review: queue overflow but OWNER_TELEGRAM_ID is empty")
        return None
    try:
        from proxy.telegram import _tg_send_message
        text = (f"🔍 Review-очередь выросла: {depth} невыверенных выводов "
                f"(порог {threshold}).\nКоманда /review — сильнейшие источники сверху.")
        _tg_send_message(owner, text)
        _log_audit("review_queue_overflow", {"depth": depth, "threshold": threshold}, "memory")
        return {"notified": True, "depth": depth}
    except Exception as e:
        log.warning(f"review: overflow notify failed (non-fatal): {e}")
        return {"notified": False, "depth": depth, "error": str(e)[:200]}


def os_owner_id():
    import os
    return os.environ.get("OWNER_TELEGRAM_ID", "")
