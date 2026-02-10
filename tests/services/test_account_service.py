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

def test_delete_account(account_service, setup_user, db_session):
    user = setup_user
    acc = account_service.create_account(AccountCreate(id="acc1", name="Delete Me", type="checking"), user.id)
    account_service.delete_account(acc.id, user.id)
    
    with pytest.raises(HTTPException):
        account_service.get_account(acc.id, user.id)
