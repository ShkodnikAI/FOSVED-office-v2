#!/usr/bin/env python3
"""SHOP-3 батч-2 (наряды #335/#337/#338/#339): честные каркасы площадок
подменой транспорта; №715 KEYS-2 (12.11): ym удалён решением владельца.

Разведка 2026-09-24 (докстринг shop_collectors — источник правды):
  - 7745/shopby — recon_unreachable (GeoIP-блок 403 датацентровых IP,
    у 7745 robots/sitemap живы — статика отдаётся, динамика нет);
  - tomas/unishop — robots_disallow_surface (поисковая поверхность
    закрыта для честных клиентов; у unishop дополнительно reagate-капча);
  - ym — УДАЛЁН 12.11 решением владельца (№715 KEYS-2 по #708):
    сборщик контентного API и его тесты убраны, история в БД сохранена.

Транспорт подменяется через sc.FETCH_JSON_FN — никакой сети в тестах.
FX зажат через SHOP_FX_RATES_JSON (первый приоритет fx_rates).
"""
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop5-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import _query  # noqa: E402
from proxy import shop_collectors as sc  # noqa: E402
from proxy import shop_watch as sw  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_kv():
    _query("CREATE TABLE IF NOT EXISTS system_settings "
           "(key TEXT PRIMARY KEY, value TEXT)")
    yield


# ── 1. Честные каркасы: kind/платформа/текст ────────────────────────────
@pytest.mark.parametrize("platform,kind", [
    ("7745", "recon_unreachable"),
    ("shopby", "recon_unreachable"),
    ("unishop", "antibot_blocked"),
])
def test_batch2_refusals_are_honest(platform, kind):
    r = sc.collect(platform, "смартфон")
    assert r["ok"] is False
    assert r["kind"] == kind
    assert r["platform"] == platform
    assert r["error"], "отказ обязан быть с текстом, не молчанкой"


# ── #406: tomas — живая попытка (стаб транспорта, без сети) ────────────
def test_tomas_live_attempt_captcha_is_honest(monkeypatch):
    """Антибот-стена «Проверка безопасности» → antibot_blocked с диагнозом."""
    def fake(tool, args):
        assert tool == "fetch_page" and "tomas.by/search/" in args["url"]
        return {"ok": True, "content": "<title>Проверка безопасности</title> recaptcha"}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    r = sc.collect_tomas("смартфон")
    assert r["ok"] is False and r["kind"] == "antibot_blocked"
    assert "антибот" in r["error"]


def test_tomas_parses_jsonld_products(monkeypatch):
    """Если egress не встречает антибот — витрина берётся из JSON-LD."""
    ld = ('<script type="application/ld+json">'
          '{"@type":"ItemList","itemListElement":[{"item":{"@type":"Product",'
          '"name":"Смартфон X","sku":"X100","offers":{"price":899.0,'
          '"priceCurrency":"BYN","url":"https://tomas.by/item/x100",'
          '"seller":{"name":"Магазин Плюс"}}}}]}</script>')
    def fake(tool, args):
        return {"ok": True, "content": ld}
    monkeypatch.setattr(sc, "FETCH_JSON_FN", fake)
    r = sc.collect_tomas("смартфон")
    assert r["ok"] is True and r["offers"]
    o = r["offers"][0]
    assert o["seller_name"] == "Магазин Плюс"  # продавец-участник, не «Tomas.by»
    assert o["price_byn"] == 899.0


def test_batch2_registered_in_collectors_and_mvp():
    for p in ("7745", "shopby", "tomas", "unishop"):
        assert p in sc.COLLECTORS, p
        assert p in sw.PLATFORMS_MVP, p
    # №715 KEYS-2: ym удалён решением владельца 12.11
    assert "ym" not in sc.COLLECTORS
    assert "ym" not in sw.PLATFORMS_MVP


def test_status_map_covers_batch2():
    from proxy import routes_admin as ra
    for p in ("7745", "shopby", "tomas", "unishop"):
        status = ra._SHOP_SOURCE_STATUS.get(p)
        assert status and status[0] and status[1] == "warn", p
    assert "ym" not in ra._SHOP_SOURCE_STATUS  # №715
