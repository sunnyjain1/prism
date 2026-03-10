from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import Account
from schemas import AccountCreate
from repositories.account_repository import AccountRepository
from typing import List, Optional
from datetime import datetime, timezone

class AccountService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AccountRepository(db)

    def create_account(self, account_in: AccountCreate, owner_id: str) -> Account:
        # Check for duplication
        existing = self.repo.get_by_name_and_owner(account_in.name, owner_id)
        if existing:
            raise HTTPException(status_code=400, detail=f"Account with name '{account_in.name}' already exists.")
            
        data = account_in.model_dump()
        data["owner_id"] = owner_id
        data["is_deleted"] = False
        return self.repo.create(data)

    def _calculate_monthly_stats(self, account: Account) -> None:
        """Calculate income and expense for the current month for an account."""
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1)
        
        income = 0.0
        expense = 0.0
        
        for tx in account.transactions:
            if tx.date >= start_of_month:
                if tx.type == "income":
                    income += tx.amount
                elif tx.type == "expense":
                    expense += tx.amount
        
        account.monthly_income = income
        account.monthly_expense = expense

    def get_accounts(self, owner_id: str) -> List[Account]:
        accounts = self.repo.get_by_owner(owner_id)
        for acc in accounts:
            self._calculate_monthly_stats(acc)
        return accounts

    def get_account(self, account_id: str, owner_id: str) -> Account:
        account = self.repo.get_by_id_and_owner(account_id, owner_id)
        if not account or account.is_deleted:
            raise HTTPException(status_code=404, detail="Account not found")
        self._calculate_monthly_stats(account)
        return account

    def update_account(self, account_id: str, update_data: dict, owner_id: str) -> Account:
        account = self.get_account(account_id, owner_id)
        for key in ['name', 'type', 'currency', 'billing_cycle_day', 'credit_limit']:
            if key in update_data:
                setattr(account, key, update_data[key])
        self.db.commit()
        self.db.refresh(account)
        self._calculate_monthly_stats(account)
        return account

    def delete_account(self, account_id: str, owner_id: str) -> None:
        account = self.get_account(account_id, owner_id)
        account.is_deleted = True
        account.deleted_at = datetime.now(timezone.utc)
        self.db.commit()

    def get_deleted_accounts(self, owner_id: str) -> List[Account]:
        return self.repo.get_deleted_by_owner(owner_id)

    def restore_account(self, account_id: str, owner_id: str) -> Account:
        account = self.repo.get_by_id_and_owner(account_id, owner_id)
        if not account or not account.is_deleted:
            raise HTTPException(status_code=400, detail="Account is not deleted")
        account.is_deleted = False
        account.deleted_at = None
        self.db.commit()
        self.db.refresh(account)
        return account
