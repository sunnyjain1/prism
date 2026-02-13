import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from services.auth_service import AuthService
import schemas
from user_models import User, UserRole
from core.config import settings

@pytest.fixture
def auth_service(db_session):
    return AuthService(db_session)

def test_register_success(auth_service, db_session):
    user_in = schemas.UserCreate(email="new@example.com", password="password123", full_name="New User")
    user = auth_service.register(user_in)
    assert user.email == "new@example.com"
    assert user.full_name == "New User"

def test_register_duplicate_email(auth_service, db_session):
    user_in = schemas.UserCreate(email="dup@example.com", password="password123")
    auth_service.register(user_in)
    with pytest.raises(HTTPException) as exc:
        auth_service.register(user_in)
    assert exc.value.status_code == 400

def test_login_success(auth_service, db_session):
    user_in = schemas.UserCreate(email="login@example.com", password="password123")
    auth_service.register(user_in)
    
    res = auth_service.login("login@example.com", "password123")
    assert "access_token" in res
    assert res["token_type"] == "bearer"

def test_login_failure(auth_service, db_session):
    user_in = schemas.UserCreate(email="fail@example.com", password="password123")
    auth_service.register(user_in)
    
    with pytest.raises(HTTPException) as exc:
        auth_service.login("fail@example.com", "wrongpassword")
    assert exc.value.status_code == 401

def test_google_login_mock_success(auth_service, db_session):
    with patch("services.auth_service.settings") as mock_settings:
        mock_settings.ALLOW_MOCK_AUTH = True
        mock_settings.MOCK_TOKEN = "test-token"
        mock_settings.SECRET_KEY = settings.SECRET_KEY
        mock_settings.ALGORITHM = settings.ALGORITHM
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        
        res = auth_service.google_login("test-token")
        assert "access_token" in res
        
        # Verify user was created
        user = auth_service.repo.get_by_email("mockuser@example.com")
        assert user is not None

def test_google_login_real_mocked_success(auth_service, db_session):
    with patch("services.auth_service.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.return_value = {
            "email": "google@example.com",
            "name": "Google User"
        }
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.ALLOW_MOCK_AUTH = False
            mock_settings.GOOGLE_CLIENT_ID = "some-id"
            mock_settings.SECRET_KEY = settings.SECRET_KEY
            mock_settings.ALGORITHM = settings.ALGORITHM
            mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
            
            res = auth_service.google_login("real-google-token")
            assert "access_token" in res
            
            user = auth_service.repo.get_by_email("google@example.com")
            assert user.full_name == "Google User"

def test_google_login_invalid_token(auth_service, db_session):
    with patch("services.auth_service.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.side_effect = ValueError("Invalid token")
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.ALLOW_MOCK_AUTH = False
            
            with pytest.raises(HTTPException) as exc:
                auth_service.google_login("bad-token")
            assert exc.value.status_code == 401

def test_google_login_general_exception(auth_service, db_session):
    with patch("services.auth_service.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.side_effect = Exception("Some error")
        with patch("services.auth_service.settings") as mock_settings:
            mock_settings.ALLOW_MOCK_AUTH = False
            
            with pytest.raises(HTTPException) as exc:
                auth_service.google_login("error-token")
            assert exc.value.status_code == 500
