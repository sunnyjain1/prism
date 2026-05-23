from core.config import settings
from main import app
from services.cache_service import cache


def test_health_readiness_and_metrics_endpoints(client, monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_ENABLED", False)
    monkeypatch.setattr(cache, "enabled", False)
    app.state.metrics.reset()

    health_response = client.get("/health", headers={"X-Request-ID": "health-test-request"})
    assert health_response.status_code == 200
    assert health_response.headers["X-Request-ID"] == "health-test-request"
    assert health_response.json()["status"] == "healthy"
    assert health_response.json()["version"] == settings.APP_VERSION

    readiness_response = client.get("/health/ready")
    assert readiness_response.status_code == 200
    readiness_payload = readiness_response.json()
    assert readiness_payload["status"] == "healthy"
    assert readiness_payload["checks"] == {"database": "ok", "search": "disabled", "cache": "disabled"}

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    metrics_payload = metrics_response.json()
    assert metrics_payload["request_count"] >= 2
    assert metrics_payload["error_count"] == 0
    assert "GET /health" in metrics_payload["routes"]
    assert "GET /health/ready" in metrics_payload["routes"]


def test_cache_health_reports_ok(client, monkeypatch):
    class HealthyCacheClient:
        def ping(self):
            return True

    monkeypatch.setattr(settings, "SEARCH_ENABLED", False)
    monkeypatch.setattr(cache, "enabled", True)
    monkeypatch.setattr(cache, "_client", HealthyCacheClient())

    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["cache"] == "ok"



def test_metrics_counts_error_responses(client):
    app.state.metrics.reset()

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401

    metrics_response = client.get("/metrics")
    payload = metrics_response.json()
    assert payload["error_count"] >= 1
    assert payload["routes"]["GET /api/v1/auth/me"]["error_count"] >= 1
