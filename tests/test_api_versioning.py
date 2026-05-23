from datetime import datetime, timezone
from uuid import uuid4

from main import app


DEFAULT_PASSWORD = "Password123!"


def register_user(client) -> tuple[dict, dict]:
    payload = {
        "email": f"versioning-{uuid4().hex}@example.com",
        "password": DEFAULT_PASSWORD,
        "full_name": "Versioning User",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()



def auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}



def test_versioned_and_legacy_routes_are_registered():
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/api/v1/auth/login" in paths
    assert "/auth/login" in paths
    assert "/api/v1/accounts" in paths
    assert "/api/accounts" in paths
    assert "/api/v1/transactions" in paths
    assert "/api/transactions" in paths
    assert "/api/v1/search" in paths
    assert "/api/v1/categorization-rules" in paths
    assert "/api/categorization-rules" in paths
    assert "/api/v1/notifications" in paths
    assert "/api/notifications" in paths
    assert "/api/v1/reports" in paths
    assert "/api/reports" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/jobs" in paths
    assert "/api/v1/investments" in paths
    assert "/api/investments" in paths
    assert "/api/v1/net-worth" in paths
    assert "/api/net-worth" in paths
    assert "/api/v1/health-score" in paths
    assert "/api/health-score" in paths
    assert "/api/v1/loans" in paths
    assert "/api/loans" in paths
    assert "/api/v1/budgets" in paths
    assert "/api/budgets" in paths



def test_versioned_transactions_openapi_uses_paginated_response():
    openapi = app.openapi()

    assert "/api/v1/transactions" in openapi["paths"]
    assert "/api/transactions" not in openapi["paths"]

    response_schema = openapi["paths"]["/api/v1/transactions"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema_name = response_schema["$ref"].split("/")[-1]
    component = openapi["components"]["schemas"][schema_name]

    assert {"items", "total", "skip", "limit"}.issubset(set(component["required"]))



def test_api_v1_routes_work_for_authenticated_requests(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"

    me_response = api_client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200, me_response.text

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Versioned Account",
            "type": "checking",
            "currency": "USD",
            "balance": 250.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    accounts_response = api_client.get("/api/v1/accounts", headers=headers)
    assert accounts_response.status_code == 200, accounts_response.text
    assert [account["id"] for account in accounts_response.json()] == [account_id]



def test_http_exception_uses_standard_error_response(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthorized",
        "message": "Could not validate credentials",
    }



def test_validation_error_uses_standard_error_response(client):
    response = client.post("/api/v1/auth/register", json={})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "validation_error"
    assert payload["message"] == "Request validation failed"
    assert payload["details"]["errors"]



def test_not_found_error_uses_standard_error_response(api_client):
    _, tokens = register_user(api_client)
    response = api_client.get(
        "/api/v1/accounts/missing-account",
        headers=auth_headers(tokens["access_token"]),
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Account not found",
    }



def test_versioned_transactions_return_paginated_payload(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"
    first_tx_time = datetime.now(timezone.utc).replace(microsecond=0)
    second_tx_time = datetime.now(timezone.utc).replace(microsecond=0)

    create_account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Pagination Account",
            "type": "checking",
            "currency": "USD",
            "balance": 0.0,
        },
        headers=headers,
    )
    assert create_account_response.status_code == 200, create_account_response.text

    for suffix, amount, tx_time in (("one", 10.0, first_tx_time), ("two", 25.0, second_tx_time)):
        response = api_client.post(
            "/api/v1/transactions",
            json={
                "id": f"tx-{suffix}-{uuid4().hex}",
                "amount": amount,
                "type": "income",
                "description": f"Transaction {suffix}",
                "date": tx_time.isoformat(),
                "timestamp": int(tx_time.timestamp()),
                "account_id": account_id,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

    response = api_client.get("/api/v1/transactions?skip=0&limit=1", headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"items", "total", "skip", "limit"}
    assert payload["total"] == 2
    assert payload["skip"] == 0
    assert payload["limit"] == 1
    assert len(payload["items"]) == 1