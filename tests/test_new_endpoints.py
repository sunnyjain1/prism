"""Integration tests for new API endpoints: smart-insights, streaks, trends, heatmap."""
import pytest
from fastapi.testclient import TestClient

from main import app


def register_and_get_headers(client: TestClient) -> dict:
    """Register a test user and return auth headers."""
    import uuid
    email = f"test_{uuid.uuid4().hex[:8]}@test.com"
    payload = {"email": email, "password": "TestPass123!", "full_name": "Test User"}
    resp = client.post("/api/v1/auth/register", json=payload, headers={"User-Agent": "pytest"})
    if resp.status_code == 201:
        token = resp.json()["access_token"]
    else:
        # Already exists, login instead
        resp = client.post("/api/v1/auth/token", data={"username": email, "password": "TestPass123!"})
        token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestSmartInsightsEndpoint:
    """Test GET /api/v1/notifications/smart-insights"""

    def test_smart_insights_requires_auth(self, api_client):
        response = api_client.get("/api/v1/notifications/smart-insights")
        assert response.status_code == 401

    def test_smart_insights_returns_structure(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/notifications/smart-insights", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "insights" in data
        assert "count" in data
        assert isinstance(data["insights"], list)
        assert data["count"] == len(data["insights"])


class TestStreaksEndpoint:
    """Test GET /api/v1/streaks"""

    def test_streaks_requires_auth(self, api_client):
        response = api_client.get("/api/v1/streaks")
        assert response.status_code == 401

    def test_streaks_returns_structure(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/streaks", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "logging_streak" in data
        assert "budget_streak" in data
        assert "achievements" in data
        assert "stats" in data

    def test_streaks_logging_streak_fields(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/streaks", headers=headers)
        data = response.json()
        streak = data["logging_streak"]
        assert "current" in streak
        assert "longest" in streak
        assert isinstance(streak["current"], int)

    def test_streaks_stats_fields(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/streaks", headers=headers)
        data = response.json()
        stats = data["stats"]
        assert "total_transactions" in stats
        assert "transactions_this_month" in stats
        assert "transactions_this_week" in stats


class TestTrendsEndpoint:
    """Test GET /api/v1/reports/analytics/trends"""

    def test_trends_requires_auth(self, api_client):
        response = api_client.get("/api/v1/reports/analytics/trends")
        assert response.status_code == 401

    def test_trends_returns_structure(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/reports/analytics/trends", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "category_trends" in data
        assert "monthly_totals" in data
        assert "months_analyzed" in data

    def test_trends_custom_months(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/reports/analytics/trends?months=3", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["months_analyzed"] == 3


class TestHeatmapEndpoint:
    """Test GET /api/v1/reports/analytics/heatmap"""

    def test_heatmap_requires_auth(self, api_client):
        response = api_client.get("/api/v1/reports/analytics/heatmap")
        assert response.status_code == 401

    def test_heatmap_returns_structure(self, api_client):
        headers = register_and_get_headers(api_client)
        response = api_client.get("/api/v1/reports/analytics/heatmap", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "month" in data
        assert "days" in data
        assert "max_daily_spend" in data
        assert isinstance(data["days"], list)
