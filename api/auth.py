from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from core.dependencies import get_db, get_current_user
from user_models import User
from services.auth_service import AuthService
import schemas

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=schemas.UserOut)
def register(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.register(user_in)

@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    service = AuthService(db)
    return service.login(form_data.username, form_data.password)

@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post("/google", response_model=schemas.Token)
def google_login(token_data: schemas.GoogleToken, db: Session = Depends(get_db)):
    # Assuming GoogleToken is also in schemas.py
    service = AuthService(db)
    return service.google_login(token_data.token)
