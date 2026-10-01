#!/usr/bin/env python3
"""Гвард наряда #438: досье без кнопок покупки, с фото товаров.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/438
Фактура 2026-09-30: «убери в ответе снизу кнопки для покупки, и до сих
пор картинки в отчёте не появляются». Причина отсутствия фото:
image_url заполнял только сборщик WB (#329), а WB с сервера закрыт
(HTTP 403, #407); сборщик Onliner поле не заполнял вовсе.

A.1 — reply_markup не передаётся ни в одном из двух мест
      (_shop_send_dossier и /shop/dossier JSON); build_inline_buttons —
      гвард-заглушка.
A.2 — collect_onliner заполняет image_url из products[].images.header
      (снято с живого ответа /search/iron 2026-09-30: URL
      imgproxy.onliner.by, проверено, не угадано).
A.3 — картинка сообщения досье: фото лучшего предложения (best_offer_image
      + _shop_fetch_offer_image), постер PNG — запасной вариант.
A.4 — правило для будущих сборщиков: image_url — обязательное поле оффера,
      если площадка отдаёт фото (docstring collect_onliner).
Запуск: python -m pytest tests/test_n438_dossier_photos.py -v
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("API_SECRET", "test-secret-123")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "tg-wh-secret")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("OWNER_TELEGRAM_ID", "555000")
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n438-test")
os.environ.setdefault("ZAI_API_KEY", "fake-key")

from proxy import shop_collectors as sc  # noqa: E402

COLLECTORS = (REPO_ROOT / "proxy" / "shop_collectors.py").read_text(encoding="utf-8")
TAIL = (REPO_ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")
DOSSIER = (REPO_ROOT / "proxy" / "shop_dossier.py").read_text(encoding="utf-8")

HEADER = "https://imgproxy.onliner.by/w:170/h:250/z:2/f:jpg/abc123"


# ── A.1: кнопки убраны ────────────────────────────────────────────────────


def test_reply_markup_not_passed_anywhere():
    # ни одного места передачи reply_markup с досье в двух точках отправки
    assert "reply_markup=markup" not in TAIL
    assert '"reply_markup": build_inline_buttons' not in TAIL
    assert "build_inline_buttons(snapshot)," not in TAIL


def test_build_inline_buttons_is_guard_stub():
    assert "raise NotImplementedError" in DOSSIER
    assert "#438" in DOSSIER


def test_endpoint_dossier_json_has_no_reply_markup_key():
    # ключ полностью убран из ответа /shop/dossier
    assert '"reply_markup"' not in TAIL


# ── A.2: image_url у Onliner ──────────────────────────────────────────────


def _stub_onliner(monkeypatch, snapshot):
    monkeypatch.setattr(
        sc, "FETCH_JSON_FN",
        lambda tool, args: {"ok": True, "data": snapshot})
    # живой словарь схем: iron подтверждён живым запросом 2026-09-30
    monkeypatch.setattr(
        sc, "_onliner_schemas_cache_read",
        lambda: {"schemas": [{"key": "iron", "name": "Утюги"}],
                 "complete": True, "ts": __import__("time").time(),
                 "next_page": 2})
    monkeypatch.setattr(sc, "_setting_set", lambda k, v: None)


def test_collect_onliner_image_url_from_header(monkeypatch):
    snap = {"products": [{
        "key": "fv8042e0", "full_name": "Tefal Puregliss FV8042E0",
        "html_url": "https://catalog.onliner.by/fv8042e0",
        "prices": {"price_min": {"amount": 142.0, "currency": "BYN"},
                   "offers": {"count": 3}},
        "reviews": {"rating": 48, "count": 12},
        "images": {"header": HEADER},
    }]}
    _stub_onliner(monkeypatch, snap)
    res = sc.collect_onliner("утюг tefal")
    assert res["ok"] is True
    assert res["offers"][0]["image_url"] == HEADER, res["offers"][0]


def test_collect_onliner_without_images_none(monkeypatch):
    # нет photos — нет фото: None, URL не выдумываем
    snap = {"products": [{
        "key": "fv8042e0", "full_name": "Tefal FV8042E0",
        "html_url": "https://catalog.onliner.by/fv8042e0",
        "prices": {"price_min": {"amount": 142.0, "currency": "BYN"},
                   "offers": {"count": 3}},
        "reviews": {"rating": 48, "count": 12},
    }]}
    _stub_onliner(monkeypatch, snap)
    res = sc.collect_onliner("утюг tefal")
    assert res["offers"][0]["image_url"] is None


def test_collect_onliner_non_http_header_rejected(monkeypatch):
    # мусор в header (не URL) — не превращается в image_url
    snap = {"products": [{
        "key": "k1", "full_name": "Tefal FV1",
        "html_url": "https://catalog.onliner.by/k1",
        "prices": {"price_min": {"amount": 100.0, "currency": "BYN"},
                   "offers": {"count": 1}},
        "reviews": {},
        "images": {"header": "javascript:alert(1)"},
    }]}
    _stub_onliner(monkeypatch, snap)
    res = sc.collect_onliner("утюг")
    assert res["offers"][0]["image_url"] is None


# ── A.3: фото лучшего предложения — картиной сообщения ────────────────────


def test_fetch_offer_image_downloads(tmp_path, monkeypatch):
    import requests as rq

    class Raw:
        def read(self, n, decode_content=True):
            return b"\xff\xd8\xff\xe0fakejpeg"

    class Resp:
        status_code = 200
        raw = Raw()

    monkeypatch.setattr(rq, "get", lambda url, **kw: Resp())
    out = tmp_path / "img.bin"
    assert sc.__name__ == "proxy.shop_collectors"  # sanity импорта
    from proxy.routes_tail import _shop_fetch_offer_image
    assert _shop_fetch_offer_image(HEADER, str(out)) is True
    assert out.read_bytes() == b"\xff\xd8\xff\xe0fakejpeg"


def test_fetch_offer_image_rejects_non_http(tmp_path):
    from proxy.routes_tail import _shop_fetch_offer_image
    assert _shop_fetch_offer_image("javascript:alert(1)",
                                   str(tmp_path / "x.bin")) is False


def test_fetch_offer_image_false_on_network_error(tmp_path, monkeypatch):
    import requests as rq

    def boom(url, **kw):
        raise ConnectionError("нет сети")

    monkeypatch.setattr(rq, "get", boom)
    from proxy.routes_tail import _shop_fetch_offer_image
    assert _shop_fetch_offer_image(HEADER, str(tmp_path / "y.bin")) is False


def test_send_dossier_falls_back_to_poster(tmp_path, monkeypatch):
    """Нет фото → постер PNG отправляется как раньше (запасной вариант)."""
    import json as _json

    snapshot = {
        "product": {"id": 42, "title": "Тестовый товар"},
        "profile": "default",
        "target_price_byn": None,
        "verdict": {"score": 50, "text": "ок", "best_offer_id": None},
        "badges": {},
        "offers": [],
        "unscored": [], "unscored_total": 0, "unscored_offers": [],
        "history_best": [], "median_best": None,
        "sources_display": [],
        "generated_at": "2026-09-30 12:00 UTC",
    }
    sent = {}

    def fake_photo(chat_id, path, caption=None, parse_mode=None, reply_markup=None):
        sent.update({"chat_id": chat_id, "path": path, "caption": caption,
                     "parse_mode": parse_mode, "reply_markup": reply_markup})
        return 1

    monkeypatch.setattr("proxy.telegram._tg_send_photo", fake_photo)
    from proxy import routes_tail as rt
    assert rt._shop_send_dossier(snapshot, "555000") is True
    assert sent["path"].endswith("shop-poster-42.png")
    assert sent["reply_markup"] is None  # #438 A.1: кнопок нет


# ── A.4: правило для будущих сборщиков ────────────────────────────────────


def test_image_url_rule_documented():
    assert "image_url — обязательное поле оффера" in COLLECTORS
    assert "ЕСЛИ площадка отдаёт фото" in COLLECTORS
