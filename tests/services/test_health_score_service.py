from datetime import date, datetime, timezone

from models import Account, Budget, Category, HealthScoreSnapshot, Investment, Loan, Transaction
from services.health_score_service import HealthScoreService
from user_models import User


CURRENT_MONTH = datetime.now(timezone.utc).replace(microsecond=0)



def test_calculate_health_score_returns_weighted_breakdown(db_session):
    user = User(id="health-user", email="health@example.com", hashed_password="hashed")
    groceries = Category(id="cat-groceries", name="Groceries", type="expense", owner_id=user.id)
    utilities = Category(id="cat-utilities", name="Utilities", type="expense", owner_id=user.id)
    checking = Account(id="acct-checking", name="Checking", type="checking", currency="INR", balance=0.0, owner_id=user.id)
    savings = Account(id="acct-savings", name="Emergency Fund", type="savings", currency="INR", balance=150000.0, owner_id=user.id)

    db_session.add_all([
        user,
        groceries,
        utilities,
        checking,
        savings,
        Budget(user_id=user.id, name="Groceries Budget", category_id=groceries.id, amount=40000.0, period="monthly", is_active=True),
        Budget(user_id=user.id, name="Utilities Budget", category_id=utilities.id, amount=35000.0, period="monthly", is_active=True),
        Transaction(
            id="tx-income",
            amount=100000.0,
            type="income",
            description="Salary",
            date=CURRENT_MONTH,
            timestamp=int(CURRENT_MONTH.timestamp()),
            owner_id=user.id,
            account_id=checking.id,
        ),
        Transaction(
            id="tx-groceries",
            amount=30000.0,
            type="expense",
            description="Groceries",
            date=CURRENT_MONTH,
            timestamp=int(CURRENT_MONTH.timestamp()),
            owner_id=user.id,
            account_id=checking.id,
            category_id=groceries.id,
        ),
        Transaction(
            id="tx-utilities",
            amount=45000.0,
            type="expense",
            description="Utilities",
            date=CURRENT_MONTH,
            timestamp=int(CURRENT_MONTH.timestamp()),
            owner_id=user.id,
            account_id=checking.id,
            category_id=utilities.id,
        ),
        Loan(
            user_id=user.id,
            name="Home Loan",
            loan_type="home",
            principal_amount=500000.0,
            outstanding_amount=450000.0,
            interest_rate=8.5,
            emi_amount=15000.0,
            is_active=True,
        ),
        Investment(user_id=user.id, name="Index Fund", type="mutual_fund", invested_amount=50000.0, current_value=52000.0),
        Investment(user_id=user.id, name="Bluechip Equity", type="stock", invested_amount=25000.0, current_value=26000.0),
    ])
    db_session.commit()

    payload = HealthScoreService().calculate_health_score(user.id, db_session)

    assert payload["score"] == 75
    assert payload["grade"] == "B+"
    assert payload["has_enough_data"] is True
    assert payload["components"]["savings_rate"] == {
        "score": 80,
        "value": 0.25,
        "label": "Savings Rate: 25%",
        "has_data": True,
    }
    assert payload["components"]["debt_ratio"] == {
        "score": 100,
        "value": 0.15,
        "label": "Debt-to-Income: 15%",
        "has_data": True,
    }
    assert payload["components"]["emergency_fund"] == {
        "score": 60,
        "value": 2.0,
        "label": "Emergency Fund: 2 months",
        "has_data": True,
    }
    assert payload["components"]["diversification"] == {
        "score": 60,
        "value": 2.0,
        "label": "2 investment types",
        "has_data": True,
    }
    assert payload["components"]["budget_adherence"] == {
        "score": 60,
        "value": 0.5,
        "label": "50% budgets on track",
        "has_data": True,
    }
    assert payload["recommendations"] == [
        "Build an emergency fund covering 3-6 months of expenses",
        "Consider diversifying across mutual funds, stocks, and fixed deposits",
        "Review and adjust your budgets to be more realistic",
    ]



def test_calculate_health_score_handles_missing_data(db_session):
    user = User(id="health-empty", email="empty@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.commit()

    payload = HealthScoreService().calculate_health_score(user.id, db_session)

    assert payload["score"] is None
    assert payload["grade"] is None
    assert payload["has_enough_data"] is False
    assert payload["message"] == "Not enough data"
    assert payload["recommendations"] == []
    assert payload["components"]["budget_adherence"]["has_data"] is False
    assert payload["components"]["diversification"] == {
        "score": 20,
        "value": 0.0,
        "label": "0 investment types",
        "has_data": True,
    }



def test_get_current_score_persists_single_monthly_snapshot(db_session):
    user = User(id="health-history", email="history@example.com", hashed_password="hashed")
    checking = Account(id="acct-history", name="Checking", type="checking", currency="INR", balance=0.0, owner_id=user.id)
    savings = Account(id="acct-history-savings", name="Savings", type="savings", currency="INR", balance=60000.0, owner_id=user.id)

    db_session.add_all([
        user,
        checking,
        savings,
        Transaction(
            id="tx-history-income",
            amount=80000.0,
            type="income",
            description="Salary",
            date=CURRENT_MONTH,
            timestamp=int(CURRENT_MONTH.timestamp()),
            owner_id=user.id,
            account_id=checking.id,
        ),
        Transaction(
            id="tx-history-expense",
            amount=40000.0,
            type="expense",
            description="Rent",
            date=CURRENT_MONTH,
            timestamp=int(CURRENT_MONTH.timestamp()),
            owner_id=user.id,
            account_id=checking.id,
        ),
        Loan(
            user_id=user.id,
            name="Car Loan",
            loan_type="car",
            principal_amount=200000.0,
            outstanding_amount=120000.0,
            interest_rate=7.0,
            emi_amount=10000.0,
            is_active=True,
        ),
    ])
    db_session.commit()

    service = HealthScoreService()
    first_payload = service.get_current_score(user.id, db_session)
    second_payload = service.get_current_score(user.id, db_session)
    history = service.get_health_score_history(user.id, db_session, months=3)

    snapshots = db_session.query(HealthScoreSnapshot).filter(HealthScoreSnapshot.user_id == user.id).all()

    assert first_payload["score"] == second_payload["score"]
    assert len(snapshots) == 1
    assert history == [
        {
            "score": first_payload["score"],
            "grade": first_payload["grade"],
            "snapshot_date": date.today().replace(day=1),
            "created_at": snapshots[0].created_at,
        }
    ]
