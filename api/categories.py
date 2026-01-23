from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import models, schemas
from api.dependencies import get_current_user, check_role
from user_models import User, UserRole

from database import SessionLocal

router = APIRouter(prefix="/api/categories", tags=["categories"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("", response_model=List[schemas.Category])
def read_categories(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(models.Category).filter(models.Category.owner_id == current_user.id).all()

@router.post("", response_model=schemas.Category)
def create_category(category: schemas.CategoryCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_category = models.Category(**category.dict())
    db_category.owner_id = current_user.id
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

@router.delete("/{category_id}")
def delete_category(category_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    category = db.query(models.Category).filter(models.Category.id == category_id, models.Category.owner_id == current_user.id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(category)
    db.commit()
    return {"message": "Category deleted"}
