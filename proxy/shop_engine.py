"""SHOP-1 (диспатч #172) — весовой движок сравнения товаров.

Чистые функции без I/O: нормализация цен, медианы истории, честная
скидка (фейк-детект v1), скоринг офферов по 4 группам критериев,
стоп-флаги, бейджи, вердикт. Сборщики площадок (SHOP-3) и вотчлист
(SHOP-4) подают плоские dict-записи — строки shop_offers с
доклеенными seller-полями.

Критерии и веса зафиксированы владельцем 2026-09-16 (issue #172):
  цена 35% / качество 30% / доступность 20% / продавец 15%.
Профиль «expensive» (дорогая покупка): цена 20 / качество 40 /
доступность 10 / продавец 30.

Базис модели — schema.org/Offer: price, priceCurrency, availability,
seller, shippingDetails (delivery_*), hasMerchantReturnPolicy
(return_ok), warranty. Колонки таблиц app.mlog (shop_products /
shop_sellers / shop_offers / shop_price_history / shop_watches /
shop_dossiers) зеркалят эти поля; цены хранятся в BYN — нормализация
parse_price + to_byn на стороне сборщиков.

Соглашения ранжирования:
  - rank_price: сравниваем реальную цену владения — card_price_byn
    (WB-кошелёк/Ozon-карта/рассрочка) если есть, иначе price_byn,
    плюс delivery_cost_byn. «Цифра на ценнике» без способа оплаты —
    несравнима (#172, урок ozon-parser: card_price vs price);
  - честная скидка считается против медианы истории по чистой
    price_byn (доставка искажает скидку), а не против зачёркнутой;
  - стоп-флаги — дисквалификаторы вне баллов: аномально низкая цена
    (<60% медианы истории), продавец без истории сделок, возврат
    невозможен, характеристики не пересекаются с базовой спекой;
  - данных нет — нейтральный балл, а не выдумка (честная деградация,
    политика офиса).

Политика FO-007: в модуле нет except-блоков вовсе — разбор строк
строго через regex-валидацию.
"""
import re

# Веса групп (декларация владельца, issue #172, 2026-09-16)
WEIGHTS_DEFAULT = {"price": 0.35, "quality": 0.30, "access": 0.20, "seller": 0.15}
WEIGHTS_EXPENSIVE = {"price": 0.20, "quality": 0.40, "access": 0.10, "seller": 0.30}

_PROFILES = {"default": WEIGHTS_DEFAULT, "expensive": WEIGHTS_EXPENSIVE}

_PRICE_RE = re.compile(r"^\d+(\.\d+)?$")

_CURRENCY_JUNK = ("р.", "Р.", "руб.", "BYN", "byn", "Br", "br", "$", "€", "₽")


def parse_price(raw):
    """«1 299,90 р.» / «1,299.90» / «BYN 89.99» → float | None.

    Правила (розничные форматы РБ):
      - пробелы и неразрывные пробелы — разделители тысяч, выбрасываются;
      - есть и запятая, и точка — ПОСЛЕДНИЙ встреченный — десятичный;
      - запятая с ровно 2 знаками после → десятичная, иначе — тысячи;
      - точка: «1.299.900» (группы по 3) → тысячи; одиночное «1.299»
        тоже считается тысячами (1299) — розничный приоритет, «1.299»
        как цена 1.299 в рознице РБ не встречается;
      - не удалось разобрать → None (сборщик честно пропустит оффер).
    """
    if raw is None:
        return None
    s = str(raw)
    for sep in (" ", "\u00a0", "\u202f"):
        s = s.replace(sep, "")
    for junk in _CURRENCY_JUNK:
        s = s.replace(junk, "")
    s = s.strip(".,;:-–—")
    if not s or not any(ch.isdigit() for ch in s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if head and len(tail) == 2:
            s = head.replace(",", "") + "." + tail
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)
        elif len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
            s = "".join(parts)
    if not _PRICE_RE.match(s):
        return None
    return round(float(s), 2)


def to_byn(amount, currency, rates):
    """Сумма в BYN. Нет курса или валюты → None (честная деградация).

    rates — dict курсов к BYN на момент среза (SHOP-3 поставляет;
    движок никаких внешних вызовов не делает).
    """
    if amount is None:
        return None
    if not currency or str(currency).upper() == "BYN":
        return round(float(amount), 2)
    rate = (rates or {}).get(str(currency).upper())
    if not rate:
        return None
    return round(float(amount) * float(rate), 2)


def median(values):
    """Медиана; пусто/None → None. Чётная длина — среднее двух середин."""
    xs = sorted(v for v in (values or []) if v is not None)
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    if n % 2:
        return float(xs[mid])
    return (xs[mid - 1] + xs[mid]) / 2.0


def honest_discount(price, old_price, history_prices):
    """Фейк-детект v1 (#172): скидка против медианы истории.

    Возвращает dict:
      claimed_pct — скидка «по объявлению»: (old − price) / old;
      honest_pct  — скидка против медианы истории; None, если точек <3
                    (cold start: медианы копятся с нуля, полная сила
                    фейк-детекта через 1–2 недели мониторинга);
      is_fake     — зачёркнутая выше типичной (медиана × 1.10) ИЛИ
                    заявлено ≥10% при фактических ≤2%;
      note        — человеческое пояснение для досье.
    """
    res = {"claimed_pct": None, "honest_pct": None, "is_fake": False, "note": ""}
    hist = [h for h in (history_prices or []) if h is not None]
    claimed = None
    if old_price and price is not None and old_price > price > 0:
        claimed = (old_price - price) / old_price * 100.0
        res["claimed_pct"] = round(claimed, 1)
    med = median(hist)
    if med is None or len(hist) < 3:
        res["note"] = (
            f"история копится ({len(hist)} точ.) — честная скидка появится "
            "через 1–2 недели мониторинга"
        )
        return res
    if price is not None and price > 0:
        res["honest_pct"] = round((med - price) / med * 100.0, 1)
    inflated_old = bool(old_price and old_price > med * 1.10)
    cosmetic = bool(claimed and claimed >= 10.0 and (res["honest_pct"] or 0) <= 2.0)
    if inflated_old:
        res["is_fake"] = True
        res["note"] = (
            f"зачёркнутая цена выше обычной (медиана {round(med, 2)} BYN) — скидка фейковая"
        )
    elif cosmetic:
        res["is_fake"] = True
        res["note"] = (
            f"заявлено -{res['claimed_pct']}%, фактически -{res['honest_pct']}% "
            "против обычной цены"
        )
    return res


def rank_price(offer):
    """Реальная цена сравнения: card_price если есть, иначе price, + доставка.

    None (цены нет) → None — оффер не участвует в ранжировании.
    """
    base = offer.get("card_price_byn")
    if base is None:
        base = offer.get("price_byn")
    if base is None:
        return None
    total = float(base)
    delivery = offer.get("delivery_cost_byn")
    if delivery:
        total += float(delivery)
    return round(total, 2)


def _clamp100(x):
    return max(0.0, min(100.0, x))


def _quality_score(o):
    """Агрегированный рейтинг × доверие к выборке (#172: <30 отзывов — срезаем)."""
    rating = o.get("rating")
    reviews = o.get("reviews_count") or 0
    if rating is None:
        return 50.0  # рейтинга нет — нейтрально, не штраф и не бонус
    if reviews >= 50:
        trust = 1.0
    elif reviews >= 30:
        trust = 0.8
    elif reviews >= 10:
        trust = 0.6
    else:
        trust = 0.4
    score = float(rating) / 5.0 * 100.0 * trust
    fresh = o.get("reviews_fresh_days")
    if fresh is not None:
        if fresh > 365:
            score -= 15.0
        elif fresh > 180:
            score -= 7.0
    return _clamp100(score)


def _access_score(o):
    """Наличие SKU (размер/комплектация — watch на уровне SKU, #172),
    срок доставки, способы оплаты (ЕРИП/рассрочка — РБ-фактор)."""
    if not o.get("in_stock"):
        return 0.0
    score = 40.0
    days = o.get("delivery_days")
    if days is None:
        score += 10.0  # срок неизвестен — осторожный нейтралитет
    elif days <= 2:
        score += 30.0
    elif days <= 5:
        score += 20.0
    elif days <= 10:
        score += 10.0
    if o.get("installment_ok"):
        score += 30.0  # рассрочка/карта рассрочки — реальная цена в РБ
    elif o.get("pay_on_delivery"):
        score += 20.0
    else:
        score += 10.0  # карта/ЕРИП есть на всех площадках
    return _clamp100(score)


def _seller_score(o):
    """Рейтинг × стаж × число сделок × официальность (#172, урок ozon-parser:
    ИНН/дата регистрации/заказы — поля доверия). Данных нет — 50 (нейтрально)."""
    keys = ("seller_rating", "seller_years", "seller_deals", "seller_official")
    if all(o.get(k) is None for k in keys):
        return 50.0
    score = 20.0
    rating = o.get("seller_rating")
    if rating is not None:
        score = float(rating) / 5.0 * 40.0
    years = o.get("seller_years")
    if years is not None:
        score += 25.0 if years >= 3 else (15.0 if years >= 1 else 5.0)
    deals = o.get("seller_deals")
    if deals is not None:
        if deals >= 1000:
            score += 25.0
        elif deals >= 100:
            score += 20.0
        elif deals >= 10:
            score += 10.0
        elif deals >= 1:
            score += 5.0
    if o.get("seller_official"):
        score += 10.0
    return _clamp100(score)


def stop_flags(offer, history_prices=None, product_specs=None):
    """Дисквалификаторы вне баллов (#172) → список {code, note}.

    spec_mismatch: у товара задана базовая спека, у оффера — своя,
    и множества ключей не пересекаются (характеристики «не те»).
    """
    flags = []
    rp = rank_price(offer)
    med = median(history_prices or [])
    if med is not None and rp is not None and rp < med * 0.60:
        flags.append({
            "code": "anomaly_price",
            "note": f"цена {rp} BYN ниже 60% медианы истории ({round(med, 2)} BYN)",
        })
    if offer.get("seller_deals") in (None, 0):
        flags.append({
            "code": "seller_no_history",
            "note": "продавец без истории сделок (или данных о нём нет) — осторожно",
        })
    if offer.get("return_ok") is not None and not offer.get("return_ok"):
        flags.append({"code": "no_returns", "note": "возврат невозможен"})
    offer_specs = offer.get("specs")
    if isinstance(product_specs, dict) and product_specs \
            and isinstance(offer_specs, dict) and offer_specs:
        if not (set(product_specs) & set(offer_specs)):
            flags.append({
                "code": "spec_mismatch",
                "note": "характеристики оффера не пересекаются с базовой спекой товара",
            })
    return flags


def score_offers(offers, history_by_offer=None, profile="default",
                 product=None, target_price_byn=None):
    """Скоринг набора офферов одного товара → срез для досье/вердикта.

    offers             — list[dict|sqlite3.Row] строк shop_offers с
                         доклеенными seller-полями (seller_rating,
                         seller_years, seller_deals, seller_official),
                         reviews_fresh_days, specs (dict, распарсенный);
    history_by_offer   — {offer_id: [price_byn, ...]} история для
                         честной скидки и аномалий;
    profile            — "default" | "expensive" (#172);
    product            — {"title":..., "specs": {...}} базовая спека;
    target_price_byn   — цель вотчлиста (SHOP-4), опционально.

    Возвращает dict с offers-скорингами (группы, total, honest,
    стоп-флаги), бейджами («cheapest»/«reliable»/«fastest»/
    «best_installment» — offer_id) и вердиктом по лучшему офферу.
    """
    weights = _PROFILES.get(profile, WEIGHTS_DEFAULT)
    history_by_offer = history_by_offer or {}
    prepared, unscored = [], []
    for raw in offers:
        o = dict(raw) if not isinstance(raw, dict) else raw
        rp = rank_price(o)
        if rp is None:
            unscored.append(o.get("id"))
            continue
        prepared.append((o, rp))

    if not prepared:
        return {
            "profile": profile,
            "offers": [],
            "unscored": unscored,
            "badges": {},
            "verdict": None,
        }

    rps = [rp for _, rp in prepared]
    lo, hi = min(rps), max(rps)
    scored = []
    for o, rp in prepared:
        oid = o.get("id")
        hist = history_by_offer.get(oid) or []
        honest = honest_discount(o.get("price_byn"), o.get("old_price_byn"), hist)

        pscore = 100.0 if hi == lo else 100.0 * (hi - rp) / (hi - lo)
        if honest["honest_pct"] is not None and honest["honest_pct"] >= 10:
            pscore += 10.0  # настоящая скидка — плюс к цене
        if honest["is_fake"]:
            pscore -= 15.0  # фейковая скидка — минус к цене
        pscore = _clamp100(pscore)

        flags = stop_flags(o, hist, (product or {}).get("specs"))
        gs = {
            "price": round(pscore, 1),
            "quality": round(_quality_score(o), 1),
            "access": round(_access_score(o), 1),
            "seller": round(_seller_score(o), 1),
        }
        total = sum(weights[g] * gs[g] for g in weights)
        scored.append({
            "id": oid,
            "platform": o.get("platform"),
            "rank_price": rp,
            "group_scores": gs,
            "total": round(total, 1),
            "honest": honest,
            "stop_flags": flags,
        })

    def _oid(pair):
        return pair[0].get("id")

    badges = {
        "cheapest": _oid(min(prepared, key=lambda p: p[1])),
        "reliable": _oid(max(prepared, key=lambda p: (
            _quality_score(p[0]) + _seller_score(p[0])) / 2.0)),
    }
    with_delivery = [p for p in prepared if p[0].get("delivery_days") is not None]
    if with_delivery:
        badges["fastest"] = _oid(min(with_delivery, key=lambda p: p[0]["delivery_days"]))
    with_installment = [p for p in prepared if p[0].get("installment_ok")]
    if with_installment:
        badges["best_installment"] = _oid(min(
            with_installment,
            key=lambda p: p[0].get("card_price_byn") if p[0].get("card_price_byn") is not None else p[1],
        ))

    best = max(scored, key=lambda s: s["total"])
    best_raw = next(o for o, _ in prepared if o.get("id") == best["id"])
    rp_best = rank_price(best_raw)
    med_best = median(history_by_offer.get(best["id"]) or [])
    if best["stop_flags"]:
        text = "осторожно: " + "; ".join(f["code"] for f in best["stop_flags"])
    elif best["honest"]["honest_pct"] is not None and best["honest"]["honest_pct"] >= 10:
        text = f"брать сейчас: настоящая скидка {best['honest']['honest_pct']}%"
    elif target_price_byn is not None and rp_best is not None and rp_best <= target_price_byn:
        text = f"цель достигнута: {rp_best} ≤ {target_price_byn} BYN"
    elif med_best is not None and rp_best is not None and rp_best > med_best * 1.10:
        text = f"ждать: цена выше обычной (медиана {round(med_best, 2)} BYN)"
    else:
        text = "цена в рынке — можно брать"

    return {
        "profile": profile,
        "offers": scored,
        "unscored": unscored,
        "badges": badges,
        "verdict": {
            "best_offer_id": best["id"],
            "score": best["total"],
            "text": text,
        },
    }
