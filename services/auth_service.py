import logging
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.auth.transport import requests
from google.oauth2 import id_token
from jose import JWTError
from sqlalchemy.orm import Session

import schemas
from auth_utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from core.config import settings
from repositories.user_repository import UserRepository
from services.category_service import CategoryService
from user_models import RefreshToken, User, UserRole

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _to_db_datetime(value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @staticmethod
    def _unauthorized_exception(detail: str = "Invalid refresh token") -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _create_user(self, email: str, password: str, full_name: str = "") -> User:
        hashed_password = get_password_hash(password)
        user_data = {
            "id": str(uuid.uuid4()),
            "email": email,
            "hashed_password": hashed_password,
            "full_name": full_name,
            "role": UserRole.EDITOR.value,
        }
        user = self.repo.create(user_data)

        cat_service = CategoryService(self.db)
        cat_service.create_default_categories(user.id)
        return user

    def _issue_tokens(self, user: User, device_info: Optional[str] = None) -> dict:
        from sqlalchemy import inspect as sa_inspect
        access_token = create_access_token(data={"sub": user.id})
        refresh_token, refresh_token_id, refresh_expires_at = create_refresh_token(data={"sub": user.id})

        # Persist the refresh token only if the table exists (guards against missing migrations).
        try:
            inspector = sa_inspect(self.db.bind)
            if "refresh_tokens" in inspector.get_table_names():
                refresh_token_record = RefreshToken(
                    id=refresh_token_id,
                    user_id=user.id,
                    token_hash=hash_token(refresh_token),
                    device_info=device_info,
                    expires_at=self._to_db_datetime(refresh_expires_at),
                )
                self.db.add(refresh_token_record)
                self.db.commit()
            else:
                logger.warning("refresh_tokens table not found — skipping token persistence. Run migrations.")
        except Exception:
            logger.exception("Failed to persist refresh token — proceeding without it")
            self.db.rollback()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    def _revoke_refresh_token(self, refresh_token_record: RefreshToken) -> None:
        if not refresh_token_record.is_active and refresh_token_record.revoked_at:
            return
        refresh_token_record.is_active = False
        refresh_token_record.revoked_at = self._utcnow()
        self.db.add(refresh_token_record)
        self.db.commit()

    def _validate_refresh_token(self, refresh_token: str) -> tuple[RefreshToken, dict]:
        try:
            payload = decode_token(refresh_token)
        except JWTError as exc:
            raise self._unauthorized_exception() from exc

        user_id = payload.get("sub")
        token_type = payload.get("type")
        token_id = payload.get("jti")
        if not user_id or token_type != "refresh" or not token_id:
            raise self._unauthorized_exception()

        refresh_token_record = (
            self.db.query(RefreshToken)
            .filter(RefreshToken.id == token_id, RefreshToken.user_id == user_id)
            .first()
        )
        if refresh_token_record is None:
            raise self._unauthorized_exception()

        if refresh_token_record.token_hash != hash_token(refresh_token):
            raise self._unauthorized_exception()

        if self._to_db_datetime(refresh_token_record.expires_at) <= self._utcnow():
            self._revoke_refresh_token(refresh_token_record)
            raise self._unauthorized_exception("Refresh token expired")

        if not refresh_token_record.is_active or refresh_token_record.revoked_at is not None:
            raise self._unauthorized_exception()

        return refresh_token_record, payload

    def _deactivate_expired_sessions(self, user_id: Optional[str] = None) -> None:
        query = self.db.query(RefreshToken).filter(
            RefreshToken.is_active.is_(True),
            RefreshToken.expires_at <= self._utcnow(),
        )
        if user_id:
            query = query.filter(RefreshToken.user_id == user_id)

        expired_sessions = query.all()
        if not expired_sessions:
            return

        revoked_at = self._utcnow()
        for session in expired_sessions:
            session.is_active = False
            session.revoked_at = revoked_at
            self.db.add(session)
        self.db.commit()

    def register(self, user_in: schemas.UserCreate, device_info: Optional[str] = None) -> dict:
        if self.repo.get_by_email(user_in.email):
            raise HTTPException(status_code=400, detail="Email already registered")

        user = self._create_user(user_in.email, user_in.password, user_in.full_name)
        return self._issue_tokens(user, device_info=device_info)

    def login(self, username: str, password: str, device_info: Optional[str] = None) -> dict:
        user = self.repo.get_by_email(username)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return self._issue_tokens(user, device_info=device_info)

    def refresh_tokens(self, refresh_token: str, device_info: Optional[str] = None) -> dict:
        refresh_token_record, payload = self._validate_refresh_token(refresh_token)
        user = self.repo.get(payload["sub"])
        if user is None or not user.is_active:
            raise self._unauthorized_exception()

        self._revoke_refresh_token(refresh_token_record)
        return self._issue_tokens(user, device_info=device_info or refresh_token_record.device_info)

    def logout(self, refresh_token: str) -> dict:
        refresh_token_record, _ = self._validate_refresh_token(refresh_token)
        self._revoke_refresh_token(refresh_token_record)
        return {"message": "Logged out successfully"}

    def list_sessions(self, user_id: str) -> list[RefreshToken]:
        self._deactivate_expired_sessions(user_id)
        return (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.is_active.is_(True),
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > self._utcnow(),
            )
            .order_by(RefreshToken.created_at.desc())
            .all()
        )

    def revoke_session(self, user_id: str, session_id: str) -> None:
        session = (
            self.db.query(RefreshToken)
            .filter(RefreshToken.id == session_id, RefreshToken.user_id == user_id)
            .first()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        self._revoke_refresh_token(session)

    def google_login(self, token: str, device_info: Optional[str] = None) -> dict:
        try:
            if settings.ALLOW_MOCK_AUTH and token == settings.MOCK_TOKEN:
                email = "mockuser@example.com"
                name = "Prism Developer"
            else:
                idinfo = id_token.verify_oauth2_token(token, requests.Request(), settings.GOOGLE_CLIENT_ID)
                email = idinfo["email"]
                name = idinfo.get("name", "")

            user = self.repo.get_by_email(email)
            if not user:
                alphabet = string.ascii_letters + string.digits + string.punctuation
                random_password = "".join(secrets.choice(alphabet) for _ in range(20))
                user = self._create_user(email, random_password, name)

            return self._issue_tokens(user, device_info=device_info)

        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid Google token")
        except Exception:
            logger.exception("Google login failed")
            raise HTTPException(status_code=500, detail="Google login failed")
