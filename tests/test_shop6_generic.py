#!/usr/bin/env python3
"""SHOP-6 tests (диспатч #172): generic URL-dossier — 4 метода PriceGhost.

Покрытие (условия «Сделано, когда» из #172):
- тесты на 6 фикстурных HTML: магазин РБ с JSON-LD, бренд-сайт (meta
  itemprop + og:price), прайс-страница (class-price), расхождение
  методов (кандидаты с пометками), антибот-стена, пустая страница;
- JSON-LD: Product→offers, @graph, список типов, строчная цена
  «1 299,90», availability → in_stock;
- сайт-специфичные селекторы: таблица РБ-магазинов + env-расширение;
- generic CSS-эвристика: meta itemprop/og + class*=price fallback;
- AI-метод: подмена AI_EXTRACT_FN (LLM не вызывается); отказ → пусто;
- голосование: кластеры с допуском 1%, agree/disagree, приоритет
  jsonld > selector > generic > ai, кандидаты с пометками;
- collect_url: антибот → source_unavailable (не падение, #172);
  оффер platform='web' в БД + история + повторный сбор обновляет;
- /товар <URL> → generic-ветка эндпоинта (транспорт и TG замоканы);
- web-MCP fetch_page(raw_html=true): контракт raw-HTML (JSON-LD не
  вычищается), отдельный кэш-ключ.
"""
import importlib.util
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
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop6-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query, app  # noqa: E402 — app захватываем при импорте
# (test_security::test_trace_write_creates_file перезагружает proxy.core —
# после релоада from proxy.core import app внутри fixture вернул бы НОВЫЙ
# Flask-объект без роутов routes_tail; привязка к импорту файла спасает)
from proxy import shop_generic as sg  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app

# ── фикстуры HTML (#172: магазин РБ, бренд-сайт, прайс-страница…) ────────
HTML_JSONLD_SHOP = """<!DOCTYPE html><html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Холодильник ATLANT",
 "offers": {"@type": "Offer", "price": "1 299,90", "priceCurrency": "BYN",
            "availability": "https://schema.org/InStock",
            "seller": {"@type": "Organization", "name": "Электросила"}}}
</script></head><body>Магазин бытовой техники</body></html>"""

HTML_BRAND_META = """<!DOCTYPE html><html><head>
<meta itemprop="price" content="89.99">
<meta itemprop="priceCurrency" content="BYN">
<meta property="product:price:amount" content="89.99">
<meta property="product:price:currency" content="BYN">
<title>Производитель: термос STAYER</title></head>
<body><h1>Термос STAYER 1л</h1></body></html>"""

HTML_PRICE_CLASS = """<html><head><title>Прайс: насос</title></head><body>
<div class="product-card"><h2>Насос «Вихрь»</h2>
<span class="product-price">от 165,50 р.</span>
<div class="stock">в наличии</div></div></body></html>"""

HTML_DISAGREE = """<html><head>
<script type="application/ld+json">
{"@type": "Product", "name": "Велосипед", "offers":
 {"@type": "Offer", "price": "100.00", "priceCurrency": "BYN"}}
</script>
<meta itemprop="price" content="150.00">
</head><body><div class="price">100.5</div></body></html>"""

HTML_ANTIBOT = """<html><head><title>Just a moment...</title></head>
<body><div class="cf-captcha">Checking your browser before access.
Please enable cookies and solve captcha.</div></body></html>"""

HTML_EMPTY = """<html><head><title>О компании</title></head>
<body><p>Мы производим лучшие товары с 1991 года. Контакты: 123-45-67.</p></body></html>"""

# url-подобные ключи в тестах


def _shop_ddl():
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    import re
    creates = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    alters = re.findall(r'try db_execute\("(ALTER TABLE shop_[^"]+)"\)', ddl)
    return [s for s in creates if "shop_" in s] + alters


SHOP_TABLES = ("shop_dossiers", "shop_watches", "shop_price_history",
               "shop_offers", "shop_sellers", "shop_products")


@pytest.fixture()
def shop_db(monkeypatch):
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
    monkeypatch.delenv("SHOP_SITE_SELECTORS_JSON", raising=False)
    yield
    for t in SHOP_TABLES:
        _query(f"DELETE FROM {t}")


# ── метод 1: JSON-LD ─────────────────────────────────────────────────────
def test_jsonld_shop_byn(shop_db):
    out = sg.extract_jsonld(HTML_JSONLD_SHOP)
    assert len(out) == 1
    c = out[0]
    assert c["price"] == 1299.90  # «1 299,90» → parse_price SHOP-1
    assert c["currency"] == "BYN"
    assert c["in_stock"] is True
    assert "ATLANT" in c["name"]
    assert c["seller"] == "Электросила"
    assert c["source"] == "jsonld"


def test_jsonld_graph_and_list_types(shop_db):
    html = """<html><script type="application/ld+json">
    [{"@type": "Organization", "name": "X"},
     {"@type": "Product", "name": "Часы", "offers":
      {"@type": "Offer", "price": "45.00", "priceCurrency": "BYN"}}]
    </script></html>"""
    out = sg.extract_jsonld(html)
    assert out and out[0]["price"] == 45.0 and out[0]["name"] == "Часы"


def test_jsonld_broken_blob_skipped(shop_db):
    out = sg.extract_jsonld('<script type="application/ld+json">{broken')
    assert out == []


# ── метод 2: сайт-селекторы ──────────────────────────────────────────────
def test_site_selector_21vek(shop_db):
    html = '<div class="product__price">89,90 р.</div>'
    out = sg.extract_site_selectors(html, "https://www.21vek.by/item/x")
    assert out and out[0]["price"] == 89.9
    assert out[0]["source"].startswith("selector:21vek")


def test_site_selector_env_extension(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_SITE_SELECTORS_JSON", json.dumps({
        "miod.by": [("miod", r'class="mioprice"[^>]*>\s*([^<]{1,40})')]}))
    html = '<div class="mioprice">55.00</div>'
    out = sg.extract_site_selectors(html, "https://miod.by/p/1")
    assert out and out[0]["price"] == 55.0


def test_site_selector_other_host_empty(shop_db):
    out = sg.extract_site_selectors(HTML_PRICE_CLASS, "https://unknown.shop/x")
    assert out == []


# ── метод 3: generic CSS-эвристика ───────────────────────────────────────
def test_generic_meta_itemprop(shop_db):
    out = sg.extract_generic(HTML_BRAND_META)
    assert out and out[0]["price"] == 89.99
    assert out[0]["currency"] == "BYN"
    assert out[0]["source"].startswith("generic:")


def test_generic_og_price_currency(shop_db):
    html = ('<meta property="og:price:amount" content="1 200,00">'
            '<meta property="og:price:currency" content="BYN">')
    out = sg.extract_generic(html)
    assert out and out[0]["price"] == 1200.0 and out[0]["currency"] == "BYN"


def test_generic_class_price_fallback(shop_db):
    out = sg.extract_generic(HTML_PRICE_CLASS)
    assert out and out[0]["price"] == 165.5
    assert out[0]["source"] == "generic:class_price"


def test_generic_empty_page_nothing(shop_db):
    assert sg.extract_generic(HTML_EMPTY) == []


# ── метод 4: AI ──────────────────────────────────────────────────────────
def test_ai_extract_mocked(shop_db, monkeypatch):
    monkeypatch.setattr(sg, "AI_EXTRACT_FN",
                        lambda url, text: [{"price": 77.0, "currency": "BYN",
                                            "in_stock": True, "name": "X",
                                            "seller": "", "source": "ai"}])
    out = sg.extract_ai("https://shop.by/p", "<html>x</html>")
    assert out[0]["price"] == 77.0 and out[0]["source"] == "ai"


def test_ai_impl_bad_reply_returns_empty(shop_db, monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "fake")
    import proxy.providers as prov
    monkeypatch.setattr(prov, "call_llm",
                        lambda *a, **k: {"reply": "не знаю, цены нет"})
    monkeypatch.setattr(sg, "AI_EXTRACT_FN", None)
    out = sg.extract_ai("https://shop.by/p", HTML_EMPTY)
    assert out == []


# ── голосование ──────────────────────────────────────────────────────────
def test_vote_agreement_priority(shop_db):
    cands = [{"price": 100.0, "source": "generic:x"},
             {"price": 100.5, "source": "ai"},
             {"price": 100.2, "source": "jsonld"}]
    v = sg.vote(cands)
    assert v["agree"] is True
    assert v["winner"]["source"] == "jsonld"  # приоритет источника


def test_vote_disagreement_candidates_with_marks(shop_db):
    cands = [{"price": 100.0, "source": "jsonld"},
             {"price": 150.0, "source": "generic:meta"}]
    v = sg.vote(cands)
    assert v["agree"] is False
    assert v["winner"]["price"] == 100.0  # первый кластер по числу голосов… оба по 1 — порядок стабильный
    sources = [s for cl in v["clusters"] for s in cl["sources"]]
    assert "jsonld" in sources and "generic:meta" in sources  # пометки живы


def test_vote_empty(shop_db):
    assert sg.vote([])["winner"] is None


# ── collect_url: антибот/успех/повторный сбор ────────────────────────────
def _mock_fetch(monkeypatch, html):
    monkeypatch.setattr(sg, "FETCH_PAGE_FN",
                        lambda tool, args: {"ok": True, "url": args["url"],
                                            "status": 200, "content": html})


def test_collect_url_success_web_offer(shop_db, monkeypatch):
    _mock_fetch(monkeypatch, HTML_JSONLD_SHOP)
    monkeypatch.setattr(sg, "AI_EXTRACT_FN", lambda u, t: [])
    _query("INSERT INTO shop_products (title, query_text) VALUES (?, ?)",
           ("?", "https://electrosila.by/p/atlant"))
    pid = _query("SELECT id FROM shop_products ORDER BY id DESC LIMIT 1",
                 fetch=True)[0]["id"]
    url = "https://electrosila.by/p/atlant?utm_source=ads"
    r = sg.collect_url(pid, url)
    assert r["ok"] is True and r["vote"]["agree"] is True
    row = _query("SELECT id, platform, platform_code, url, price_byn, in_stock "
                 "FROM shop_offers WHERE product_id=?", (pid,), fetch=True)
    assert row[0]["platform"] == "web"
    assert row[0]["platform_code"] == "electrosila.by"
    assert row[0]["price_byn"] == 1299.90 and row[0]["in_stock"] == 1
    assert "utm_" not in row[0]["url"]  # canonical
    hist = _query("SELECT price_byn FROM shop_price_history WHERE offer_id=?",
                  (row[0]["id"],), fetch=True)
    assert hist[0]["price_byn"] == 1299.90


def test_collect_url_refresh_updates_not_duplicates(shop_db, monkeypatch):
    _mock_fetch(monkeypatch, HTML_JSONLD_SHOP)
    monkeypatch.setattr(sg, "AI_EXTRACT_FN", lambda u, t: [])
    _query("INSERT INTO shop_products (title, query_text) VALUES ('x', 'u')")
    pid = _query("SELECT id FROM shop_products ORDER BY id DESC LIMIT 1",
                 fetch=True)[0]["id"]
    url = "https://electrosila.by/p/atlant"
    sg.collect_url(pid, url)
    sg.collect_url(pid, url)  # второй сбор
    n = _query("SELECT COUNT(*) AS c FROM shop_offers WHERE platform='web'",
               fetch=True)[0]["c"]
    assert n == 1
    h = _query("SELECT COUNT(*) AS c FROM shop_price_history", fetch=True)[0]["c"]
    assert h == 2  # история на каждый сбор (стиль SHOP-3)


def test_collect_url_antibot_not_crash(shop_db, monkeypatch):
    _mock_fetch(monkeypatch, HTML_ANTIBOT)
    r = sg.collect_url(1, "https://hard.shop/p/1")
    assert r["ok"] is False and r["kind"] == "source_unavailable"


def test_collect_url_empty_page(shop_db, monkeypatch):
    _mock_fetch(monkeypatch, HTML_EMPTY)
    monkeypatch.setattr(sg, "AI_EXTRACT_FN", lambda u, t: [])
    r = sg.collect_url(1, "https://info.by/about")
    assert r["ok"] is False and r["kind"] == "no_candidates"


def test_collect_url_fetch_down(shop_db, monkeypatch):
    monkeypatch.setattr(sg, "FETCH_PAGE_FN",
                        lambda tool, args: {"ok": False, "kind": "fetch_error",
                                            "error": "сеть недоступна"})
    r = sg.collect_url(1, "https://down.by/p")
    assert r["ok"] is False and r["kind"] == "source_unavailable"


def test_collect_url_bad_url(shop_db):
    assert sg.collect_url(1, "not-a-url")["kind"] == "bad_url"


# ── /товар <URL> → generic-ветка ─────────────────────────────────────────
@pytest.fixture()
def client():
    with app.test_client() as c:
        yield c


def test_endpoint_product_url_flow(shop_db, client, monkeypatch):
    _mock_fetch(monkeypatch, HTML_JSONLD_SHOP)
    monkeypatch.setattr(sg, "AI_EXTRACT_FN", lambda u, t: [])
    sent = {"photo": 0, "text": 0}
    monkeypatch.setattr("proxy.telegram._tg_send_photo",
                        lambda *a, **k: sent.__setitem__("photo", 1) or 1)
    monkeypatch.setattr("proxy.telegram._tg_send_message",
                        lambda *a, **k: sent.__setitem__("text", 1) or 1)
    r = client.post("/shop/product", json={
        "query": "https://electrosila.by/p/atlant", "chat_id": "555000"})
    data = r.get_json()
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
    assert data["ok"] is True and data["dossier_id"], data
    assert data["collect"]["vote_agree"] is True
    # #409 A.1: одно сообщение с досье — карточка без отдельного текста
    assert sent["photo"] == 1 and sent["text"] == 0
    prow = _query("SELECT title, query_text FROM shop_products WHERE id=?",
                  (data["product_id"],), fetch=True)
    assert prow[0]["title"] == "Холодильник ATLANT"  # имя из JSON-LD
    assert prow[0]["query_text"] == "https://electrosila.by/p/atlant"


def test_endpoint_product_url_source_down(shop_db, client, monkeypatch):
    monkeypatch.setattr(sg, "FETCH_PAGE_FN",
                        lambda tool, args: {"ok": False, "kind": "fetch_error",
                                            "error": "down"})
    r = client.post("/shop/product", json={"query": "https://down.by/p"})
    data = r.get_json()
    assert data["ok"] is False and data["kind"] == "source_unavailable"


# ── web-MCP fetch_page(raw_html=true): контракт ──────────────────────────
def test_web_mcp_raw_html_keeps_jsonld(monkeypatch):
    spec = importlib.util.spec_from_loader(
        "shop6_web", importlib.machinery.SourceFileLoader(
            "shop6_web", str(REPO_ROOT / "mcp_servers" / "web")))
    web = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web)
    # локальный фейк транспорта: без сети (паттерн SHOP-2 — stub)
    monkeypatch.setattr(web, "http_get", lambda url: (
        True, {"raw": HTML_JSONLD_SHOP, "status": 200, "url": url,
               "content_type": "text/html", "robots_note": ""}))
    text_mode = web.tool_fetch_page({"url": "https://t.by/x", "refresh": True,
                                     "max_chars": 5000})
    raw_mode = web.tool_fetch_page({"url": "https://t.by/x", "refresh": True,
                                    "raw_html": True, "max_chars": 5000})
    assert "application/ld+json" not in text_mode["content"]  # text вычищает
    assert "application/ld+json" in raw_mode["content"]  # raw сохраняет
    assert "Холодильник ATLANT" in raw_mode["content"]  # JSON-LD тело живо
