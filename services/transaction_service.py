from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import Transaction, Account, TransactionType
from schemas import TransactionCreate
from repositories.transaction_repository import TransactionRepository
from typing import List, Optional

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

    def get_transactions(self, owner_id: str, month: Optional[int] = None, year: Optional[int] = None) -> List[Transaction]:
        return self.repo.get_by_owner(owner_id=owner_id, month=month, year=year)

    def delete_transaction(self, id: str, owner_id: str):
        tx = self.repo.get_by_id_and_owner(id, owner_id)
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")
            
        # Optional: Reverse the balance impact before deleting? 
        # For now, following current implementation which just deletes.
        return self.repo.remove(tx.id)
