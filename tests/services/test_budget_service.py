from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from models import Account, Category, Transaction, TransactionType
from schemas import BudgetCreate, BudgetUpdate
from services.budget_service import BudgetService
from user_models import User


@pytest.fixture
def budget_service(db_session):
    return BudgetService(db_session)


@pytest.fixture
def setup_budget_data(db_session):
    user = User(id="budget-user", email="budget@example.com", hashed_password="hashed")
    account = Account(
        id="budget-account",
        name="Budget Account",
        type="checking",
        currency="USD",
        balance=1000.0,
        owner_id=user.id,
    )
    food_category = Category(id="food-category", name="Food", type="expense", color="#ef4444", owner_id=user.id)
    travel_category = Category(id="travel-category", name="Travel", type="expense", color="#3b82f6", owner_id=user.id)
    income_category = Category(id="income-category", name="Salary", type="income", color="#10b981", owner_id=user.id)

    db_session.add_all([user, account, food_category, travel_category, income_category])
    db_session.commit()

    return user, account, food_category, travel_category, income_category


def test_get_budgets_calculates_current_period_spending(budget_service, setup_budget_data, db_session):
    user, account, food_category, travel_category, _ = setup_budget_data
    now = datetime.utcnow().replace(microsecond=0)
    last_month = (now.replace(day=1) - timedelta(days=1)).replace(hour=12, minute=0, second=0)

    db_session.add_all(
        [
            Transaction(
                id="food-current",
                amount=120.0,
                type=TransactionType.expense.value,
                description="Groceries",
                date=now,
                timestamp=int(now.timestamp()),
                owner_id=user.id,
                account_id=account.id,
                category_id=food_category.id,
            ),
            Transaction(
                id="travel-current",
                amount=75.0,
                type=TransactionType.expense.value,
                description="Taxi",
                date=now,
                timestamp=int(now.timestamp()),
                owner_id=user.id,
                account_id=account.id,
                category_id=travel_category.id,
            ),
            Transaction(
                id="food-previous",
                amount=210.0,
                type=TransactionType.expense.value,
                description="Old groceries",
                date=last_month,
                timestamp=int(last_month.timestamp()),
                owner_id=user.id,
                account_id=account.id,
                category_id=food_category.id,
            ),
        ]
    )
    db_session.commit()

    food_budget = budget_service.create_budget(
        user.id,
        BudgetCreate(name="Monthly Food Budget", category_id=food_category.id, amount=200.0, period="monthly"),
    )
    overall_budget = budget_service.create_budget(
        user.id,
        BudgetCreate(name="Monthly Spending", amount=250.0, period="monthly"),
    )

    budgets = {budget["id"]: budget for budget in budget_service.get_budgets(user.id)}

    assert budgets[food_budget["id"]]["spent"] == 120.0
    assert budgets[food_budget["id"]]["remaining"] == 80.0
    assert budgets[food_budget["id"]]["status"] == "on_track"

    assert budgets[overall_budget["id"]]["spent"] == 195.0
    assert budgets[overall_budget["id"]]["remaining"] == 55.0
    assert budgets[overall_budget["id"]]["status"] == "on_track"


def test_check_budget_alerts_returns_warning_and_exceeded(budget_service, setup_budget_data, db_session):
    user, account, food_category, travel_category, _ = setup_budget_data
    now = datetime.utcnow().replace(microsecond=0)

    db_session.add_all(
        [
            Transaction(
                id="food-alert",
                amount=90.0,
                type=TransactionType.expense.value,
                description="Groceries",
                date=now,
                timestamp=int(now.timestamp()),
                owner_id=user.id,
                account_id=account.id,
                category_id=food_category.id,
            ),
            Transaction(
                id="travel-alert",
                amount=150.0,
                type=TransactionType.expense.value,
                description="Flight",
                date=now,
                timestamp=int(now.timestamp()),
                owner_id=user.id,
                account_id=account.id,
                category_id=travel_category.id,
            ),
        ]
    )
    db_session.commit()

    budget_service.create_budget(
        user.id,
        BudgetCreate(name="Food Budget", category_id=food_category.id, amount=100.0, period="monthly"),
    )
    budget_service.create_budget(
        user.id,
        BudgetCreate(name="Travel Budget", category_id=travel_category.id, amount=120.0, period="monthly"),
    )

    alerts = budget_service.check_budget_alerts(user.id)

    assert [alert["severity"] for alert in alerts] == ["exceeded", "warning"]
    assert alerts[0]["budget"]["name"] == "Travel Budget"
    assert alerts[1]["budget"]["name"] == "Food Budget"


def test_update_budget_changes_progress_and_delete_removes_budget(budget_service, setup_budget_data):
    user, _, food_category, _, _ = setup_budget_data

    created = budget_service.create_budget(
        user.id,
        BudgetCreate(name="Weekly Food", category_id=food_category.id, amount=50.0, period="weekly"),
    )

    updated = budget_service.update_budget(
        user.id,
        created["id"],
        BudgetUpdate(name="Weekly Meals", amount=80.0, is_active=False, start_date=date(2025, 1, 1)),
    )

    assert updated["name"] == "Weekly Meals"
    assert updated["amount"] == 80.0
    assert updated["is_active"] is False
    assert updated["start_date"] == date(2025, 1, 1)

    budget_service.delete_budget(user.id, created["id"])
    assert budget_service.get_budgets(user.id) == []


def test_create_budget_rejects_income_categories(budget_service, setup_budget_data):
    user, _, _, _, income_category = setup_budget_data

    with pytest.raises(HTTPException) as exc:
        budget_service.create_budget(
            user.id,
            BudgetCreate(name="Income Budget", category_id=income_category.id, amount=100.0, period="monthly"),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Budget category must be an expense category"



def test_get_budgets_uses_cached_progress(budget_service, setup_budget_data, db_session, cache_store):
    user, account, food_category, _, _ = setup_budget_data
    now = datetime.utcnow().replace(microsecond=0)

    db_session.add(
        Transaction(
            id="budget-cache-expense-1",
            amount=80.0,
            type=TransactionType.expense.value,
            description="Groceries",
            date=now,
            timestamp=int(now.timestamp()),
            owner_id=user.id,
            account_id=account.id,
            category_id=food_category.id,
        )
    )
    db_session.commit()

    budget_service.create_budget(
        user.id,
        BudgetCreate(name="Cached Food Budget", category_id=food_category.id, amount=200.0, period="monthly"),
    )

    first_budgets = budget_service.get_budgets(user.id)

    db_session.add(
        Transaction(
            id="budget-cache-expense-2",
            amount=50.0,
            type=TransactionType.expense.value,
            description="Direct insert",
            date=now,
            timestamp=int(now.timestamp()) + 1,
            owner_id=user.id,
            account_id=account.id,
            category_id=food_category.id,
        )
    )
    db_session.commit()

    cached_budgets = budget_service.get_budgets(user.id)
    assert cached_budgets == first_budgets
    assert f"budget_progress:{user.id}" in cache_store
    assert cache_store[f"budget_progress:{user.id}"][0]["spent"] == 80.0
