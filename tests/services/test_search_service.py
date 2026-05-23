from datetime import datetime

from models import Account, Category, TransactionType
from schemas import TransactionCreate
from services.search_service import SearchService
from services.transaction_service import TransactionService
from user_models import User
from core.config import settings


def test_search_service_falls_back_to_sql_and_returns_aggregations(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_ENABLED", False)

    user = User(id="search-user", email="search@example.com", hashed_password="hashed")
    account = Account(id="search-acc", name="Primary Account", type="checking", currency="INR", balance=10000.0, owner_id=user.id)
    transport = Category(id="search-cat-transport", name="Transport", type="expense", color="#111111", owner_id=user.id)
    other = Category(id="search-cat-other", name="Other", type="expense", color="#222222", owner_id=user.id)
    db_session.add_all([user, account, transport, other])
    db_session.commit()

    transaction_service = TransactionService(db_session)
    transactions = [
        TransactionCreate(
            id="search-tx-1",
            amount=1000.0,
            type=TransactionType.expense,
            description="Petrol pump",
            merchant="Shell",
            date=datetime(2025, 1, 5, 9, 0, 0),
            timestamp=1,
            account_id=account.id,
            category_id=transport.id,
        ),
        TransactionCreate(
            id="search-tx-2",
            amount=2000.0,
            type=TransactionType.expense,
            description="PETROL refill",
            merchant="IndianOil",
            date=datetime(2025, 2, 3, 9, 0, 0),
            timestamp=2,
            account_id=account.id,
            category_id=transport.id,
        ),
        TransactionCreate(
            id="search-tx-3",
            amount=1500.0,
            type=TransactionType.expense,
            description="Fuel card",
            notes="petrol voucher",
            date=datetime(2025, 1, 20, 9, 0, 0),
            timestamp=3,
            account_id=account.id,
            category_id=other.id,
        ),
        TransactionCreate(
            id="search-tx-4",
            amount=500.0,
            type=TransactionType.expense,
            description="Groceries",
            merchant="Fresh Mart",
            date=datetime(2025, 1, 10, 9, 0, 0),
            timestamp=4,
            account_id=account.id,
            category_id=other.id,
        ),
    ]

    for transaction in transactions:
        transaction_service.create_transaction(transaction, user.id)

    result = SearchService(db_session).search(user.id, "petrol", {"limit": 2, "offset": 0})

    assert result["total"] == 3
    assert [hit["id"] for hit in result["hits"]] == ["search-tx-2", "search-tx-3"]
    assert result["aggregations"] == {
        "total_amount": 4500.0,
        "count": 3,
        "by_category": {"Other": 1, "Transport": 2},
        "by_month": {"2025-01": 2500.0, "2025-02": 2000.0},
        "average_amount": 1500.0,
    }


def test_create_transaction_ignores_search_queue_failures(db_session, monkeypatch):
    user = User(id="search-safe-user", email="safe@example.com", hashed_password="hashed")
    account = Account(id="search-safe-acc", name="Checking", type="checking", currency="USD", balance=1000.0, owner_id=user.id)
    db_session.add_all([user, account])
    db_session.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(SearchService, "queue_index_transaction", boom)

    service = TransactionService(db_session)
    transaction = service.create_transaction(
        TransactionCreate(
            id="search-safe-tx",
            amount=100.0,
            type=TransactionType.income,
            description="Salary",
            date=datetime(2025, 1, 1, 9, 0, 0),
            timestamp=1,
            account_id=account.id,
        ),
        user.id,
    )

    db_session.refresh(account)
    assert transaction.id == "search-safe-tx"
    assert account.balance == 1100.0
