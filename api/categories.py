from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from core.dependencies import get_db, get_current_user
from user_models import User
import schemas
from services.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["categories"])

@router.get("", response_model=List[schemas.Category])
def read_categories(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = CategoryService(db)
    return service.get_categories(current_user.id)

@router.post("", response_model=schemas.Category)
def create_category(
    category: schemas.CategoryCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = CategoryService(db)
    return service.create_category(category, current_user.id)

@router.delete("/{category_id}", response_model=schemas.MessageResponse)
def delete_category(
    category_id: str, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    service = CategoryService(db)
    service.delete_category(category_id, current_user.id)
    return {"message": "Category deleted"}
