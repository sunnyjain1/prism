from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import Optional
from core.dependencies import get_db, get_current_user
from user_models import User
from services.bulk_upload_service import BulkUploadService

router = APIRouter(prefix="/api/bulk", tags=["bulk-upload"])

@router.post("/upload")
async def bulk_upload_file(
    file: UploadFile = File(...),
    source_type: Optional[str] = Form(None),
    account_id: Optional[str] = Form(None),
    currency: str = Form("USD"),
    skip_duplicates: bool = Form(True),
    auto_detect: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload and import transactions from a file.
    
    Supported formats:
    - Bank CSV/Excel: chase, bank_of_america, wells_fargo, generic_bank
    - Credit Card PDF: chase_credit, amex, citi, capital_one, generic_credit_card
    - Money Manager: money_manager
    
    If source_type is not provided and auto_detect is True, the system will attempt
    to automatically detect the file format.
    """
    service = BulkUploadService(db)
    return await service.process_upload(
        file=file,
        source_type=source_type,
        owner_id=current_user.id,
        target_account_id=account_id,
        currency=currency,
        skip_duplicates=skip_duplicates,
        auto_detect=auto_detect
    )

@router.get("/formats")
def get_supported_formats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of supported import formats."""
    service = BulkUploadService(db)
    return service.get_supported_formats()
