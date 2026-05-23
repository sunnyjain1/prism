from datetime import date, datetime, timedelta

import pytest

from models import Account, Category, Subscription
from services.subscription_service import SubscriptionService
from services.transaction_service import TransactionService
from schemas import SubscriptionCreate, SubscriptionUpdate, TransactionCreate
from user_models import User


@pytest.fixture
def subscription_service(db_session):
    return SubscriptionService(db_session)


@pytest.fixture
def setup_data(db_session):
    user = User(id="user-sub", email="subs@example.com", hashed_password="hashed")
    account = Account(id="acc-sub", name="Checking", type="checking", currency="INR", balance=20000.0, owner_id=user.id)
    category = Category(id="cat-sub", name="Bills", type="expense", color="#123456", owner_id=user.id)
    db_session.add_all([user, account, category])
    db_session.commit()
    return user, account, category


def test_create_and_update_subscription(subscription_service, setup_data):
    user, account, category = setup_data
    created = subscription_service.create_subscription(
        user.id,
        SubscriptionCreate(
            name="Netflix",
            amount=499.0,
            currency="inr",
            frequency="monthly",
            account_id=account.id,
            category_id=category.id,
            last_paid_date=date(2026, 1, 5),
        ),
    )

    assert created.currency == "INR"
    assert created.next_due_date == date(2026, 2, 5)

    updated = subscription_service.update_subscription(
        user.id,
        created.id,
        SubscriptionUpdate(amount=649.0, frequency="quarterly"),
    )
    assert updated.amount == 649.0
    assert updated.frequency == "quarterly"
    assert updated.next_due_date == date(2026, 4, 5)


def test_detect_and_confirm_recurring_transactions(subscription_service, setup_data, db_session):
    user, account, category = setup_data
    transaction_service = TransactionService(db_session)
    transaction_dates = [datetime(2026, 1, 5), datetime(2026, 2, 4), datetime(2026, 3, 6)]

    for index, tx_date in enumerate(transaction_dates, start=1):
        transaction_service.create_transaction(
            TransactionCreate(
                id=f"sub-tx-{index}",
                amount=499.0 + index,
                type="expense",
                description=f"NETFLIX.COM {index}",
                date=tx_date,
                timestamp=index,
                account_id=account.id,
                category_id=category.id,
            ),
            user.id,
        )

    suggestions = subscription_service.detect_recurring_transactions(user.id)
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion["frequency"] == "monthly"
    assert suggestion["occurrences"] == 3

    confirmed = subscription_service.confirm_detected_subscription(user.id, suggestion["id"])
    assert confirmed.auto_detected is True
    assert confirmed.name == suggestion["name"]

    all_subscriptions = subscription_service.get_subscriptions(user.id)
    assert len(all_subscriptions) == 1
    assert subscription_service.get_monthly_subscription_cost(user.id) == pytest.approx(suggestion["amount"])


def test_get_upcoming_renewals_and_cancel_subscription(subscription_service, setup_data, db_session):
    user, account, category = setup_data
    last_paid = date.today() - timedelta(days=30)
    subscription = subscription_service.create_subscription(
        user.id,
        {
            "name": "Gym Membership",
            "amount": 1200.0,
            "currency": "INR",
            "frequency": "monthly",
            "account_id": account.id,
            "category_id": category.id,
            "last_paid_date": last_paid,
        },
    )

    upcoming = subscription_service.get_upcoming_renewals(user.id, days=7)
    assert [item.id for item in upcoming] == [subscription.id]

    cancelled = subscription_service.cancel_subscription(user.id, subscription.id)
    assert cancelled.is_active is False
    assert subscription_service.get_subscriptions(user.id) == []
