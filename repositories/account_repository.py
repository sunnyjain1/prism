from typing import List, Optional
from sqlalchemy.orm import Session
from models import Account
from repositories.base_repository import BaseRepository

class AccountRepository(BaseRepository[Account]):
    def __init__(self, db: Session):
        super().__init__(Account, db)

    def get_by_owner(self, owner_id: str, skip: int = 0, limit: int = 100) -> List[Account]:
        return self.db.query(self.model).filter(
            self.model.owner_id == owner_id
        ).offset(skip).limit(limit).all()

    def get_by_id_and_owner(self, id: str, owner_id: str) -> Optional[Account]:
        return self.db.query(self.model).filter(
            self.model.id == id, 
            self.model.owner_id == owner_id
        ).first()
