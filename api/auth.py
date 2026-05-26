from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

import schemas
from core.config import settings
from core.dependencies import get_current_user, get_db
from core.rate_limit import limiter
from services.auth_service import AuthService
from user_models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.Token)
@limiter.limit(settings.AUTH_RATE_LIMITS["register"])
def register(request: Request, user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.register(user_in, device_info=request.headers.get("user-agent"))


@router.post("/login", response_model=schemas.Token)
@router.post("/token", response_model=schemas.Token)
@limiter.limit(settings.AUTH_RATE_LIMITS["login"])
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.login(form_data.username, form_data.password, device_info=request.headers.get("user-agent"))


@router.post("/refresh", response_model=schemas.Token)
def refresh_tokens(request: Request, token_data: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.refresh_tokens(token_data.refresh_token, device_info=request.headers.get("user-agent"))


@router.post("/logout", response_model=schemas.MessageResponse)
def logout(token_data: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.logout(token_data.refresh_token)


@router.get("/sessions", response_model=list[schemas.SessionOut])
def list_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.list_sessions(current_user.id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    service = AuthService(db)
    service.revoke_session(current_user.id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/google", response_model=schemas.Token)
@limiter.limit(settings.AUTH_RATE_LIMITS["google"])
def google_login(request: Request, token_data: schemas.GoogleToken, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.google_login(token_data.token, device_info=request.headers.get("user-agent"))
