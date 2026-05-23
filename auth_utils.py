import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext

from core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def _create_token(data: dict, token_type: str, expires_delta: timedelta):
    expire = datetime.now(timezone.utc) + expires_delta
    jti = str(uuid4())
    to_encode = data.copy()
    to_encode.update({"exp": expire, "type": token_type, "jti": jti})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt, jti, expire


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    token, _, _ = _create_token(
        data,
        "access",
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return token


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    return _create_token(
        data,
        "refresh",
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
