from datetime import date
from uuid import uuid4

from tests.test_api_integration import auth_headers, register_user



def test_net_worth_endpoints_calculate_current_snapshot_and_allocation(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])

    account_payloads = [
        {
            "id": f"acct-{uuid4().hex}",
            "name": "Household Checking",
            "type": "checking",
            "currency": "INR",
            "balance": 2000.0,
        },
        {
            "id": f"acct-{uuid4().hex}",
            "name": "Emergency Savings",
            "type": "savings",
            "currency": "INR",
            "balance": 5000.0,
        },
        {
            "id": f"acct-{uuid4().hex}",
            "name": "Brokerage Cash",
            "type": "investment",
            "currency": "INR",
            "balance": 3000.0,
        },
        {
            "id": f"acct-{uuid4().hex}",
            "name": "Rewards Card",
            "type": "credit_card",
            "currency": "INR",
            "balance": 1500.0,
        },
        {
            "id": f"acct-{uuid4().hex}",
            "name": "Car Loan",
            "type": "loan",
            "currency": "INR",
            "balance": 8000.0,
        },
    ]

    for payload in account_payloads:
        response = api_client.post("/api/v1/accounts", json=payload, headers=headers)
        assert response.status_code == 200, response.text

    investment_payloads = [
        {
            "name": "Index Fund",
            "type": "mutual_fund",
            "invested_amount": 10000.0,
            "current_value": 12000.0,
            "currency": "INR",
        },
        {
            "name": "Rental Property",
            "type": "real_estate",
            "invested_amount": 15000.0,
            "current_value": 18000.0,
            "currency": "INR",
        },
    ]

    for payload in investment_payloads:
        response = api_client.post("/api/v1/investments", json=payload, headers=headers)
        assert response.status_code == 200, response.text

    current_response = api_client.get("/api/v1/net-worth", headers=headers)
    assert current_response.status_code == 200, current_response.text
    current_payload = current_response.json()

    assert current_payload["total_assets"] == 40000.0
    assert current_payload["total_liabilities"] == 9500.0
    assert current_payload["net_worth"] == 30500.0
    assert current_payload["asset_breakdown"] == {
        "checking": 2000.0,
        "investment_accounts": 3000.0,
        "mutual_fund": 12000.0,
        "real_estate": 18000.0,
        "savings": 5000.0,
    }
    assert current_payload["liability_breakdown"] == {
        "credit_cards": 1500.0,
        "loans": 8000.0,
    }
    assert round(current_payload["debt_to_asset_ratio"], 4) == 0.2375

    snapshot_response = api_client.post("/api/v1/net-worth/snapshot", headers=headers)
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot_payload = snapshot_response.json()
    assert snapshot_payload["snapshot_date"] == date.today().isoformat()
    assert snapshot_payload["net_worth"] == 30500.0

    history_response = api_client.get("/api/v1/net-worth/history?months=12", headers=headers)
    assert history_response.status_code == 200, history_response.text
    history_payload = history_response.json()
    assert len(history_payload) == 1
    assert history_payload[0]["snapshot_date"] == date.today().isoformat()
    assert history_payload[0]["total_assets"] == 40000.0

    allocation_response = api_client.get("/api/v1/net-worth/allocation", headers=headers)
    assert allocation_response.status_code == 200, allocation_response.text
    allocation_payload = allocation_response.json()
    assert allocation_payload["total_assets"] == 40000.0
    assert allocation_payload["allocation"][0] == {
        "type": "real_estate",
        "value": 18000.0,
        "percentage": 45.0,
    }
    assert any(item["type"] == "credit_cards" for item in allocation_payload["allocation"]) is False
