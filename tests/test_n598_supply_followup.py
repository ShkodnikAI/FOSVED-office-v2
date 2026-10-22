#!/usr/bin/env python3
"""Наряд #598: снабженец — возможности, связь, «Досье обновлено».

Приёмка по разделам наряда:
- A.1: /supply/next при валидном токене пишет supply_platforms
  (из X-Supply-Platforms) и supply_last_seen в system_settings; без
  заголовка — фолбэк env SUPPLY_AGENT_COLLECTORS, дефолт 7745 (работа
  со старым снабженцем); очередь ставится только площадкам из
  интерсекции SUPPLY_AGENT_PLATFORMS ∩ supply_platforms, остальные —
  collector_not_ready без задания;
- A.2: supply_pending в досье — живой статус связи: «передано снабженцу…»
  при контакте ≤5 мин, «снабженец недоступен с <время МСК>» — старше;
- A.3: закрытие волны (apply_supply_result / expire_stale_tasks) → РОВНО
  одно сообщение владельцу «Досье обновлено» (исход по каждой площадке +
  ссылка на пересобранное досье); защита от дублей — флаг в БД; ночь
  00:00–06:59 МСК → owner_outbox; пересбор досье БЕЗ повторного сбора.

Сеть и Telegram не трогаются: collect() подменён, _tg_send_message
записан в список-рекордер.
"""
import json
import os
import re
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
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n598-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy import shop_collectors as sc  # noqa: E402
from proxy import shop_dossier as sd  # noqa: E402
from proxy import shop_supply as sup  # noqa: E402
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app
from proxy.core import DB_FILE, _query, app  # noqa: E402

TOKEN = "supply-test-token-abc123"
HDR = {"Authorization": f"Bearer {TOKEN}"}

KV_KEYS = ("supply_platforms", "supply_last_seen")
CLEAN_TABLES = ("shop_price_history", "shop_offers", "shop_sellers",
                "shop_products", "shop_watches", "shop_supply_queue",
                "shop_supply_waves", "shop_dossiers", "owner_outbox")


def _shop_ddl():
    """CREATE + идемпотентные ALTER shop_* — ровно как исполняет офис."""
    ddl = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    creates = re.findall(r'db_execute\("(CREATE (?:TABLE|INDEX)[^"]+)"\)', ddl)
    alters = re.findall(r'try db_execute\("(ALTER TABLE shop_[^"]+)"\)', ddl)
    return [s for s in creates if "shop_" in s] + alters


@pytest.fixture(autouse=True)
def shop_db(monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_FX_RATES_JSON", "{}")
    monkeypatch.setenv("SUPPLY_AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "555000")
    monkeypatch.delenv("SUPPLY_TASK_TIMEOUT_S", raising=False)
    monkeypatch.delenv("SUPPLY_AGENT_COLLECTORS", raising=False)
    # Урок волны #598: в общей батарейной БД _query читает core.DB_FILE
    # (кэш первого импорта proxy.core), а не os.environ["DATABASE_PATH"]
    # на момент фикстуры — чужие модули жёстко переназначают env. DDL
    # идёт ровно туда, куда смотрит _query, иначе «no such column».
    # Оздоровление: чужие фикстуры (forge_ui9) создают УРЕЗАННЫЕ shop_*
    # в этой же общей БД — дроп и полная схема app.mlog (полная ⊇ любой
    # урезанной; строки каждая фикстура и так чистит).
    conn = sqlite3.connect(DB_FILE)
    for stmt in _shop_ddl():
        m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", stmt)
        if m:
            conn.execute(f"DROP TABLE IF EXISTS {m.group(1)}")
    for stmt in _shop_ddl():
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    conn.commit()
    conn.close()
    sup.ensure_schema()
    for t in CLEAN_TABLES:
        _query(f"DELETE FROM {t}")
    _query("DELETE FROM system_settings WHERE key IN (?, ?)", KV_KEYS)
    # сбор по неснабженческим площадкам — честная заглушка-отказ (сеть не трогается)
    def fake_collect(platform, query, **kw):
        return {"ok": False, "platform": platform,
                "error": "тестовая заглушка", "kind": "test_stub"}
    monkeypatch.setattr(sc, "collect", fake_collect)
    yield
    for t in CLEAN_TABLES:
        _query(f"DELETE FROM {t}")
    _query("DELETE FROM system_settings WHERE key IN (?, ?)", KV_KEYS)


@pytest.fixture()
def client():
    return app.test_client()


@pytest.fixture()
def tg_sent(monkeypatch):
    """Рекордер вместо Telegram-транспорта."""
    sent = []
    monkeypatch.setattr("proxy.telegram._tg_send_message",
                        lambda chat_id, text, **kw: sent.append((chat_id, text)) or 42)
    return sent


def _set_platforms(csv):
    _query("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
           ("supply_platforms", csv))


def _set_last_seen(sql_age):
    _query("INSERT OR REPLACE INTO system_settings (key, value) "
           "VALUES (?, datetime('now', ?))", ("supply_last_seen", sql_age))


def _product(title="Алюминиевая лопата для снега"):
    _query("INSERT INTO shop_products (title, query_text) VALUES (?, ?)",
           (title, "лопата для снега"))
    return _query("SELECT id FROM shop_products ORDER BY id DESC LIMIT 1",
                  fetch=True)[0]["id"]


def _wave_id(task_id):
    row = _query("SELECT wave_id FROM shop_supply_queue WHERE task_id=?",
                 (task_id,), fetch=True)
    return row[0]["wave_id"] if row else None


def _notified(wave_id):
    row = _query("SELECT notified FROM shop_supply_waves WHERE wave_id=?",
                 (wave_id,), fetch=True)
    return bool(row and row[0]["notified"])


# ── A.1: возможности снабженца ────────────────────────────────────────────

def test_next_touch_saves_platforms_and_last_seen(client):
    """Валидный опрос с X-Supply-Platforms → оба ключа в system_settings."""
    r = client.get("/supply/next", headers={**HDR,
                   "X-Supply-Platforms": "7745, Ozon ,7745"})
    assert r.status_code == 200
    plats = _query("SELECT value FROM system_settings WHERE key='supply_platforms'",
                   fetch=True)[0]["value"]
    assert plats == "7745,ozon"  # нормализация: trim/lower, без дублей
    seen = _query("SELECT value FROM system_settings WHERE key='supply_last_seen'",
                  fetch=True)
    assert seen and seen[0]["value"]


def test_next_touch_without_header_keeps_env_fallback(client, monkeypatch):
    """Старый снабженец без заголовка: supply_last_seen пишется, платформы
    в БД НЕ затираются; резолв — env SUPPLY_AGENT_COLLECTORS."""
    _set_platforms("")  # ключа в БД нет
    _query("DELETE FROM system_settings WHERE key='supply_platforms'")
    monkeypatch.setenv("SUPPLY_AGENT_COLLECTORS", "7745,tomas")
    r = client.get("/supply/next", headers=HDR)
    assert r.status_code == 200
    row = _query("SELECT value FROM system_settings WHERE key='supply_platforms'",
                 fetch=True)
    assert not row  # заголовка не было — БД не тронута
    assert sup.resolve_supplier_platforms() == frozenset({"7745", "tomas"})
    assert _query("SELECT value FROM system_settings WHERE key='supply_last_seen'",
                  fetch=True)


def test_platforms_fallback_default_7745(monkeypatch):
    """Ни БД, ни env → дефолт 7745 (наряд A.1)."""
    monkeypatch.delenv("SUPPLY_AGENT_COLLECTORS", raising=False)
    assert sup.resolve_supplier_platforms() == frozenset({"7745"})


def test_refresh_queues_only_intersection(monkeypatch):
    """A.1: 7745 (в supply_platforms) → supply_pending + pending-задание;
    ozon (снабженческая, но не в supply_platforms) → collector_not_ready,
    задания в очереди НЕТ."""
    _set_platforms("7745")
    pid = _product()
    res_ok = sc.refresh_product(pid, "7745", "лопата")
    assert res_ok["kind"] == "supply_pending"
    res_no = sc.refresh_product(pid, "ozon", "лопата")
    assert res_no["ok"] is False
    assert res_no["kind"] == "collector_not_ready"
    assert res_no["error"] is None  # текст даёт метка в досье, без дублей
    rows = _query("SELECT platform, status FROM shop_supply_queue",
                  fetch=True)
    assert [dict(r) for r in rows] == [{"platform": "7745", "status": "pending"}]


def test_collector_not_ready_label():
    """Честная метка в досье для несобираемых снабженцем площадок."""
    assert sd.humanize_source_status(
        {"ok": False, "kind": "collector_not_ready", "error": None}) == \
        "сбор по этой площадке ещё не реализован"


# ── A.2: живой статус связи со снабженцем ─────────────────────────────────

def test_connection_status_no_contact():
    """Связи не было вовсе — честный статус, не «ждёт выполнения»."""
    text = sd.humanize_source_status({"ok": False, "kind": "supply_pending"})
    assert "недоступен" in text and "ждёт его" in text


def test_connection_status_fresh():
    """Контакт ≤5 минут → «передано снабженцу (домашний сервер)…»."""
    _set_last_seen("-0 minutes")
    text = sd.humanize_source_status({"ok": False, "kind": "supply_pending"})
    assert text == "передано снабженцу (домашний сервер), результат придёт отдельно"


def test_connection_status_stale():
    """Контакт старше 5 минут → «снабженец недоступен с <дата> МСК…»."""
    _set_last_seen("-15 minutes")
    text = sd.humanize_source_status({"ok": False, "kind": "supply_pending"})
    assert text.startswith("снабженец недоступен с ")
    assert " МСК — задание ждёт его" in text


def test_next_poll_makes_status_fresh(client):
    """Реальный сценарий: опрос снабженца → статус «передано снабженцу…»."""
    client.get("/supply/next", headers=HDR)
    text = sd.humanize_source_status({"ok": False, "kind": "supply_pending"})
    assert text.startswith("передано снабженцу")


# ── A.3: «Досье обновлено» — одно сообщение на волну ──────────────────────

def test_wave_single_message(tg_sent):
    """Два задания одной волны: после первого — тишина; после второго —
    РОВНО одно сообщение (исходы обеих площадок + ссылка); повторный
    apply не дублирует; новая волна → своё сообщение."""
    _set_platforms("7745,tomas")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    t2 = sup.enqueue_supply_task(pid, "tomas", "лопата")
    assert _wave_id(t1) == _wave_id(t2)  # один такт — одна волна
    offer = {"platform_code": "7745-1", "url": "https://7745.by/x",
             "title": "Лопата", "price_byn": 25.9}
    sup.apply_supply_result(t1, {"ok": True, "offers": [offer]})
    assert tg_sent == []  # tomas ещё открыт — волна не закрыта
    sup.apply_supply_result(t2, {"ok": False, "kind": "antibot_blocked",
                                 "error": "капча"})
    assert len(tg_sent) == 1
    chat_id, text = tg_sent[0]
    assert chat_id == "555000"
    assert "📦 Досье обновлено" in text
    assert "7745: 1 предложение" in text
    assert "tomas: отказ снабженца — antibot_blocked: капча" in text
    assert "Полное досье: " in text
    assert _notified(_wave_id(t1))
    # дубль-защита: повторная попытка по закрытому заданию не шлёт
    sup.apply_supply_result(t1, {"ok": True, "offers": [offer]})
    assert len(tg_sent) == 1
    # новая волна (такт вотча) → своё сообщение
    t3 = sup.enqueue_supply_task(pid, "7745", "лопата")
    assert _wave_id(t3) != _wave_id(t1)
    sup.apply_supply_result(t3, {"ok": True, "offers": [offer]})
    assert len(tg_sent) == 2


def test_wave_notify_after_expire(tg_sent):
    """Протухло последнее задание волны → то же сообщение с честным
    «задание протухло без результата» (наряд A.3: и после expire)."""
    _set_platforms("7745")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    _query("UPDATE shop_supply_queue SET created_at=datetime('now','-2000 seconds') "
           "WHERE task_id=?", (t1,))
    sup.expire_stale_tasks()
    status = _query("SELECT status, kind FROM shop_supply_queue WHERE task_id=?",
                    (t1,), fetch=True)[0]
    assert dict(status) == {"status": "failed", "kind": "task_timeout"}
    assert len(tg_sent) == 1
    assert "задание протухло без результата" in tg_sent[0][1]
    assert _notified(_wave_id(t1))


def test_night_goes_to_outbox(tg_sent, monkeypatch):
    """Ночь 00:00–06:59 МСК → owner_outbox (source='shop-supply'), не Telegram."""
    monkeypatch.setattr(sup, "_is_supply_night_msk", lambda now=None: True)
    _set_platforms("7745")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    sup.apply_supply_result(t1, {"ok": True, "offers": []})
    assert tg_sent == []
    row = _query("SELECT source, text FROM owner_outbox ORDER BY id DESC LIMIT 1",
                 fetch=True)[0]
    assert row["source"] == "shop-supply"
    assert "📦 Досье обновлено" in row["text"]


def test_day_sends_telegram(tg_sent, monkeypatch):
    """День (12:00 МСК) → Telegram напрямую, outbox пуст."""
    monkeypatch.setattr(sup, "_is_supply_night_msk", lambda now=None: False)
    _set_platforms("7745")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    sup.apply_supply_result(t1, {"ok": True, "offers": []})
    assert len(tg_sent) == 1
    assert _query("SELECT COUNT(*) c FROM owner_outbox",
                  fetch=True)[0]["c"] == 0


def test_rebuild_without_recollection(tg_sent, monkeypatch):
    """Пересбор досье НЕ дёргает сбор: collect() под миной — сообщение
    всё равно ушло тем же build_snapshot, что и /shop/product."""
    def bomb(platform, query, **kw):
        raise AssertionError("повторный сбор при пересборке досье запрещён")
    monkeypatch.setattr(sc, "collect", bomb)
    _set_platforms("7745")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    sup.apply_supply_result(t1, {"ok": True, "offers": []})
    assert len(tg_sent) == 1
    assert "Полное досье: " in tg_sent[0][1]


def test_owner_id_missing_is_honest(tg_sent, monkeypatch):
    """Адресат не задан → без падения, флаг волны стоит, в лог — warning."""
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    _set_platforms("7745")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    sup.apply_supply_result(t1, {"ok": True, "offers": []})  # не роняет
    assert tg_sent == []
    assert _notified(_wave_id(t1))


def test_dossier_snapshot_written(tg_sent):
    """Пересобранное досье сохранено в shop_dossiers (ссылка ведёт на свежий срез)."""
    _set_platforms("7745")
    pid = _product()
    t1 = sup.enqueue_supply_task(pid, "7745", "лопата")
    sup.apply_supply_result(t1, {"ok": True, "offers": []})
    row = _query("SELECT COUNT(*) c FROM shop_dossiers WHERE product_id=?",
                 (pid,), fetch=True)[0]
    assert row["c"] >= 1
