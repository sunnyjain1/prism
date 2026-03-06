from sqlalchemy.orm import Session
from fastapi import HTTPException
from models import Category
from schemas import CategoryCreate
from repositories.category_repository import CategoryRepository
from typing import List

class CategoryService:
    def create_default_categories(self, owner_id: str):
        import uuid
        defaults = [
            {"name": "Food & Dining", "type": "expense", "color": "#ef4444"},
            {"name": "Transportation", "type": "expense", "color": "#f59e0b"},
            {"name": "Shopping", "type": "expense", "color": "#3b82f6"},
            {"name": "Entertainment", "type": "expense", "color": "#8b5cf6"},
            {"name": "Housing", "type": "expense", "color": "#ec4899"},
            {"name": "Utilities", "type": "expense", "color": "#06b6d4"},
            {"name": "Healthcare", "type": "expense", "color": "#10b981"},
            {"name": "Salary", "type": "income", "color": "#10b981"},
            {"name": "Freelance", "type": "income", "color": "#34d399"},
            {"name": "Investments", "type": "income", "color": "#6366f1"},
            {"name": "General", "type": "expense", "color": "#6b7280"}
        ]
        
        for cat in defaults:
            cat_data = {
                "id": str(uuid.uuid4()),
                "owner_id": owner_id,
                **cat
            }
            self.repo.create(cat_data)

    def __init__(self, db: Session):
        self.db = db
        self.repo = CategoryRepository(db)

    def create_category(self, category_in: CategoryCreate, owner_id: str) -> Category:
        data = category_in.model_dump()
        data["owner_id"] = owner_id
        return self.repo.create(data)

    def get_categories(self, owner_id: str) -> List[Category]:
        return self.repo.get_by_owner(owner_id)

    def delete_category(self, category_id: str, owner_id: str):
        cat = self.repo.get_by_id_and_owner(category_id, owner_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")
        return self.repo.remove(cat.id)
