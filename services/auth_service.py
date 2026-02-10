import secrets
import string
import uuid
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from google.oauth2 import id_token
from google.auth.transport import requests

from user_models import User, UserRole
from repositories.user_repository import UserRepository
from auth_utils import get_password_hash, verify_password, create_access_token
from core.config import settings
import schemas
from services.category_service import CategoryService

class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def register(self, user_in: schemas.UserCreate) -> User:
        if self.repo.get_by_email(user_in.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        
        hashed_password = get_password_hash(user_in.password)
        user_data = {
            "id": str(uuid.uuid4()),
            "email": user_in.email,
            "hashed_password": hashed_password,
            "full_name": user_in.full_name,
            "role": UserRole.EDITOR.value
        }
        user = self.repo.create(user_data)
        
        # Seed default categories
        cat_service = CategoryService(self.db)
        cat_service.create_default_categories(user.id)
        
        return user

    def login(self, username: str, password: str) -> dict:
        user = self.repo.get_by_email(username)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token = create_access_token(data={"sub": user.email})
        return {"access_token": access_token, "token_type": "bearer"}

    def google_login(self, token: str) -> dict:
        try:
            if settings.ALLOW_MOCK_AUTH and token == settings.MOCK_TOKEN:
                email = "mockuser@example.com"
                name = "Prism Developer"
            else:
                idinfo = id_token.verify_oauth2_token(token, requests.Request(), settings.GOOGLE_CLIENT_ID)
                email = idinfo['email']
                name = idinfo.get('name', '')
            
            user = self.repo.get_by_email(email)
            if not user:
                # Create a new user with a random secure password
                alphabet = string.ascii_letters + string.digits + string.punctuation
                random_password = ''.join(secrets.choice(alphabet) for i in range(20))
                hashed_password = get_password_hash(random_password)
                
                user_data = {
                    "id": str(uuid.uuid4()),
                    "email": email,
                    "hashed_password": hashed_password,
                    "full_name": name,
                    "role": UserRole.EDITOR.value
                }
                user = self.repo.create(user_data)
                
                # Seed default categories
                cat_service = CategoryService(self.db)
                cat_service.create_default_categories(user.id)
                
            access_token = create_access_token(data={"sub": user.email})
            return {"access_token": access_token, "token_type": "bearer"}
            
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid Google token")
        except Exception as e:
            print(f"Google login error: {e}")
            raise HTTPException(status_code=500, detail="Google login failed")
