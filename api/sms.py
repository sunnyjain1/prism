"""
SMS Transaction Ingestion API.

Endpoints:
- POST /sms/ingest — bulk submit parsed SMS from device
- GET /sms/drafts — review queue (pending confirmations)
- GET /sms/drafts/count — count pending drafts
- POST /sms/confirm/{id} — confirm a draft → creates real transaction
- POST /sms/reject/{id} — reject a draft
- POST /sms/batch-confirm — bulk confirm
- POST /sms/batch-reject — bulk reject
"""
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from database import get_db
from api.dependencies import get_current_user
from user_models import User
from services.sms_transaction_service import SMSTransactionService

router = APIRouter(prefix="/sms", tags=["SMS Ingestion"])


# --- Request/Response schemas ---

class SMSMessage(BaseModel):
    sender: str = ""
    body: str
    timestamp: Optional[str] = None  # ISO format


class SMSIngestRequest(BaseModel):
    messages: List[SMSMessage] = Field(..., max_length=500)
    device_id: Optional[str] = None


class SMSIngestResponse(BaseModel):
    ingested: int
    duplicates: int
    non_transactional: int
    total_processed: int


class SMSDraftResponse(BaseModel):
    id: str
    raw_body: str
    sender: Optional[str]
    sms_timestamp: Optional[datetime]
    amount: Optional[float]
    transaction_type: Optional[str]
    merchant: Optional[str]
    bank_name: Optional[str]
    masked_account: Optional[str]
    reference_number: Optional[str]
    available_balance: Optional[float]
    upi_id: Optional[str]
    card_type: Optional[str]
    matched_account_id: Optional[str]
    suggested_category_id: Optional[str]
    confidence: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SMSConfirmRequest(BaseModel):
    override_amount: Optional[float] = None
    override_category_id: Optional[str] = None
    override_account_id: Optional[str] = None
    override_description: Optional[str] = None


class SMSBatchRequest(BaseModel):
    ids: List[str] = Field(..., max_length=100)


class SMSDraftCountResponse(BaseModel):
    count: int


# --- Endpoints ---

@router.post("/ingest", response_model=SMSIngestResponse)
def ingest_sms(
    request: SMSIngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk ingest SMS messages from device. Parses and creates drafts."""
    service = SMSTransactionService(db)
    messages = [msg.model_dump() for msg in request.messages]
    result = service.ingest_batch(
        user_id=user.id,
        messages=messages,
        device_id=request.device_id,
    )
    return result


@router.get("/drafts", response_model=List[SMSDraftResponse])
def get_drafts(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get pending SMS transactions for review."""
    service = SMSTransactionService(db)
    drafts = service.get_drafts(user.id, limit=limit, offset=offset)
    return drafts


@router.get("/drafts/count", response_model=SMSDraftCountResponse)
def get_draft_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get count of pending drafts."""
    service = SMSTransactionService(db)
    return {"count": service.get_draft_count(user.id)}


@router.post("/confirm/{sms_txn_id}")
def confirm_draft(
    sms_txn_id: str,
    request: SMSConfirmRequest = SMSConfirmRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm a draft SMS transaction, creating a real transaction."""
    service = SMSTransactionService(db)
    transaction = service.confirm_draft(
        user_id=user.id,
        sms_txn_id=sms_txn_id,
        override_amount=request.override_amount,
        override_category_id=request.override_category_id,
        override_account_id=request.override_account_id,
        override_description=request.override_description,
    )
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found or already processed",
        )
    return {
        "status": "confirmed",
        "transaction_id": transaction.id,
        "amount": transaction.amount,
        "type": transaction.type,
        "description": transaction.description,
    }


@router.post("/reject/{sms_txn_id}")
def reject_draft(
    sms_txn_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reject a draft SMS transaction."""
    service = SMSTransactionService(db)
    success = service.reject_draft(user.id, sms_txn_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found or already processed",
        )
    return {"status": "rejected"}


@router.post("/batch-confirm")
def batch_confirm(
    request: SMSBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk confirm multiple draft SMS transactions."""
    service = SMSTransactionService(db)
    result = service.batch_confirm(user.id, request.ids)
    return result


@router.post("/batch-reject")
def batch_reject(
    request: SMSBatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk reject multiple draft SMS transactions."""
    service = SMSTransactionService(db)
    result = service.batch_reject(user.id, request.ids)
    return result
