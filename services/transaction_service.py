import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from core.config import settings
from models import Transaction, Account, TransactionType
from repositories.transaction_repository import TransactionRepository
from schemas import TransactionCreate, TransactionUpdate
from services.cache_service import cache
from services.notification_service import NotificationService
from services.search_service import SearchService
from services.smart_categorization_service import SmartCategorizationService

logger = logging.getLogger(__name__)

LARGE_TRANSACTION_THRESHOLD = 10000

class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TransactionRepository(db)
        self.smart_categorizer = SmartCategorizationService()

    def _dashboard_cache_key(self, owner_id: str, year: int, month: int) -> str:
        return f"dashboard:{owner_id}:{year}:{month}"

    def _history_cache_key(
        self,
        owner_id: str,
        months: int,
        end_month: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> str:
        normalized_month = end_month or "current"
        normalized_year = end_year or "current"
        return f"dashboard:{owner_id}:{normalized_year}:{normalized_month}:history:{months}"

    def _invalidate_user_caches(self, owner_id: str) -> None:
        cache.delete_pattern(f"*:{owner_id}:*")
        cache.delete(f"budget_progress:{owner_id}")
        cache.delete_pattern(f"budget_progress:{owner_id}:*")
        cache.delete(f"net_worth:{owner_id}")

    def _queue_transaction_index(self, owner_id: str, transaction: Transaction) -> None:
        try:
            SearchService.queue_index_transaction(owner_id, SearchService.build_document(transaction))
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Unable to queue search indexing for transaction %s: %s", transaction.id, exc)

    def _queue_transaction_delete(self, owner_id: str, transaction_id: str) -> None:
        try:
            SearchService.queue_delete_transaction(owner_id, transaction_id)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("Unable to queue search deletion for transaction %s: %s", transaction_id, exc)

    def _create_large_transaction_notification(self, owner_id: str, transaction: Transaction) -> None:
        if float(transaction.amount) <= LARGE_TRANSACTION_THRESHOLD:
            return

        NotificationService(self.db).create_notification(
            user_id=owner_id,
            title="Large transaction detected",
            message=f"A {transaction.type} transaction of ₹{transaction.amount:,.2f} was recorded.",
            type="alert",
            category="transaction",
            action_url="/transactions",
            metadata={
                "transaction_id": transaction.id,
                "amount": float(transaction.amount),
                "transaction_type": str(transaction.type),
                "account_id": transaction.account_id,
                "destination_account_id": transaction.destination_account_id,
            },
        )

    def _normalize_transaction_merchant(self, tx_data: dict) -> None:
        normalized_merchant = self.smart_categorizer.normalize_merchant(
            tx_data.get("merchant") or tx_data.get("description") or ""
        )
        if normalized_merchant:
            tx_data["merchant"] = normalized_merchant

    def _apply_smart_categorization(self, tx_data: dict, owner_id: str) -> None:
        self._normalize_transaction_merchant(tx_data)

        if tx_data.get("category_id") or tx_data.get("type") == TransactionType.transfer:
            return

        suggestion = self.smart_categorizer.categorize_transaction(
            user_id=owner_id,
            description=tx_data.get("description") or "",
            merchant=tx_data.get("merchant") or "",
            amount=tx_data.get("amount") or 0,
            type=tx_data.get("type"),
            db=self.db,
        )
        if suggestion.get("category_id"):
            tx_data["categorization_method"] = suggestion["method"]
            tx_data["categorization_confidence"] = suggestion["confidence"]

        if suggestion.get("category_id") and suggestion.get("confidence", 0) >= SmartCategorizationService.AUTO_ASSIGN_CONFIDENCE:
            tx_data["category_id"] = suggestion["category_id"]

    def create_transaction(self, transaction_in: TransactionCreate, owner_id: str) -> Transaction:
        tx_data = transaction_in.model_dump()
        tx_data["owner_id"] = owner_id

        self._apply_smart_categorization(tx_data, owner_id)
        self._validate_transaction_state(tx_data, owner_id)

        db_transaction = Transaction(**tx_data)
        self.db.add(db_transaction)
        self._update_balances(db_transaction, owner_id)
        self._create_large_transaction_notification(owner_id, db_transaction)
        self.db.commit()
        self.db.refresh(db_transaction)
        self._invalidate_user_caches(owner_id)
        self._queue_transaction_index(owner_id, db_transaction)
        return db_transaction

    def _validate_transaction_state(self, tx_data: dict, owner_id: str):
        if tx_data.get("type") == TransactionType.transfer and not tx_data.get("destination_account_id"):
            raise HTTPException(status_code=400, detail="Destination account required for transfer")

        self._validate_ownership(tx_data, owner_id)

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


    def _resolve_transaction_date_range(
        self,
        month: Optional[int] = None,
        year: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        s_date = start_date
        e_date = end_date

        if month and year and not s_date:
            s_date = datetime(year, month, 1)
            if month == 12:
                e_date = datetime(year + 1, 1, 1) - timedelta(microseconds=1)
            else:
                e_date = datetime(year, month + 1, 1) - timedelta(microseconds=1)

        return s_date, e_date

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
        limit: int = 100,
    ) -> List[Transaction]:
        s_date, e_date = self._resolve_transaction_date_range(month, year, start_date, end_date)

        return self.repo.get_by_owner(
            owner_id=owner_id,
            start_date=s_date,
            end_date=e_date,
            search=search,
            category_ids=category_ids,
            account_id=account_id,
            skip=skip,
            limit=limit,
        )

    def count_transactions(
        self,
        owner_id: str,
        month: Optional[int] = None,
        year: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
    ) -> int:
        s_date, e_date = self._resolve_transaction_date_range(month, year, start_date, end_date)
        return self.repo.count_by_owner(
            owner_id=owner_id,
            start_date=s_date,
            end_date=e_date,
            search=search,
            category_ids=category_ids,
            account_id=account_id,
        )

    def aggregate_transactions(
        self,
        owner_id: str,
        month: Optional[int] = None,
        year: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
    ) -> dict:
        s_date, e_date = self._resolve_transaction_date_range(month, year, start_date, end_date)

        return self.repo.aggregate_by_owner(
            owner_id=owner_id,
            start_date=s_date,
            end_date=e_date,
            search=search,
            category_ids=category_ids,
            account_id=account_id,
        )

    def update_transaction(self, id: str, tx_update: TransactionUpdate, owner_id: str) -> Transaction:
        existing = self.repo.get_by_id_and_owner(id, owner_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Transaction not found")

        update_data = tx_update.model_dump(exclude_unset=True)

        if "type" in update_data and update_data["type"] != TransactionType.transfer:
            update_data["destination_account_id"] = None

        updated_state = {
            "type": update_data.get("type", existing.type),
            "account_id": update_data.get("account_id", existing.account_id),
            "destination_account_id": update_data.get("destination_account_id", existing.destination_account_id),
        }
        self._validate_transaction_state(updated_state, owner_id)

        balance_fields = {"amount", "type", "account_id", "destination_account_id"}
        should_rebalance = any(field in update_data for field in balance_fields)
        category_changed = "category_id" in update_data and update_data["category_id"] != existing.category_id

        if should_rebalance:
            self._revert_balance(existing, owner_id)

        for key, value in update_data.items():
            setattr(existing, key, value)

        merchant_fields = {"description", "merchant"}
        if merchant_fields.intersection(update_data.keys()):
            normalized_merchant = self.smart_categorizer.normalize_merchant(existing.merchant or existing.description or "")
            if normalized_merchant:
                existing.merchant = normalized_merchant

        if category_changed:
            existing.categorization_method = "manual"
            existing.categorization_confidence = 1.0
            if existing.category_id:
                self.smart_categorizer.learn_from_transaction(
                    user_id=owner_id,
                    description=existing.description or "",
                    merchant=existing.merchant or "",
                    category_id=existing.category_id,
                    db=self.db,
                )

        if should_rebalance:
            self._update_balances(existing, owner_id)

        self.db.commit()
        self.db.refresh(existing)
        self._invalidate_user_caches(owner_id)
        self._queue_transaction_index(owner_id, existing)
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

        self._revert_balance(tx, owner_id)
        self.db.delete(tx)
        self.db.commit()
        self._invalidate_user_caches(owner_id)
        self._queue_transaction_delete(owner_id, id)
        return tx

    def get_monthly_history(self, owner_id: str, months: int = 6, end_month: Optional[int] = None, end_year: Optional[int] = None):
        cache_key = self._history_cache_key(owner_id, months, end_month, end_year)
        cached_history = cache.get(cache_key)
        if cached_history is not None:
            return cached_history

        # Calculate start date based on end date (default now)
        if end_month and end_year:
            # Set end_date to the first of the month AFTER end_month
            if end_month == 12:
                end_date = datetime(end_year + 1, 1, 1)
            else:
                end_date = datetime(end_year, end_month + 1, 1)
        else:
            now = datetime.now()
            if now.month == 12:
                end_date = datetime(now.year + 1, 1, 1)
            else:
                end_date = datetime(now.year, now.month + 1, 1)

        # Calculate precise start_date (N months ago, 1st of the month)
        start_month = end_date.month - months
        start_year = end_date.year
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start_date = datetime(start_year, start_month, 1)
        
        # Ensure we filter out future transactions by passing end_date
        txs = self.repo.get_by_owner(owner_id, start_date=start_date, end_date=end_date, limit=10000)
        
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
        history_items = sorted(history.values(), key=lambda x: x["month"])
        cache.set(cache_key, jsonable_encoder(history_items), ttl=settings.CACHE_TTL_DASHBOARD)
        return history_items

    def get_transaction_summary(self, owner_id: str, month: int, year: int):
        cache_key = self._dashboard_cache_key(owner_id, year, month)
        cached_summary = cache.get(cache_key)
        if cached_summary is not None:
            return cached_summary

        from datetime import datetime
        from sqlalchemy import func
        
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        # Query for income/expense grouped by currency
        results = (
            self.db.query(
                Transaction.type,
                Account.currency,
                func.sum(Transaction.amount).label("total")
            )
            .join(Account, Transaction.account_id == Account.id)
            .filter(Transaction.owner_id == owner_id)
            .filter(Transaction.date >= start_date)
            .filter(Transaction.date < end_date)
            .group_by(Transaction.type, Account.currency)
            .all()
        )
        
        summary = [{"type": r[0], "currency": r[1], "total": r[2]} for r in results]
        cache.set(cache_key, jsonable_encoder(summary), ttl=settings.CACHE_TTL_DASHBOARD)
        return summary
