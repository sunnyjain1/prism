"""
Credit Score & Report API

Endpoints for fetching credit scores, full credit reports,
account discovery from credit data, and consent management.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, get_db
from models import Account
from user_models import User
from schemas import (
    AccountDiscoveryRequest,
    AccountDiscoveryResponse,
    CreditConsentRequest,
    CreditConsentResponse,
    CreditReportResponse,
    CreditScoreResponse,
    ImportAccountRequest,
)
from services.credit_score_service import (
    discover_accounts_from_credit,
    fetch_credit_report,
    get_credit_report,
    get_credit_score,
)
from uuid import uuid4

router = APIRouter(prefix="/credit-score", tags=["Credit Score"])


@router.get("", response_model=CreditScoreResponse)
def get_score(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the user's latest credit score."""
    return get_credit_score(db, current_user.id)


@router.get("/report", response_model=CreditReportResponse)
def get_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the user's latest full credit report with accounts and inquiries."""
    report = get_credit_report(db, current_user.id)
    if not report:
        raise HTTPException(status_code=404, detail="No credit report found. Fetch one first.")
    return report


@router.post("/fetch", response_model=CreditReportResponse)
def fetch_report(
    request: CreditConsentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a fresh credit report from the bureau.
    Requires user consent. PAN is optional but improves accuracy.
    """
    return fetch_credit_report(
        db=db,
        user_id=current_user.id,
        provider=request.provider,
        pan=request.pan,
    )


@router.post("/consent", response_model=CreditConsentResponse)
def initiate_consent(
    request: CreditConsentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Initiate consent for credit report access.
    In production, this redirects to the bureau's consent page.
    Currently simulates immediate approval for development.
    """
    consent_id = f"ccs_{uuid4().hex[:16]}"
    return CreditConsentResponse(
        consent_id=consent_id,
        status="approved",
        provider=request.provider,
        redirect_url=None,
    )


@router.post("/discover-accounts", response_model=AccountDiscoveryResponse)
def discover_accounts(
    request: AccountDiscoveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Discover financial accounts from the user's credit report.
    Returns credit cards and loans that can be imported as app accounts.
    """
    existing_accounts = (
        db.query(Account)
        .filter(Account.owner_id == current_user.id, Account.is_deleted == False)
        .all()
    )
    existing_names = [a.name for a in existing_accounts]

    return discover_accounts_from_credit(db, current_user.id, existing_names)


@router.post("/import-account")
def import_discovered_account(
    request: ImportAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Import a discovered account into the user's account list.
    Creates a new Account record from the credit report data.
    """
    # Determine name
    name = request.name or f"{request.institution} {request.account_type.replace('_', ' ').title()}"

    # Check for duplicates
    existing = (
        db.query(Account)
        .filter(
            Account.owner_id == current_user.id,
            Account.name == name,
            Account.is_deleted == False,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Account '{name}' already exists.")

    # Map credit type to account type
    account_type = request.account_type
    if account_type not in ["checking", "current", "savings", "credit", "credit_card", "loan", "investment", "cash"]:
        account_type = "credit_card" if "card" in request.account_type else "loan"

    account = Account(
        id=str(uuid4()),
        name=name,
        type=account_type,
        balance=request.balance,
        credit_limit=request.credit_limit,
        owner_id=current_user.id,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    return {
        "id": account.id,
        "name": account.name,
        "type": account.type,
        "balance": account.balance,
        "message": f"Account '{name}' imported successfully.",
    }
