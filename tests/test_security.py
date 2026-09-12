"""Basic tests for llm_proxy — health, auth, webhook verification."""
import os
import sys
import json
import pytest

# Ensure the app can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def app():
    """Create app with test config."""
    os.environ['API_SECRET'] = 'test-secret-123'
    os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
    os.environ['OWNER_TELEGRAM_ID'] = '12345'
    os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db'
    os.environ['ZAI_API_KEY'] = 'fake-key'

    from llm_proxy import app
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthEndpoint:
    """GET /health — always open, no auth."""

    def test_health_returns_ok(self, client):
        r = client.get('/health')
        assert r.status_code == 200

    def test_health_returns_json(self, client):
        r = client.get('/health')
        data = r.get_json()
        assert data is not None


class TestAuthMiddleware:
    """Bearer token required for protected prefixes.

    Note: /memory/ endpoints bypass auth for localhost (127.0.0.1)
    because mlog http_post() has no custom-header support. Flask
    test_client uses 127.0.0.1 as remote_addr, so the bypass applies.
    This is by design — external traffic is blocked by reverse_proxy.
    """

    def test_api_without_token_returns_401(self, client):
        r = client.get('/api/dashboard')
        assert r.status_code == 401

    def test_api_with_wrong_token_returns_401(self, client):
        r = client.get('/api/dashboard', headers={'Authorization': 'Bearer wrong'})
        assert r.status_code == 401

    def test_api_with_correct_token_passes(self, client):
        r = client.get('/api/dashboard', headers={'Authorization': 'Bearer test-secret-123'})
        assert r.status_code != 401

    def test_admin_ua_without_token_returns_401(self, client):
        r = client.get('/admin-ua/scan')
        assert r.status_code == 401

    def test_memory_localhost_bypass(self, client):
        """/memory/ bypasses auth for localhost (mlog internal calls)."""
        r = client.post('/memory/recall', json={'query': 'test'})
        assert r.status_code == 200

    def test_memory_without_data_returns_400(self, client):
        """/memory/recall requires proper JSON body."""
        r = client.post('/memory/recall', json={})
        assert r.status_code == 400

    def test_miniapp_action_without_token_returns_401(self, client):
        r = client.post('/webhook/miniapp-action', json={})
        assert r.status_code == 401


class TestWebhookSecret:
    """Telegram webhook secret verification.

    /webhook/telegram is handled by reverse_proxy.py, NOT llm_proxy.py.
    The webhook secret check is tested in scripts/test_sec3.py against
    reverse_proxy. These tests verify that llm_proxy's webhook-related
    endpoints behave correctly.
    """

    def test_webhook_miniapp_action_rejects_no_token(self, client):
        """/webhook/miniapp-action requires Bearer token."""
        r = client.post('/webhook/miniapp-action', json={})
        assert r.status_code == 401

    def test_webhook_miniapp_action_accepts_token(self, client):
        """/webhook/miniapp-action with valid Bearer passes auth."""
        r = client.post('/webhook/miniapp-action', json={},
                        headers={'Authorization': 'Bearer test-secret-123'})
        assert r.status_code != 401


class TestOpenEndpoints:
    """Endpoints that should NOT require auth."""

    def test_miniapp_spa_open(self, client):
        r = client.get('/miniapp-spa/')
        assert r.status_code != 401

    def test_health_open(self, client):
        r = client.get('/health')
        assert r.status_code != 401

    def test_now_time_open(self, client):
        r = client.get('/now-time')
        assert r.status_code != 401


class TestLLMTraces:
    """FO-004: Per-call LLM trace JSONL files."""

    def test_traces_endpoint_auth_required(self, client):
        """/traces endpoints require Bearer auth."""
        r = client.get('/traces-stats')
        assert r.status_code == 401

    def test_traces_endpoint_with_auth(self, client):
        """/trace-stats returns data with Bearer auth."""
        r = client.get('/trace-stats', headers={'Authorization': 'Bearer test-secret-123'})
        assert r.status_code != 401

    def test_traces_query_with_auth(self, client):
        """/traces returns data with Bearer auth."""
        r = client.get('/traces', headers={'Authorization': 'Bearer test-secret-123'})
        assert r.status_code != 401

    def test_trace_write_function_exists(self, app):
        """_write_llm_trace and _prune_old_traces are importable."""
        from llm_proxy import _write_llm_trace, _prune_old_traces
        assert callable(_write_llm_trace)
        assert callable(_prune_old_traces)

    def test_trace_write_creates_file(self, app, tmp_path):
        """Writing a trace record creates a JSONL file."""
        import importlib
        os.environ['DATABASE_PATH'] = str(tmp_path)
        # Re-import to pick up new _TRACE_DIR.
        # FO-008: trace-утилиты живут в proxy.core — перезагружаем и его.
        import llm_proxy
        import proxy.core
        importlib.reload(proxy.core)
        importlib.reload(llm_proxy)
        llm_proxy._write_llm_trace({"trace_id": "test123", "dept": "osp", "ok": True})
        trace_dir = os.path.join(str(tmp_path), "traces")
        assert os.path.isdir(trace_dir)
        files = [f for f in os.listdir(trace_dir) if f.endswith('.jsonl')]
        assert len(files) >= 1
