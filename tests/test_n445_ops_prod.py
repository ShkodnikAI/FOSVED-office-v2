#!/usr/bin/env python3
"""Наряд #445 [P1][OPS] — тест-барьер эксплуатации прода.

Класс бага (аудит 2026-09-30): Flask dev-сервер в проде (Werkzeug),
полумёртвый контейнер (wait всех процессов без супервизии), один общий
rate-limit на всех клиентов (peer 127.0.0.1 как ключ), нет HEALTHCHECK.

Пять уровней защиты:
  1. WSGI: оба приложения стартуют через waitress.serve — app.run запрещён.
  2. Супервизия: entrypoint завершает контейнер при смерти критичного
     процесса (wait -n), tg-monitor некритичен.
  3. Rate-limit по клиенту: METALOGOS_TRUSTED_PROXIES=127.0.0.1 exported,
     reverse_proxy ПЕРЕЗАПИСЫВАЕТ XFF (контракт №263, не append).
  4. Dockerfile HEALTHCHECK на /health (через reverse_proxy → mlog).
  5. waitress объявлен в requirements.txt (иначе прод-билд молча везёт
     dev-сервер — ImportError падает только на буте).
"""
import ast
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '555000')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n445-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

import reverse_proxy  # noqa: E402

ENTRYPOINT = (REPO_ROOT / "entrypoint.sh").read_text()
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text()
REQUIREMENTS = (REPO_ROOT / "requirements.txt").read_text()

RP_SRC = (REPO_ROOT / "reverse_proxy.py").read_text()
LLM_SRC = (REPO_ROOT / "llm_proxy.py").read_text()


# ── 1. WSGI: waitress вместо dev-сервера ────────────────────────────────────

def test_waitress_serve_in_both_apps():
    for name, src in (("reverse_proxy.py", RP_SRC), ("llm_proxy.py", LLM_SRC)):
        assert "from waitress import serve" in src, f"{name}: waitress не импортирован"
        assert "serve(" in src, f"{name}: waitress.serve не вызван"


def test_no_werkzeug_dev_server_left():
    """app.run(...) — только под dev; в __main__ обоих приложений его быть
    не должно вовсе (это и был факт аудита: «development server» в бут-логе)."""
    for name, src in (("reverse_proxy.py", RP_SRC), ("llm_proxy.py", LLM_SRC)):
        assert "app.run(" not in src, f"{name}: dev-сервер app.run остался в __main__"


def test_waitress_channel_timeout_covers_long_llm():
    """Upstream timeout прокси 300 с; канальный таймаут waitress должен
    его покрывать, иначе долгие LLM-ответы рвутся в середине."""
    for name, src in (("reverse_proxy.py", RP_SRC), ("llm_proxy.py", LLM_SRC)):
        assert "channel_timeout=360" in src, (
            f"{name}: channel_timeout=360 отсутствует — долгие LLM-запросы порвутся"
        )


def test_waitress_reverse_proxy_trusts_edge_xff():
    """waitress по умолчанию срезает XFF (clear_untrusted_proxy_headers=True)
    — тогда прокси видит только peer и перезаписывает XFF самим peer'ом:
    ВСЕ клиенты делят один rate-limit ключ (живой инцидент смока #445:
    e2e burst давал 429 другому клиенту). reverse_proxy обязан доверять
    входящим прокси-заголовкам и перезаписывать XFF по контракту №263."""
    assert "trusted_proxy" in RP_SRC, (
        "reverse_proxy: waitress срезает XFF от edge — лимит снова общий"
    )
    assert "trusted_proxy_headers" in RP_SRC, (
        "reverse_proxy: не указано, каким прокси-заголовкам доверять"
    )


def test_waitress_declared_in_requirements():
    assert "waitress>=" in REQUIREMENTS, "waitress не объявлен в requirements.txt"


# ── 2. Супервизия в entrypoint.sh ───────────────────────────────────────────

def test_entrypoint_supervises_critical_processes():
    assert "wait -n $LLM_PID $MLOG_PID $PROXY_PID" in ENTRYPOINT, (
        "entrypoint: wait -n по критичным процессам отсутствует"
    )
    assert "exit \"${SUP_EXIT:-1}\"" in ENTRYPOINT, (
        "entrypoint: ненулевой exit при смерти критичного процесса отсутствует"
    )
    assert "kill $LLM_PID $MLOG_PID $PROXY_PID" in ENTRYPOINT, (
        "entrypoint: добивание остальных критичных процессов отсутствует"
    )


def test_entrypoint_old_wait_all_removed():
    """Старый wait ждал ВСЕХ: падение mlog не завершало контейнер — Render
    считал сервис живым, офис полумёртв (факт аудита). Регресс запрещён."""
    assert "wait $LLM_PID $MLOG_PID $PROXY_PID $TG_MONITOR_PID" not in ENTRYPOINT


def test_entrypoint_tg_monitor_not_supervised():
    """tg-monitor НЕ критичен (kill-switch TG_MONITOR_ENABLED) — его смерть
    офис не роняет: он не в wait -n списке и не в kill списке супервизора."""
    superv_wait = ENTRYPOINT[ENTRYPOINT.index("wait -n $LLM_PID"):]
    assert "TG_MONITOR_PID" not in superv_wait.split("wait -n")[1].split("\n")[0]


# ── 3. Rate-limit по реальному клиенту ──────────────────────────────────────

def test_entrypoint_exports_trusted_proxies():
    assert 'METALOGOS_TRUSTED_PROXIES="${METALOGOS_TRUSTED_PROXIES:-127.0.0.1}"' in ENTRYPOINT


def test_client_ip_leftmost_xff_wins():
    """Контракт №263 (REFERENCE §5.6): ключ лимита — leftmost XFF."""
    with reverse_proxy.app.test_request_context(
        "/", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    ):
        assert reverse_proxy._client_ip() == "203.0.113.7"


def test_client_ip_falls_back_to_peer():
    with reverse_proxy.app.test_request_context(
        "/", headers={"X-Forwarded-For": "   "}
    ):
        assert reverse_proxy._client_ip() == "unknown"
    with reverse_proxy.app.test_request_context("/"):
        assert reverse_proxy._client_ip() == "unknown"
    with reverse_proxy.app.test_request_context(
        "/", environ_base={"REMOTE_ADDR": "127.0.0.1"}
    ):
        assert reverse_proxy._client_ip() == "127.0.0.1"


def test_upstream_headers_overwrite_xff():
    """Прокси ОБЯЗАН перезаписывать XFF клиентским адресом (не append):
    иначе клиент подделывает чужой лимит-ключ через дописывание в цепочку."""
    with reverse_proxy.app.test_request_context(
        "/health",
        headers={"Host": "office.example.com",
                 "X-Forwarded-For": "203.0.113.7, 10.0.0.1",
                 "X-Real-IP": "1.2.3.4"},
    ):
        headers = reverse_proxy._upstream_headers()
    assert headers["X-Forwarded-For"] == "203.0.113.7"
    assert headers["X-Real-IP"] == "203.0.113.7"
    assert "host" not in {k.lower() for k in headers}


def test_upstream_headers_uses_peer_when_no_xff():
    with reverse_proxy.app.test_request_context(
        "/health", environ_base={"REMOTE_ADDR": "198.51.100.9"}
    ):
        headers = reverse_proxy._upstream_headers()
    assert headers["X-Forwarded-For"] == "198.51.100.9"


def test_upstream_headers_used_at_both_forward_sites():
    """Оба места форварда (preview-live и общий прокси) обязаны идти через
    _upstream_headers() — иначе сайт без перезаписи XFF снова даёт один
    лимит-ключ на всех."""
    assert RP_SRC.count("headers = _upstream_headers()") >= 2, (
        "не оба места форварда используют _upstream_headers()"
    )
    assert 'k.lower() != "host"}' not in RP_SRC, (
        "осталось место ручной сборки заголовков без перезаписи XFF"
    )


# ── 4. HEALTHCHECK ──────────────────────────────────────────────────────────

def test_dockerfile_healthcheck_on_health_route():
    assert "HEALTHCHECK" in DOCKERFILE, "HEALTHCHECK отсутствует в Dockerfile"
    hc_block = DOCKERFILE[DOCKERFILE.index("HEALTHCHECK"):].split("CMD")
    assert len(hc_block) >= 2 and "curl" in hc_block[1], (
        "HEALTHCHECK CMD должен вызывать curl"
    )
    assert "/health" in hc_block[1], "HEALTHCHECK должен бить в /health"
    assert "start-period" in DOCKERFILE, (
        "бут офиса долгий (skills bootstrap, backup, mlog serve) — нужен start-period"
    )
