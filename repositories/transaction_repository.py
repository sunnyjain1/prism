from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from models import Transaction
from repositories.base_repository import BaseRepository
from datetime import datetime

class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, db: Session):
        super().__init__(Transaction, db)

    def get_by_owner(
        self, 
        owner_id: str, 
        skip: int = 0, 
        limit: int = 100,
        month: Optional[int] = None,
        year: Optional[int] = None
    ) -> List[Transaction]:
        query = self.db.query(self.model)\
            .options(joinedload(self.model.category), joinedload(self.model.account))\
            .filter(self.model.owner_id == owner_id)
        
        if month is not None and year is not None:
            start_date = datetime(year, month, 1)
            # Simplistic next month calculation
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            query = query.filter(self.model.date >= start_date, self.model.date < end_date)
            
        return query.order_by(self.model.date.desc()).offset(skip).limit(limit).all()

    def get_by_id_and_owner(self, id: str, owner_id: str) -> Optional[Transaction]:
        return self.db.query(self.model).filter(
            self.model.id == id, 
            self.model.owner_id == owner_id
        ).first()
