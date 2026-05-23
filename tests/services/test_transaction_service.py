import pytest
from datetime import datetime
from fastapi import HTTPException
from services.transaction_service import TransactionService
from schemas import TransactionCreate, TransactionUpdate
from models import TransactionType, Account, Category, Notification, Transaction
from user_models import User

@pytest.fixture
def transaction_service(db_session):
    return TransactionService(db_session)

@pytest.fixture
def setup_data(db_session):
    # Create a user
    user = User(id="user1", email="test@example.com", hashed_password="hashed")
    db_session.add(user)
    
    # Create accounts
    acc1 = Account(id="acc1", name="Checking", type="checking", currency="USD", balance=1000.0, owner_id="user1")
    acc2 = Account(id="acc2", name="Savings", type="savings", currency="USD", balance=5000.0, owner_id="user1")
    db_session.add(acc1)
    db_session.add(acc2)
    
    # Create a category
    cat1 = Category(id="cat1", name="Food", type="expense", color="#ff0000", owner_id="user1")
    db_session.add(cat1)
    
    db_session.commit()
    return user, acc1, acc2, cat1

def test_create_income_transaction(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(
        id="tx1",
        amount=100.0,
        type=TransactionType.income,
        description="Salary",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        category_id=cat1.id
    )
    
    tx = transaction_service.create_transaction(tx_in, user.id)
    
    assert tx.amount == 100.0
    assert tx.type == TransactionType.income
    # Check balance update
    db_session.refresh(acc1)
    assert acc1.balance == 1100.0

def test_create_expense_transaction(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(
        id="tx2",
        amount=50.0,
        type=TransactionType.expense,
        description="Dinner",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        category_id=cat1.id
    )
    
    tx = transaction_service.create_transaction(tx_in, user.id)
    
    db_session.refresh(acc1)
    assert acc1.balance == 950.0

def test_create_transfer_transaction(transaction_service, setup_data, db_session):
    user, acc1, acc2, _ = setup_data
    tx_in = TransactionCreate(
        id="tx3",
        amount=200.0,
        type=TransactionType.transfer,
        description="Transfer",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        destination_account_id=acc2.id
    )
    
    tx = transaction_service.create_transaction(tx_in, user.id)
    
    db_session.refresh(acc1)
    db_session.refresh(acc2)
    assert acc1.balance == 800.0
    assert acc2.balance == 5200.0

def test_large_transaction_creates_notification(transaction_service, setup_data, db_session):
    user, acc1, _, _ = setup_data
    tx_in = TransactionCreate(
        id="tx_large_alert",
        amount=15000.0,
        type=TransactionType.expense,
        description="Rent payment",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
    )

    tx = transaction_service.create_transaction(tx_in, user.id)

    notification = db_session.query(Notification).filter(Notification.user_id == user.id).one()
    assert notification.title == "Large transaction detected"
    assert notification.type == "alert"
    assert notification.category == "transaction"
    assert notification.action_url == "/transactions"
    assert notification.extra_metadata["transaction_id"] == tx.id
    assert notification.extra_metadata["amount"] == 15000.0


def test_create_transfer_without_destination_fails(transaction_service, setup_data):
    user, acc1, _, _ = setup_data
    tx_in = TransactionCreate(
        id="tx4",
        amount=200.0,
        type=TransactionType.transfer,
        description="Transfer",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id
    )
    
    with pytest.raises(HTTPException) as exc:
        transaction_service.create_transaction(tx_in, user.id)
    assert exc.value.status_code == 400

def test_validate_ownership_fails_unauthorized_account(transaction_service, setup_data, db_session):
    # Create another user's account
    other_acc = Account(id="other_acc", name="Other", type="checking", currency="USD", balance=100.0, owner_id="user2")
    db_session.add(other_acc)
    db_session.commit()
    
    user, _, _, _ = setup_data
    tx_in = TransactionCreate(
        id="tx5",
        amount=100.0,
        type=TransactionType.income,
        description="Unauthorized",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id="other_acc"
    )
    
    with pytest.raises(HTTPException) as exc:
        transaction_service.create_transaction(tx_in, user.id)
    assert exc.value.status_code == 403

def test_update_transaction_metadata(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(
        id="tx6",
        amount=100.0,
        type=TransactionType.income,
        description="Old Description",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        category_id=cat1.id
    )
    tx = transaction_service.create_transaction(tx_in, user.id)
    
    update_in = TransactionCreate(
        id=tx.id,
        amount=100.0,
        type=TransactionType.income,
        description="New Description",
        date=tx.date,
        timestamp=tx.timestamp,
        account_id=acc1.id,
        category_id=cat1.id
    )
    
    updated_tx = transaction_service.update_transaction(tx.id, update_in, user.id)
    assert updated_tx.description == "New Description"

def test_update_transaction_amount_reverts_and_applies(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(
        id="tx7",
        amount=100.0,
        type=TransactionType.expense,
        description="Old Expense",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        category_id=cat1.id
    )
    tx = transaction_service.create_transaction(tx_in, user.id)
    # Balance: 1000 - 100 = 900
    
    update_in = TransactionCreate(
        id=tx.id,
        amount=300.0,
        type=TransactionType.expense,
        description="Updated Expense",
        date=tx.date,
        timestamp=tx.timestamp,
        account_id=acc1.id,
        category_id=cat1.id
    )
    
    updated_tx = transaction_service.update_transaction(tx.id, update_in, user.id)
    db_session.refresh(acc1)
    # Expected: (900 + 100) - 300 = 700
    assert acc1.balance == 700.0


def test_update_transaction_partial_amount_rebalances(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(
        id="tx7_partial",
        amount=100.0,
        type=TransactionType.expense,
        description="Old Expense",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        category_id=cat1.id
    )
    tx = transaction_service.create_transaction(tx_in, user.id)

    update_in = TransactionUpdate(amount=300.0)

    updated_tx = transaction_service.update_transaction(tx.id, update_in, user.id)
    db_session.refresh(acc1)
    assert updated_tx.amount == 300.0
    assert updated_tx.description == "Old Expense"
    assert acc1.balance == 700.0

def test_delete_transaction(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(
        id="tx8",
        amount=100.0,
        type=TransactionType.expense,
        description="To Delete",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        category_id=cat1.id
    )
    tx = transaction_service.create_transaction(tx_in, user.id)
    # Balance: 900
    
    transaction_service.delete_transaction(tx.id, user.id)
    db_session.refresh(acc1)
    assert acc1.balance == 1000.0

def test_get_monthly_history(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    
    # Oct 2025
    tx1 = TransactionCreate(id="tx9", amount=500.0, type=TransactionType.income, description="I1", date=datetime(2025, 10, 15), timestamp=1, account_id=acc1.id)
    # Nov 2025
    tx2 = TransactionCreate(id="tx10", amount=200.0, type=TransactionType.expense, description="E1", date=datetime(2025, 11, 5), timestamp=2, account_id=acc1.id)
    
    transaction_service.create_transaction(tx1, user.id)
    transaction_service.create_transaction(tx2, user.id)
    
    history = transaction_service.get_monthly_history(user.id, months=3, end_month=12, end_year=2025)
    
    # Should have entries for 2025-10 and 2025-11
    assert len(history) >= 2
    assert any(h["month"] == "2025-10" and h["income"] == 500.0 for h in history)
    assert any(h["month"] == "2025-11" and h["expense"] == 200.0 for h in history)

def test_get_monthly_history_non_dec(transaction_service, setup_data):
    user, acc1, _, _ = setup_data
    transaction_service.get_monthly_history(user.id, months=3, end_month=6, end_year=2025)

def test_get_transactions_with_all_filters(transaction_service, setup_data):
    user, acc1, _, cat1 = setup_data
    # Search filter
    tx = TransactionCreate(id="tx_filt", amount=10, type=TransactionType.income, description="Filter Me", date=datetime(2025,1,1), timestamp=1, account_id=acc1.id, category_id=cat1.id, notes="SecretNote")
    transaction_service.create_transaction(tx, user.id)
    
    # Filter by category_ids
    res = transaction_service.get_transactions(user.id, category_ids=[cat1.id])
    assert len(res) >= 1
    
    # Filter by account_id
    res = transaction_service.get_transactions(user.id, account_id=acc1.id)
    assert len(res) >= 1
    
    # Filter by search
    res = transaction_service.get_transactions(user.id, search="Secret")
    assert len(res) >= 1
    
    # Filter by date range
    res = transaction_service.get_transactions(user.id, start_date=datetime(2025,1,1), end_date=datetime(2025,1,31))
    assert len(res) >= 1
    
    # Test Dec/Year roll
    txs_dec = transaction_service.get_transactions(user.id, month=12, year=2025)
    assert len(txs_dec) == 0

def test_validate_ownership_fails_unauthorized_destination(transaction_service, setup_data, db_session):
    other_user = User(id="user2", email="o@e.com", hashed_password="h")
    db_session.add(other_user)
    other_acc = Account(id="other_acc_dst", name="OtherDst", type="checking", currency="USD", balance=100.0, owner_id="user2")
    db_session.add(other_acc)
    db_session.commit()
    
    user, acc1, _, _ = setup_data
    tx_in = TransactionCreate(
        id="tx12",
        amount=100.0,
        type=TransactionType.transfer,
        description="Unauthorized Dst",
        date=datetime.now(),
        timestamp=int(datetime.now().timestamp()),
        account_id=acc1.id,
        destination_account_id=other_acc.id
    )
    
    with pytest.raises(HTTPException) as exc:
        transaction_service.create_transaction(tx_in, user.id)
    assert exc.value.status_code == 403

def test_update_transaction_not_found(transaction_service, setup_data):
    user, _, _, _ = setup_data
    tx_in = TransactionCreate(id="nx", amount=10, type=TransactionType.income, description="x", date=datetime.now(), timestamp=1)
    with pytest.raises(HTTPException) as exc:
        transaction_service.update_transaction("non-existent", tx_in, user.id)
    assert exc.value.status_code == 404

def test_delete_transaction_not_found(transaction_service, setup_data):
    user, _, _, _ = setup_data
    with pytest.raises(HTTPException) as exc:
        transaction_service.delete_transaction("non-existent", user.id)
    assert exc.value.status_code == 404

def test_get_monthly_history_default_end(transaction_service, setup_data):
    user, _, _, _ = setup_data
    transaction_service.get_monthly_history(user.id, months=3)

def test_update_transaction_metadata_exclusive(transaction_service, setup_data, db_session):
    from schemas import TransactionUpdate
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(id="tx_excl", amount=100.0, type=TransactionType.income, description="Old", date=datetime.now(), timestamp=1, account_id=acc1.id)
    tx = transaction_service.create_transaction(tx_in, user.id)
    
    # Use TransactionUpdate to only send metadata
    update_in = TransactionUpdate(description="Only Meta Change")
    updated_tx = transaction_service.update_transaction(tx.id, update_in, user.id)
    assert updated_tx.description == "Only Meta Change"
    assert updated_tx.amount == 100.0 # Unchanged

def test_update_transaction_metadata_only(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    tx_in = TransactionCreate(id="tx_meta", amount=100.0, type=TransactionType.income, description="Old", date=datetime.now(), timestamp=1, account_id=acc1.id)
    tx = transaction_service.create_transaction(tx_in, user.id)
    
    update_in = TransactionCreate(id=tx.id, amount=100.0, type=TransactionType.income, description="New Meta", date=tx.date, timestamp=tx.timestamp, account_id=acc1.id, notes="New Note")
    updated_tx = transaction_service.update_transaction(tx.id, update_in, user.id)
    assert updated_tx.description == "New Meta"
    assert updated_tx.notes == "New Note"

def test_revert_transfer_balance(transaction_service, setup_data, db_session):
    user, acc1, acc2, _ = setup_data
    tx_in = TransactionCreate(id="tx_rev_tr", amount=200.0, type=TransactionType.transfer, description="TR", date=datetime.now(), timestamp=1, account_id=acc1.id, destination_account_id=acc2.id)
    tx = transaction_service.create_transaction(tx_in, user.id)
    # acc1: 800, acc2: 5200
    
    transaction_service.delete_transaction(tx.id, user.id)
    db_session.refresh(acc1)
    db_session.refresh(acc2)
    assert acc1.balance == 1000.0
    assert acc2.balance == 5000.0

def test_get_transaction_summary(transaction_service, setup_data, db_session):
    user, acc1, _, cat1 = setup_data
    # Create income and expense transactions for Jan 2025
    tx1 = TransactionCreate(id="tx_sum1", amount=500.0, type=TransactionType.income, description="Salary", date=datetime(2025, 1, 15), timestamp=1, account_id=acc1.id)
    tx2 = TransactionCreate(id="tx_sum2", amount=200.0, type=TransactionType.expense, description="Groceries", date=datetime(2025, 1, 20), timestamp=2, account_id=acc1.id, category_id=cat1.id)
    tx3 = TransactionCreate(id="tx_sum3", amount=100.0, type=TransactionType.expense, description="Coffee", date=datetime(2025, 1, 25), timestamp=3, account_id=acc1.id)
    # Transaction outside the target month (Feb)
    tx4 = TransactionCreate(id="tx_sum4", amount=999.0, type=TransactionType.income, description="Bonus", date=datetime(2025, 2, 1), timestamp=4, account_id=acc1.id)
    
    for tx in [tx1, tx2, tx3, tx4]:
        transaction_service.create_transaction(tx, user.id)
    
    summary = transaction_service.get_transaction_summary(user.id, month=1, year=2025)
    
    # Should have entries for income and expense, grouped by currency
    income_entries = [s for s in summary if s["type"] == "income"]
    expense_entries = [s for s in summary if s["type"] == "expense"]
    
    assert len(income_entries) == 1
    assert income_entries[0]["total"] == 500.0
    assert income_entries[0]["currency"] == "USD"  # acc1 currency
    
    assert len(expense_entries) == 1
    assert expense_entries[0]["total"] == 300.0  # 200 + 100



def test_summary_cache_invalidates_after_transaction_write(transaction_service, setup_data, cache_store):
    user, acc1, _, _ = setup_data
    transaction_service.create_transaction(
        TransactionCreate(
            id="tx_cache_sum_1",
            amount=500.0,
            type=TransactionType.income,
            description="Salary",
            date=datetime(2025, 1, 15),
            timestamp=1,
            account_id=acc1.id,
        ),
        user.id,
    )

    cached_summary = transaction_service.get_transaction_summary(user.id, month=1, year=2025)
    assert cache_store["dashboard:user1:2025:1"] == cached_summary

    transaction_service.create_transaction(
        TransactionCreate(
            id="tx_cache_sum_2",
            amount=150.0,
            type=TransactionType.expense,
            description="Groceries",
            date=datetime(2025, 1, 20),
            timestamp=2,
            account_id=acc1.id,
        ),
        user.id,
    )

    refreshed_summary = transaction_service.get_transaction_summary(user.id, month=1, year=2025)
    expense_entries = [item for item in refreshed_summary if item["type"] == "expense"]
    assert expense_entries[0]["total"] == 150.0



def test_monthly_history_uses_cached_value(transaction_service, setup_data, db_session, cache_store):
    user, acc1, _, _ = setup_data
    transaction_service.create_transaction(
        TransactionCreate(
            id="tx_cache_history_1",
            amount=300.0,
            type=TransactionType.income,
            description="Consulting",
            date=datetime(2025, 10, 10),
            timestamp=1,
            account_id=acc1.id,
        ),
        user.id,
    )

    first_history = transaction_service.get_monthly_history(user.id, months=3, end_month=12, end_year=2025)

    db_session.add(
        Transaction(
            id="tx_cache_history_2",
            amount=125.0,
            type=TransactionType.expense,
            description="Direct insert",
            date=datetime(2025, 10, 12),
            timestamp=2,
            owner_id=user.id,
            account_id=acc1.id,
        )
    )
    db_session.commit()

    cached_history = transaction_service.get_monthly_history(user.id, months=3, end_month=12, end_year=2025)
    assert cached_history == first_history
    assert cache_store["dashboard:user1:2025:12:history:3"] == first_history

