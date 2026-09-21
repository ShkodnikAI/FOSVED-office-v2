#!/usr/bin/env python3
"""FO-022 tests: free-tier intelligence llm_proxy (наряд #88).

Критерии «сделано, когда»:
- failure buckets категорируются верно (429-тест-кит записанных форм ответов);
- cooldown до ролловера доказан на моках (Retry-After / RetryInfo / limit:0 /
  ролловер в таймзоне провайдера);
- redact-инвариант: payload с секретом не уходит к LLM-провайдеру;
- redactor перестраивается при смене ключа;
- /health-агрегат buckets_last_24h() читает трейсы FO-004;
- пустой ответ провайдера = отказ (bucket empty), цепь идёт дальше.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['TELEGRAM_BOT_TOKEN'] = 'test-bot-token'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo22-test'
os.environ['ZAI_API_KEY'] = 'zai-fake-key-123456'
os.environ['DEEPSEEK_API_KEY'] = 'ds-fake-key-123456'

import llm_proxy  # noqa: E402,F401
from proxy import resilience as res  # noqa: E402
from proxy.core import _TRACE_DIR, _write_llm_trace  # noqa: E402
from proxy.providers import _call_single_provider  # noqa: E402
from proxy.redact import (  # noqa: E402
    invalidate_values_cache, known_secret_values, redact_obj, redact_values_in_text,
)


@pytest.fixture(autouse=True)
def _clean_quota_state():
    res._quota._cooldown.clear()
    res._long_cooldown.clear()
    invalidate_values_cache()
    yield
    res._quota._cooldown.clear()
    res._long_cooldown.clear()
    invalidate_values_cache()


# ─────────────────── 1. Failure buckets ───────────────────

class TestClassifyFailure:
    def test_429_status(self):
        assert res.classify_failure(status_code=429) == "rateLimit"

    def test_401_403_forbidden(self):
        assert res.classify_failure(status_code=401) == "forbidden"
        assert res.classify_failure(status_code=403) == "forbidden"

    def test_404_not_found(self):
        assert res.classify_failure(status_code=404) == "notFound"

    def test_5xx_server_error(self):
        assert res.classify_failure(status_code=502) == "serverError"
        assert res.classify_failure(status_code=500) == "serverError"

    def test_timeout_kind(self):
        assert res.classify_failure(kind="timeout") == "timeout"

    def test_conn_aborted(self):
        assert res.classify_failure(kind="conn", error_text="Connection aborted.") == "aborted"

    def test_text_rate_limit(self):
        assert res.classify_failure(error_text="Rate limit reached for model") == "rateLimit"

    def test_text_model_not_found(self):
        assert res.classify_failure(error_text="Model gpt-oss-99b does not exist") == "notFound"

    def test_text_invalid_key(self):
        assert res.classify_failure(error_text="Invalid API key provided") == "forbidden"

    def test_empty_kind(self):
        assert res.classify_failure(kind="empty") == "empty"

    def test_unknown_other(self):
        assert res.classify_failure(error_text="something weird happened") == "other"


# ─────────────────── 2. 429-тест-кит (quota.mjs) ───────────────────

class TestQuotaTracker:
    def test_retry_after_header(self, monkeypatch):
        now = 1_000_000.0
        monkeypatch.setattr(res.time, "time", lambda: now)
        q = res.QuotaTracker()
        until = q.note_rate_limited("groq", "m1", body_text="{}", headers={"Retry-After": "30"}, now=now)
        assert until == now + 30.0
        assert "retry_after" in (q.is_limited("groq", "m1", now=now + 1) or "")

    def test_retry_info_json(self, monkeypatch):
        now = 2_000_000.0
        monkeypatch.setattr(res.time, "time", lambda: now)
        q = res.QuotaTracker()
        body = json.dumps({"error": {"details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "26s"}]}})
        until = q.note_rate_limited("cerebras", "m2", body_text=body, now=now)
        assert until == now + 26.0

    def test_limit_zero_no_free_tier(self, monkeypatch):
        now = 3_000_000.0
        monkeypatch.setattr(res.time, "time", lambda: now)
        q = res.QuotaTracker()
        body = json.dumps({"error": {"code": 429,
                                     "message": "Limit 0 reached. Model not available on free tier."}})
        until = q.note_rate_limited("groq", "m3", body_text=body, now=now)
        assert until == now + res._NO_TIER_COOLDOWN_S
        reason = q.is_limited("groq", "m3", now=now + 60)
        assert "no_tier" in reason

    def test_rollover_utc(self, monkeypatch):
        now = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc).timestamp()
        q = res.QuotaTracker()
        until = q.note_rate_limited("deepseek", "m4", body_text="rate limit", now=now)
        expected = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc).timestamp()
        assert until == expected

    def test_rollover_provider_tz(self, monkeypatch):
        monkeypatch.setitem(res._PROVIDER_TZ, "groq", "America/Chicago")
        # 2026-09-13 10:00 UTC = 05:00 Chicago (CDT, UTC-5) → ролловер 14.09 00:00 Chicago = 05:00 UTC
        now = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc).timestamp()
        q = res.QuotaTracker()
        until = q.note_rate_limited("groq", "m5", body_text="rate limit", now=now)
        expected = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc).timestamp()
        assert until == expected

    def test_expiry_frees_pair(self, monkeypatch):
        now = [4_000_000.0]
        monkeypatch.setattr(res.time, "time", lambda: now[0])
        q = res.QuotaTracker()
        q.note_rate_limited("zai", "m6", body_text="{}", headers={"Retry-After": "5"}, now=now[0])
        assert q.is_limited("zai", "m6") is not None
        now[0] += 6
        assert q.is_limited("zai", "m6") is None

    def test_provider_skipped_and_health(self, monkeypatch):
        now = 5_000_000.0
        monkeypatch.setattr(res.time, "time", lambda: now)
        res._quota.note_rate_limited("groq", "openai/gpt-oss-20b",
                                     body_text="{}", headers={"Retry-After": "60"}, now=now)
        reason = res.provider_skipped("groq", "openai/gpt-oss-20b", now=now + 1)
        assert reason and "retry_after" in reason
        # /health-снимок до истечения кулдауна
        assert "groq/openai/gpt-oss-20b" in res.quota_status(now=now + 1)
        # после истечения — пара свободна, из /health ушла
        assert res.provider_skipped("groq", "openai/gpt-oss-20b", now=now + 61) is None
        assert "groq/openai/gpt-oss-20b" not in res.quota_status(now=now + 61)


# ─────────────────── 3. Long cooldown (notFound/forbidden) ───────────────────

class TestLongCooldown:
    def test_forbidden_exiles_provider(self, monkeypatch):
        now = 6_000_000.0
        monkeypatch.setattr(res.time, "time", lambda: now)
        res.note_long_cooldown("openai", "forbidden: Invalid API key", now=now)
        assert res.provider_skipped("openai", "gpt-4o", now=now + 1)
        # через 7 ч — отпустило
        assert res.provider_skipped("openai", "gpt-4o", now=now + 7 * 3600) is None

    def test_rate_limit_does_not_exile(self):
        # rateLimit → только квотный кулдаун пары, provider остаётся в цепи
        assert res.provider_long_cooldown("groq") is None


# ─────────────────── 4. Redact-инвариант (upstream) ───────────────────

class _FakeResp:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body or {"choices": [{"message": {"content": "ok"}}],
                              "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        self.text = json.dumps(self._body)
        self.headers = headers or {}

    def raise_for_status(self):
        import requests as rq
        if self.status_code >= 400:
            err = rq.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err

    def json(self):
        return self._body


SECRET_VAL = "sk-super-secret-value-98765"


class TestRedactUpstream:
    def test_redact_invariant_upstream(self, monkeypatch):
        """Payload с секретом не уходит к провайдеру: ни поле, ни вставка в текст."""
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _FakeResp(200)

        monkeypatch.setattr("proxy.providers.http_requests.post", fake_post)
        monkeypatch.setenv("TEST_SECRET_KEY", SECRET_VAL)
        invalidate_values_cache()
        messages = [
            {"role": "system", "content": f"Контекст владельца: TEST_SECRET_KEY={SECRET_VAL}"},
            {"role": "user", "content": "привет"},
        ]
        result = _call_single_provider("deepseek", "deepseek-chat", messages, dept="yana")
        assert result and result.get("reply") == "ok"
        sent = json.dumps(captured["json"], ensure_ascii=False)
        assert SECRET_VAL not in sent, "секрет ушёл к LLM-провайдеру — taint-инвариант нарушен"
        assert "[REDACTED]" in sent

    def test_secret_field_redacted_deep(self):
        obj = {"config": {"api_key": SECRET_VAL, "nested": [{"token": "abcd12345"}]}}
        out = json.dumps(redact_obj(obj))
        assert SECRET_VAL not in out and "abcd12345" not in out
        assert "[REDACTED]" in out

    def test_redactor_rebuilds_on_key_change(self, monkeypatch):
        """Смена ключа → множество значений перестраивается (TTL/invalidate)."""
        monkeypatch.setenv("TEST_SECRET_KEY", "first-key-value-111")
        invalidate_values_cache()
        assert "first-key-value-111" in known_secret_values()
        assert redact_values_in_text(f"ключ: first-key-value-111") == "ключ: [REDACTED]"

        monkeypatch.setenv("TEST_SECRET_KEY", "second-key-value-222")
        invalidate_values_cache()  # ротация без рестарта
        vals = known_secret_values()
        assert "second-key-value-222" in vals
        assert "first-key-value-111" not in vals
        assert redact_values_in_text("второй: second-key-value-222") == "второй: [REDACTED]"

    def test_ttl_rebuild(self, monkeypatch):
        """TTL: множество значений перестраивается после истечения TTL без invalidate."""
        fake_now = [1000.0]
        monkeypatch.setattr("proxy.redact.time.time", lambda: fake_now[0])
        monkeypatch.setenv("TEST_SECRET_KEY", "ttl-key-value-333")
        invalidate_values_cache()
        assert "ttl-key-value-333" in known_secret_values()
        monkeypatch.setenv("TEST_SECRET_KEY", "ttl-key-value-444")
        # TTL не истёк → старое множество
        assert "ttl-key-value-444" not in known_secret_values()
        fake_now[0] += 6.0  # > _VALUES_TTL → пересбор
        assert "ttl-key-value-444" in known_secret_values()


# ─────────────────── 5. Empty reply = отказ (bucket empty) ───────────────────

class TestEmptyReply:
    def test_empty_reply_is_failure(self, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResp(200, body={"choices": [{"message": {"content": ""}}], "usage": {}})

        monkeypatch.setattr("proxy.providers.http_requests.post", fake_post)
        result = _call_single_provider("deepseek", "deepseek-chat",
                                       [{"role": "user", "content": "hi"}], dept="yana")
        assert result is None, "пустой ответ не должен считаться успехом"


# ─────────────────── 6. /health агрегат за 24 ч ───────────────────

@pytest.fixture
def _clean_traces(tmp_path, monkeypatch):
    """Герметичная пара «запись/чтение» трейсов в одном tmp-каталоге.

    Раньше фикстура чистила общий _TRACE_DIR ядра. Он заморожен при первом
    импорте proxy.core в коллекции, а другие тест-файлы перезатирают
    DATABASE_PATH на уровне модуля (fo016/fo017/fo019/fo020/fo025/ui8) —
    в полном прогоне запись шла в замороженный каталог, а
    buckets_last_24h() читала текущий env: расхождение путей давало
    пустые buckets (2 red в CI на self-hosted прогоне 2026-09-22).

    Теперь запись (proxy.core._TRACE_DIR) и чтение (env DATABASE_PATH)
    патчатся в один и тот же tmp_path: порядок исполнения и соседние
    тест-файлы не влияют.

    Retention-прут (7 дней по реальным часам) на время теста отключается:
    иначе _prune_old_traces мгновенно удаляет файл, записанный с
    фейковым ts 2026-09-13 — тест test_old_records_excluded «истёк»
    2026-09-21, когда реальная дата вышла из 7-дневного окна
    захардкоженной даты (маскировалось падением CI по квоте).
    """
    db = tmp_path / "fosved-traces-db"
    monkeypatch.setenv("DATABASE_PATH", str(db))
    monkeypatch.setattr("proxy.core._TRACE_DIR", str(db / "traces"))
    monkeypatch.setattr("proxy.core._TRACE_RETENTION", 3650)
    yield


class TestBucketsAggregation:
    def test_buckets_last_24h_reads_traces(self, _clean_traces):
        _write_llm_trace({
            "ts": datetime.now(timezone.utc).isoformat(),
            "gen_ai.system": "groq", "gen_ai.request.model": "openai/gpt-oss-20b",
            "ok": False, "error": "Rate limit reached", "failure_bucket": "rateLimit",
        })
        _write_llm_trace({
            "ts": datetime.now(timezone.utc).isoformat(),
            "gen_ai.system": "openai", "gen_ai.request.model": "gpt-4o",
            "ok": False, "error": "401 Unauthorized", "failure_bucket": "forbidden",
        })
        buckets = res.buckets_last_24h()
        assert buckets.get("rateLimit", 0) >= 1
        assert buckets.get("forbidden", 0) >= 1
        # успехи и события без ok=false не считаются
        assert set(buckets.keys()) <= set(res.BUCKETS)

    def test_old_records_excluded(self, _clean_traces, monkeypatch):
        """Записи старше 24 ч не попадают в агрегат (окно /health)."""
        from datetime import timedelta
        fake_now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(res.time, "time", lambda: fake_now.timestamp())
        _write_llm_trace({
            "ts": (fake_now - timedelta(hours=30)).isoformat(),
            "gen_ai.system": "groq", "ok": False, "error": "old",
            "failure_bucket": "serverError",
        })
        _write_llm_trace({
            "ts": (fake_now - timedelta(hours=1)).isoformat(),
            "gen_ai.system": "deepseek", "ok": False, "error": "recent",
            "failure_bucket": "notFound",
        })
        buckets = res.buckets_last_24h()
        assert buckets.get("serverError", 0) == 0, "запись 30-часовой давности в окне 24 ч"
        assert buckets.get("notFound", 0) == 1


# ─────────────────── 7. Integration: skip в цепи ───────────────────

class TestChainSkip:
    def test_chain_skips_quota_limited_provider(self, monkeypatch):
        """Провайдер в квотном кулдауне вычеркивается из обхода цепи."""
        from proxy import providers as prov_mod
        calls = []

        def fake_single(provider_name, model, messages, dept="yana", max_tokens=4096, is_internal=False):
            calls.append((provider_name, model))
            if (provider_name, model) == ("groq", "openai/gpt-oss-20b"):
                return None  # упал
            return {"reply": "fallback ok", "provider": provider_name, "model": model,
                    "tokens_in": 1, "tokens_out": 1}

        monkeypatch.setattr(prov_mod, "_call_single_provider", fake_single)
        monkeypatch.setattr(prov_mod, "compact_context",
                            lambda msgs, dept, chain=None, summarize_fn=None, chat_id=None:
                            (msgs, {"tokens_before": 0, "tokens_after": 0}))
        monkeypatch.setattr(prov_mod, "_call_single_provider", fake_single)
        res._quota.note_rate_limited("cerebras", "gpt-oss-120b",
                                     body_text="{}", headers={"Retry-After": "600"},
                                     now=res.time.time())
        try:
            result = prov_mod._call_llm_impl("yana", [{"role": "user", "content": "hi"}],
                                             combo="fosved-free")
            assert result.get("reply") == "fallback ok"
            # cerebras/gpt-oss-120b не вызван (в квотном кулдауне)
            assert ("cerebras", "gpt-oss-120b") not in calls
        finally:
            res._quota._cooldown.clear()
