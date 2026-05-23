from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from tests.test_api_integration import auth_headers, register_user


def test_detect_confirm_and_summarize_subscriptions(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"
    category_id = f"cat-{uuid4().hex}"

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Subscription Account",
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
            "name": "Subscriptions",
            "type": "expense",
            "color": "#8b5cf6",
        },
        headers=headers,
    )
    assert category_response.status_code == 200, category_response.text

    today = date.today()
    recurring_dates = [today - timedelta(days=91), today - timedelta(days=61), today - timedelta(days=30)]

    for index, tx_date in enumerate(recurring_dates, start=1):
        tx_datetime = datetime.combine(tx_date, datetime.min.time(), tzinfo=timezone.utc)
        response = api_client.post(
            "/api/v1/transactions",
            json={
                "id": f"tx-{uuid4().hex}",
                "amount": 499.0,
                "type": "expense",
                "description": f"NETFLIX {index}",
                "date": tx_datetime.isoformat(),
                "timestamp": int(tx_datetime.timestamp()),
                "account_id": account_id,
                "category_id": category_id,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

    detect_response = api_client.get("/api/v1/subscriptions/detect", headers=headers)
    assert detect_response.status_code == 200, detect_response.text
    suggestions = detect_response.json()
    assert len(suggestions) == 1
    suggestion_id = suggestions[0]["id"]
    assert suggestions[0]["frequency"] == "monthly"

    confirm_response = api_client.post(f"/api/v1/subscriptions/{suggestion_id}/confirm", headers=headers)
    assert confirm_response.status_code == 200, confirm_response.text
    confirmed_payload = confirm_response.json()
    assert confirmed_payload["auto_detected"] is True
    assert confirmed_payload["amount"] == 499.0

    summary_response = api_client.get("/api/v1/subscriptions/summary", headers=headers)
    assert summary_response.status_code == 200, summary_response.text
    summary_payload = summary_response.json()
    assert summary_payload["active_count"] == 1
    assert summary_payload["monthly_cost"] == 499.0
    assert len(summary_payload["upcoming_renewals"]) == 1

    delete_response = api_client.delete(f"/api/v1/subscriptions/{confirmed_payload['id']}", headers=headers)
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json() == {"message": "Subscription cancelled successfully"}

    list_response = api_client.get("/api/v1/subscriptions", headers=headers)
    assert list_response.status_code == 200, list_response.text
    assert list_response.json() == []
