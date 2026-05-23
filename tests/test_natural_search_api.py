from datetime import datetime
from uuid import uuid4

from test_api_integration import auth_headers, register_user


def test_natural_search_endpoint_returns_parsed_interpretation_and_results(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])

    account_id = f"acct-{uuid4().hex}"
    category_id = f"cat-{uuid4().hex}"

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Primary",
            "type": "checking",
            "currency": "INR",
            "balance": 10000.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    category_response = api_client.post(
        "/api/v1/categories",
        json={
            "id": category_id,
            "name": "Transport",
            "type": "expense",
            "color": "#111111",
        },
        headers=headers,
    )
    assert category_response.status_code == 200, category_response.text

    transactions = [
        {
            "id": f"tx-{uuid4().hex}",
            "amount": 1000.0,
            "type": "expense",
            "description": "Petrol pump",
            "merchant": "Shell",
            "date": datetime(2025, 1, 5, 9, 0, 0).isoformat(),
            "timestamp": 1,
            "account_id": account_id,
            "category_id": category_id,
        },
        {
            "id": f"tx-{uuid4().hex}",
            "amount": 2000.0,
            "type": "expense",
            "description": "Office commute",
            "notes": "petrol voucher",
            "date": datetime(2025, 1, 10, 9, 0, 0).isoformat(),
            "timestamp": 2,
            "account_id": account_id,
            "category_id": category_id,
        },
        {
            "id": f"tx-{uuid4().hex}",
            "amount": 500.0,
            "type": "expense",
            "description": "Groceries",
            "date": datetime(2025, 1, 12, 9, 0, 0).isoformat(),
            "timestamp": 3,
            "account_id": account_id,
            "category_id": category_id,
        },
    ]

    for payload in transactions:
        response = api_client.post("/api/v1/transactions", json=payload, headers=headers)
        assert response.status_code == 200, response.text

    response = api_client.get(
        "/api/v1/search/natural",
        params={"q": "how much did I spend on petrol"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "petrol"
    assert body["total"] == 2
    assert body["aggregations"]["total_amount"] == 3000.0
    assert body["parsed_query"]["search"] == "petrol"
    assert body["parsed_query"]["type"] == "expense"
    assert body["parsed_query"]["aggregate"] == "sum"
    assert body["interpretation"] == "Showing total expenses matching 'petrol'"
