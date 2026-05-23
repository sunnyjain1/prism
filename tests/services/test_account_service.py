import pytest
from fastapi import HTTPException
from services.account_service import AccountService
from schemas import AccountCreate
from models import Account
from user_models import User

@pytest.fixture
def account_service(db_session):
    return AccountService(db_session)

@pytest.fixture
def setup_user(db_session):
    user = User(id="user1", email="test@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.commit()
    return user

def test_create_account(account_service, setup_user, db_session):
    user = setup_user
    acc_in = AccountCreate(id="acc1", name="Checking", type="checking", currency="USD", balance=0.0)
    
    acc = account_service.create_account(acc_in, user.id)
    assert acc.name == "Checking"
    assert acc.owner_id == user.id


def test_create_account_generates_id(account_service, setup_user):
    user = setup_user
    acc = account_service.create_account(AccountCreate(name="Auto ID", type="checking"), user.id)
    assert acc.id
    assert acc.owner_id == user.id

def test_create_duplicate_account_fails(account_service, setup_user):
    user = setup_user
    acc_in = AccountCreate(id="acc1", name="Checking", type="checking", currency="USD", balance=0.0)
    account_service.create_account(acc_in, user.id)
    
    with pytest.raises(HTTPException) as exc:
        account_service.create_account(acc_in, user.id)
    assert exc.value.status_code == 400

def test_get_accounts(account_service, setup_user):
    user = setup_user
    account_service.create_account(AccountCreate(id="acc1", name="A1", type="checking"), user.id)
    account_service.create_account(AccountCreate(id="acc2", name="A2", type="savings"), user.id)
    
    accounts = account_service.get_accounts(user.id)
    assert len(accounts) == 2

def test_get_account_not_found(account_service, setup_user):
    user = setup_user
    with pytest.raises(HTTPException) as exc:
        account_service.get_account("non-existent", user.id)
    assert exc.value.status_code == 404

def test_calculate_monthly_stats(account_service, setup_user, db_session):
    from models import Transaction
    from datetime import datetime, timedelta, timezone
    
    user = setup_user
    acc = account_service.create_account(AccountCreate(id="acc_stats", name="Stats Acc", type="checking"), user.id)
    
    # Add transactions
    now = datetime.now(timezone.utc)
    this_month = datetime(now.year, now.month, 1) + timedelta(hours=1)
    last_month = this_month - timedelta(days=5)
    
    # 1. Income this month
    tx1 = Transaction(id="tx1", amount=1000.0, type="income", date=this_month, owner_id=user.id, account_id=acc.id, timestamp=0)
    # 2. Expense this month
    tx2 = Transaction(id="tx2", amount=400.0, type="expense", date=this_month, owner_id=user.id, account_id=acc.id, timestamp=0)
    # 3. Income last month (should be ignored)
    tx3 = Transaction(id="tx3", amount=5000.0, type="income", date=last_month, owner_id=user.id, account_id=acc.id, timestamp=0)
    
    db_session.add_all([tx1, tx2, tx3])
    db_session.commit()
    
    # Reload account
    acc_loaded = account_service.get_account(acc.id, user.id)
    
    assert acc_loaded.monthly_income == 1000.0
    assert acc_loaded.monthly_expense == 400.0

def test_delete_account(account_service, setup_user, db_session):
    user = setup_user
    acc = account_service.create_account(AccountCreate(id="acc1", name="Delete Me", type="checking"), user.id)
    account_service.delete_account(acc.id, user.id)
    
    with pytest.raises(HTTPException):
        account_service.get_account(acc.id, user.id)
