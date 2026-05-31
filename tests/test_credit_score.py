"""Tests for credit score service and API."""
from uuid import uuid4


def _register_and_auth(client):
    uid = uuid4().hex[:8]
    payload = {
        "email": f"credit_{uid}@test.com",
        "password": "TestPass123!",
        "full_name": "Credit Test User",
    }
    response = client.post(
        "/api/v1/auth/register",
        json=payload,
        headers={"user-agent": "pytest"},
    )
    assert response.status_code == 200, response.text
    tokens = response.json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_get_score_no_report(api_client):
    headers = _register_and_auth(api_client)
    response = api_client.get("/api/v1/credit-score", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["has_report"] is False
    assert data["score"] is None


def test_fetch_credit_report(api_client):
    headers = _register_and_auth(api_client)
    response = api_client.post(
        "/api/v1/credit-score/fetch",
        json={"provider": "cibil", "pan": "ABCDE1234F"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["score"] is not None
    assert 300 <= data["score"] <= 900
    assert data["provider"] == "cibil"
    assert data["classification"] in ["excellent", "good", "fair", "poor", "very_poor"]
    assert "summary" in data
    assert "accounts" in data
    assert "inquiries" in data
    assert "recommendations" in data
    assert len(data["accounts"]) > 0


def test_get_report_after_fetch(api_client):
    headers = _register_and_auth(api_client)
    api_client.post(
        "/api/v1/credit-score/fetch",
        json={"provider": "cibil"},
        headers=headers,
    )
    response = api_client.get("/api/v1/credit-score/report", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["score"] is not None
    assert data["summary"]["total_accounts"] > 0


def test_get_score_after_fetch(api_client):
    headers = _register_and_auth(api_client)
    api_client.post(
        "/api/v1/credit-score/fetch",
        json={"provider": "experian"},
        headers=headers,
    )
    response = api_client.get("/api/v1/credit-score", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["has_report"] is True
    assert data["score"] is not None
    assert data["provider"] == "experian"


def test_consent_initiation(api_client):
    headers = _register_and_auth(api_client)
    response = api_client.post(
        "/api/v1/credit-score/consent",
        json={"provider": "cibil", "consent_purpose": "credit_monitoring"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["provider"] == "cibil"
    assert "consent_id" in data


def test_discover_accounts_no_report(api_client):
    headers = _register_and_auth(api_client)
    response = api_client.post(
        "/api/v1/credit-score/discover-accounts",
        json={},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["discovered_accounts"] == []


def test_discover_accounts_with_report(api_client):
    headers = _register_and_auth(api_client)
    api_client.post(
        "/api/v1/credit-score/fetch",
        json={"provider": "cibil"},
        headers=headers,
    )
    response = api_client.post(
        "/api/v1/credit-score/discover-accounts",
        json={},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["consent_active"] is True
    assert len(data["discovered_accounts"]) > 0
    for account in data["discovered_accounts"]:
        assert "institution" in account
        assert "account_type" in account
        assert "suggested_name" in account


def test_import_account(api_client):
    headers = _register_and_auth(api_client)
    response = api_client.post(
        "/api/v1/credit-score/import-account",
        json={
            "account_type": "credit_card",
            "institution": "HDFC Bank",
            "balance": 15000.0,
            "credit_limit": 200000.0,
            "name": "HDFC Credit Card",
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "HDFC Credit Card"
    assert data["type"] == "credit_card"


def test_import_duplicate_account(api_client):
    headers = _register_and_auth(api_client)
    payload = {
        "account_type": "credit_card",
        "institution": "SBI",
        "balance": 5000.0,
        "name": "SBI Card Dup Test",
    }
    r1 = api_client.post("/api/v1/credit-score/import-account", json=payload, headers=headers)
    assert r1.status_code == 200
    r2 = api_client.post("/api/v1/credit-score/import-account", json=payload, headers=headers)
    assert r2.status_code == 409


def test_report_summary_fields(api_client):
    headers = _register_and_auth(api_client)
    api_client.post(
        "/api/v1/credit-score/fetch",
        json={"provider": "cibil"},
        headers=headers,
    )
    response = api_client.get("/api/v1/credit-score/report", headers=headers)
    data = response.json()
    summary = data["summary"]
    assert "total_accounts" in summary
    assert "active_accounts" in summary
    assert "credit_utilization_percent" in summary
    assert "total_emi_obligation" in summary
    assert "inquiries_last_6_months" in summary
