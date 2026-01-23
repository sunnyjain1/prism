from typing import List, Optional
from sqlalchemy.orm import Session
from models import Category
from repositories.base_repository import BaseRepository

class CategoryRepository(BaseRepository[Category]):
    def __init__(self, db: Session):
        super().__init__(Category, db)

    def get_by_owner(self, owner_id: str) -> List[Category]:
        return self.db.query(self.model).filter(
            self.model.owner_id == owner_id
        ).all()

    def get_by_id_and_owner(self, id: str, owner_id: str) -> Optional[Category]:
        return self.db.query(self.model).filter(
            self.model.id == id, 
            self.model.owner_id == owner_id
        ).first()
