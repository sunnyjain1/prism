from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from models import Transaction
from repositories.base_repository import BaseRepository
from datetime import datetime

class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, db: Session):
        super().__init__(Transaction, db)

    def _apply_filters(
        self,
        query,
        *,
        owner_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
    ):
        query = query.filter(self.model.owner_id == owner_id)

        if start_date:
            query = query.filter(self.model.date >= start_date)
        if end_date:
            query = query.filter(self.model.date <= end_date)
        if category_ids:
            query = query.filter(self.model.category_id.in_(category_ids))
        if account_id:
            query = query.filter(
                or_(
                    self.model.account_id == account_id,
                    self.model.destination_account_id == account_id,
                )
            )
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (self.model.description.ilike(search_pattern))
                | (self.model.notes.ilike(search_pattern))
            )

        return query

    def get_by_owner(
        self,
        owner_id: str,
        skip: int = 0,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
    ) -> List[Transaction]:
        query = self.db.query(self.model).options(
            joinedload(self.model.category), joinedload(self.model.account)
        )
        query = self._apply_filters(
            query,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
            category_ids=category_ids,
            account_id=account_id,
        )
        return query.order_by(self.model.date.desc()).offset(skip).limit(limit).all()

    def count_by_owner(
        self,
        owner_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
    ) -> int:
        query = self.db.query(self.model.id)
        query = self._apply_filters(
            query,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
            category_ids=category_ids,
            account_id=account_id,
        )
        return query.count()

    def get_by_id_and_owner(self, id: str, owner_id: str) -> Optional[Transaction]:
        return self.db.query(self.model).filter(
            self.model.id == id,
            self.model.owner_id == owner_id,
        ).first()

    def aggregate_by_owner(
        self,
        owner_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None,
    ) -> dict:
        from sqlalchemy import case, func

        query = self.db.query(
            func.count(self.model.id).label("count"),
            func.coalesce(
                func.sum(case((self.model.type == "income", self.model.amount), else_=0)),
                0,
            ).label("total_income"),
            func.coalesce(
                func.sum(case((self.model.type == "expense", self.model.amount), else_=0)),
                0,
            ).label("total_expense"),
        )
        query = self._apply_filters(
            query,
            owner_id=owner_id,
            start_date=start_date,
            end_date=end_date,
            search=search,
            category_ids=category_ids,
            account_id=account_id,
        )

        row = query.one()
        return {
            "count": row.count,
            "total_income": float(row.total_income),
            "total_expense": float(row.total_expense),
        }
