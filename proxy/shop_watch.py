"""SHOP-4 (диспатч #172) — вотчлист цен/скидок + алерты владельцу.

Механика (#172):
  - watch на уровне продукта/SKU: цели «<X BYN», «настоящая скидка ≥Y%»,
    «появился в наличии»; опрос 4 раза/сутки (cron /cron/shop-tick, раз в 6ч);
  - события → личка владельца офисным бот-контуром (_tg_send_message,
    OWNER_TELEGRAM_ID). Telethon-контур MON-1 (#171) — отдельный аккаунт
    для LZ-каналов, к офисным алертам отношения не имеет;
  - дельта-алерты не дублируются: watch.last_alert_json хранит уже
    отправленные значения; повтор — только если событие УЛУЧШИЛОСЬ
    (цена ниже прошлей алертной, скидка больше, наличие после отсутствия);
  - kill-switch SHOP_ENABLED=0 — такт молчит (проверяется тестом);
  - cold start честно: медианы копятся с нуля, честная скидка набирает
    силу через 1–2 недели (shop_engine.honest_discount — note в досье);
  - сбор в такте — через refresh_product (SHOP-3): robots/rate-limit/кэш
    соблюдаются дисциплиной SHOP-2; площадка недоступна → такт живёт.

Границы нарядов скорректированы при реализации: команды /товар /вотч
уходят в SHOP-5 вместе с досье (UX единым блоком), SHOP-4 — ядро.
"""
import json
import logging
import os

log = logging.getLogger("shop_watch")

PLATFORMS_MVP = ("wb", "kufar")  # onliner/21vek — каркасы, не в такте


def enabled():
    return os.environ.get("SHOP_ENABLED", "1") != "0"


def _send_alert(text):
    """Алерт владельцу. Ошибка отправки не роняет такт (FO-007: не молчим)."""
    owner_id = os.environ.get("OWNER_TELEGRAM_ID", "")
    if not owner_id:
        log.warning("OWNER_TELEGRAM_ID не задан — алерт вотчлиста не отправлен")
        return False
    try:
        from proxy.telegram import _tg_send_message
        _tg_send_message(owner_id, text)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("алерт вотчлиста не отправлен: %s", e)
        return False


# ── управление вотчлистом ───────────────────────────────────────────────
def ensure_product(query, title=None):
    """Создать товар (если нет) и снять первичный срез по MVP-площадкам.

    Возвращает product_id. Площадка может быть недоступна — товар всё
    равно создаётся (такт дособерёт остальные при следующих запусках).
    """
    from proxy.core import _query
    from proxy.shop_collectors import refresh_product
    _query("INSERT INTO shop_products (title, query_text) VALUES (?, ?)",
           (title or query, query))
    row = _query("SELECT id FROM shop_products WHERE query_text=? ORDER BY id DESC LIMIT 1",
                 (query,), fetch=True)
    pid = row[0]["id"]
    details = {}
    for platform in PLATFORMS_MVP:
        details[platform] = refresh_product(pid, platform, query)
    return pid, details


def add_watch(product_id, target_price_byn=None, discount_pct=None,
              alert_in_stock=False):
    """Поставить товар на отслеживание (один активный watch на продукт)."""
    from proxy.core import _query
    _query("UPDATE shop_watches SET status='paused' WHERE product_id=?", (product_id,))
    _query("INSERT INTO shop_watches (product_id, target_price_byn, discount_pct, "
           "alert_in_stock) VALUES (?, ?, ?, ?)",
           (product_id, target_price_byn, discount_pct, 1 if alert_in_stock else 0))
    return _query("SELECT id FROM shop_watches WHERE product_id=? AND status='active' "
                  "ORDER BY id DESC LIMIT 1", (product_id,), fetch=True)[0]["id"]


def pause_watch(product_id):
    from proxy.core import _query
    _query("UPDATE shop_watches SET status='paused' WHERE product_id=? AND status='active'",
           (product_id,))
    return True


def list_watches():
    """Активные вотчи с последними ценами (для досье/команд SHOP-5)."""
    from proxy.core import _query
    rows = _query(
        "SELECT w.id, w.product_id, p.title, p.query_text, w.target_price_byn, "
        "w.discount_pct, w.alert_in_stock, w.last_checked_at, w.last_alert_json "
        "FROM shop_watches w JOIN shop_products p ON p.id = w.product_id "
        "WHERE w.status='active' ORDER BY w.id", fetch=True)
    return [dict(r) for r in rows]


# ── такт: сбор + оценка событий + алерты ────────────────────────────────
def _format_alert(product_title, events, best_offers):
    lines = [f"🔔 Вотчлист: {product_title}"]
    for ev in events:
        lines.append(f"• {ev}")
    if best_offers:
        lines.append("Топ предложений сейчас:")
        for o in best_offers:
            lines.append(f"  {o['rank_price']} BYN — {o['platform']}: {o['url']}")
    return "\n".join(lines)


def evaluate_watch(watch, send=None):
    """Один вотч: свежий скоринг → события → дедуп → алерт.

    Возвращает {"alerts": n, "events": [...], "skipped": reason?}.
    """
    from proxy.core import _query
    from proxy.shop_collectors import score_product
    pid = watch["product_id"]
    res = score_product(pid)
    if not res.get("ok") or not res["scored"].get("offers"):
        return {"alerts": 0, "events": [], "skipped": "no_scored_offers"}
    scored = res["scored"]
    verdict = scored.get("verdict") or {}
    best_id = verdict.get("best_offer_id")
    best = next((o for o in scored["offers"] if o["id"] == best_id), None)
    if best is None:
        return {"alerts": 0, "events": [], "skipped": "no_best_offer"}

    try:
        la = json.loads(watch.get("last_alert_json") or "{}")
    except ValueError:
        la = {}

    events = []
    # 1) цель по цене: rank_price <= X, повтор только при УЛУЧШЕНИИ
    target = watch.get("target_price_byn")
    if target is not None and best["rank_price"] is not None \
            and best["rank_price"] <= target:
        prev = la.get("target_price")
        if prev is None or best["rank_price"] < prev:
            events.append(f"цена достигла цели: {best['rank_price']} BYN "
                          f"(цель {target})")
            la["target_price"] = best["rank_price"]
    # 2) настоящая скидка ≥ Y% (фейк отсекается движком)
    dmin = watch.get("discount_pct")
    honest = (best.get("honest") or {}).get("honest_pct")
    is_fake = (best.get("honest") or {}).get("is_fake")
    if dmin is not None and honest is not None and honest >= dmin and not is_fake:
        prev = la.get("discount_pct")
        if prev is None or honest > prev:
            events.append(f"настоящая скидка {honest}% (порог {dmin}%)")
            la["discount_pct"] = honest
    # 3) появление в наличии: алерт на переход out → in у лучшего оффера
    #    (in_stock приходит из shop_offers.* в score_product)
    in_stock = bool(best.get("in_stock"))
    if watch.get("alert_in_stock"):
        prev_stock = la.get("in_stock")
        if in_stock and prev_stock is False:
            events.append("товар появился в наличии")
        la["in_stock"] = in_stock
    else:
        la["in_stock"] = in_stock

    sent = 0
    if events:
        top = sorted(scored["offers"], key=lambda o: o["rank_price"])[:3]
        top_offers = [{"rank_price": o["rank_price"], "platform": o["platform"],
                       "url": ""} for o in top]
        # URL офферов лежит в БД — добираем по id
        from proxy.core import _query as _q
        for i, to in enumerate(top_offers):
            urow = _q("SELECT url FROM shop_offers WHERE id=?", (top[i]["id"],),
                      fetch=True)
            if urow:
                top_offers[i]["url"] = urow[0]["url"]
        text = _format_alert(res["product"]["title"], events, top_offers)
        send_fn = send or _send_alert
        if send_fn(text):
            sent = 1

    _query("UPDATE shop_watches SET last_alert_json=?, last_checked_at=datetime('now') "
           "WHERE id=?", (json.dumps(la, ensure_ascii=False), watch["id"]))
    return {"alerts": sent, "events": events}


def tick_shop_watches():
    """Крон-такт: kill-switch → сбор по активным площадкам → оценка вотчей."""
    if not enabled():
        return {"ok": False, "kind": "disabled",
                "note": "SHOP_ENABLED=0 — вотчлист выключен"}
    from proxy.core import _query
    from proxy.shop_collectors import refresh_product
    watches = list_watches()
    alerts = 0
    details = []
    for w in watches:
        # свежий сбор по MVP-площадкам продукта
        for platform in PLATFORMS_MVP:
            try:
                refresh_product(w["product_id"], platform, w["query_text"])
            except Exception as e:  # noqa: BLE001 — площадка недоступна, такт живёт
                log.warning("refresh %s/%s не удался: %s", platform, w["product_id"], e)
                details.append(f"{platform}/{w['product_id']}: refresh error")
        # watch-строка могла устареть после refresh — перечитываем
        wrow = _query("SELECT * FROM shop_watches WHERE id=?", (w["id"],), fetch=True)
        if not wrow:
            continue
        ev = evaluate_watch(dict(wrow[0]))
        alerts += ev["alerts"]
        details.append(f"watch {w['id']}: {', '.join(ev['events']) or 'без событий'}")
    return {"ok": True, "watches": len(watches), "alerts": alerts, "details": details}
