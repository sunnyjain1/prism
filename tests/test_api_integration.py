from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import schemas
from models import HealthScoreSnapshot


def make_user_payload() -> dict:
    suffix = uuid4().hex
    return {
        "email": f"integration-{suffix}@example.com",
        "password": "Password123!",
        "full_name": "Integration Test User",
    }


def register_user(client, user_payload: dict | None = None, user_agent: str = "pytest-register") -> tuple[dict, dict]:
    payload = user_payload or make_user_payload()
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


def test_transaction_schema_normalizes_blank_optional_strings():
    transaction = schemas.Transaction.model_validate(
        {
            "id": "tx-blank-optional",
            "amount": 10.0,
            "type": "expense",
            "description": "Coffee",
            "merchant": "",
            "notes": "   ",
            "date": datetime.now(timezone.utc),
            "timestamp": 1,
        }
    )

    assert transaction.merchant is None
    assert transaction.notes is None


def test_auth_flow_register_login_refresh_and_logout(api_client):
    user, registered_tokens = register_user(api_client)

    login_tokens = login_user(api_client, user["email"], user["password"])
    assert login_tokens["refresh_token"]
    assert login_tokens["refresh_token"] != registered_tokens["refresh_token"]

    me_response = api_client.get("/api/v1/auth/me", headers=auth_headers(login_tokens["access_token"]))
    assert me_response.status_code == 200, me_response.text
    assert me_response.json() == {
        "id": me_response.json()["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": "editor",
    }

    refresh_response = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_tokens["refresh_token"]},
        headers={"user-agent": "pytest-refresh"},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed_tokens = refresh_response.json()
    assert refreshed_tokens["refresh_token"] != login_tokens["refresh_token"]

    logout_response = api_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refreshed_tokens["refresh_token"]},
    )
    assert logout_response.status_code == 200, logout_response.text
    assert logout_response.json() == {"message": "Logged out successfully"}

    reuse_response = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refreshed_tokens["refresh_token"]},
    )
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"] == "unauthorized"


def test_account_crud_flow_with_soft_delete_and_restore(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"

    create_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Emergency Fund",
            "type": "savings",
            "currency": "USD",
            "balance": 5000.0,
        },
        headers=headers,
    )
    assert create_response.status_code == 200, create_response.text
    assert create_response.json()["id"] == account_id

    list_response = api_client.get("/api/v1/accounts", headers=headers)
    assert list_response.status_code == 200, list_response.text
    assert [account["id"] for account in list_response.json()] == [account_id]

    update_response = api_client.put(
        f"/api/v1/accounts/{account_id}",
        json={"name": "Emergency Fund Updated", "currency": "INR"},
        headers=headers,
    )
    assert update_response.status_code == 200, update_response.text
    updated_account = update_response.json()
    assert updated_account["name"] == "Emergency Fund Updated"
    assert updated_account["currency"] == "INR"

    delete_response = api_client.delete(f"/api/v1/accounts/{account_id}", headers=headers)
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json() == {"message": "Account deleted successfully"}

    active_accounts_response = api_client.get("/api/v1/accounts", headers=headers)
    assert active_accounts_response.status_code == 200, active_accounts_response.text
    assert active_accounts_response.json() == []

    deleted_accounts_response = api_client.get("/api/v1/accounts/deleted", headers=headers)
    assert deleted_accounts_response.status_code == 200, deleted_accounts_response.text
    assert [account["id"] for account in deleted_accounts_response.json()] == [account_id]

    restore_response = api_client.post(f"/api/v1/accounts/{account_id}/restore", headers=headers)
    assert restore_response.status_code == 200, restore_response.text
    assert restore_response.json()["is_deleted"] is False

    restored_accounts_response = api_client.get("/api/v1/accounts", headers=headers)
    assert restored_accounts_response.status_code == 200, restored_accounts_response.text
    assert [account["id"] for account in restored_accounts_response.json()] == [account_id]


def test_transaction_flow_updates_balance_and_summary(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"
    tx_time = datetime.now(timezone.utc).replace(microsecond=0)

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Daily Spending",
            "type": "checking",
            "currency": "USD",
            "balance": 1000.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    transaction_id = f"tx-{uuid4().hex}"
    create_transaction_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": transaction_id,
            "amount": 250.0,
            "type": "expense",
            "description": "Groceries",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()),
            "account_id": account_id,
        },
        headers=headers,
    )
    assert create_transaction_response.status_code == 200, create_transaction_response.text
    assert create_transaction_response.json()["id"] == transaction_id

    account_details_response = api_client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert account_details_response.status_code == 200, account_details_response.text
    assert account_details_response.json()["balance"] == 750.0

    transactions_response = api_client.get("/api/v1/transactions", headers=headers)
    assert transactions_response.status_code == 200, transactions_response.text
    transactions_payload = transactions_response.json()
    assert transactions_payload["total"] == 1
    assert transactions_payload["items"][0]["id"] == transaction_id

    summary_response = api_client.get(
        f"/api/v1/transactions/summary?month={tx_time.month}&year={tx_time.year}",
        headers=headers,
    )
    assert summary_response.status_code == 200, summary_response.text
    assert summary_response.json() == [
        {"type": "expense", "currency": "USD", "total": 250.0}
    ]


def test_bulk_upload_creates_transactions_from_csv(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Imported Transactions",
            "type": "checking",
            "currency": "USD",
            "balance": 0.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    csv_content = "Date,Description,Amount\n2025-01-10,Coffee,-5.50\n2025-01-11,Salary,100.00\n"
    upload_response = api_client.post(
        "/api/v1/bulk/upload",
        headers=headers,
        data={
            "source_type": "generic_bank",
            "account_id": account_id,
            "auto_detect": "false",
            "skip_duplicates": "true",
        },
        files={"file": ("sample_upload.csv", csv_content, "text/csv")},
    )
    assert upload_response.status_code == 200, upload_response.text
    upload_payload = upload_response.json()
    assert upload_payload["count"] == 2
    assert upload_payload["failed"] == 0

    transactions_response = api_client.get("/api/v1/transactions", headers=headers)
    assert transactions_response.status_code == 200, transactions_response.text
    transactions_payload = transactions_response.json()
    assert transactions_payload["total"] == 2
    assert {item["description"] for item in transactions_payload["items"]} == {"Coffee", "Salary"}

    account_details_response = api_client.get(f"/api/v1/accounts/{account_id}", headers=headers)
    assert account_details_response.status_code == 200, account_details_response.text
    assert account_details_response.json()["balance"] == 94.5


def test_health_score_endpoints_return_current_score_and_history(api_client, db_session):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    checking_id = f"acct-checking-{uuid4().hex}"
    savings_id = f"acct-savings-{uuid4().hex}"
    tx_time = datetime.now(timezone.utc).replace(microsecond=0)

    for account_id, name, account_type, balance in (
        (checking_id, "Primary Checking", "checking", 0.0),
        (savings_id, "Emergency Savings", "savings", 90000.0),
    ):
        response = api_client.post(
            "/api/v1/accounts",
            json={
                "id": account_id,
                "name": name,
                "type": account_type,
                "currency": "INR",
                "balance": balance,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

    for transaction_id, amount, tx_type, description in (
        (f"tx-income-{uuid4().hex}", 100000.0, "income", "Salary"),
        (f"tx-expense-{uuid4().hex}", 50000.0, "expense", "Rent and bills"),
    ):
        response = api_client.post(
            "/api/v1/transactions",
            json={
                "id": transaction_id,
                "amount": amount,
                "type": tx_type,
                "description": description,
                "date": tx_time.isoformat(),
                "timestamp": int(tx_time.timestamp()),
                "account_id": checking_id,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

    investment_response = api_client.post(
        "/api/v1/investments",
        json={
            "name": "Balanced Fund",
            "type": "mutual_fund",
            "invested_amount": 25000.0,
            "current_value": 26000.0,
            "currency": "INR",
            "is_active": True,
        },
        headers=headers,
    )
    assert investment_response.status_code == 200, investment_response.text

    loan_response = api_client.post(
        "/api/v1/loans",
        json={
            "name": "Car Loan",
            "loan_type": "car",
            "principal_amount": 300000.0,
            "outstanding_amount": 180000.0,
            "interest_rate": 8.0,
            "emi_amount": 12000.0,
            "is_active": True,
        },
        headers=headers,
    )
    assert loan_response.status_code == 200, loan_response.text

    current_response = api_client.get("/api/v1/health-score", headers=headers)
    assert current_response.status_code == 200, current_response.text
    current_payload = current_response.json()
    assert current_payload["has_enough_data"] is True
    assert current_payload["score"] == 80
    assert current_payload["grade"] == "A"
    assert current_payload["components"]["savings_rate"]["label"] == "Savings Rate: 50%"
    assert current_payload["components"]["debt_ratio"]["label"] == "Debt-to-Income: 12%"

    history_response = api_client.get("/api/v1/health-score/history", headers=headers)
    assert history_response.status_code == 200, history_response.text
    history_payload = history_response.json()
    assert len(history_payload) == 1
    assert history_payload[0]["score"] == current_payload["score"]
    assert db_session.query(HealthScoreSnapshot).count() == 1



def test_notification_endpoints_track_large_transaction_alerts(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"
    tx_time = datetime.now(timezone.utc).replace(microsecond=0)

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "High Value Account",
            "type": "checking",
            "currency": "INR",
            "balance": 50000.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    create_transaction_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": f"tx-{uuid4().hex}",
            "amount": 15000.0,
            "type": "expense",
            "description": "Laptop purchase",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()),
            "account_id": account_id,
        },
        headers=headers,
    )
    assert create_transaction_response.status_code == 200, create_transaction_response.text

    count_response = api_client.get("/api/v1/notifications/count", headers=headers)
    assert count_response.status_code == 200, count_response.text
    assert count_response.json() == {"unread_count": 1}

    notifications_response = api_client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert notifications_response.status_code == 200, notifications_response.text
    notifications_payload = notifications_response.json()
    assert len(notifications_payload) == 1
    notification_id = notifications_payload[0]["id"]
    assert notifications_payload[0]["type"] == "alert"
    assert notifications_payload[0]["category"] == "transaction"
    assert notifications_payload[0]["metadata"]["amount"] == 15000.0

    mark_read_response = api_client.patch(f"/api/v1/notifications/{notification_id}/read", headers=headers)
    assert mark_read_response.status_code == 200, mark_read_response.text
    assert mark_read_response.json()["is_read"] is True

    create_second_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": f"tx-{uuid4().hex}",
            "amount": 12000.0,
            "type": "expense",
            "description": "Phone purchase",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()),
            "account_id": account_id,
        },
        headers=headers,
    )
    assert create_second_response.status_code == 200, create_second_response.text

    mark_all_response = api_client.post("/api/v1/notifications/read-all", headers=headers)
    assert mark_all_response.status_code == 200, mark_all_response.text
    assert mark_all_response.json() == {"updated_count": 1}

    final_count_response = api_client.get("/api/v1/notifications/count", headers=headers)
    assert final_count_response.status_code == 200, final_count_response.text
    assert final_count_response.json() == {"unread_count": 0}


def test_investment_crud_flow_and_portfolio_summary(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])

    create_response = api_client.post(
        "/api/v1/investments",
        json={
            "name": "HDFC Mid-Cap Fund",
            "type": "mutual_fund",
            "symbol": "123456",
            "quantity": 100,
            "buy_price": 10.0,
            "current_price": 12.5,
            "buy_date": "2025-01-01",
            "invested_amount": 1000.0,
        },
        headers=headers,
    )
    assert create_response.status_code == 200, create_response.text
    investment = create_response.json()
    investment_id = investment["id"]
    assert investment["current_value"] == 1250.0

    list_response = api_client.get("/api/v1/investments", headers=headers)
    assert list_response.status_code == 200, list_response.text
    assert [item["id"] for item in list_response.json()] == [investment_id]

    filtered_response = api_client.get("/api/v1/investments?type=mutual_fund", headers=headers)
    assert filtered_response.status_code == 200, filtered_response.text
    assert [item["id"] for item in filtered_response.json()] == [investment_id]

    detail_response = api_client.get(f"/api/v1/investments/{investment_id}", headers=headers)
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["name"] == "HDFC Mid-Cap Fund"

    refresh_response = api_client.post(f"/api/v1/investments/{investment_id}/refresh-price", headers=headers)
    assert refresh_response.status_code == 200, refresh_response.text

    update_response = api_client.put(
        f"/api/v1/investments/{investment_id}",
        json={"current_price": 13.0},
        headers=headers,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["current_value"] == 1300.0

    summary_response = api_client.get("/api/v1/investments/portfolio", headers=headers)
    assert summary_response.status_code == 200, summary_response.text
    assert summary_response.json() == {
        "total_invested": 1000.0,
        "total_current_value": 1300.0,
        "total_returns": 300.0,
        "returns_percentage": 30.0,
        "allocation_by_type": {"mutual_fund": 1300.0},
        "top_performers": [
            {
                "id": investment_id,
                "name": "HDFC Mid-Cap Fund",
                "type": "mutual_fund",
                "invested_amount": 1000.0,
                "current_value": 1300.0,
                "total_returns": 300.0,
                "returns_percentage": 30.0,
            }
        ],
        "worst_performers": [
            {
                "id": investment_id,
                "name": "HDFC Mid-Cap Fund",
                "type": "mutual_fund",
                "invested_amount": 1000.0,
                "current_value": 1300.0,
                "total_returns": 300.0,
                "returns_percentage": 30.0,
            }
        ],
    }

    delete_response = api_client.delete(f"/api/v1/investments/{investment_id}", headers=headers)
    assert delete_response.status_code == 200, delete_response.text
    assert delete_response.json() == {"message": "Investment deleted successfully"}

    final_list_response = api_client.get("/api/v1/investments", headers=headers)
    assert final_list_response.status_code == 200, final_list_response.text
    assert final_list_response.json() == []


def test_budget_endpoints_return_progress_and_alerts(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"
    category_id = f"cat-{uuid4().hex}"
    tx_time = datetime.now(timezone.utc).replace(microsecond=0)

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Budget Account",
            "type": "checking",
            "currency": "USD",
            "balance": 1000.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    category_response = api_client.post(
        "/api/v1/categories",
        json={"id": category_id, "name": "Dining", "type": "expense", "color": "#ef4444"},
        headers=headers,
    )
    assert category_response.status_code == 200, category_response.text

    transaction_response = api_client.post(
        "/api/v1/transactions",
        json={
            "id": f"tx-{uuid4().hex}",
            "amount": 90.0,
            "type": "expense",
            "description": "Dinner",
            "date": tx_time.isoformat(),
            "timestamp": int(tx_time.timestamp()),
            "account_id": account_id,
            "category_id": category_id,
        },
        headers=headers,
    )
    assert transaction_response.status_code == 200, transaction_response.text

    create_budget_response = api_client.post(
        "/api/v1/budgets",
        json={
            "name": "Dining Budget",
            "category_id": category_id,
            "amount": 100.0,
            "period": "monthly",
        },
        headers=headers,
    )
    assert create_budget_response.status_code == 200, create_budget_response.text
    created_budget = create_budget_response.json()
    assert created_budget["spent"] == 90.0
    assert created_budget["remaining"] == 10.0
    assert created_budget["status"] == "warning"

    budgets_response = api_client.get("/api/v1/budgets", headers=headers)
    assert budgets_response.status_code == 200, budgets_response.text
    budgets_payload = budgets_response.json()
    assert len(budgets_payload) == 1
    assert budgets_payload[0]["category"]["id"] == category_id

    alerts_response = api_client.get("/api/v1/budgets/alerts", headers=headers)
    assert alerts_response.status_code == 200, alerts_response.text
    alerts_payload = alerts_response.json()
    assert alerts_payload[0]["severity"] == "warning"
    assert alerts_payload[0]["budget"]["id"] == created_budget["id"]

    update_budget_response = api_client.put(
        f"/api/v1/budgets/{created_budget['id']}",
        json={"amount": 80.0},
        headers=headers,
    )
    assert update_budget_response.status_code == 200, update_budget_response.text
    assert update_budget_response.json()["status"] == "exceeded"

    delete_budget_response = api_client.delete(f"/api/v1/budgets/{created_budget['id']}", headers=headers)
    assert delete_budget_response.status_code == 200, delete_budget_response.text
    assert delete_budget_response.json() == {"message": "Budget deleted successfully"}

    final_budgets_response = api_client.get("/api/v1/budgets", headers=headers)
    assert final_budgets_response.status_code == 200, final_budgets_response.text
    assert final_budgets_response.json() == []


def test_report_generation_and_quick_exports(api_client):
    _, tokens = register_user(api_client)
    headers = auth_headers(tokens["access_token"])
    account_id = f"acct-{uuid4().hex}"
    category_id = f"cat-{uuid4().hex}"

    account_response = api_client.post(
        "/api/v1/accounts",
        json={
            "id": account_id,
            "name": "Reports Account",
            "type": "checking",
            "currency": "USD",
            "balance": 1000.0,
        },
        headers=headers,
    )
    assert account_response.status_code == 200, account_response.text

    category_response = api_client.post(
        "/api/v1/categories",
        json={
            "id": category_id,
            "name": "Food",
            "type": "expense",
            "color": "#ef4444",
        },
        headers=headers,
    )
    assert category_response.status_code == 200, category_response.text

    for tx_id, amount, tx_type, description, day in [
        (f"tx-income-{uuid4().hex}", 2500.0, "income", "Salary", 3),
        (f"tx-expense-{uuid4().hex}", 120.0, "expense", "Coffee", 12),
    ]:
        tx_time = datetime(2025, 1, day, tzinfo=timezone.utc).replace(microsecond=0)
        response = api_client.post(
            "/api/v1/transactions",
            json={
                "id": tx_id,
                "amount": amount,
                "type": tx_type,
                "description": description,
                "date": tx_time.isoformat(),
                "timestamp": int(tx_time.timestamp()),
                "account_id": account_id,
                "category_id": category_id if tx_type == "expense" else None,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

    report_response = api_client.post(
        "/api/v1/reports/generate",
        json={
            "report_type": "monthly_summary",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "format": "pdf",
        },
        headers=headers,
    )
    assert report_response.status_code == 200, report_response.text
    job_payload = report_response.json()
    assert job_payload["name"] == "generate_report"
    assert job_payload["status"] == "completed"
    assert job_payload["result"]["download_url"].endswith(
        f"/api/v1/reports/{job_payload['result']['report_id']}/download"
    )

    jobs_response = api_client.get("/api/v1/jobs", headers=headers)
    assert jobs_response.status_code == 200, jobs_response.text
    jobs_payload = jobs_response.json()
    assert [job["id"] for job in jobs_payload] == [job_payload["id"]]

    job_status_response = api_client.get(f"/api/v1/jobs/{job_payload['id']}", headers=headers)
    assert job_status_response.status_code == 200, job_status_response.text
    assert job_status_response.json()["result"]["report_id"] == job_payload["result"]["report_id"]

    reports_response = api_client.get("/api/v1/reports", headers=headers)
    assert reports_response.status_code == 200, reports_response.text
    reports_payload = reports_response.json()
    assert [report["id"] for report in reports_payload] == [job_payload["result"]["report_id"]]

    download_response = api_client.get(job_payload["result"]["download_url"], headers=headers)
    assert download_response.status_code == 200, download_response.text
    assert download_response.headers["content-type"].startswith("text/html")
    assert "Monthly Summary" in download_response.text
    Path(job_payload["result"]["file_path"]).unlink(missing_ok=True)

    csv_response = api_client.post(
        "/api/v1/reports/export/csv",
        json={"start_date": "2025-01-01", "end_date": "2025-01-31"},
        headers=headers,
    )
    assert csv_response.status_code == 200, csv_response.text
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "Salary" in csv_response.text
    assert "Coffee" in csv_response.text

    xlsx_response = api_client.post(
        "/api/v1/reports/export/xlsx",
        json={"start_date": "2025-01-01", "end_date": "2025-01-31"},
        headers=headers,
    )
    assert xlsx_response.status_code == 200, xlsx_response.text
    assert xlsx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(xlsx_response.content) > 100
