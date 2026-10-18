#!/usr/bin/env python3
"""Наряд #550 (P1): ночной цикл — отложенная доставка 07:15, токен /admin-ua,
indicators/evals на mlog-эндпоинты, ленты без языка не теряются.

Факты наряда (18.10, логи прода lf8cr):
- ночные сообщения уходили немедленно (night-tick 05:00) — владелец просил блок в 07:15;
- фазы 1a–6 AdminNightCycle били на /admin-ua/* без авторизации → 401 с июля;
- indicators/evals били на Flask :4000, где /cron/indicator-reminders и
  /cron/golden-evals НЕ существуют (это маршруты mlog :10001) → 404;
- collect_rss падал KeyError 'language' на лентах из БД → все записи ленты терялись.

ОТКЛОНЕНИЕ ОТ ТЕКСТА НАРЯДА (задокументировано, живая проба mlog 0.32.0 от 18.10):
наряд предлагал http_get(url, headers) — в 0.32.0 http_get принимает только
(url, timeout 1..300), исходящих заголовков нет, ключи объектов с дефисом
не парсятся. Канал — hash-токен itok в query (прецедент ReposAccessToken
#442), равнозначный по безопасности: сырой секрет не ходит, scope ":admin-ua".
"""
import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

# env ДО импорта llm_proxy — тот же набор, что tests/test_security.py
# (порядок импорта тестовых файлов не должен менять поведение).
os.environ["API_SECRET"] = "test-secret-123"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "tg-wh-secret"
os.environ["OWNER_TELEGRAM_ID"] = "12345"
os.environ["DATABASE_PATH"] = "/tmp/fosved-test-db"
os.environ["ZAI_API_KEY"] = "fake-key"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
SCHEDULES = (REPO_ROOT / "dept" / "schedules.mlog").read_text(encoding="utf-8")
NEWS_PY = (REPO_ROOT / "proxy" / "news.py").read_text(encoding="utf-8")
LZ_PY = (REPO_ROOT / "proxy" / "lz_github.py").read_text(encoding="utf-8")


def _code_lines(src: str) -> list:
    """Некомментарные строки (упоминания в комментариях не считаются)."""
    return [l for l in src.splitlines() if not l.strip().startswith("//")]


def _segment(src: str, pattern_decl: str) -> str:
    """Тело одного паттерна: от 'pattern NAME' до следующего 'pattern '."""
    start = src.index(pattern_decl)
    rest = src[start + len(pattern_decl):]
    nxt = rest.find("\npattern ")
    return rest[:nxt] if nxt != -1 else rest


# ── Статические гварды mlog-стороны ──────────────────────────────────────


class TestOutboxMlogGuards:
    """A.1: outbox-контур в dept/scheduler.mlog + реестре schedules."""

    def test_schedules_has_night_report_slot(self):
        seg = "\n".join(_code_lines(SCHEDULES))
        assert 'name: "night-report"' in seg, "запись night-report отсутствует в реестре"
        assert 'cron: "15 7 * * *"' in seg, "расписание night-report не 07:15"
        assert 'tz: "Europe/Moscow"' in seg
        assert 'target: "NightReportSlot"' in seg
        assert 'catch_up: "run_once"' in seg
        # включённость — прямое решение владельца в наряде
        rec = [l for l in seg.splitlines() if '"night-report"' in l][0]
        assert "enabled: true" in rec, "night-report должен быть enabled: true (наряд #550)"

    def test_outbox_patterns_exist(self):
        seg = "\n".join(_code_lines(SCHED))
        assert "pattern OutboxPut(" in seg
        assert "pattern OutboxFlush(" in seg
        assert "pattern NightReportSlot(" in seg
        assert 'INSERT INTO owner_outbox' in seg
        assert "UPDATE owner_outbox SET sent_at" in seg
        # дедуп повторного запуска — по дню отправки
        assert "date(sent_at) = date('now')" in seg, "нет дедупа по дню"
        # заголовок и разделы
        assert "🌙 Ночной отчёт" in seg

    def test_night_tick_no_immediate_send(self):
        """Итог night-tick уходит в outbox, не в Telegram."""
        seg = "\n".join(_code_lines(_segment(SCHED, "pattern NightTickSlot()")))
        assert "SendTelegramReply" not in seg, "NightTickSlot всё ещё шлёт немедленно"
        assert 'OutboxPut("night-tick"' in seg, "итог тика не пишется в outbox"

    def test_night_slot_no_immediate_send(self):
        """NightSlot: FO-027 и «Ночная проверка» — в outbox."""
        seg = "\n".join(_code_lines(_segment(APP, "pattern NightSlot()")))
        assert "SendTelegramReply" not in seg, "NightSlot шлёт немедленно"
        assert 'OutboxPut("fo027"' in seg, "FO-027-алерты не в outbox"
        assert 'OutboxPut("night"' in seg, "итог «Ночная проверка» не в outbox"

    def test_night_report_slot_delegates_to_flush(self):
        seg = "\n".join(_code_lines(_segment(SCHED, "pattern NightReportSlot()")))
        assert "OutboxFlush()" in seg
        assert "TryVal" in seg, "сбой flush не защищён TryVal"
        assert "cron_night_report" in seg, "нет audit-записи прогонов слота"


class TestAdminUaTokenGuards:
    """A.2: все вызовы /admin-ua/* — с внутренним hash-токеном."""

    def _mlog_admin_ua_calls(self):
        calls = []
        for src in (APP, ADMIN):
            for l in _code_lines(src):
                if "127.0.0.1:4000/admin-ua/" in l and ("http_get(" in l or "http_post(" in l):
                    calls.append(l.strip())
        return calls

    def test_all_admin_ua_calls_have_token(self):
        calls = self._mlog_admin_ua_calls()
        assert len(calls) >= 15, f"ожидались ночные + ручные вызовы admin-ua, найдено {len(calls)}"
        for l in calls:
            assert "itok=" in l or "AdminUaToken()" in l, f"вызов без токена: {l}"

    def test_admin_ua_token_pattern(self):
        seg = "\n".join(_code_lines(ADMIN))
        assert "pattern AdminUaToken()" in seg
        assert 'env("INTERNAL_API_TOKEN")' in seg
        # hash_only-мост, не raw
        assert 'hash_only' in seg.split("pattern AdminUaToken()")[1][:400]

    def test_python_fail_closed(self):
        from proxy.core import _admin_ua_authorized  # noqa: F401
        import proxy.core as core
        src = Path(core.__file__).read_text(encoding="utf-8")
        assert "hmac.compare_digest" in src
        # пустой env → отказ: ветка `if not token: return False` в _admin_ua_authorized
        seg = _segment(src, "def _admin_ua_authorized")
        assert "INTERNAL_API_TOKEN" in seg
        assert 'if not token:\n        return False' in seg, "пустой env обязан давать отказ"


class TestIndicatorsEvalsGuards:
    """A.3: indicators/evals идут на Python-эндпоинты напрямую (mlog-роуты :10001)."""

    def test_night_tick_calls_python_endpoints(self):
        seg = "\n".join(_code_lines(_segment(SCHED, "pattern NightTickSlot()")))
        assert "127.0.0.1:4000/scheduler/indicator-pre-reminders" in seg, \
            "indicators не идут на Python-эндпоинт"
        assert "127.0.0.1:4000/scheduler/golden-evals" in seg, \
            "evals не идут на Python-эндпоинт"
        # старые 404-вызовы убраны из кода слота
        assert '"indicator-reminders" + qs' not in seg
        assert '"golden-evals" + qs' not in seg

    def test_mlog_routes_remain_fallback(self):
        """Роуты :10001 (ручной/аварийный фолбэк) не удалены."""
        assert 'route "/cron/indicator-reminders"' in APP
        assert 'route "/cron/golden-evals"' in APP


class TestNewsLanguageGuard:
    """A.4: ленты без языка сохраняются."""

    def test_no_bracket_access_on_feed_dict(self):
        seg = "\n".join(_code_lines(NEWS_PY))
        assert 'fc["language"]' not in seg, "collect_rss всё ещё роняет KeyError 'language'"
        assert 'fc.get("language"' in seg
        assert 'fc.get("category"' in seg
        assert 'fc.get("name"' in seg

    def test_rss_enabled_feeds_language_empty(self):
        seg = "\n".join(_code_lines(NEWS_PY))
        assert '"language": ""' in seg, "ленты из БД должны отдавать language: ''"


class TestLzDeliverOutbox:
    """A.1: ночной LZ DAILY пишет в outbox, дневной — как раньше."""

    def test_route_reads_deliver(self):
        seg = "\n".join(_code_lines(_segment(LZ_PY, "@app.post(\"/scheduler/lz-daily\")")))
        assert 'd.get("deliver", "telegram")' in seg

    def test_core_inserts_to_outbox(self):
        seg = "\n".join(_code_lines(_segment(LZ_PY, "def scheduler_lz_daily_core")))
        assert 'deliver == "outbox"' in seg
        assert "INSERT INTO owner_outbox (source, text) VALUES (?, ?)" in seg
        assert '("lz-daily", report)' in seg


# ── Функциональные тесты ─────────────────────────────────────────────────


@pytest.fixture
def client():
    from llm_proxy import app
    app.config["TESTING"] = True
    return app.test_client()


class TestAdminUaAuth:
    """A.2: /admin-ua/ — 127.0.0.1 И внутренний токен; снаружи закрыт."""

    TOKEN = "internal-token-test-987654321"

    def _itok(self):
        from proxy.core import _admin_ua_token_hash
        return _admin_ua_token_hash(self.TOKEN)

    @pytest.fixture(autouse=True)
    def _set_token(self, monkeypatch):
        monkeypatch.setenv("INTERNAL_API_TOKEN", self.TOKEN)

    def test_header_token_localhost_200(self, client):
        r = client.get("/admin-ua/scan", headers={"X-Internal-Token": self.TOKEN})
        assert r.status_code == 200

    def test_hash_token_query_200(self, client):
        r = client.get(f"/admin-ua/scan?itok={self._itok()}")
        assert r.status_code == 200

    def test_without_token_401(self, client):
        r = client.get("/admin-ua/scan")
        assert r.status_code == 401

    def test_wrong_header_401(self, client):
        r = client.get("/admin-ua/scan", headers={"X-Internal-Token": "wrong-token"})
        assert r.status_code == 401

    def test_wrong_itok_401(self, client):
        r = client.get("/admin-ua/scan?itok=deadbeefdeadbeef")
        assert r.status_code == 401

    def test_token_of_other_scope_does_not_open(self, client):
        """Токен другого scope (прецедент #442: невзаимозаменяемость)."""
        other = hashlib.sha256((self.TOKEN + ":repos").encode()).hexdigest()[:16]
        r = client.get(f"/admin-ua/scan?itok={other}")
        assert r.status_code == 401

    def test_external_ip_with_valid_token_401(self, client):
        """Внешний вход через reverse_proxy (XFF ≠ localhost) — закрыт даже с токеном."""
        r = client.get(
            f"/admin-ua/scan?itok={self._itok()}",
            headers={"X-Internal-Token": self.TOKEN, "X-Forwarded-For": "203.0.113.7"},
        )
        assert r.status_code == 401

    def test_empty_env_fail_closed(self, client, monkeypatch):
        monkeypatch.setenv("INTERNAL_API_TOKEN", "")
        r = client.get("/admin-ua/scan", headers={"X-Internal-Token": ""})
        assert r.status_code == 401
        r2 = client.get("/admin-ua/scan", headers={"X-Internal-Token": self.TOKEN})
        assert r2.status_code == 401, "пустой env обязан закрывать префикс всегда"

    def test_bearer_is_not_enough(self, client):
        """Bearer API_SECRET не открывает /admin-ua/ (нужен именно внутренний токен)."""
        r = client.get("/admin-ua/scan", headers={"Authorization": "Bearer test-secret-123"})
        assert r.status_code == 401


class TestOwnerOutboxTable:
    """A.1: таблица outbox, запись и дедуп-механика на Python-стороне."""

    @pytest.fixture()
    def db(self):
        from proxy.core import init_db, _query
        init_db()
        _query("DELETE FROM owner_outbox")
        return _query

    def test_table_exists_and_insert(self, db):
        db("INSERT INTO owner_outbox (source, text) VALUES (?, ?)", ("night-tick", "test: hello"))
        rows = db("SELECT source, text, sent_at FROM owner_outbox WHERE sent_at IS NULL", fetch=True)
        assert len(rows) == 1
        assert rows[0]["source"] == "night-tick"
        assert rows[0]["sent_at"] is None

    def test_mark_sent_and_dedup(self, db):
        db("INSERT INTO owner_outbox (source, text) VALUES (?, ?)", ("night", "x"))
        db("UPDATE owner_outbox SET sent_at = datetime('now') WHERE sent_at IS NULL")
        rows = db(
            "SELECT COUNT(*) AS cnt FROM owner_outbox WHERE sent_at IS NOT NULL "
            "AND date(sent_at) = date('now')", fetch=True,
        )
        assert rows[0]["cnt"] >= 1
        pend = db("SELECT COUNT(*) AS cnt FROM owner_outbox WHERE sent_at IS NULL", fetch=True)
        assert pend[0]["cnt"] == 0


class TestNewsNoLanguage:
    """A.4: лента из БД без language сохраняет записи, data_loss не пишется."""

    def test_collect_rss_without_language(self, monkeypatch):
        from proxy.core import init_db, _query
        init_db()
        from proxy import news as news_mod

        monkeypatch.setattr(
            news_mod, "rss_enabled_feeds",
            lambda: {"dbfeed": {"url": "http://127.0.0.1:1/rss", "name": "DB Feed",
                                "category": "test", "language": ""}},
        )

        class _FakeEntry(dict):
            def get(self, k, d=None):
                return super().get(k, d)

        class _FakeFeed:
            entries = [
                _FakeEntry(title="News without language", summary="sum", link="http://x/1"),
                _FakeEntry(title="News second", summary="sum2", link="http://x/2"),
            ]

        import feedparser
        monkeypatch.setattr(feedparser, "parse", lambda url: _FakeFeed())

        _query("DELETE FROM news_cache WHERE source = 'DB Feed'")
        before_errors = _query(
            "SELECT COUNT(*) AS cnt FROM error_log WHERE kind = 'data_loss'", fetch=True
        )[0]["cnt"]

        collected = news_mod.collect_rss()

        assert collected >= 2, "записи ленты без language должны сохраняться"
        rows = _query("SELECT language, category FROM news_cache WHERE source = 'DB Feed'", fetch=True)
        assert len(rows) >= 2
        assert all((r["language"] or "") == "" for r in rows)
        after_errors = _query(
            "SELECT COUNT(*) AS cnt FROM error_log WHERE kind = 'data_loss'", fetch=True
        )[0]["cnt"]
        assert after_errors == before_errors, "data_loss не должен писаться для ленты без language"
