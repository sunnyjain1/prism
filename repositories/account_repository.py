from typing import List, Optional
from sqlalchemy.orm import Session
from models import Account
from repositories.base_repository import BaseRepository

class AccountRepository(BaseRepository[Account]):
    def __init__(self, db: Session):
        super().__init__(Account, db)

    def get_by_owner(self, owner_id: str, skip: int = 0, limit: int = 500) -> List[Account]:
        return self.db.query(self.model).filter(
            self.model.owner_id == owner_id,
            self.model.is_deleted == False
        ).offset(skip).limit(limit).all()

    def get_deleted_by_owner(self, owner_id: str) -> List[Account]:
        return self.db.query(self.model).filter(
            self.model.owner_id == owner_id,
            self.model.is_deleted == True
        ).all()

    def get_by_id_and_owner(self, id: str, owner_id: str) -> Optional[Account]:
        return self.db.query(self.model).filter(
            self.model.id == id, 
            self.model.owner_id == owner_id
        ).first()

    def get_by_name_and_owner(self, name: str, owner_id: str) -> Optional[Account]:
        return self.db.query(self.model).filter(
            self.model.name == name,
            self.model.owner_id == owner_id
        ).first()
