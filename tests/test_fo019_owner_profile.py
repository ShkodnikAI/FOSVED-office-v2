"""FO-019 tests: профиль владельца — static/dynamic/buckets одним вызовом.

Наряд #85 (пакет G). Критерии «сделано, когда»:
- департамент получает профиль одним вызовом (трейс event=owner_profile);
- инвалидация по ночной консолидации работает, stale-профиль не выдаётся;
- секреты не попадают в профиль по построению (taint-контур).
Golden-set «ответы с профилем ≥ без» — ручная оценка владельца (вне сьюта).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-fo19-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402
from proxy import owner_profile as op  # noqa: E402
from proxy.core import _query, _write_llm_trace  # noqa: E402


@pytest.fixture(autouse=True)
def clean_profile(monkeypatch):
    op._ensure_schema()
    _query("DELETE FROM owner_profile")
    _query("DELETE FROM facts")
    _query("UPDATE system_settings SET value = '' WHERE key = 'owner_profile_version'")
    op._cache.update({"version": None, "key": (), "payload": None})
    recs = []
    monkeypatch.setattr(op, "_write_llm_trace", lambda r: recs.append(r))
    yield recs


def _seed_fact(content, dept="finance", conf=0.9):
    _query("INSERT INTO facts (dept, chat_id, content, status, confidence) "
           "VALUES (?, '0', ?, 'active', ?)", (dept, content, conf))


def _rebuild_with_llm_mock(monkeypatch, payload):
    """rebuild с замоканным LLM-ответом (без сети)."""
    monkeypatch.setattr("proxy.providers.call_llm",
                        lambda dept, messages, **kw:
                        {"reply": "```json\n" + json.dumps(payload) + "\n```",
                         "provider": "mock", "model": "mock",
                         "tokens_in": 10, "tokens_out": 10})


# ────────────────────────── хранилище и генерация ──────────────────────────

class TestRebuild:
    def test_rebuild_llm_mode_writes_sections(self, clean_profile, monkeypatch):
        _seed_fact("Владелец живёт в Минске", dept="qa")
        _seed_fact("Запустил проект FOSVED в августе", dept="dev")
        _seed_fact("Предпочитает короткие ответы в Telegram", dept="design")
        _rebuild_with_llm_mock(monkeypatch, {
            "static": ["Владелец живёт в Минске"],
            "dynamic": ["Запускает проект FOSVED"],
            "buckets": {"проекты": ["FOSVED — офис-платформа"],
                        "предпочтения": ["короткие ответы в Telegram"]},
        })
        res = op.rebuild_owner_profile(source="test")
        assert res["status"] == "ok" and res["mode"] == "llm"
        assert res["items"] == 4  # static 1 + dynamic 1 + buckets 2
        rows = _query("SELECT section, bucket, content FROM owner_profile WHERE valid_to IS NULL", fetch=True)
        sections = {r["section"] for r in rows}
        assert sections == {"static", "dynamic", "bucket"}
        assert any(r["bucket"] == "проекты" for r in rows)

    def test_versioning_closes_old(self, clean_profile, monkeypatch):
        _seed_fact("Факт v1")
        _rebuild_with_llm_mock(monkeypatch, {"static": ["версия 1"], "dynamic": [], "buckets": {}})
        op.rebuild_owner_profile(source="test")
        _rebuild_with_llm_mock(monkeypatch, {"static": ["версия 2"], "dynamic": [], "buckets": {}})
        res2 = op.rebuild_owner_profile(source="test")
        active = _query("SELECT content, valid_to, superseded_by FROM owner_profile WHERE valid_to IS NULL", fetch=True)
        old = _query("SELECT content, valid_to, superseded_by FROM owner_profile WHERE valid_to IS NOT NULL", fetch=True)
        assert [r["content"] for r in active] == ["версия 2"]
        assert old and all(r["superseded_by"] is not None for r in old)
        assert old[0]["valid_to"] is not None

    def test_deterministic_fallback_on_llm_failure(self, clean_profile, monkeypatch):
        _seed_fact("Финансовая цель — подушка 6 месяцев", dept="finance")
        monkeypatch.setattr("proxy.providers.call_llm",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no providers")))
        res = op.rebuild_owner_profile(source="test")
        assert res["status"] == "ok" and res["mode"] == "deterministic"
        rows = _query("SELECT section, bucket, content FROM owner_profile WHERE valid_to IS NULL", fetch=True)
        assert rows  # профиль не пуст даже без LLM

    def test_no_facts_keeps_profile(self, clean_profile):
        res = op.rebuild_owner_profile(source="test")
        assert res["status"] == "no_facts"
        assert _query("SELECT COUNT(*) AS n FROM owner_profile", fetch=True)[0]["n"] == 0


# ────────────────────────── приватность ──────────────────────────

class TestPrivacy:
    def test_secrets_blocked_by_construction(self, clean_profile, monkeypatch):
        _seed_fact("Ключ от гитхаба: github_pat_11BST2XAI0AR7bhZZfNKwt1234", dept="dev")
        _seed_fact("Любит эспрессо", dept="design")
        # даже LLM «пытается» протянуть секрет — выходной контур режет
        _rebuild_with_llm_mock(monkeypatch, {
            "static": ["sk-proj-AAAAAAAAAAAAAAAAAAAAAAAAAA"],
            "dynamic": ["Любит эспрессо"],
            "buckets": {},
        })
        res = op.rebuild_owner_profile(source="test")
        rows = _query("SELECT content FROM owner_profile WHERE valid_to IS NULL", fetch=True)
        texts = " ".join(r["content"] for r in rows)
        assert "github_pat_" not in texts and "sk-proj-" not in texts
        assert "эспрессо" in texts
        assert res["secrets_blocked"] >= 1

    def test_secret_input_fact_filtered(self, clean_profile, monkeypatch):
        _seed_fact("пароль: supersecret12345", dept="qa")
        monkeypatch.setattr("proxy.providers.call_llm",
                            lambda *a, **kw: {"reply": "не json"})
        res = op.rebuild_owner_profile(source="test")
        # факт с секретом отфильтрован на входе → LLM не получил строк → fallback
        rows = _query("SELECT content FROM owner_profile WHERE valid_to IS NULL", fetch=True)
        assert all("supersecret" not in r["content"] for r in rows)

    def test_taint_label_on_rows(self, clean_profile, monkeypatch):
        _seed_fact("Работает над офисом", dept="dev")
        _rebuild_with_llm_mock(monkeypatch, {"static": ["работает над офисом"],
                                             "dynamic": [], "buckets": {}})
        op.rebuild_owner_profile(source="test")
        rows = _query("SELECT taint FROM owner_profile WHERE valid_to IS NULL", fetch=True)
        assert all(r["taint"] == "personal" for r in rows)


# ────────────────────────── чтение одним вызовом ──────────────────────────

class TestGet:
    def _build(self, monkeypatch):
        _seed_fact("Владелец живёт в Минске", dept="qa")
        _seed_fact("Проект FOSVED — приоритет", dept="dev")
        _seed_fact("Обязательство: отчёт до 20-го", dept="finance")
        _rebuild_with_llm_mock(monkeypatch, {
            "static": ["Владелец живёт в Минске"],
            "dynamic": ["Готовит отчёт"],
            "buckets": {"проекты": ["FOSVED — приоритет"],
                        "обязательства": ["отчёт до 20-го"]},
        })
        op.rebuild_owner_profile(source="test")

    def test_one_call_returns_profile_and_trace(self, clean_profile, monkeypatch):
        self._build(monkeypatch)
        res = op.get_owner_profile(dept="finance")
        assert res["profile"] and res["chars"] > 0
        assert "Минске" in res["profile"]
        assert "обязательства" in " ".join(res["sections"]).lower()
        traces = [r for r in clean_profile if r.get("event") == "owner_profile"]
        assert traces and traces[-1]["dept"] == "finance"

    def test_cache_and_invalidation(self, clean_profile, monkeypatch):
        """Критерий: инвалидация по ночной консолидации; stale не выдаётся."""
        _seed_fact("Старый факт", dept="qa")
        _rebuild_with_llm_mock(monkeypatch, {"static": ["версия A"], "dynamic": [], "buckets": {}})
        op.rebuild_owner_profile(source="test")
        first = op.get_owner_profile(dept="qa")
        assert "версия A" in first["profile"]
        second = op.get_owner_profile(dept="qa")
        assert second["cached"] is True  # кэш работает
        # «ночная консолидация» — новый rebuild с новым контентом
        _rebuild_with_llm_mock(monkeypatch, {"static": ["версия B"], "dynamic": [], "buckets": {}})
        op.rebuild_owner_profile(source="nightly")
        third = op.get_owner_profile(dept="qa")
        assert third["cached"] is False
        assert "версия B" in third["profile"] and "версия A" not in third["profile"]

    def test_topic_filter(self, clean_profile, monkeypatch):
        self._build(monkeypatch)
        res = op.get_owner_profile(topic="проекты")
        assert "FOSVED" in res["profile"]
        assert "Текущий контекст" not in res["profile"]  # dynamic вне топика

    def test_dept_metafilter_prioritizes_buckets(self, clean_profile, monkeypatch):
        self._build(monkeypatch)
        res = op.get_owner_profile(dept="finance")
        # обязательства (приоритет finance) встречаются раньше предпочтений/проектов
        idx = {s: i for i, s in enumerate(res["sections"])}
        if "bucket:обязательства" in idx and "bucket:проекты" in idx:
            assert idx["bucket:обязательства"] < idx["bucket:проекты"]

    def test_unknown_section_rejected(self, clean_profile):
        with pytest.raises(ValueError):
            op.get_owner_profile(section="bananas")

    def test_max_chars_truncation(self, clean_profile, monkeypatch):
        self._build(monkeypatch)
        res = op.get_owner_profile(max_chars=60)
        assert res["chars"] <= 60 + len("\n[…профиль усечён]")


# ────────────────────────── ночная wiring и совместимость ──────────────────────────

class TestWiring:
    def test_consolidation_endpoint_triggers_rebuild(self, clean_profile, monkeypatch):
        """Ночная консолидация FO-006 обновляет профиль (генератор в цепочке)."""
        calls = []
        def fake_rebuild(*a, **kw):
            calls.append(kw.get("source"))
            return {"status": "no_facts", "version": "v"}
        # патчим в пространстве routes_tail (эндпоинт берёт функцию оттуда)
        import proxy.routes_tail as rt
        monkeypatch.setattr(rt, "profile_rebuild_owner_profile", fake_rebuild)
        monkeypatch.setenv("CRON_SECRET", "test-cron")
        client = llm_proxy.app.test_client()
        resp = client.post("/cron/consolidate-memory?secret=test-cron")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert "owner_profile" in body
        assert calls == ["nightly"]  # генератор вызван ночной цепочкой

    def test_facade_exports(self):
        for name in ("get_owner_profile", "rebuild_owner_profile",
                     "invalidate_owner_profile", "ensure_profile_schema"):
            assert hasattr(llm_proxy, name), f"facade lost {name}"

    def test_profile_endpoints_exist(self):
        rules = [str(r) for r in llm_proxy.app.url_map.iter_rules()]
        assert "/profile/owner" in rules and "/profile/rebuild" in rules
