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
