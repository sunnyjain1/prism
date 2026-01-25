from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from core.dependencies import get_db, get_current_user
from user_models import User
from services.bulk_upload_service import BulkUploadService

router = APIRouter(prefix="/api/bulk", tags=["bulk-upload"])

@router.post("/upload")
async def bulk_upload_file(
    file: UploadFile = File(...),
    source_type: str = Form(...),
    account_id: Optional[str] = Form(None),
    currency: str = Form("USD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = BulkUploadService(db)
    return await service.process_upload(
        file=file,
        source_type=source_type,
        owner_id=current_user.id,
        target_account_id=account_id,
        currency=currency
    )
