from datetime import date
from uuid import uuid4

from tests.test_api_versioning import auth_headers, register_user


def test_create_list_amortize_pay_and_archive_loan(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Loan Payment Account",
            "type": "checking",
            "currency": "INR",
            "balance": 500000.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    create_response = api_client.post(
        "/api/v1/loans",
        json={
            "name": "Car Loan - HDFC",
            "loan_type": "car",
            "principal_amount": 240000.0,
            "interest_rate": 9.0,
            "tenure_months": 24,
            "start_date": date.today().isoformat(),
            "emi_day": date.today().day,
            "lender": "HDFC",
            "account_id": account_id,
            "notes": "Primary family car",
        },
        headers=headers,
    )
    assert create_response.status_code == 200, create_response.text
    created = create_response.json()
    loan_id = created["id"]
    assert created["emi_amount"] > 0
    assert created["next_due_date"] == date.today().isoformat()

    list_response = api_client.get("/api/v1/loans", headers=headers)
    assert list_response.status_code == 200, list_response.text
    list_payload = list_response.json()
    assert list_payload["summary"]["active_count"] == 1
    assert len(list_payload["loans"]) == 1
    assert list_payload["upcoming_emis"][0]["loan_id"] == loan_id

    summary_response = api_client.get("/api/v1/loans/summary", headers=headers)
    assert summary_response.status_code == 200, summary_response.text
    assert summary_response.json()["total_outstanding"] == 240000.0

    amortization_response = api_client.get(f"/api/v1/loans/{loan_id}/amortization", headers=headers)
    assert amortization_response.status_code == 200, amortization_response.text
    amortization_payload = amortization_response.json()
    assert amortization_payload["remaining_tenure_months"] >= 1
    assert len(amortization_payload["schedule"]) == 24
    assert amortization_payload["schedule"][0]["is_current"] is True

    payment_response = api_client.post(
        f"/api/v1/loans/{loan_id}/payment",
        json={"amount": 15000.0, "date": date.today().isoformat()},
        headers=headers,
    )
    assert payment_response.status_code == 200, payment_response.text
    payment_payload = payment_response.json()
    assert payment_payload["loan"]["outstanding_amount"] < 240000.0
    assert payment_payload["principal_component"] > 0

    archive_response = api_client.delete(f"/api/v1/loans/{loan_id}", headers=headers)
    assert archive_response.status_code == 200, archive_response.text
    assert archive_response.json() == {"message": "Loan archived successfully"}

    active_list_response = api_client.get("/api/v1/loans", headers=headers)
    assert active_list_response.status_code == 200, active_list_response.text
    assert active_list_response.json()["loans"] == []
