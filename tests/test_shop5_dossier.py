#!/usr/bin/env python3
"""SHOP-5 tests (диспатч #172): досье — текст / постер PNG / HTML.

Покрытие:
- build_snapshot: единый срез (продукт + скоринг + URLs + история),
  сортировка «дешевле — первым» (решение владельца #172 п.2),
  canonical URL даже для старых строк БД;
- ТРИ формата из ОДНОГО среза: render_text / render_caption /
  render_poster / render_html дают одни и те же цифры и ссылки
  (ключевое требование #172: «оба формата рендерятся из одного среза»);
- кликабельность: caption ≤1000 с HTML-ссылками; inline-кнопки «Купить»
  (Bot API reply_markup: label ≤64, URL http/https); HTML-досье со всеми
  ссылками; HMAC-токен доступа к странице досье;
- постер: PNG 1080×1350, RGB, открывается PIL (RAM-фиксированный размер);
- /товар /вотч: парсер аргументов, эндпоинты (тест-клиент Flask),
  kill-switch SHOP_ENABLED=0;
- mlog-команды зарегистрированы в webhook-роуте (статическая проверка).
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop5-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query, app  # noqa: E402 — app захватываем при импорте
# (test_security перезагружает proxy.core — from-import внутри fixture вернул
# бы новый Flask-объект без роутов routes_tail; привязка к импорту спасает)
from proxy import shop_dossier as sd  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app

WB_URL = "https://www.wildberries.ru/catalog/414389121/detail.aspx?utm_source=test"
KUFAR_URL = "https://www.kufar.by/item/1001?utm_medium=x"


def _shop_ddl():
    """CREATE + идемпотентные ALTER shop_* — ровно как исполняет офис
    (ALTER через db_execute И через db_execute_with_grant, паттерн #329)."""
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    import re
    creates = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    alters = re.findall(r'try db_execute\("(ALTER TABLE shop_[^"]+)"\)', ddl)
    alters += re.findall(r'try db_execute_with_grant\(grant_issue\([^)]*\), '
                         r'"(ALTER TABLE shop_[^"]+)"\)', ddl)
    return [s for s in creates if "shop_" in s] + alters


SHOP_TABLES = ("shop_dossiers", "shop_watches", "shop_price_history",
               "shop_offers", "shop_sellers", "shop_products")


@pytest.fixture()
def shop_db():
    db_file = os.path.join(os.environ["DATABASE_PATH"], "fosved.db")
    conn = sqlite3.connect(db_file)
    for stmt in _shop_ddl():
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    conn.commit()
    conn.close()
    for t in SHOP_TABLES:
        _query(f"DELETE FROM {t}")
    yield
    for t in SHOP_TABLES:
        _query(f"DELETE FROM {t}")


def _seed_product():
    """Продукт + 3 оффера (WB дешевле всех, фейк-скидка у третьего) + история."""
    _query("INSERT INTO shop_products (title, query_text) VALUES (?, ?)",
           ("Кофемолка SM-200", "кофемолка"))
    pid = _query("SELECT id FROM shop_products ORDER BY id DESC LIMIT 1",
                 fetch=True)[0]["id"]
    offers = [
        ("wb", "414389121", WB_URL, "Кофемолка электрическая SM-200",
         23.94, None, None, 1, 4.8, 18790),
        ("kufar", "1001", KUFAR_URL, "Кофемолка ручная Manual",
         220.0, None, None, 1, None, None),
        ("kufar", "1002", "https://www.kufar.by/item/1002",
         "Кофемолка SM-200 с жерновами", 300.0, 400.0,
         None, 1, None, None),
    ]
    oids = []
    for platform, code, url, title, price, old, card, stock, rating, reviews in offers:
        _query("INSERT INTO shop_offers (product_id, platform, platform_code, "
               "url, title, price_byn, old_price_byn, card_price_byn, in_stock, "
               "rating, reviews_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (pid, platform, code, url, title, price, old, card, stock, rating,
                reviews))
        oids.append(_query("SELECT id FROM shop_offers WHERE platform=? AND "
                           "platform_code=? ORDER BY id DESC LIMIT 1",
                           (platform, code), fetch=True)[0]["id"])
    # история третьего оффера: медиана 300 → скидка «к зачёркнутой» фейк
    for p in (300.0, 299.0, 301.0):
        _query("INSERT INTO shop_price_history (offer_id, price_byn) VALUES (?, ?)",
               (oids[2], p))
    return pid, oids


# ── единый срез ──────────────────────────────────────────────────────────
def test_snapshot_sorted_cheapest_first_and_canonical(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid, save=False)
    assert snap["ok"] is True
    prices = [o["rank_price"] for o in snap["offers"]]
    assert prices == sorted(p for p in prices if p is not None)
    assert snap["offers"][0]["platform"] == "wb"
    assert snap["offers"][0]["rank_price"] == pytest.approx(23.94)
    # canonical: utm вычищен даже из старой строки БД
    assert "utm_" not in snap["offers"][0]["url"]
    assert snap["offers"][0]["url"].endswith("detail.aspx")


def test_snapshot_saves_dossier_row(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    assert snap.get("dossier_id")
    row = _query("SELECT product_id, format, snapshot_json FROM shop_dossiers "
                 "WHERE id=?", (snap["dossier_id"],), fetch=True)
    assert row and row[0]["product_id"] == pid and row[0]["format"] == "snapshot"
    assert json.loads(row[0]["snapshot_json"])["ok"] is True


def test_snapshot_missing_product(shop_db):
    snap = sd.build_snapshot(999999, save=False)
    assert snap["ok"] is False and snap["kind"] == "not_found"


# ── три формата из одного среза ──────────────────────────────────────────
def test_all_formats_render_from_one_snapshot(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    text = sd.render_text(snap)
    caption = sd.render_caption(snap)
    html = sd.render_html(snap)
    best = snap["offers"][0]
    # одна и та же цифра лучшей цены во всех форматах
    assert "23.94" in text
    assert "23.94" in caption
    assert "23.94" in html
    # одна и та же ссылка лучшего оффера в тексте, caption и HTML
    assert best["url"] in text
    assert best["url"] in caption
    assert best["url"] in html


def test_render_text_structure_and_limit(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    text = sd.render_text(snap)
    assert len(text) <= sd.MAX_TEXT
    assert "Досье: Кофемолка SM-200" in text
    assert "Вердикт" in text
    assert "дешевле всех" in text  # бейдж
    assert "СКИДКА ФЕЙКОВАЯ" in text  # фейк-детект виден в досье
    assert "Осторожно" in text  # стоп-флаг продавца без истории
    # порядок «дешевле — первым»: wb упомянут раньше kufar
    assert text.index("wildberries.ru") < text.index("kufar.by")


def test_render_caption_html_links_limit(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    caption = sd.render_caption(snap)
    assert len(caption) <= sd.MAX_CAPTION
    assert "<b>Досье:" in caption
    assert f"<a href=\"{snap['offers'][0]['url']}\">" in caption
    if snap.get("dossier_id"):
        assert "Полное досье" in caption


def test_inline_buttons_valid_bot_api(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    markup = sd.build_inline_buttons(snap)
    data = json.loads(markup)
    buttons = data["inline_keyboard"][0]
    assert 1 <= len(buttons) <= sd.MAX_BUTTONS + 1
    for b in buttons:
        assert len(b["text"]) <= 64
        assert b["url"].startswith(("http://", "https://"))
    # первая кнопка — лучший (дешевле всех) оффер
    assert buttons[0]["url"] == snap["offers"][0]["url"]


def test_inline_buttons_empty_without_urls(shop_db):
    pid, _ = _seed_product()
    _query("UPDATE shop_offers SET url=''")
    snap = sd.build_snapshot(pid)
    assert sd.build_inline_buttons(snap) is None


def test_render_poster_png_verified(shop_db):
    from PIL import Image
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    out = "/tmp/shop5-poster-test.png"
    if os.path.exists(out):
        os.remove(out)
    sd.render_poster(snap, out)
    img = Image.open(out)
    img.verify()
    img = Image.open(out)
    assert img.size == (sd.POSTER_W, sd.POSTER_H)
    assert img.mode == "RGB"
    assert os.path.getsize(out) > 10_000  # непустой постер


def test_render_html_full_and_clickable(shop_db):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    html = sd.render_html(snap)
    assert "Досье: Кофемолка SM-200" in html
    for o in snap["offers"]:
        assert f"<a href=\"{o['url']}\"" in html
    assert "--paper" in html  # legacy-алиасы сохранены (паттерн report_css.txt)
    assert "фейк" in html  # честная скидка отмечена
    assert "Как читать" in html


# ── наряд #330: токены FORGE-UI-0 вместо «Диспетчерской» ────────────────
def test_render_html_fosved_tokens_not_dispetcherskaya(shop_db):
    pid, _ = _seed_product()
    html = sd.render_html(sd.build_snapshot(pid, save=False))
    # точные значения из miniapp/index.html через report_css.txt (не изобретены)
    assert "--bg:#0A0A0C" in html
    assert "--surface:#151517" in html
    assert "--red:#E8262E" in html and "--red-light:#FF8A8F" in html
    assert "--ink:#EDEDED" in html and "--muted:#8A8A8F" in html
    assert "--green:#7ED957" in html and "--yellow:#F5C93E" in html
    # старая светлая тема «Диспетчерской» ушла полностью
    assert "Newsreader" not in html and "IBM Plex Sans" not in html
    assert "#EFEAE0" not in html and "#FBF8F2" not in html and "#A8321E" not in html
    # контраст A.2: мелкий красный текст — red-light, не чистый red
    assert ".status-red{color:var(--red-light)}" in html
    assert ".status-yellow{color:var(--yellow)}" in html
    assert "a{color:var(--red-light)" in html
    # фон и поверхности — тёмные, печать — светлая (приём FORGE-UI-6)
    assert "body{font-family:var(--f);background:var(--bg);color:var(--ink)" in html
    assert "@media print" in html and "--bg:#FFFFFF" in html


def test_render_html_offers_images_and_honest_placeholder(shop_db):
    """Наряд #329: <img loading=lazy> для оффера с image_url; без ссылки —
    явный «нет фото», без битой иконки (onerror → data-URI плейсхолдер)."""
    pid, oids = _seed_product()
    _query("UPDATE shop_offers SET image_url=? WHERE id=?",
           ("https://basket-28.wbbasket.ru/vol4143/part414389/414389121/"
            "images/big/1.webp", oids[0]))
    snap = sd.build_snapshot(pid, save=False)
    html = sd.render_html(snap)
    assert '<th>Фото</th>' in html
    assert 'loading="lazy"' in html
    assert "basket-28.wbbasket.ru" in html
    assert "onerror=\"this.onerror=null;this.src='" in html
    assert "data:image/svg+xml" in html  # фолбэк-плейсхолдер
    # оффер без ссылки — явный плейсхолдер, не пустота
    assert html.count('class="img-miss"') >= 2  # kufar × 2 без фото
    # снапшот прокидывает image_url (один срез — все форматы)
    assert snap["offers"][0]["image_url"].startswith("https://basket-28")


def test_dossier_token_stable_and_url(shop_db, monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://office.example.com")
    t1 = sd.dossier_token(7)
    assert t1 == sd.dossier_token(7)
    assert t1 != sd.dossier_token(8)
    url = sd.dossier_url(7)
    assert url.startswith("https://office.example.com/shop/dossier/7?t=")
    assert len(url.split("?t=")[1]) == 16


# ── /товар /вотч: парсер + эндпоинты ─────────────────────────────────────
def test_parse_watch_args_numbers_and_words():
    from proxy.routes_tail import _parse_watch_args
    target, disc, stock, unknown = _parse_watch_args("250")
    assert target == 250.0 and disc is None and stock is False and not unknown
    target, disc, stock, unknown = _parse_watch_args("скидка 15")
    assert target is None and disc == 15.0 and stock is False
    target, disc, stock, unknown = _parse_watch_args("наличие")
    assert stock is True and target is None and disc is None
    target, disc, stock, unknown = _parse_watch_args("250,90 скидка 10 наличие")
    assert target == 250.9 and disc == 10.0 and stock is True
    target, disc, stock, unknown = _parse_watch_args("мусор")
    assert target is None and disc is None and stock is False and unknown == ["мусор"]


@pytest.fixture()
def client():
    with app.test_client() as c:
        yield c


def test_endpoint_watch_list_empty(shop_db, client):
    r = client.post("/shop/watch", json={"args": ""})
    data = r.get_json()
    assert r.status_code == 200 and data["ok"] is True
    assert "Вотчей нет" in data["reply"]


def test_endpoint_watch_set_target(shop_db, client):
    _seed_product()
    r = client.post("/shop/watch", json={"args": "250"})
    data = r.get_json()
    assert data["ok"] is True and "Следить" in data["reply"]
    row = _query("SELECT target_price_byn FROM shop_watches WHERE "
                 "status='active'", fetch=True)
    assert row and row[0]["target_price_byn"] == 250.0


def test_endpoint_watch_unparseable(shop_db, client):
    _seed_product()
    r = client.post("/shop/watch", json={"args": "мусор"})
    data = r.get_json()
    assert data["ok"] is False and "Не понял" in data["reply"]


def test_endpoint_dossier_json(shop_db, client):
    pid, _ = _seed_product()
    r = client.post("/shop/dossier", json={"product_id": pid})
    data = r.get_json()
    assert r.status_code == 200 and data["ok"] is True
    assert data["text"] and data["caption"] and data["html_url"]
    assert data["reply_markup"] is not None
    assert "/shop/dossier/" in data["html_url"]


def test_endpoint_dossier_page_token(shop_db, client):
    pid, _ = _seed_product()
    snap = sd.build_snapshot(pid)
    did = snap["dossier_id"]
    r403 = client.get(f"/shop/dossier/{did}")
    assert r403.status_code == 403
    ok = client.get(f"/shop/dossier/{did}?t={sd.dossier_token(did)}")
    assert ok.status_code == 200
    assert "Досье: Кофемолка SM-200" in ok.get_data(as_text=True)
    miss = client.get(f"/shop/dossier/999999?t={sd.dossier_token(999999)}")
    assert miss.status_code == 404


def test_endpoint_product_kill_switch(shop_db, client, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "0")
    r = client.post("/shop/product", json={"query": "кофемолка"})
    data = r.get_json()
    assert data["ok"] is False and data.get("kind") == "disabled"


def test_endpoint_product_full_flow(shop_db, client, monkeypatch):
    """Живой путь команды /товар: сбор (мок транспорта) → срез → досье →
    отправка владельцу (TG замокан)."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    from proxy import shop_collectors as sc
    from proxy import routes_tail as rt

    def fake_fetch(tool, args):
        url = args.get("url", "")
        if "search.wb.ru" in url:
            return {"ok": True, "data": {"products": [{
                "id": 414389121, "name": "Кофемолка SM", "rating": 5,
                "reviewRating": 4.8, "feedbacks": 100, "totalQuantity": 5,
                "supplier": "Маг", "supplierId": 1, "supplierRating": 4.9,
                "sizes": [{"price": {"basic": 100000, "product": 70000}}],
            }]}}
        if "ozon.by" in url:
            # ozon — каркас за антиботом: честный отказ (как живой)
            return {"ok": False, "error": "антибот (тест): 307-петля",
                    "kind": "transport"}
        return {"ok": False, "error": "неожиданный URL", "kind": "test"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake_fetch)

    sent = {"photo": None, "text": None}

    def fake_photo(chat_id, path, caption=None, parse_mode=None, reply_markup=None):
        sent["photo"] = (path, caption, reply_markup)
        return 1

    def fake_text(chat_id, text, **kw):
        sent["text"] = text
        return 1

    monkeypatch.setattr(rt, "_tg_send_photo", fake_photo, raising=False)
    monkeypatch.setattr("proxy.telegram._tg_send_photo", fake_photo)
    monkeypatch.setattr("proxy.telegram._tg_send_message", fake_text)

    r = client.post("/shop/product", json={"query": "кофемолка",
                                           "chat_id": "555000"})
    data = r.get_json()
    assert data["ok"] is True and data["dossier_id"], data
    path, caption, markup = sent["photo"]
    assert os.path.exists(path) and caption and markup
    json.loads(markup)  # reply_markup валидный JSON
    # #409 A.1: РОВНО ОДНО сообщение с досье — карточка; отдельная
    # текстовая выжимка снята (на одну просьбу приходило 2-3 сообщения)
    assert sent["text"] is None and sent["photo"]


# ── mlog-команды зарегистрированы (статическая проверка UX) ──────────────
def test_mlog_has_shop_commands():
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    assert 'starts_with(text, "/товар ")' in ddl
    assert 'starts_with(text, "/вотч")' in ddl
    assert "http://127.0.0.1:4000/shop/product" in ddl
    assert "http://127.0.0.1:4000/shop/watch" in ddl


def test_render_yaml_and_deps_have_pillow():
    reqs = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "Pillow" in reqs
    docker = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "fonts-dejavu-core" in docker


# ── живой кейс владельца (досье #2): ни одной цены BYN ──────────────────
def _seed_unpriced_product():
    """Продукт, все офферы без цены. Платформа kufar в БД — REGRESS:
    сборщик выведен (2026-09-16), но старые строки обязаны рендериться."""
    _query("INSERT INTO shop_products (title, query_text) VALUES (?, ?)",
           ("Боксеры мужские", "боксеры"))
    pid = _query("SELECT id FROM shop_products ORDER BY id DESC LIMIT 1",
                 fetch=True)[0]["id"]
    for platform, code, url in (("wb", "1", WB_URL),
                                ("kufar", "1001", KUFAR_URL)):
        _query("INSERT INTO shop_offers (product_id, platform, platform_code, "
               "url, price_byn, in_stock) VALUES (?, ?, ?, ?, NULL, 1)",
               (pid, platform, code, url))
    return pid


def test_zero_priced_dossier_is_honest_and_clickable(shop_db, tmp_path):
    pid = _seed_unpriced_product()
    snap = sd.build_snapshot(pid, save=False)
    assert snap["verdict"] is None
    assert snap["unscored_total"] == 2
    assert [u["platform"] for u in snap["unscored_offers"]] == ["wb", "kufar"]
    text = sd.render_text(snap)
    assert "Вердикт: —/100" in text
    assert "цены не получены" in text
    assert "Топ предложений" not in text
    assert "История копится" not in text
    assert "kufar.by/item/1001" in text  # ссылки не спрятаны даже без цен
    caption = sd.render_caption(snap)
    assert "—/100" in caption and "цены не получены" in caption
    html = sd.render_html(snap)
    assert "не ранжированы" in html and "kufar.by/item/1001" in html
    poster_path = tmp_path / "poster.png"
    sd.render_poster(snap, str(poster_path))
    assert poster_path.exists()
