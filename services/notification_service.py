from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Notification


class NotificationService:
    def __init__(self, db: Session):
        self.db = db

    def create_notification(
        self,
        user_id: str,
        title: str,
        message: str,
        type: str,
        category: Optional[str] = None,
        action_url: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=type,
            category=category,
            action_url=action_url,
            extra_metadata=metadata,
        )
        self.db.add(notification)
        self.db.flush()
        return notification

    def get_notifications(self, user_id: str, unread_only: bool = False, limit: int = 50) -> list[Notification]:
        query = self.db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            query = query.filter(Notification.is_read.is_(False))
        return query.order_by(Notification.created_at.desc()).limit(limit).all()

    def mark_as_read(self, notification_id: str, user_id: str) -> Notification:
        notification = (
            self.db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        if not notification.is_read:
            notification.is_read = True
            self.db.commit()
            self.db.refresh(notification)
        return notification

    def mark_all_as_read(self, user_id: str) -> int:
        updated_count = (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
            .update({Notification.is_read: True}, synchronize_session=False)
        )
        self.db.commit()
        return int(updated_count)

    def get_unread_count(self, user_id: str) -> int:
        return int(
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
            .count()
        )

    def delete_old_notifications(self, user_id: str, days: int = 30) -> int:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted_count = (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return int(deleted_count)
