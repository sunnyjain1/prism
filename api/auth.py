from fastapi import APIRouter, Depends, HTTPException, status
import traceback
from google.oauth2 import id_token
from google.auth.transport import requests
import os
import secrets
import string

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "252443340779-4u7edgsne2m72dkjjggs4gedqmvi95d0.apps.googleusercontent.com")


from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import get_db
from user_models import User, UserRole
from auth_utils import get_password_hash, verify_password, create_access_token
from pydantic import BaseModel, EmailStr
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""

class Token(BaseModel):
    access_token: str
    token_type: str

class UserOut(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str

    class Config:
        from_attributes = True

@router.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user_in.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user_in.password)
    user = User(
        id=str(uuid.uuid4()),
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        role=UserRole.EDITOR.value # Default role
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user



@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

from api.dependencies import get_current_user

@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


class GoogleToken(BaseModel):
    token: str

@router.post("/google", response_model=Token)
def google_login(token_data: GoogleToken, db: Session = Depends(get_db)):
    try:
        # Developer Mock Auth Support
        allow_mock = os.environ.get("ALLOW_MOCK_AUTH", "true").lower() == "true"
        mock_token = "dev-token-prism"
        
        if allow_mock and token_data.token == mock_token:
            email = "mockuser@example.com"
            name = "Prism Developer"
        else:
            # Verify the token with Google
            idinfo = id_token.verify_oauth2_token(token_data.token, requests.Request(), CLIENT_ID)
            email = idinfo['email']
            name = idinfo.get('name', '')
        
        # Check if user exists
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            # Create a new user with a random secure password
            # We strictly enforce password existence, so we generate a strong random one
            alphabet = string.ascii_letters + string.digits + string.punctuation
            random_password = ''.join(secrets.choice(alphabet) for i in range(20))
            hashed_password = get_password_hash(random_password)
            
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                hashed_password=hashed_password,
                full_name=name,
                role=UserRole.EDITOR.value
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
        access_token = create_access_token(data={"sub": user.email})
        return {"access_token": access_token, "token_type": "bearer"}
        
    except ValueError:
        # Invalid token
        raise HTTPException(status_code=401, detail="Invalid Google token")
    except Exception as e:
        print(f"Google login error: {e}")
        raise HTTPException(status_code=500, detail="Google login failed")
