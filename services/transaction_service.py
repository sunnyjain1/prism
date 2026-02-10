from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import Transaction, Account, TransactionType
from schemas import TransactionCreate
from repositories.transaction_repository import TransactionRepository
from typing import List, Optional
from datetime import datetime

class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TransactionRepository(db)

    def create_transaction(self, transaction_in: TransactionCreate, owner_id: str) -> Transaction:
        # Business Logic: Prevent transfers without destination
        if transaction_in.type == TransactionType.transfer and not transaction_in.destination_account_id:
            raise HTTPException(status_code=400, detail="Destination account required for transfer")

        # Create the transaction record
        tx_data = transaction_in.dict()
        tx_data["owner_id"] = owner_id
        
        # Validation checks
        self._validate_ownership(tx_data, owner_id)
        
        db_transaction = self.repo.create(tx_data)

        # Business Logic: Update account balances
        self._update_balances(db_transaction, owner_id)
        
        return db_transaction

    def _validate_ownership(self, tx_data: dict, owner_id: str):
        if tx_data.get("account_id"):
            acc = self.db.query(Account).filter(Account.id == tx_data["account_id"], Account.owner_id == owner_id).first()
            if not acc:
                raise HTTPException(status_code=403, detail="Not authorized to use this account")
        
        if tx_data.get("destination_account_id"):
            acc = self.db.query(Account).filter(Account.id == tx_data["destination_account_id"], Account.owner_id == owner_id).first()
            if not acc:
                raise HTTPException(status_code=403, detail="Not authorized to use this destination account")

    def _update_balances(self, tx: Transaction, owner_id: str):
        # Update source account
        if tx.account_id:
            account = self.db.query(Account).filter(Account.id == tx.account_id, Account.owner_id == owner_id).first()
            if account:
                if tx.type == TransactionType.income:
                    account.balance += tx.amount
                elif tx.type == TransactionType.expense:
                    account.balance -= tx.amount
                elif tx.type == TransactionType.transfer:
                    account.balance -= tx.amount

        # Update destination account for transfers
        if tx.type == TransactionType.transfer and tx.destination_account_id:
            dst_account = self.db.query(Account).filter(Account.id == tx.destination_account_id, Account.owner_id == owner_id).first()
            if dst_account:
                dst_account.balance += tx.amount

        # Commit all changes (including the creation from repo)
        self.db.commit()

    def get_transactions(
        self, 
        owner_id: str, 
        month: Optional[int] = None, 
        year: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Transaction]:
        # Handle legacy month/year if provided and dates are not
        s_date = start_date
        e_date = end_date
        
        if month and year and not s_date:
            from datetime import datetime
            s_date = datetime(year, month, 1)
            if month == 12:
                e_date = datetime(year + 1, 1, 1)
            else:
                e_date = datetime(year, month + 1, 1)
                
        return self.repo.get_by_owner(
            owner_id=owner_id, 
            start_date=s_date, 
            end_date=e_date, 
            search=search,
            category_ids=category_ids,
            account_id=account_id,
            skip=skip,
            limit=limit
        )

    def update_transaction(self, id: str, tx_update: TransactionCreate, owner_id: str) -> Transaction:
        # Note: tx_update here is actually TransactionUpdate schema but for basic CRUD using dict is fine or specific schema
        # We need to fetch existing to validate ownership
        existing = self.repo.get_by_id_and_owner(id, owner_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Transaction not found")
            
        update_data = tx_update.dict(exclude_unset=True)
        
        # Handle Balance Updates if amount or type changed?
        # This is complex. For Phase 1/2, a simple update is allowed.
        # But for correctness, we should revert old balance and apply new.
        # Let's do a naive update for properties first, but warn about complex balance logic.
        # Actually, let's implement the balance fix:
        
        if 'amount' in update_data or 'type' in update_data or 'account_id' in update_data:
            # Revert old transaction effect
            self._revert_balance(existing, owner_id)
            
            # Update object
            for key, value in update_data.items():
                setattr(existing, key, value)
            
            # Apply new transaction effect
            self._update_balances(existing, owner_id)
        else:
            # Just updating metadata like description, notes, category
            for key, value in update_data.items():
                setattr(existing, key, value)
                
        self.db.commit()
        self.db.refresh(existing)
        return existing

    def _revert_balance(self, tx: Transaction, owner_id: str):
        # Reverse of _update_balances
        if tx.account_id:
            account = self.db.query(Account).filter(Account.id == tx.account_id, Account.owner_id == owner_id).first()
            if account:
                if tx.type == TransactionType.income:
                    account.balance -= tx.amount
                elif tx.type == TransactionType.expense:
                    account.balance += tx.amount
                elif tx.type == TransactionType.transfer:
                    account.balance += tx.amount

        if tx.type == TransactionType.transfer and tx.destination_account_id:
            dst_account = self.db.query(Account).filter(Account.id == tx.destination_account_id, Account.owner_id == owner_id).first()
            if dst_account:
                dst_account.balance -= tx.amount

    def delete_transaction(self, id: str, owner_id: str):
        tx = self.repo.get_by_id_and_owner(id, owner_id)
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")
            
        # Revert balance before deleting
        self._revert_balance(tx, owner_id)
        
        return self.repo.remove(tx.id)

    def get_monthly_history(self, owner_id: str, months: int = 6, end_month: Optional[int] = None, end_year: Optional[int] = None):
        from datetime import datetime, timedelta
        
        # Calculate start date based on end date (default now)
        if end_month and end_year:
            # Set end_date to the first of the month AFTER end_month, or the first of this month but end of it
            if end_month == 12:
                end_date = datetime(end_year + 1, 1, 1)
            else:
                end_date = datetime(end_year, end_month + 1, 1)
        else:
            end_date = datetime.now()

        # For simplicity, just grab last N*31 days to ensure coverage
        start_date = end_date - timedelta(days=months * 31)
        
        txs = self.repo.get_by_owner(owner_id, start_date=start_date, limit=10000) # Ensure we get enough
        
        history = {} # Key: "YYYY-MM", Value: {month: "YYYY-MM", income: 0, expense: 0}
        
        for tx in txs:
            # Check if tx.date is string or datetime (it should be datetime from ORM)
            d = tx.date if isinstance(tx.date, datetime) else datetime.fromisoformat(str(tx.date))
            month_key = d.strftime("%Y-%m")
            
            if month_key not in history:
                history[month_key] = {"month": month_key, "income": 0, "expense": 0}
            
            if tx.type == TransactionType.income:
                history[month_key]["income"] += tx.amount
            elif tx.type == TransactionType.expense:
                history[month_key]["expense"] += tx.amount
                
        # Return sorted list
        return sorted(history.values(), key=lambda x: x["month"])
