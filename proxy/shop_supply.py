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

Наряд №598 (доводка): возможности снабженца (X-Supply-Platforms →
system_settings supply_platforms/supply_last_seen; фолбэк env
SUPPLY_AGENT_COLLECTORS, дефолт 7745) режут очередь до интерсекции
SUPPLY_AGENT_PLATFORMS ∩ supply_platforms; статус связи — живой в
humanize_source_status (shop_dossier); закрытие волны заданий товара →
одно сообщение «Досье обновлено» владельцу (shop_supply_waves.notified,
ночь 00:00–06:59 МСК → owner_outbox).

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
from datetime import datetime, timedelta, timezone

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

# №598 A.1: платформы, которые снабженец СЕЙЧАС умеет собирать, и время
# последнего его контакта — ключи в system_settings (общая kv с Metalogos).
# Порядок разрешения: заголовок X-Supply-Platforms из /supply/next (авторитет
# живого снабженца) → env SUPPLY_AGENT_COLLECTORS → дефолт 7745.
# Фолбэк обязателен (наряд №598, A.1): старый снабженец без заголовка
# должен продолжать получать задания.
SUPPLY_PLATFORMS_KEY = "supply_platforms"
SUPPLY_LAST_SEEN_KEY = "supply_last_seen"
SUPPLY_COLLECTORS_ENV = "SUPPLY_AGENT_COLLECTORS"
SUPPLY_COLLECTORS_DEFAULT = "7745"

# №598 A.2: «снабженец доступен» = контакт не старше 5 минут.
SUPPLY_FRESH_SECS = 300

# №598 A.3: ночное окно тишины для сообщений «Досье обновлено» —
# 00:00–06:59 МСК (МСК = UTC+3): ночью — в owner_outbox (доставка слотом
# night-report 07:15 МСК), днём — сразу в Telegram.
SOURCE_OUTBOX = "shop-supply"

# Process-local выдача (см. докстринг модуля про модель гонок).
_dequeue_lock = threading.Lock()
# №598 A.3: выдача «одного сообщения на волну» — тот же класс гонок,
# что и dequeue (один python-процесс, потоки Flask): check+mark под замком.
_notify_lock = threading.Lock()


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
    """Таблица очереди — DDL ровно по наряду #421 (идемпотентно, как shop_sources).

    №598 A.3: + wave_id (какая волна заданий; одно сообщение на волну)
    и реестр волн shop_supply_waves (флаг notified — защита от дублей).
    Миграция wave_id — идемпотентный ALTER на КАЖДЫЙ вызов (не флаг
    процесса: тесты и многобазовость — урок волны #598, флаг-процесс
    пропускал ALTER для второй БД → «no such column»). Повторный ALTER
    на мигрированной базе — дешёвый ожидаемый OperationalError.
    """
    from proxy.core import _query
    _query(
        "CREATE TABLE IF NOT EXISTS shop_supply_queue("
        "task_id TEXT PRIMARY KEY, product_id INTEGER, platform TEXT, "
        "type TEXT, query TEXT, url TEXT, status TEXT, created_at TEXT, "
        "dispatched_at TEXT, timeout_s INTEGER, result_json TEXT, "
        "error TEXT, kind TEXT)")
    _query(
        "CREATE TABLE IF NOT EXISTS shop_supply_waves("
        "wave_id TEXT PRIMARY KEY, product_id INTEGER, "
        "notified INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))")
    try:
        _query("ALTER TABLE shop_supply_queue ADD COLUMN wave_id TEXT")
    except Exception as e:  # noqa: BLE001 — «duplicate column» = база уже мигрирована
        if "duplicate column name" not in str(e).lower():
            log.warning("supply: миграция wave_id не применилась: %s", e)


def _parse_platforms_csv(raw):
    """"7745, ozon" → ("7745", "ozon") — нормализация без дублей и пустых."""
    seen = dict.fromkeys(p.strip().lower() for p in str(raw or "").split(","))
    return tuple(p for p in seen if p)


def resolve_supplier_platforms():
    """№598 A.1: что снабженец умеет сейчас — frozenset платформ.

    Порядок: system_settings supply_platforms (заполняется из заголовка
    X-Supply-Platforms живого снабженца) → env SUPPLY_AGENT_COLLECTORS →
    дефолт 7745. Фолбэк — совместимость со старым снабженцем без заголовка.
    """
    from proxy.core import _get_setting
    raw = _get_setting(SUPPLY_PLATFORMS_KEY, "")
    if not raw.strip():
        raw = os.environ.get(SUPPLY_COLLECTORS_ENV, "") or SUPPLY_COLLECTORS_DEFAULT
    return frozenset(_parse_platforms_csv(raw))


def touch_supplier(x_supply_platforms):
    """№598 A.1: контакт снабженца (вызывается из GET /supply/next при валидном токене).

    supply_last_seen — всегда (SQLite datetime('now'), UTC — единый клок
    с created_at/dispatched_at очереди). supply_platforms — только когда
    заголовок реально пришёл: старый снабженец без заголовка НЕ должен
    затирать записанные возможности; их тогда держит env/дефолт.
    """
    from proxy.core import _query
    _query("INSERT OR REPLACE INTO system_settings (key, value) "
           "VALUES (?, datetime('now'))", (SUPPLY_LAST_SEEN_KEY,))
    plats = _parse_platforms_csv(x_supply_platforms)
    if plats:
        _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
               (SUPPLY_PLATFORMS_KEY, ",".join(plats)))
        log.info("supply: возможности снабженца: %s", ",".join(plats))


def supplier_last_seen():
    """№598 A.2: datetime последнего контакта снабженца (UTC) или None."""
    from proxy.core import _get_setting
    raw = _get_setting(SUPPLY_LAST_SEEN_KEY, "")
    if not raw.strip():
        return None
    try:
        return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        log.warning("supply_last_seen=%r не разобран — считаем связи не было", raw)
        return None


def _is_supply_night_msk(now=None):
    """№598 A.3: ночное окно 00:00–06:59 МСК (МСК = UTC+3, фиксированный пояс).

    Ночью сообщение о обновлённом досье уходит в owner_outbox (доставка
    слотом night-report 07:15 МСК), днём — сразу в Telegram. Отдельная
    функция (не routes_tail._is_night_msk): окно наряда #598 — 00:00,
    а не 22:00 тишины #550.
    """
    dt = now or datetime.now(timezone.utc)
    return (dt.hour + 3) % 24 < 7


def _assign_wave(product_id):
    """№598 A.3: wave_id для нового задания — открытая волна товара или новая.

    Открытая = у товара есть pending/dispatched (задания одного такта
    ensure_product/вотча сшиваются в одну волну → одно сообщение).
    Всё закрыто → новая волна uuid4 + строка в реестре волн.
    """
    from proxy.core import _query
    ensure_schema()
    rows = _query(
        "SELECT wave_id FROM shop_supply_queue WHERE product_id=? "
        "AND status IN (?, ?) AND wave_id IS NOT NULL "
        "ORDER BY rowid DESC LIMIT 1",
        (int(product_id), STATUS_PENDING, STATUS_DISPATCHED), fetch=True)
    if rows and rows[0]["wave_id"]:
        return rows[0]["wave_id"]
    wave_id = str(uuid.uuid4())
    _query("INSERT INTO shop_supply_waves (wave_id, product_id) VALUES (?, ?)",
           (wave_id, int(product_id)))
    return wave_id


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
    wave_id = _assign_wave(product_id)
    _query(
        "INSERT INTO shop_supply_queue (task_id, product_id, platform, type, "
        "query, url, status, created_at, timeout_s, wave_id) "
        "VALUES (?, ?, ?, ?, ?, NULL, ?, datetime('now'), ?, ?)",
        (task_id, int(product_id), platform, TASK_TYPE_SEARCH,
         str(query or ""), STATUS_PENDING, _default_timeout_s(), wave_id))
    _audit(f"enqueue task={task_id} platform={platform} "
           f"product={product_id} query={str(query or '')[:80]}",
           STATUS_PENDING)
    return task_id


def expire_stale_tasks():
    """pending/dispatched без результата дольше timeout_s → failed/task_timeout.

    Точка отсчёта — выдача (dispatched_at), для невыданных — создание.
    Единый SQL-клок datetime('now') против datetime(created_at/dispatched_at):
    ничего не сравнивается с часами Python.

    №598 A.3: волны пострадавших заданий проверяются на «вся волна закрыта»
    — если протухло последнее задание товара, владелец получает то же
    сообщение «Досье обновлено» с честным «задание протухло» (досье
    пересобирается тем же кодом, повторного сбора нет).
    """
    from proxy.core import _query
    ensure_schema()
    stale_sql = (
        "WHERE status IN (?, ?) AND timeout_s IS NOT NULL AND timeout_s > 0 "
        "AND datetime(COALESCE(dispatched_at, created_at), "
        "  '+' || CAST(timeout_s AS TEXT) || ' seconds') <= datetime('now')")
    stale = _query("SELECT wave_id FROM shop_supply_queue " + stale_sql,
                   (STATUS_PENDING, STATUS_DISPATCHED), fetch=True) or []
    _query(
        "UPDATE shop_supply_queue SET status=?, kind='task_timeout', "
        "error=COALESCE(error, 'задание протухло без результата (timeout_s)') "
        + stale_sql,
        (STATUS_FAILED, STATUS_PENDING, STATUS_DISPATCHED))
    for wave_id in dict.fromkeys(r["wave_id"] for r in stale if r["wave_id"]):
        try:
            notify_wave_if_complete(wave_id)
        except Exception as e:  # noqa: BLE001 — протухание не должно ронять очередь
            log.warning("supply: волна %s: notify после expire упал: %s", wave_id, e)


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
    if task.get("wave_id"):
        # №598 A.3: результат пришёл — волна могла закрыться. Падение
        # нотификации не роняет приём результата (аудит уже записан).
        try:
            notify_wave_if_complete(task["wave_id"])
        except Exception as e:  # noqa: BLE001 — см. выше
            log.warning("supply: волна %s: notify после result упал: %s",
                        task["wave_id"], e)
    return {"applied": True, "ok": ok, "offers_saved": offers_saved,
            "kind": kind, "error": error}


# ── №598 A.3: «Досье обновлено» — одно сообщение на волну ────────────────
def _plural_ru(n, one, few, many):
    """Русская плюрализация: 1 предложение / 2 предложения / 5 предложений."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _wave_task_line(row):
    """Исход одного задания волны человеческой фразой (для сообщения).

    done + ok:true → «N предложений»; done + ok:false → честный отказ
    снабженца (kind/error из payload); failed → протухло/формат.
    Формат результата и офферов НЕ меняется (запрет наряда) — только чтение.
    """
    platform = row["platform"]
    if row["status"] == STATUS_DONE:
        try:
            payload = json.loads(row["result_json"] or "{}")
        except (ValueError, TypeError):
            payload = {}
        if payload.get("ok"):
            n = len(payload.get("offers") or [])
            word = _plural_ru(n, "предложение", "предложения", "предложений")
            return f"· {platform}: {n} {word}"
        kind = payload.get("kind") or "отказ"
        err = str(payload.get("error") or "")[:80]
        return f"· {platform}: отказ снабженца — {kind}" + (f": {err}" if err else "")
    kind = row["kind"] or "ошибка"
    err = str(row["error"] or "")[:80]
    if kind == "task_timeout":
        return f"· {platform}: задание протухло без результата"
    if kind == "result_format":
        return f"· {platform}: не выполнено — формат результата нарушен"
    if kind == "collector_not_implemented":
        return f"· {platform}: сбор снабженцем ещё не реализован"
    # прочие failed — честный отказ снабженца (ok:false в payload) или
    # иная ошибка: что в задании, то и показываем
    return f"· {platform}: отказ снабженца — {kind}" + (f": {err}" if err else "")


def _send_owner_update(text):
    """Доставка владельцу (№598 A.3): день — Telegram, ночь 00:00–06:59 МСК —
    owner_outbox (доставка слотом night-report 07:15 МСК). Адресат —
    OWNER_TELEGRAM_ID (тот же источник, что у golden-evals/budget),
    фолбэк — system_settings owner_chat_id. Пусто → честный warning.
    """
    from proxy.core import _get_setting, _query
    owner = (os.environ.get("OWNER_TELEGRAM_ID", "").strip()
             or str(_get_setting("owner_chat_id", "")).strip())
    if not owner:
        log.warning("supply: OWNER_TELEGRAM_ID пуст — «Досье обновлено» не отправлено")
        return False
    if _is_supply_night_msk():
        _query("INSERT INTO owner_outbox (source, text) VALUES (?, ?)",
               (SOURCE_OUTBOX, text))
    else:
        from proxy.telegram import _tg_send_message
        _tg_send_message(owner, text)
    return True


def notify_wave_if_complete(wave_id):
    """№598 A.3: волна закрылась целиком → РОВНО одно сообщение владельцу.

    Условия (все обязаны сойтись): волна существует в реестре; флаг
    notified ещё не стоит (защита от дублей — флаг в БД, одна волна =
    одно сообщение); у товара не осталось заданий в pending|dispatched.
    Флаг ставится ДО отправки под _notify_lock (тот же класс гонок, что
    dequeue): двойное закрытие двух заданий волны в соседних потоках
    даст одно сообщение. Досье пересобирается тем же build_snapshot,
    что и /shop/product — БЕЗ повторного сбора (score_product читает
    только БД); сеть на площадках не дёргается.
    """
    from proxy.core import _query
    ensure_schema()
    with _notify_lock:
        wrows = _query("SELECT product_id, notified FROM shop_supply_waves "
                       "WHERE wave_id=?", (wave_id,), fetch=True)
        if not wrows or wrows[0]["notified"]:
            return None
        product_id = int(wrows[0]["product_id"])
        open_rows = _query(
            "SELECT COUNT(*) AS c FROM shop_supply_queue WHERE product_id=? "
            "AND status IN (?, ?)",
            (product_id, STATUS_PENDING, STATUS_DISPATCHED), fetch=True)
        if open_rows and int(open_rows[0]["c"] or 0) > 0:
            return None
        _query("UPDATE shop_supply_waves SET notified=1 WHERE wave_id=?", (wave_id,))
    # вне замка: сборка и отправка (падение — в лог, флаг уже стоит:
    # ровно одно сообщение на волну, сбой доставки виден в логе)
    try:
        text = _build_wave_message(wave_id, product_id)
    except Exception as e:  # noqa: BLE001 — не роняем вызывающий путь (result/expire/enqueue)
        log.warning("supply: волна %s: сообщение не собрано: %s", wave_id, e)
        return None
    try:
        _send_owner_update(text)
    except Exception as e:  # noqa: BLE001 — Telegram/БД не роняют очередь
        log.warning("supply: волна %s: отправка владельцу упала: %s", wave_id, e)
    return wave_id


def _build_wave_message(wave_id, product_id):
    """Текст «Досье обновлено»: исход по каждой площадке волны + свежее досье.

    Пересбор досье — тот же build_snapshot, что у /shop/product (профиль
    default, collect_details=None — повторного сбора нет, сеть не дёргается).
    Досье не собралось — исходы волны всё равно уходят, честно без ссылки.
    """
    from proxy.core import _query
    rows = _query(
        "SELECT platform, status, kind, error, result_json "
        "FROM shop_supply_queue WHERE wave_id=? ORDER BY rowid",
        (wave_id,), fetch=True) or []
    lines = ["📦 Досье обновлено:"]
    title = None
    link = None
    try:
        from proxy.shop_dossier import build_snapshot, dossier_url
        snapshot = build_snapshot(product_id, profile="default")
        if snapshot.get("ok"):
            title = (snapshot.get("product") or {}).get("title")
            if snapshot.get("dossier_id"):
                link = dossier_url(snapshot["dossier_id"])
    except Exception as e:  # noqa: BLE001 — сообщение важнее досье
        log.warning("supply: волна %s: досье не пересобрано: %s", wave_id, e)
    if title:
        lines = [f"📦 Досье обновлено: {title}"]
    lines.extend(_wave_task_line(r) for r in rows)
    if link:
        lines.append(f"Полное досье: {link}")
    return "\n".join(lines)
