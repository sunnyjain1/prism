from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.budget_service import BudgetService
from user_models import User

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("", response_model=List[schemas.BudgetProgress])
def read_budgets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return BudgetService(db).get_budgets(current_user.id)


@router.get("/alerts", response_model=List[schemas.BudgetAlert])
def read_budget_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return BudgetService(db).check_budget_alerts(current_user.id)


@router.get("/{budget_id}", response_model=schemas.BudgetProgress)
def read_budget_progress(
    budget_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return BudgetService(db).get_budget_progress(current_user.id, budget_id)


@router.post("", response_model=schemas.BudgetProgress)
def create_budget(
    budget: schemas.BudgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return BudgetService(db).create_budget(current_user.id, budget)


@router.put("/{budget_id}", response_model=schemas.BudgetProgress)
def update_budget(
    budget_id: str,
    budget: schemas.BudgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return BudgetService(db).update_budget(current_user.id, budget_id, budget)


@router.delete("/{budget_id}", response_model=schemas.MessageResponse)
def delete_budget(
    budget_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    BudgetService(db).delete_budget(current_user.id, budget_id)
    return {"message": "Budget deleted successfully"}
