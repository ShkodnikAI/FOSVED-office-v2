"""FO-005 tests: golden-наборы, формат-скоринг, регрессии, алерты, endpoint auth."""
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['CRON_SECRET'] = 'cron-test-secret'

import llm_proxy  # noqa: E402
import proxy.routes_tail as _rt  # noqa: E402 — FO-008: функции живут здесь


@pytest.fixture
def client():
    llm_proxy.app.config['TESTING'] = True
    with llm_proxy.app.test_client() as c:
        yield c


class TestGoldenFiles:
    """Golden-файлы валидны: схема, уникальные id, задачи содержательны."""

    def test_all_sets_valid(self):
        depts = [p.stem for p in llm_proxy._GOLDEN_DIR.glob("*.json")]
        assert len(depts) >= 3, "минимум yana, osp, lz"
        seen_ids = set()
        for dept in depts:
            tasks = llm_proxy._golden_load(dept)
            assert 10 <= len(tasks) <= 20, f"{dept}: 10-20 задач"
            for t in tasks:
                assert t.get("id") and t.get("input"), f"{dept}: id+input"
                assert t["id"] not in seen_ids, f"дубликат id {t['id']}"
                seen_ids.add(t["id"])


class TestFormatScore:
    def _task(self, expect):
        return {"id": "t", "input": "q", "expect": expect}

    def test_contains_any(self):
        t = self._task({"contains_any": ["вероятность", "сценарий"]})
        assert llm_proxy._golden_format_score(t, "Здесь вероятность 0.7") == 1.0
        assert llm_proxy._golden_format_score(t, "ничего подходящего") == 0.0

    def test_contains_regex(self):
        t = self._task({"contains_regex": r"\[DELEGATE:\s*osp\]"})
        assert llm_proxy._golden_format_score(t, "[DELEGATE: osp]") == 1.0
        assert llm_proxy._golden_format_score(t, "ответ сам") == 0.0

    def test_not_contains(self):
        t = self._task({"not_contains": ["я симуляция"]})
        assert llm_proxy._golden_format_score(t, "нормальный ответ") == 1.0
        assert llm_proxy._golden_format_score(t, "Я симуляция") == 0.0

    def test_length_bounds(self):
        t = self._task({"min_chars": 10, "max_chars": 20})
        assert llm_proxy._golden_format_score(t, "x" * 15) == 1.0
        assert llm_proxy._golden_format_score(t, "x" * 5) == 0.0
        assert llm_proxy._golden_format_score(t, "x" * 50) == 0.0

    def test_mixed_rules_partial(self):
        t = self._task({"contains_any": ["да"], "min_chars": 100})
        assert llm_proxy._golden_format_score(t, "да") == 0.5

    def test_no_rules_full_score(self):
        assert llm_proxy._golden_format_score(self._task({}), "любой") == 1.0


class TestRunDept:
    def _mock_llm(self, monkeypatch, reply):
        monkeypatch.setattr(_rt, "call_llm", lambda d, m: {
            "reply": reply, "provider": "test", "model": "test-m", "tokens_in": 1, "tokens_out": 1})
        # верификатор не дёргаем в юнит-тесте — мокаем score
        import llm_verifier
        monkeypatch.setattr(llm_verifier, "score", lambda p, c, criteria="": 0.8)

    def test_scores_computed(self, monkeypatch):
        self._mock_llm(monkeypatch, "[DELEGATE: expert] передаю экспертам")
        tasks = [{"id": "t1", "input": "q", "expect": {"contains_regex": "DELEGATE"}}]
        summary = llm_proxy._golden_run_dept("yana", tasks)
        assert summary["tasks_total"] == 1
        assert 0.0 <= summary["avg_score"] <= 1.0
        assert summary["results"][0]["verifier_score"] == 0.8

    def test_llm_failure_counted(self, monkeypatch):
        def boom(d, m):
            raise RuntimeError("down")
        monkeypatch.setattr(_rt, "call_llm", boom)
        tasks = [{"id": "t1", "input": "q", "expect": {}}]
        summary = llm_proxy._golden_run_dept("yana", tasks)
        assert summary["failed"] == 1
        assert summary["avg_score"] == 0.0

    def test_trace_written(self, monkeypatch):
        self._mock_llm(monkeypatch, "ответ")
        tasks = [{"id": f"tr_{uuid.uuid4().hex[:6]}", "input": "q", "expect": {}}]
        llm_proxy._golden_run_dept("yana", tasks)
        found = False
        for name in os.listdir(llm_proxy._TRACE_DIR):
            if name.endswith(".jsonl"):
                if "golden_eval" in open(os.path.join(llm_proxy._TRACE_DIR, name), encoding="utf-8").read():
                    found = True
                    break
        assert found


class TestRegression:
    def test_regression_threshold_and_alert(self, client, monkeypatch):
        sent = []
        monkeypatch.setattr(_rt, "_tg_send_message", lambda cid, text, **kw: sent.append(text) or "ok")
        # Оба департамента мокаем: один низкий скор, один высокий
        def fake_llm(d, m):
            if d == "osp":
                return {"reply": "короткий", "provider": "t", "model": "m"}
            return {"reply": "x" * 500, "provider": "t", "model": "m"}
        monkeypatch.setattr(_rt, "call_llm", fake_llm)
        import llm_verifier
        monkeypatch.setattr(llm_verifier, "score", lambda p, c, criteria="": 0.9)

        # osp: задача с min_chars 400 → формат-скор 0 → avg < 0.6 → регрессия
        osp_tasks = [{"id": "r1", "input": "q", "expect": {"min_chars": 400}},
                     {"id": "r2", "input": "q", "expect": {"min_chars": 400}}]
        yana_tasks = [{"id": "y1", "input": "q", "expect": {}}]
        monkeypatch.setattr(_rt, "_golden_load", lambda dept: {
            "osp": osp_tasks, "yana": yana_tasks}.get(dept))
        monkeypatch.setattr(_rt, "_golden_previous_avg", lambda dept: 0.9)
        # №588 B.3: доставка зависит от времени суток — тест фиксирует день
        # (иначе алерт честно уходит в owner_outbox по тишине #550)
        monkeypatch.setattr(_rt, "_is_night_msk", lambda: False)

        r = client.post("/scheduler/golden-evals?secret=cron-test-secret", json={"depts": ["osp", "yana"]})
        assert r.status_code == 200
        data = r.get_json()
        assert data["totals"]["regressions"] == 1
        assert len(sent) == 1, "алерт владельцу должен быть отправлен"
        assert "Регрессия" in sent[0]

    def test_auth_required(self, client):
        r = client.post("/scheduler/golden-evals?secret=wrong", json={})
        assert r.status_code == 403

    def test_dept_metrics_recorded(self, client, monkeypatch):
        monkeypatch.setattr(_rt, "call_llm", lambda d, m: {
            "reply": "х" * 300, "provider": "t", "model": "m"})
        import llm_verifier
        monkeypatch.setattr(llm_verifier, "score", lambda p, c, criteria="": 0.9)
        dept = f"qa_{uuid.uuid4().hex[:6]}"
        tasks = [{"id": "m1", "input": "q", "expect": {"min_chars": 100}}]
        monkeypatch.setattr(_rt, "_golden_load", lambda d: tasks if d == dept else None)
        r = client.post("/scheduler/golden-evals?secret=cron-test-secret", json={"depts": [dept]})
        assert r.status_code == 200
        rows = llm_proxy._query(
            "SELECT metric_value FROM dept_metrics WHERE dept=? AND metric_name='golden_eval_avg'",
            (dept,), fetch=True)
        assert rows, "тренд должен писаться в dept_metrics"
