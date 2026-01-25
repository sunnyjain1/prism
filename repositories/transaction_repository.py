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
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        search: Optional[str] = None,
        category_ids: Optional[List[str]] = None,
        account_id: Optional[str] = None
    ) -> List[Transaction]:
        query = self.db.query(self.model)\
            .options(joinedload(self.model.category), joinedload(self.model.account))\
            .filter(self.model.owner_id == owner_id)
        
        if start_date:
            query = query.filter(self.model.date >= start_date)
        
        if end_date:
            query = query.filter(self.model.date <= end_date)
            
        if category_ids:
            query = query.filter(self.model.category_id.in_(category_ids))

        if account_id:
            query = query.filter(self.model.account_id == account_id)
            
        if search:
            search_pattern = f"%{search}%"
            # Case insensitive search on description or notes
            query = query.filter(
                (self.model.description.ilike(search_pattern)) | 
                (self.model.notes.ilike(search_pattern))
            )
            
        return query.order_by(self.model.date.desc()).offset(skip).limit(limit).all()

    def get_by_id_and_owner(self, id: str, owner_id: str) -> Optional[Transaction]:
        return self.db.query(self.model).filter(
            self.model.id == id, 
            self.model.owner_id == owner_id
        ).first()
