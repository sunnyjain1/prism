from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.investment_service import InvestmentService
from user_models import User

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/portfolio", response_model=schemas.InvestmentPortfolioSummary)
def get_portfolio_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return InvestmentService(db).get_portfolio_summary(current_user.id)


@router.get("", response_model=List[schemas.Investment])
def list_investments(
    type_filter: Optional[schemas.InvestmentType] = Query(default=None, alias="type"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return InvestmentService(db).get_investments(current_user.id, type_filter=type_filter.value if type_filter else None)


@router.post("", response_model=schemas.Investment)
def create_investment(
    investment: schemas.InvestmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return InvestmentService(db).create_investment(current_user.id, investment.model_dump(exclude_unset=True))


@router.get("/{investment_id}", response_model=schemas.Investment)
def get_investment(
    investment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return InvestmentService(db).get_investment(current_user.id, investment_id)


@router.put("/{investment_id}", response_model=schemas.Investment)
def update_investment(
    investment_id: str,
    investment: schemas.InvestmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return InvestmentService(db).update_investment(current_user.id, investment_id, investment.model_dump(exclude_unset=True))


@router.delete("/{investment_id}", response_model=schemas.MessageResponse)
def delete_investment(
    investment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    InvestmentService(db).delete_investment(current_user.id, investment_id)
    return {"message": "Investment deleted successfully"}


@router.post("/{investment_id}/refresh-price", response_model=schemas.Investment)
def refresh_investment_price(
    investment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = InvestmentService(db)
    investment = service.get_investment(current_user.id, investment_id)
    if investment.type == "mutual_fund":
        return service.update_mutual_fund_nav(investment_id)
    return service.update_investment(current_user.id, investment_id, {})
