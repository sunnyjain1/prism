from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.loan_service import LoanService
from user_models import User

router = APIRouter(prefix="/loans", tags=["loans"])
v1_router = APIRouter(prefix="/loans", tags=["loans"])


@v1_router.get("/summary", response_model=schemas.LoanSummaryResponse)
@router.get("/summary", response_model=schemas.LoanSummaryResponse)
def get_loan_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return LoanService(db).get_loan_summary(current_user.id)


@v1_router.get("", response_model=schemas.LoanListResponse)
@router.get("", response_model=schemas.LoanListResponse)
def read_loans(
    active_only: bool = Query(default=True),
    upcoming_days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = LoanService(db)
    return {
        "summary": service.get_loan_summary(current_user.id),
        "loans": service.get_loans(current_user.id, active_only=active_only),
        "upcoming_emis": service.get_upcoming_emis(current_user.id, days=upcoming_days),
    }


@v1_router.post("", response_model=schemas.LoanOverview)
@router.post("", response_model=schemas.LoanOverview)
def create_loan(
    loan: schemas.LoanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return LoanService(db).create_loan(current_user.id, loan)


@v1_router.put("/{loan_id}", response_model=schemas.LoanOverview)
@router.put("/{loan_id}", response_model=schemas.LoanOverview)
def update_loan(
    loan_id: str,
    loan: schemas.LoanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return LoanService(db).update_loan(current_user.id, loan_id, loan)


@v1_router.delete("/{loan_id}", response_model=schemas.MessageResponse)
@router.delete("/{loan_id}", response_model=schemas.MessageResponse)
def close_loan(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    LoanService(db).close_loan(current_user.id, loan_id)
    return {"message": "Loan archived successfully"}


@v1_router.get("/{loan_id}/amortization", response_model=schemas.LoanAmortizationResponse)
@router.get("/{loan_id}/amortization", response_model=schemas.LoanAmortizationResponse)
def get_amortization_schedule(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return LoanService(db).get_amortization_details(current_user.id, loan_id)


@v1_router.post("/{loan_id}/payment", response_model=schemas.LoanPaymentResponse)
@router.post("/{loan_id}/payment", response_model=schemas.LoanPaymentResponse)
def record_emi_payment(
    loan_id: str,
    payment: schemas.LoanPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return LoanService(db).record_emi_payment(current_user.id, loan_id, payment.amount, payment.date)
