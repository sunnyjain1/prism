from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import Account
from schemas import AccountCreate
from repositories.account_repository import AccountRepository
from typing import List, Optional

class AccountService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AccountRepository(db)

    def create_account(self, account_in: AccountCreate, owner_id: str) -> Account:
        # Check for duplication
        existing = self.repo.get_by_name_and_owner(account_in.name, owner_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"Account with name '{account_in.name}' already exists.")
            
        data = account_in.dict()
        data["owner_id"] = owner_id
        return self.repo.create(data)

    def get_accounts(self, owner_id: str) -> List[Account]:
        return self.repo.get_by_owner(owner_id)

    def get_account(self, account_id: str, owner_id: str) -> Account:
        account = self.repo.get_by_id_and_owner(account_id, owner_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return account

    def delete_account(self, account_id: str, owner_id: str) -> None:
        account = self.get_account(account_id, owner_id)
        self.repo.remove(account_id)
