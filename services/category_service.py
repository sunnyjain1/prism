from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import Category
from schemas import CategoryCreate
from repositories.category_repository import CategoryRepository
from typing import List

class CategoryService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CategoryRepository(db)

    def create_category(self, category_in: CategoryCreate, owner_id: str) -> Category:
        data = category_in.dict()
        data["owner_id"] = owner_id
        return self.repo.create(data)

    def get_categories(self, owner_id: str) -> List[Category]:
        return self.repo.get_by_owner(owner_id)

    def delete_category(self, category_id: str, owner_id: str):
        cat = self.repo.get_by_id_and_owner(category_id, owner_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")
        return self.repo.remove(cat.id)
