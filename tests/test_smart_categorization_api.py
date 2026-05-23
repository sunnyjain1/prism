from datetime import datetime, timezone
from uuid import uuid4


def register_user(client, user_agent: str = "pytest-register") -> tuple[dict, dict]:
    suffix = uuid4().hex
    payload = {
        "email": f"smart-api-{suffix}@example.com",
        "password": "Password123!",
        "full_name": "Smart Categorization User",
    }
    response = client.post(
        "/api/v1/auth/register",
        json=payload,
        headers={"user-agent": user_agent},
    )
    assert response.status_code == 200, response.text
    return payload, response.json()



def login_user(client, email: str, password: str, user_agent: str = "pytest-login") -> dict:
    response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"user-agent": user_agent},
    )
    assert response.status_code == 200, response.text
    return response.json()



def auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}



def test_categorization_endpoints_learn_and_apply_patterns(api_client):
    user_payload, _ = register_user(api_client)
    tokens = login_user(api_client, user_payload["email"], user_payload["password"])
    headers = auth_headers(tokens["access_token"])

    account_id = f"acct-{uuid4().hex}"
    create_account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Categorization Account",
            "type": "checking",
            "currency": "INR",
            "balance": 5000.0,
        },
        headers=headers,
    )
    assert create_account_response.status_code == 200, create_account_response.text

    groceries_category_id = f"cat-{uuid4().hex}"
    create_category_response = api_client.post(
        "/api/v1/categories",
        json={
            "id": groceries_category_id,
            "name": "Groceries",
            "type": "expense",
            "color": "#f97316",
        },
        headers=headers,
    )
    assert create_category_response.status_code == 200, create_category_response.text

    tx_time = datetime.now(timezone.utc).replace(microsecond=0)
    first_transaction_id = f"tx-{uuid4().hex}"
    create_first_tx_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": first_transaction_id,
            "amount": 180.0,
            "type": "expense",
            "description": "UPI/FRESH BASKET/1111",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()),
            "account_id": account_id,
        },
        headers=headers,
    )
    assert create_first_tx_response.status_code == 200, create_first_tx_response.text
    assert create_first_tx_response.json()["category_id"] is None

    update_first_tx_response = api_client.put(
        f"/api/v1/transactions/{first_transaction_id}",
        json={"category_id": groceries_category_id},
        headers=headers,
    )
    assert update_first_tx_response.status_code == 200, update_first_tx_response.text
    assert update_first_tx_response.json()["categorization_method"] == "manual"

    patterns_response = api_client.get("/api/v1/categorize/patterns", headers=headers)
    assert patterns_response.status_code == 200, patterns_response.text
    patterns = patterns_response.json()
    assert len(patterns) == 1
    assert patterns[0]["merchant_pattern"] == "Fresh Basket"
    assert patterns[0]["category_id"] == groceries_category_id

    suggest_response = api_client.post(
        "/api/v1/categorize/suggest",
        json={
            "description": "UPI/FRESH BASKET/2222",
            "amount": 220.0,
            "type": "expense",
        },
        headers=headers,
    )
    assert suggest_response.status_code == 200, suggest_response.text
    suggestion = suggest_response.json()
    assert suggestion["method"] == "user_history"
    assert suggestion["category_id"] == groceries_category_id
    assert suggestion["normalized_merchant"] == "Fresh Basket"

    second_transaction_id = f"tx-{uuid4().hex}"
    create_second_tx_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": second_transaction_id,
            "amount": 240.0,
            "type": "expense",
            "description": "UPI/FRESH BASKET/3333",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()) + 1,
            "account_id": account_id,
        },
        headers=headers,
    )
    assert create_second_tx_response.status_code == 200, create_second_tx_response.text
    assert create_second_tx_response.json()["category_id"] == groceries_category_id
    assert create_second_tx_response.json()["categorization_method"] == "user_history"

    third_transaction_id = f"tx-{uuid4().hex}"
    create_third_tx_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": third_transaction_id,
            "amount": 260.0,
            "type": "expense",
            "description": "UPI/FRESH BASKET/4444",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()) + 2,
            "account_id": account_id,
        },
        headers=headers,
    )
    assert create_third_tx_response.status_code == 200, create_third_tx_response.text
    assert create_third_tx_response.json()["category_id"] == groceries_category_id

    bulk_response = api_client.post(
        "/api/v1/categorize/bulk",
        json={
            "apply": True,
            "transactions": [
                {
                    "transaction_id": third_transaction_id,
                },
                {
                    "description": "UPI-SWIGGY-5555",
                    "amount": 300.0,
                    "type": "expense",
                },
            ],
        },
        headers=headers,
    )
    assert bulk_response.status_code == 200, bulk_response.text
    bulk_payload = bulk_response.json()
    assert bulk_payload[0]["transaction_id"] == third_transaction_id
    assert bulk_payload[0]["category_id"] == groceries_category_id
    assert bulk_payload[0]["applied"] is False
    assert bulk_payload[1]["method"] == "keyword"
    assert bulk_payload[1]["category_name"] == "Food & Dining"
