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
    """Bearer token required for protected prefixes."""

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

    def test_memory_without_token_returns_401(self, client):
        r = client.post('/memory/recall', json={})
        assert r.status_code == 401

    def test_miniapp_action_without_token_returns_401(self, client):
        r = client.post('/webhook/miniapp-action', json={})
        assert r.status_code == 401


class TestWebhookSecret:
    """Telegram webhook must verify X-Telegram-Bot-Api-Secret-Token."""

    def test_webhook_without_secret_returns_403(self, client):
        r = client.post('/webhook/telegram', json={})
        assert r.status_code == 403

    def test_webhook_with_wrong_secret_returns_403(self, client):
        r = client.post('/webhook/telegram',
                        headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong'},
                        json={})
        assert r.status_code == 403

    def test_webhook_with_correct_secret_passes(self, client):
        r = client.post('/webhook/telegram',
                        headers={'X-Telegram-Bot-Api-Secret-Token': 'tg-wh-secret'},
                        json={"message": {"chat": {"id": "12345"}, "from": {"id": "12345"}, "text": "/health"}})
        assert r.status_code != 403


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