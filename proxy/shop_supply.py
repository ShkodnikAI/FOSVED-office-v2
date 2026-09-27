"""SHOP-SUPPLY-1 (наряд #421, волна 1 «Виртуальный снабженец») — очередь заданий снабженцу.

Зачем: 7 из 10 MVP-площадок (ozon, 21vek, tmby, 7745, shopby, tomas,
unishop) недоступны с датацентровых IP Render (антибот/GeoIP/капча —
рекогносцировка наряда, живые пробы 2026-09-24/27). Единственный честный
путь к ним — настоящий браузер на домашнем IP владельца: внешний
клиент-снабженец (волна 2, отдельный наряд в закрытом репо
fosved-supply-agent) опрашивает офис по /supply/next, ходит на площадку
и возвращает офферы через /supply/result.

Контур (этот модуль):
  - refresh_product() для площадок из SUPPLY_AGENT_PLATFORMS больше не
    вызывает collect() — ставит задание в очередь (shop_supply_queue) и
    возвращает kind="supply_pending" (старые antibot_blocked/api_form_unknown
    больше не притворяются, что «сбор не удался» — теперь сбор ВОЗМОЖЕН,
    он просто выполняется снабженцем);
  - GET /supply/next (routes_tail) — выдача следующего задания FIFO;
    одно задание — одному вызову: pending → dispatched атомарно;
  - POST /supply/result (routes_tail) — приём результата: ok:true →
    офферы сохраняются ТЕМ ЖЕ кодом, что и обычный collect()-результат
    (proxy.shop_collectors._persist_offers — SQL не дублируется);
    ok:false → failed с kind/error от снабженца (antibot_blocked и т.п.);
  - expire_stale_tasks() — задания без результата дольше timeout_s →
    failed, kind="task_timeout" (не блокируют очередь вечно).

Тайминг-модель: задание живёт от выдачи (dispatched_at) или от создания
(pending) не дольше timeout_s; протухшее — failed. Новый цикл сбора
(такт вотчлиста / досье) поставит свежее задание — очередь самовосстанавливается.

CONTRACT.md (закрытый репо fosved-supply-agent @ 212fcb19) исполнителю
недоступен (токен офиса не имеет доступа — 403, проверено клоном
2026-09-28). Формат провода ниже реконструирован по проверяемому
чек-листу наряда #421; расхождение с контрактом ловится пост-приёмкой
владельца (раздел «Сделано когда»).

Модель гонок: офис на Render — ОДИН python-процесс (llm_proxy.py,
app.run threaded=True, один инстанс 512 МБ), поэтому выдача заданий
закрыта process-local _dequeue_lock вокруг SELECT+UPDATE (двух _query
не сшить в одну транзакцию без RETURNING). SQLite-перезаписи между
процессами отсутствуют по построению деплоя.
"""
import hmac
import json
import logging
import os
import threading
import uuid

log = logging.getLogger("shop_supply")

# Ровно те 7 площадок, что по факту требуют домашний IP и/или настоящий
# браузер (наряд #421). wb/onliner/ym собираются сервером как раньше —
# в списке ОТСУТСТВУЮТ и без отдельного решения владельца не появляются.
SUPPLY_AGENT_PLATFORMS = {"ozon", "21vek", "tmby", "7745", "shopby", "tomas", "unishop"}

# Дефолтное окно на исполнение задания. Клиент волны 2 опрашивает раз в
# 30–60 с; 15 минут — с запасом на очередь из нескольких заданий и
# медленный браузерный проход. Переопределяется env SUPPLY_TASK_TIMEOUT_S.
DEFAULT_TASK_TIMEOUT_S = 900

# Тип задания: ensure_product отдаёт только «search» (поиск площадки по
# запросу). open_url/check_price — задел на будущее (наряд #421), в эту
# волну не заполняются.
TASK_TYPE_SEARCH = "search"

# Статусы очереди: pending → dispatched → done | failed.
STATUS_PENDING = "pending"
STATUS_DISPATCHED = "dispatched"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# Process-local выдача (см. докстринг модуля про модель гонок).
_dequeue_lock = threading.Lock()


def _default_timeout_s():
    raw = os.environ.get("SUPPLY_TASK_TIMEOUT_S", "")
    if raw.strip():
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            log.warning("SUPPLY_TASK_TIMEOUT_S=%r не целое — дефолт %s с",
                        raw, DEFAULT_TASK_TIMEOUT_S)
    return DEFAULT_TASK_TIMEOUT_S


def _audit(details, status):
    """Журнал очереди в audit_log (тот же класс, что shop_collectors._audit):
    ошибка журнала не роняет очередь."""
    try:
        from proxy.core import _query
        _query("INSERT INTO audit_log (action, actor, dept, details, status) "
               "VALUES ('shop_supply', 'shop', 'shop', ?, ?)", (details, status))
    except Exception as e:  # noqa: BLE001
        log.warning("audit_log недоступен: %s", e)


def ensure_schema():
    """Таблица очереди — DDL ровно по наряду #421 (идемпотентно, как shop_sources)."""
    from proxy.core import _query
    _query(
        "CREATE TABLE IF NOT EXISTS shop_supply_queue("
        "task_id TEXT PRIMARY KEY, product_id INTEGER, platform TEXT, "
        "type TEXT, query TEXT, url TEXT, status TEXT, created_at TEXT, "
        "dispatched_at TEXT, timeout_s INTEGER, result_json TEXT, "
        "error TEXT, kind TEXT)")


def token_ok(auth_header):
    """Сверка Authorization: Bearer <SUPPLY_AGENT_TOKEN>.

    Fail-closed: токен не задан в окружении → любой заголовок отклоняется
    (паттерн ACTIVITY_FEED_TOKEN / урок #325 — открытых при незаданном
    секрете эндпоинтов быть не должно). Сравнение — compare_digest.
    """
    expected = os.environ.get("SUPPLY_AGENT_TOKEN", "")
    if not expected:
        return False
    supplied = str(auth_header or "")
    if not supplied.startswith("Bearer "):
        return False
    return hmac.compare_digest(supplied[len("Bearer "):], expected)


def enqueue_supply_task(product_id, platform, query):
    """Поставить задание «search» в очередь. Возвращает task_id.

    expire_stale_tasks() здесь же (см. наряд #421: протухшие задания
    не должны доживать до чужого dequeue): /shop/diagnose и такт вотчлиста
    попадают сюда через ensure_product → refresh_product, отдельного крона
    в эту волну нет сознательно (не плодить /cron/*).
    """
    from proxy.core import _query
    ensure_schema()
    expire_stale_tasks()
    task_id = str(uuid.uuid4())
    _query(
        "INSERT INTO shop_supply_queue (task_id, product_id, platform, type, "
        "query, url, status, created_at, timeout_s) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?, datetime('now'), ?)",
        (task_id, int(product_id), platform, TASK_TYPE_SEARCH,
         str(query or ""), STATUS_PENDING, _default_timeout_s()))
    _audit(f"enqueue task={task_id} platform={platform} "
           f"product={product_id} query={str(query or '')[:80]}",
           STATUS_PENDING)
    return task_id


def expire_stale_tasks():
    """pending/dispatched без результата дольше timeout_s → failed/task_timeout.

    Точка отсчёта — выдача (dispatched_at), для невыданных — создание.
    Единый SQL-клок datetime('now') против datetime(created_at/dispatched_at):
    ничего не сравнивается с часами Python.
    """
    from proxy.core import _query
    ensure_schema()
    _query(
        "UPDATE shop_supply_queue SET status=?, kind='task_timeout', "
        "error=COALESCE(error, 'задание протухло без результата (timeout_s)') "
        "WHERE status IN (?, ?) AND timeout_s IS NOT NULL AND timeout_s > 0 "
        "AND datetime(COALESCE(dispatched_at, created_at), "
        "  '+' || CAST(timeout_s AS TEXT) || ' seconds') <= datetime('now')",
        (STATUS_FAILED, STATUS_PENDING, STATUS_DISPATCHED))


def dequeue_next_task():
    """Следующее задание FIFO (created_at ASC) или None.

    pending → dispatched атомарно в смысле «одно задание — одному вызову»:
    выдача держит _dequeue_lock от SELECT до подтверждённого UPDATE
    (WHERE task_id=? AND status='pending'), повторная выдача того же
    задания до истечения таймаута исключена; протухший dispatched
    уводит expire_stale_tasks() в failed.
    """
    from proxy.core import _query
    ensure_schema()
    with _dequeue_lock:
        expire_stale_tasks()
        rows = _query(
            "SELECT * FROM shop_supply_queue WHERE status=? "
            "ORDER BY created_at, rowid LIMIT 1",
            (STATUS_PENDING,), fetch=True)
        if not rows:
            return None
        task = dict(rows[0])
        _query(
            "UPDATE shop_supply_queue SET status=?, dispatched_at=datetime('now') "
            "WHERE task_id=? AND status=?",
            (STATUS_DISPATCHED, task["task_id"], STATUS_PENDING))
        check = _query("SELECT status FROM shop_supply_queue WHERE task_id=?",
                       (task["task_id"],), fetch=True)
        if not check or check[0]["status"] != STATUS_DISPATCHED:
            # выдать другому не смогли (состояние изменилось) — честный None
            return None
        _audit(f"dispatch task={task['task_id']} platform={task['platform']} "
               f"product={task['product_id']}", STATUS_DISPATCHED)
        return {
            "task_id": task["task_id"],
            "product_id": task["product_id"],
            "platform": task["platform"],
            "type": task["type"],
            "query": task["query"],
            "url": task["url"],
        }


def apply_supply_result(task_id, payload):
    """Применить результат снабженца. Возвращает dict приёма.

    ok:true  → офферы сохраняются тем же путём, что collect()-результат
               (_persist_offers в shop_collectors: shop_offers /
               _upsert_seller / shop_price_history — SQL не дублируется),
               статус done, payload целиком в result_json (аудит-след).
    ok:false → статус failed, kind/error из payload (antibot_blocked и
               т.п. — честный исход, площадка в /shop/diagnose показывает
               именно его, а не supply_pending).

    Приём результата и успех на площадке — разные вещи: этот вызов может
    вернуть applied=True при payload ok:false (отказ снабженца принят).
    """
    from proxy.core import _query
    ensure_schema()
    if not isinstance(payload, dict):
        return {"applied": False, "error": "payload должен быть JSON-объектом"}
    rows = _query("SELECT * FROM shop_supply_queue WHERE task_id=?",
                  (task_id,), fetch=True)
    if not rows:
        return {"applied": False, "error": "задание не найдено"}
    task = dict(rows[0])
    if task["status"] in (STATUS_DONE, STATUS_FAILED):
        return {"applied": False,
                "error": f"задание уже закрыто (status={task['status']})"}
    ok = bool(payload.get("ok"))
    result_json = json.dumps(payload, ensure_ascii=False)
    kind = payload.get("kind")
    error = None if ok else str(payload.get("error") or "")
    offers_saved = 0
    if ok:
        offers = payload.get("offers")
        if isinstance(offers, list) and offers:
            # батч-валидация ДО записи: кривой оффер не должен ронять
            # 500-й посередине _persist_offers (половина батча уже в БД)
            bad = [i for i, o in enumerate(offers)
                   if not isinstance(o, dict)
                   or not str(o.get("platform_code") or "").strip()
                   or not str(o.get("url") or "").strip()]
            if bad:
                ok = False
                kind = "result_format"
                error = (f"офферы {bad} без platform_code/url — "
                         "формат раздела 4 контракта нарушен")
            else:
                from proxy.shop_collectors import _persist_offers
                offers_saved, _hist = _persist_offers(
                    int(task["product_id"]), task["platform"], offers)
        elif isinstance(offers, list):
            offers_saved = 0  # честный «ничего не нашлось» — тоже результат
        else:
            ok = False  # ok:true без offers[] — формат раздела 4 нарушен
            kind = "result_format"
            error = "ok:true без offers[] — формат раздела 4 контракта нарушен"
    _query(
        "UPDATE shop_supply_queue SET status=?, result_json=?, kind=?, "
        "error=? WHERE task_id=?",
        (STATUS_DONE if ok else STATUS_FAILED, result_json, kind, error,
         task_id))
    _audit(f"result task={task_id} platform={task['platform']} ok={ok} "
           f"kind={kind} offers_saved={offers_saved}",
           STATUS_DONE if ok else (kind or STATUS_FAILED))
    return {"applied": True, "ok": ok, "offers_saved": offers_saved,
            "kind": kind, "error": error}
