from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from core.dependencies import get_db, get_current_user
from user_models import User
import schemas
from services.account_service import AccountService

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

@router.post("", response_model=schemas.Account)
def create_account(
    account: schemas.AccountCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.create_account(account, current_user.id)

@router.get("", response_model=List[schemas.Account])
def read_accounts(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.get_accounts(current_user.id)

@router.get("/deleted", response_model=List[schemas.Account])
def read_deleted_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.get_deleted_accounts(current_user.id)

@router.get("/{account_id}", response_model=schemas.Account)
def read_account(
    account_id: str, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.get_account(account_id, current_user.id)

@router.put("/{account_id}", response_model=schemas.Account)
def update_account(
    account_id: str,
    account: schemas.AccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.update_account(account_id, account.dict(exclude_unset=True), current_user.id)

@router.post("/{account_id}/restore", response_model=schemas.Account)
def restore_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.restore_account(account_id, current_user.id)

@router.delete("/{account_id}")
def delete_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    service.delete_account(account_id, current_user.id)
    return {"message": "Account deleted successfully"}
