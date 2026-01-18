from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas, database
from .dependencies import get_current_user, check_role
from ..user_models import User, UserRole


router = APIRouter(prefix="/api/accounts", tags=["accounts"])

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.Account)
def create_account(
    account: schemas.AccountCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(check_role([UserRole.ADMIN, UserRole.EDITOR]))
):
    db_account = models.Account(**account.dict(), owner_id=current_user.id)
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


@router.get("/", response_model=List[schemas.Account])
def read_accounts(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    accounts = db.query(models.Account).filter(models.Account.owner_id == current_user.id).offset(skip).limit(limit).all()
    return accounts


@router.get("/{account_id}", response_model=schemas.Account)
def read_account(
    account_id: str, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = db.query(models.Account).filter(
        models.Account.id == account_id,
        models.Account.owner_id == current_user.id
    ).first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account

