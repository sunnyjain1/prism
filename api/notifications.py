from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.notification_service import NotificationService
from user_models import User

router = APIRouter(prefix="/notifications", tags=["notifications"])
v1_router = APIRouter(prefix="/notifications", tags=["notifications"])


@v1_router.get("", response_model=List[schemas.Notification])
@router.get("", response_model=List[schemas.Notification])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return NotificationService(db).get_notifications(current_user.id, unread_only=unread_only, limit=limit)


@v1_router.get("/count", response_model=schemas.NotificationUnreadCount)
@router.get("/count", response_model=schemas.NotificationUnreadCount)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"unread_count": NotificationService(db).get_unread_count(current_user.id)}


@v1_router.patch("/{notification_id}/read", response_model=schemas.Notification)
@router.patch("/{notification_id}/read", response_model=schemas.Notification)
def mark_notification_as_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return NotificationService(db).mark_as_read(notification_id, current_user.id)


@v1_router.post("/read-all", response_model=schemas.NotificationReadAllResponse)
@router.post("/read-all", response_model=schemas.NotificationReadAllResponse)
def mark_all_notifications_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated_count = NotificationService(db).mark_all_as_read(current_user.id)
    return {"updated_count": updated_count}
