from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from core.dependencies import get_db, get_current_user
from user_models import User
import schemas
from services.account_service import AccountService
from services.account_discovery_service import AccountDiscoveryService
from repositories.sync_repository import SyncRepository

router = APIRouter(prefix="/accounts", tags=["accounts"])

@router.get("/discover", response_model=List[dict])
def discover_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    sync_repo = SyncRepository(db)
    refresh_token = sync_repo.get_decrypted_refresh_token(current_user.id)
    if not refresh_token:
        return [] # Or raise error if preferred, but empty list is safer for UI
    
    discovery_service = AccountDiscoveryService(refresh_token)
    return discovery_service.discover_accounts()

@router.get("/{account_id}/portfolio", response_model=schemas.PortfolioResponse)
def get_account_portfolio(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Mock portfolio for investment accounts
    service = AccountService(db)
    account = service.get_account(account_id, current_user.id)
    if account.type != "investment":
        return {"total_value": 0, "holdings": []}
    
    # In a real app, this would call CAMS API or similar
    # For now, we return mock data as requested
    return {
        "total_value": account.balance,
        "holdings": [
            {"symbol": "RELIANCE", "name": "Reliance Industries", "quantity": 10, "avg_price": 2400, "current_price": 2950, "gain_pct": 22.9},
            {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "quantity": 50, "avg_price": 1550, "current_price": 1450, "gain_pct": -6.4},
            {"symbol": "INFY", "name": "Infosys Ltd", "quantity": 25, "avg_price": 1400, "current_price": 1620, "gain_pct": 15.7},
            {"symbol": "TATASTEEL", "name": "Tata Steel", "quantity": 100, "avg_price": 120, "current_price": 155, "gain_pct": 29.1}
        ]
    }

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
    return service.update_account(account_id, account.model_dump(exclude_unset=True), current_user.id)

@router.post("/{account_id}/restore", response_model=schemas.Account)
def restore_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    return service.restore_account(account_id, current_user.id)

@router.delete("/{account_id}", response_model=schemas.MessageResponse)
def delete_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = AccountService(db)
    service.delete_account(account_id, current_user.id)
    return {"message": "Account deleted successfully"}
