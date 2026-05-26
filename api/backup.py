"""
Backup & Restore API endpoints.

- POST /backup/export — create encrypted backup
- POST /backup/import — restore from encrypted backup
- POST /backup/verify — verify backup integrity without importing
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from database import get_db
from api.dependencies import get_current_user
from user_models import User
from services.backup_service import BackupService

router = APIRouter(prefix="/backup", tags=["Backup & Restore"])


class BackupExportRequest(BaseModel):
    password: str = Field(..., min_length=6, description="Encryption password")


class BackupImportRequest(BaseModel):
    password: str = Field(..., min_length=6)
    backup: dict = Field(..., description="The encrypted backup envelope")


class BackupVerifyRequest(BaseModel):
    password: str = Field(..., min_length=6)
    backup: dict = Field(..., description="The encrypted backup envelope")


@router.post("/export")
def export_backup(
    request: BackupExportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create an encrypted backup of all user data."""
    service = BackupService(db)
    try:
        backup = service.export_user_data(user.id, request.password)
        return backup
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create backup: {str(e)}",
        )


@router.post("/import")
def import_backup(
    request: BackupImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Restore data from an encrypted backup."""
    service = BackupService(db)
    try:
        summary = service.import_user_data(user.id, request.backup, request.password)
        return {
            "status": "success",
            "message": "Backup restored successfully",
            **summary,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore backup: {str(e)}",
        )


@router.post("/verify")
def verify_backup(
    request: BackupVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Verify backup integrity without importing."""
    service = BackupService(db)
    result = service.verify_backup(request.backup, request.password)
    return result
