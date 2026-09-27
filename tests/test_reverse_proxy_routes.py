#!/usr/bin/env python3
"""Горячий фикс #172: рассинхрон reverse_proxy ↔ роуты LLM Proxy.

Класс бага FO-042 (молчаливый 404 cron'а) повторился на SHOP: роут
зарегистрирован на Flask (порт 4000), но префикса нет в LLM_ROUTES_PREFIXES
reverse_proxy.py → путь по умолчанию уходит в Metalogos → 404 на публичном
порту. CI это не видит, видит только живой деплой (Render-cron логал
"shop-tick failed").

Три уровня защиты:
  1. Каждый крон render.yaml покрыт префиксом LLM_ROUTES_PREFIXES.
  2. Каждый Flask-роут /cron/ /scheduler/ /shop/ либо публично
     маршрутизирован, либо осознанно внутренний (KNOWN_INTERNAL с мотивом).
  3. POST-роуты /shop/* (без auth, зовёт только mlog на 127.0.0.1:4000)
     НЕ должны стать публичными — защита от «наоборот открыли лишнее».
"""
import ast
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-shop-routes-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from proxy.core import app  # noqa: E402 — app захватываем при импорте
# (после importlib.reload(proxy.core) в test_security from-import внутри
# теста вернул бы новый Flask-объект; привязка к импорту файла спасает)
import llm_proxy  # noqa: E402,F401 — регистрация роутов routes_tail на app

# Осознанно внутренние роуты (зовутся только mlog'ом напрямую на 4000).
# Каждая строка — с мотивом; добавлять сюда новый путь = писать почему.
KNOWN_INTERNAL = {
    # SHOP-5 (#172): команды /товар /вотч /вотч-лист — mlog webhook дергает
    # POST напрямую на 127.0.0.1:4000; auth нет, публично нельзя.
    "/shop/product",
    "/shop/watch",
    "/shop/watches",
    "/shop/dossier",   # POST json-досье; GET-версия "/shop/dossier/<id>" публична по HMAC
    # FO-042 B (#149): выгрузка FORGE — в коде задокументировано
    # «публично недостижим»; защита CRON_SECRET, но наружу не светим.
    "/forge/export-state",
}


def _proxy_list(name):
    """Список-литерал из reverse_proxy.py через ast (импорт тянет requests
    и создаёт второй Flask-app; литералы чисто взять из AST)."""
    src = (REPO_ROOT / "reverse_proxy.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            return [e.value for e in node.value.elts
                    if isinstance(e, ast.Constant)]
    pytest.fail(f"{name} не найден в reverse_proxy.py")


def _covered(path, prefixes):
    return any(path == pre or path.startswith(pre) for pre in prefixes)


def _render_cron_paths():
    """Все крон-пути render.yaml (то, что реально дёргает Render по HTTPS)."""
    text = (REPO_ROOT / "render.yaml").read_text()
    return sorted(set(re.findall(r"https://[\w.-]+(/[\w/-]+)\?", text)))


# ── 1. render.yaml ↔ префиксы ────────────────────────────────────────────
def test_render_yaml_crons_routed_to_flask():
    prefixes = _proxy_list("LLM_ROUTES_PREFIXES")
    missing = [p for p in _render_cron_paths() if not _covered(p, prefixes)]
    assert not missing, (
        f"render.yaml кронит пути без префикса в LLM_ROUTES_PREFIXES: "
        f"{missing} — путь уйдёт в mlog и молча 404 (класс FO-042). "
        f"Добавь префикс(ы) в reverse_proxy.py")


# ── 2. Flask-роуты cron/scheduler/shop ↔ префиксы ────────────────────────
def test_flask_cron_scheduler_shop_routes_routed():
    llm = _proxy_list("LLM_ROUTES_PREFIXES")
    internal = _proxy_list("INTERNAL_ONLY_PREFIXES")  # SEC-1 гейт: 404 наружу, зовёт mlog
    rules = {r.rule for r in app.url_map.iter_rules()
             if r.endpoint != "static"}
    # "/metrics/" — с 2026-09-27: класс FO-042 повторился на /metrics/activity
    # (FO-053 смёржнут, а фронт-дверь забыли — прод отвечал 404). Все будущие
    # /metrics/*-роуты обязаны быть явно маршрутизированы или явно внутренние.
    unrouted = [r for r in sorted(rules)
                if r.startswith(("/cron/", "/scheduler/", "/shop/", "/metrics/"))
                and not _covered(r, llm)
                and not _covered(r, internal)
                and r not in KNOWN_INTERNAL]
    assert not unrouted, (
        f"Flask-роуты без маршрутизации с публичного порта: {unrouted}. "
        f"Либо добавь префикс в LLM_ROUTES_PREFIXES (если путь должен быть "
        f"публичным), либо в INTERNAL_ONLY_PREFIXES (если зовёт только mlog), "
        f"либо в KNOWN_INTERNAL этого файла с мотивом")


# ── 3. HTML-досье публично (клик из inline-кнопки) ───────────────────────
def test_shop_dossier_page_is_public():
    prefixes = _proxy_list("LLM_ROUTES_PREFIXES")
    assert _covered("/shop/dossier/1", prefixes), (
        "GET /shop/dossier/<id> — клик владельца по inline-кнопке "
        "(RENDER_EXTERNAL_URL) — должен маршрутизироваться в LLM Proxy; "
        "защита — HMAC-токен ?t= в самом роуте")


# ── 4. POST /shop/* не публичны (нет auth, зовёт только mlog) ────────────
@pytest.mark.parametrize("path", ["/shop/product", "/shop/watch",
                                  "/shop/watches", "/shop/dossier"])
def test_shop_post_endpoints_stay_internal(path):
    assert not _covered(path, _proxy_list("LLM_ROUTES_PREFIXES")), (
        f"{path} не должен быть публично маршрутизирован: у роута нет auth, "
        f"его дёргает только mlog webhook напрямую на 127.0.0.1:4000")


# ── 4b. FO-053: фид счётчиков маршрутизирован наружу (класс FO-042) ──────
def test_metrics_activity_is_publicly_routed():
    """GET /metrics/activity (FO-053, office#325) — фид owner_activity для
    FO-052 ступени 1: VM-экспортёр опрашивает его через публичный порт,
    auth (ACTIVITY_FEED_TOKEN, fail-closed) несёт сам роут на 4000.
    2026-09-27: префикса не было → прод отвечал 404 на мёржнутый эндпоинт
    (путь проваливался в default → mlog); тесты ловить не могли — гоняли
    4000 напрямую, минуя reverse_proxy."""
    prefixes = _proxy_list("LLM_ROUTES_PREFIXES")
    assert _covered("/metrics/activity", prefixes), (
        "GET /metrics/activity должен маршрутизироваться в LLM Proxy "
        "(фид owner_activity, FO-052); auth — токен в самом роуте")
    assert not _covered("/metrics/activity", _proxy_list("INTERNAL_ONLY_PREFIXES")), (
        "/metrics/activity не должен попасть в INTERNAL_ONLY: "
        "фид по дизайну опрашивается снаружи (VM исполнителя)")


# ── 5. Flask-приложение реально владеет роутами SHOP (ловит переименование)
@pytest.mark.parametrize("path", ["/cron/shop-tick", "/shop/product",
                                  "/shop/watch", "/shop/watches",
                                  "/shop/dossier",
                                  "/shop/dossier/<int:dossier_id>"])
def test_flask_app_owns_shop_routes(path):
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert path in rules, f"роут {path} пропал из Flask url_map"
