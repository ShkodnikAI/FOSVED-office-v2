"""SHOP-5 (диспатч #172) — досье товара: текст / постер PNG / HTML.

Все форматы рендерятся из ОДНОГО среза build_snapshot() (решение #172:
«оба формата рендерятся из одного среза») — текст, caption, кнопки,
постер и HTML не могут разойтись в цифрах.

Кликабельность (вопрос владельца из #172): PNG гиперссылок не несёт →
  (1) caption под постером с HTML-ссылками на офферы,
  (2) inline URL-кнопки «Купить» на сообщении с постером (Bot API
      reply_markup — офисный бот, тот же контур, что SHOP-4),
  (3) полное HTML-досье на вебе офиса (GET /shop/dossier/<id>?t=<hmac>)
      — там все ссылки кликабельны.
Сами ссылки — canonical URL из shop_offers (чистка utm в SHOP-3 при
записи; досье повторно прогоняет canonical_url — защита от старых строк).

Постер: 1080×1350, палитра «Диспетчерской» (токены miniapp/index.html:
paper #EFEAE0, ink #1C1B18, stamp #A8321E…), RAM-friendly — одна
картинка, никакого накопления буферов; шрифты системные DejaVu с
честным фолбэком на PIL-дефолт (Dockerfile ставит fonts-dejavu-core).

Политика FO-007: в ядре нет except-блоков — JSON досье пишем/читаем
сами, рендер пусть падает громко на ошибке данных, чем молча рисует
неправду. Транспортные функции (TG) ловят наверху в shop_watch-стиле.
"""
import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone

from proxy.shop_collectors import canonical_url

log = logging.getLogger("shop_dossier")

# Токены «Диспетчерской» (miniapp/index.html :root) — для постера PNG
PAPER = "#EFEAE0"
PAPER_RAISED = "#FBF8F2"
INK = "#1C1B18"
MUTED = "#6B6558"
STAMP = "#A8321E"
OK = "#3D6B2C"
WARN = "#9C6B0B"
LINE = "#D8D1C4"

POSTER_W, POSTER_H = 1080, 1350
MAX_TEXT = 3800        # tg_send_long-лимит офиса
MAX_CAPTION = 1000     # лимит caption в sendPhoto
MAX_BUTTONS = 3        # кнопки «Купить» (плюс «Полное досье» отдельным рядом)

_BADGE_LABELS = {
    "cheapest": "дешевле всех",
    "reliable": "надёжнее всех",
    "fastest": "быстрее всех",
    "best_installment": "лучшая цена в рассрочку",
}

_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
)


def dossier_token(dossier_id):
    """HMAC-токен доступа к HTML-досье (stateless; секрет — API_SECRET)."""
    secret = os.environ.get("API_SECRET", "dev-secret")
    return hmac.new(secret.encode(), f"shop-dossier:{dossier_id}".encode(),
                    hashlib.sha256).hexdigest()[:16]


def dossier_url(dossier_id, base_url=None):
    """Кликабельная ссылка на полное HTML-досье."""
    base = (base_url or os.environ.get("RENDER_EXTERNAL_URL")
            or os.environ.get("RENDER_URL") or "").rstrip("/")
    return f"{base}/shop/dossier/{dossier_id}?t={dossier_token(dossier_id)}"


# ── единый срез ──────────────────────────────────────────────────────────
def build_snapshot(product_id, profile="default", target_price_byn=None,
                   save=True):
    """Срез данных досье: продукт + скоринг + URLs + история.

    Единственный источник правды для render_text / render_caption /
    build_inline_buttons / render_poster / render_html (тест следит,
    что все рендеры читают ровно этот dict).
    """
    from proxy.core import _query
    from proxy.shop_collectors import score_product
    res = score_product(product_id, profile=profile,
                        target_price_byn=target_price_byn)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error", "товар не найден"),
                "kind": res.get("kind", "not_found")}
    product = res["product"]
    scored = res["scored"]

    offers = []
    for s in scored["offers"]:
        row = _query("SELECT url, platform, price_byn, old_price_byn, "
                     "card_price_byn, delivery_days, delivery_cost_byn, "
                     "installment_ok, rating, reviews_count, seller_id "
                     "FROM shop_offers WHERE id=?", (s["id"],), fetch=True)
        if not row:
            continue
        o = dict(row[0])
        seller_name = None
        if o.get("seller_id"):
            srow = _query("SELECT name FROM shop_sellers WHERE id=?",
                          (o["seller_id"],), fetch=True)
            seller_name = srow[0]["name"] if srow else None
        offers.append({
            "id": s["id"], "platform": o["platform"],
            "url": canonical_url(o["url"]),
            "rank_price": s["rank_price"], "price_byn": o["price_byn"],
            "old_price_byn": o["old_price_byn"],
            "card_price_byn": o["card_price_byn"],
            "in_stock": s["in_stock"],
            "delivery_days": o["delivery_days"],
            "delivery_cost_byn": o["delivery_cost_byn"],
            "installment_ok": bool(o["installment_ok"]),
            "rating": o["rating"], "reviews_count": o["reviews_count"],
            "seller_name": seller_name,
            "total": s["total"], "group_scores": s["group_scores"],
            "honest": s["honest"], "stop_flags": s["stop_flags"],
        })
    # решение владельца #172 п.2: офферы в досье — «дешевле — первым»,
    # без цены — в конец (участвуют в HTML, не в ранжировании)
    offers.sort(key=lambda o: (o["rank_price"] is None,
                               o["rank_price"] if o["rank_price"] is not None else 0.0))

    best_id = (scored.get("verdict") or {}).get("best_offer_id")
    history_best, median_best = [], None
    if best_id is not None:
        hrows = _query(
            "SELECT price_byn FROM shop_price_history WHERE offer_id=? "
            "ORDER BY ts DESC LIMIT 14", (best_id,), fetch=True)
        history_best = [r["price_byn"] for r in reversed(hrows)]
        vals = sorted(history_best)
        if vals:
            n = len(vals)
            median_best = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0

    snapshot = {
        "ok": True,
        "product": product,
        "profile": profile,
        "target_price_byn": target_price_byn,
        "verdict": scored.get("verdict"),
        "badges": scored.get("badges") or {},
        "unscored": scored.get("unscored") or [],
        "offers": offers,
        "history_best": history_best,
        "median_best": median_best,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    if save:
        from proxy.core import _query as _q
        _q("INSERT INTO shop_dossiers (product_id, format, payload, snapshot_json) "
           "VALUES (?, 'snapshot', NULL, ?)",
           (product_id, json.dumps(snapshot, ensure_ascii=False)))
        row = _q("SELECT id FROM shop_dossiers WHERE product_id=? AND format='snapshot' "
                 "ORDER BY id DESC LIMIT 1", (product_id,), fetch=True)
        if row:
            snapshot["dossier_id"] = row[0]["id"]
    return snapshot


# ── формат А: текст-выжимка ──────────────────────────────────────────────
def _fmt_price(v, suffix=" BYN"):
    return ("?" if v is None else f"{v:g}") + suffix


def render_text(snapshot):
    """Формат А «текст»: выжимка в сообщении (критерии, топ-офферы,
    вердикт, стоп-флаги). ≤3800 симв (tg_send_long-лимит)."""
    lines = [f"Досье: {snapshot['product'].get('title', '?')}",
             f"профиль {snapshot['profile']} · {snapshot['generated_at']}"]
    verdict = snapshot.get("verdict")
    if verdict:
        lines.append(f"Вердикт: {verdict.get('score', '?')}/100 — {verdict.get('text', '')}")
    badge_parts = []
    by_id = {o["id"]: o for o in snapshot["offers"]}
    for key, oid in snapshot["badges"].items():
        o = by_id.get(oid)
        if o:
            badge_parts.append(f"{_BADGE_LABELS.get(key, key)}: {o['platform']} "
                               f"{_fmt_price(o['rank_price'])}")
    if badge_parts:
        lines.append("Бейджи: " + "; ".join(badge_parts))
    lines.append("Топ предложений (дешевле — первым):")
    for i, o in enumerate(snapshot["offers"][:5], 1):
        stock = "в наличии" if o["in_stock"] else "нет"
        disc = ""
        h = o.get("honest") or {}
        if h.get("honest_pct") is not None and h["honest_pct"] >= 10:
            disc = f", настоящая −{h['honest_pct']}%"
        if h.get("is_fake"):
            disc = ", СКИДКА ФЕЙКОВАЯ"
        inst = ", рассрочка" if o["installment_ok"] else ""
        lines.append(f"{i}. {o['platform']} — {_fmt_price(o['rank_price'])} "
                     f"({stock}{disc}{inst})")
        lines.append(f"   {o['url']}")
    flags = [f["note"] for o in snapshot["offers"] for f in o["stop_flags"]]
    if flags:
        lines.append("Осторожно:")
        for f in dict.fromkeys(flags):
            lines.append(f"⚠ {f}")
    if snapshot["unscored"]:
        lines.append(f"Без цены (не ранжированы): {len(snapshot['unscored'])} офф.")
    if snapshot["median_best"] is not None:
        lines.append(f"Медиана истории лучшего: {_fmt_price(snapshot['median_best'])}")
    elif snapshot["history_best"] is not None and len(snapshot["history_best"]) < 3:
        lines.append("История копится — честная скидка появится через 1–2 недели.")
    if snapshot.get("dossier_id"):
        lines.append(f"Полное досье: {dossier_url(snapshot['dossier_id'])}")
    text = "\n".join(lines)
    if len(text) > MAX_TEXT:  # срезаем по строкам, URL-строки не жертвуем первыми
        text = text[:MAX_TEXT]
    return text


# ── caption + inline-кнопки (кликабельность вокруг PNG) ──────────────────
def render_caption(snapshot):
    """HTML-caption под постером: вердикт + ссылка лучшего оффера +
    ссылка на полное досье. ≤1000 симв (лимит sendPhoto)."""
    v = snapshot.get("verdict") or {}
    title = snapshot["product"].get("title", "?")
    lines = [f"<b>Досье: {title}</b>",
             f"Вердикт: <b>{v.get('score', '?')}/100</b> — {v.get('text', '')}"]
    best = next((o for o in snapshot["offers"]
                 if o["id"] == v.get("best_offer_id")), None)
    if best is None and snapshot["offers"]:
        best = snapshot["offers"][0]
    if best:
        lines.append(f"Купить: <a href=\"{best['url']}\">{best['platform']} — "
                     f"{_fmt_price(best['rank_price'])}</a>")
    if snapshot.get("dossier_id"):
        lines.append(f"<a href=\"{dossier_url(snapshot['dossier_id'])}\">Полное досье</a>"
                     " (все ссылки кликабельны)")
    text = "\n".join(lines)
    if len(text) > MAX_CAPTION:
        text = text[:MAX_CAPTION - 1] + "…"
    return text


def build_inline_buttons(snapshot):
    """reply_markup JSON: до MAX_BUTTONS кнопок «Купить» (по порядку
    «дешевле — первым») + кнопка «Полное досье». Bot API: label ≤64,
    URL только http/https. Пустые URL не превращаются в кнопку."""
    buttons = []
    for o in snapshot["offers"]:
        url = o.get("url") or ""
        if not url.startswith(("http://", "https://")):
            continue
        label = f"Купить: {o['platform']} — {_fmt_price(o['rank_price'])}"[:64]
        buttons.append({"text": label, "url": url})
        if len(buttons) >= MAX_BUTTONS:
            break
    if snapshot.get("dossier_id"):
        du = dossier_url(snapshot["dossier_id"])
        if du.startswith("http"):
            buttons.append({"text": "Полное досье", "url": du})
    if not buttons:
        return None
    return json.dumps({"inline_keyboard": [buttons]}, ensure_ascii=False)


# ── формат Б: постер PNG ─────────────────────────────────────────────────
def _load_fonts():
    """DejaVu → Liberation → PIL-дефолт (Dockerfile ставит fonts-dejavu-core)."""
    from PIL import ImageFont
    names = {"reg": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf",
             "mono": "DejaVuSansMono.ttf"}
    for d in _FONT_DIRS:
        reg = os.path.join(d, names["reg"])
        if os.path.exists(reg):
            bold = os.path.join(d, names["bold"])
            mono = os.path.join(d, names["mono"])
            return (reg if os.path.exists(bold) else reg,
                    reg, mono if os.path.exists(mono) else reg)
    for d in _FONT_DIRS:
        reg = os.path.join(d, "LiberationSans-Regular.ttf")
        if os.path.exists(reg):
            return reg, reg, reg
    return None, None, None


def _sparkline(draw, x0, y0, w, h, values, color):
    """Мини-график истории цен: точки → линия, min/max — цифры."""
    if len(values) < 2:
        return
    lo, hi = min(values), max(values)
    if hi <= lo:
        hi = lo + 1.0
    pts = []
    for i, v in enumerate(values):
        px = x0 + w * i / (len(values) - 1)
        py = y0 + h - h * (v - lo) / (hi - lo)
        pts.append((px, py))
    draw.line(pts, fill=color, width=3)
    for px, py in pts:
        draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=color)


def render_poster(snapshot, out_path):
    """Формат Б «красота»: постер-инфографика PNG 1080×1350 из среза.

    Палитра «Диспетчерской», спарклайн истории лучшего оффера,
    топ-5 офферов таблицей, вердикт крупно, стоп-флаги внизу.
    RAM-friendly: один Image.new, одна текстовая поверхность.
    """
    from PIL import Image, ImageDraw, ImageFont
    fonts = _load_fonts()
    f_title = ImageFont.truetype(fonts[0], 46) if fonts[0] else None
    f_big = ImageFont.truetype(fonts[1], 120) if fonts[1] else None
    f_head = ImageFont.truetype(fonts[1], 34) if fonts[1] else None
    f_body = ImageFont.truetype(fonts[0], 28) if fonts[0] else None
    f_small = ImageFont.truetype(fonts[2], 24) if fonts[2] else None

    img = Image.new("RGB", (POSTER_W, POSTER_H), PAPER)
    draw = ImageDraw.Draw(img)

    def esc(s):
        return str(s or "")

    # шапка
    draw.rectangle([0, 0, POSTER_W, 8], fill=STAMP)
    title = esc(snapshot["product"].get("title"))
    if len(title) > 38:
        title = title[:37] + "…"
    draw.text((60, 44), title, fill=INK, font=f_title)
    draw.text((60, 110),
              f"{snapshot['generated_at']} · профиль {snapshot['profile']}",
              fill=MUTED, font=f_small)
    draw.line([60, 156, POSTER_W - 60, 156], fill=LINE, width=2)

    # вердикт: балл крупно + текст
    v = snapshot.get("verdict") or {}
    score_txt = f"{v.get('score', 0):g}"
    draw.text((60, 196), score_txt, fill=STAMP, font=f_big)
    draw.text((60 + (230 if len(score_txt) < 4 else 320), 226), "/ 100",
              fill=MUTED, font=f_head)
    verdict_txt = esc(v.get("text"))
    if len(verdict_txt) > 46:
        verdict_txt = verdict_txt[:45] + "…"
    draw.text((60, 340), verdict_txt, fill=INK, font=f_head)

    # бейджи
    y = 400
    by_id = {o["id"]: o for o in snapshot["offers"]}
    for key, oid in snapshot["badges"].items():
        o = by_id.get(oid)
        if not o:
            continue
        label = _BADGE_LABELS.get(key, key)
        draw.rounded_rectangle([60, y, 60 + 24 + 7 * len(label) + 90, y + 40],
                               radius=8, fill=PAPER_RAISED, outline=LINE, width=1)
        draw.text((84, y + 6), label, fill=STAMP, font=f_small)
        y += 52
    # (без clamp: таблица просто начинается ниже последнего бейджа)

    # топ-5 офферов
    y += 24
    draw.text((60, y), "ТОП ПРЕДЛОЖЕНИЙ (дешевле — первым)", fill=MUTED, font=f_small)
    y += 44
    for i, o in enumerate(snapshot["offers"][:5], 1):
        draw.rectangle([60, y, POSTER_W - 60, y + 62], fill=PAPER_RAISED)
        stock_c = OK if o["in_stock"] else WARN
        draw.rectangle([60, y, 66, y + 62], fill=stock_c)
        price = "?" if o["rank_price"] is None else f"{o['rank_price']:g}"
        h = o.get("honest") or {}
        note = ""
        if h.get("is_fake"):
            note = "скидка фейковая"
        elif h.get("honest_pct") is not None and h["honest_pct"] >= 10:
            note = f"настоящая −{h['honest_pct']:g}%"
        stock = "в наличии" if o["in_stock"] else "нет"
        draw.text((84, y + 6), f"{i}. {esc(o['platform'])}", fill=INK, font=f_head)
        draw.text((84, y + 40),
                  f"{stock}" + (f" · {note}" if note else "") +
                  (" · рассрочка" if o["installment_ok"] else ""),
                  fill=MUTED, font=f_small)
        draw.text((POSTER_W - 380, y + 16), f"{price} BYN", fill=INK, font=f_head)
        y += 70

    # спарклайн истории лучшего
    hist = snapshot.get("history_best") or []
    if len(hist) >= 2:
        y += 18
        draw.text((60, y), "ИСТОРИЯ ЦЕНЫ (лучший оффер)", fill=MUTED, font=f_small)
        y += 40
        _sparkline(draw, 60, y, POSTER_W - 360, 80, hist, STAMP)
        med = snapshot.get("median_best")
        if med is not None:
            med_txt = f"медиана {med:g} BYN"
            mw = draw.textlength(med_txt, font=f_small)
            draw.text((POSTER_W - 60 - mw, y + 24), med_txt,
                      fill=MUTED, font=f_small)

    # стоп-флаги + подпись
    flags = []
    for o in snapshot["offers"]:
        for f in o["stop_flags"]:
            if f["note"] not in flags:
                flags.append(f["note"])
    fy = POSTER_H - 60 - 34 * len(flags) - (46 if flags else 0)
    if flags:
        draw.text((60, fy), "ОСТОРОЖНО", fill=WARN, font=f_small)
        fy += 34
        for f in flags[:4]:
            draw.text((60, fy), f"• {f[:58]}", fill=INK, font=f_small)
            fy += 34
    draw.line([60, POSTER_H - 48, POSTER_W - 60, POSTER_H - 48], fill=LINE, width=2)
    footer = "Полное досье с кликабельными ссылками — по кнопке под постером"
    draw.text((60, POSTER_H - 40), footer, fill=MUTED, font=f_small)

    img.save(out_path, "PNG", optimize=True)
    return out_path


# ── полное HTML-досье ────────────────────────────────────────────────────
def render_html(snapshot):
    """Полное HTML-досье: токены «Диспетчерской», ВСЕ офферы со
    ссылками (кликабельность — слой 3), группы скоринга, история."""
    e = (lambda s: str(s or "")
         .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
         .replace('"', "&quot;"))
    title = e(snapshot["product"].get("title"))
    v = snapshot.get("verdict") or {}
    rows = []
    for o in snapshot["offers"]:
        gs = o.get("group_scores") or {}
        h = o.get("honest") or {}
        honest_txt = "—"
        if h.get("is_fake"):
            honest_txt = '<span class="status-red">фейк</span>'
        elif h.get("honest_pct") is not None:
            honest_txt = f"−{h['honest_pct']:g}%"
        flags = "".join(f'<div class="flag">⚠ {e(f["note"])}</div>'
                        for f in o.get("stop_flags"))
        rows.append(f"""<tr>
<td><a href="{e(o['url'])}" rel="noopener">{e(o['platform'])}</a><br>
<span class="muted">{e(o.get('seller_name'))}</span>{flags}</td>
<td class="mono">{o['rank_price'] if o['rank_price'] is not None else '—'} BYN</td>
<td>{'в наличии' if o['in_stock'] else '<span class="status-yellow">нет</span>'}
<br><span class="muted">доставка {o.get('delivery_days') if o.get('delivery_days') is not None else '?'} дн.</span></td>
<td>{honest_txt}</td>
<td class="mono">{o.get('total', '—')}</td>
<td class="mono muted">цена {gs.get('price', '—')} · кач-во {gs.get('quality', '—')} ·
доступ {gs.get('access', '—')} · продавец {gs.get('seller', '—')}</td>
</tr>""")
    badges_html = " · ".join(
        f'<span class="badge badge-fact">{e(_BADGE_LABELS.get(k, k))}</span>'
        for k in snapshot["badges"])
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Досье: {title}</title><style>
:root{{--ink:#1C1B18;--paper:#EFEAE0;--paper-raised:#FBF8F2;--line:rgba(28,27,24,.14);
--stamp:#A8321E;--muted:#6B6558;--ok:#3D6B2C;--warn:#9C6B0B;--bad:#A8321E;
--d:'Newsreader',Georgia,serif;--b:'IBM Plex Sans',system-ui,sans-serif;
--m:'IBM Plex Mono',ui-monospace,monospace}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--b);background:var(--paper);color:var(--ink);padding:24px}}
h1{{font-family:var(--d);font-size:1.8rem}}
.card{{background:var(--paper-raised);border:1px solid var(--line);border-radius:12px;padding:20px;margin:16px 0}}
.score{{font-family:var(--m);font-size:2.4rem;color:var(--stamp)}}
table{{width:100%;border-collapse:collapse;margin:12px 0}} th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);font-size:.9rem;vertical-align:top}}
th{{color:var(--muted);font-weight:500;text-transform:uppercase;font-size:.7rem;letter-spacing:1px}}
a{{color:var(--stamp);text-decoration:none}} a:hover{{text-decoration:underline}}
.mono{{font-family:var(--m)}} .muted{{color:var(--muted);font-size:.8rem}}
.status-red{{color:var(--bad)}} .status-yellow{{color:var(--warn)}}
.badge{{font-family:var(--m);font-size:.8rem;padding:1px 8px;border-radius:4px;display:inline-block;background:rgba(61,107,44,.12);color:var(--ok)}}
.flag{{color:var(--warn);font-size:.75rem}}
.meta{{color:var(--muted);font-size:.85rem;margin:8px 0}}
</style></head><body>
<h1>Досье: {title}</h1>
<div class="meta">{e(snapshot['generated_at'])} · профиль {e(snapshot['profile'])} ·
срез #{snapshot.get('dossier_id', '—')}</div>
<div class="card"><span class="score">{v.get('score', '—')}</span>
<span style="font-size:1.4rem"> / 100</span>
<p style="margin-top:8px;font-size:1.1rem">{e(v.get('text'))}</p>
<p style="margin-top:8px">{badges_html}</p></div>
<div class="card"><table>
<tr><th>Оффер (дешевле — первым)</th><th>Реальная цена</th><th>Наличие</th><th>Честная скидка</th><th>Балл</th><th>Группы</th></tr>
{''.join(rows)}
</table></div>
<div class="card"><b>Как читать</b><p class="meta">«Реальная цена» — цена с учётом
способа оплаты и доставки (rank_price). «Честная скидка» — процент к медиане
истории цен, не к зачёркнутой «старой цене»; фейк — когда зачёркнутая выше
обычной. Стоп-флаги (⚠) — дисквалификаторы вне баллов: аномальная цена,
продавец без истории, запрет возврата, расхождение характеристик.</p></div>
</body></html>"""
