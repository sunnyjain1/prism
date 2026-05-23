import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import schemas
from auth_utils import decode_token
from core.config import settings
from core.dependencies import get_current_user
from services.auth_service import AuthService
from user_models import RefreshToken


@pytest.fixture
def auth_service(db_session):
    return AuthService(db_session)


def assert_token_response(response: dict):
    assert response["access_token"]
    assert response["refresh_token"]
    assert response["token_type"] == "bearer"
    assert response["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_register_success(auth_service, db_session):
    user_in = schemas.UserCreate(email="new@example.com", password="password123", full_name="New User")

    response = auth_service.register(user_in, device_info="Chrome on macOS")

    assert_token_response(response)
    user = auth_service.repo.get_by_email("new@example.com")
    assert user is not None
    assert user.full_name == "New User"

    session = db_session.query(RefreshToken).filter(RefreshToken.user_id == user.id).one()
    assert session.device_info == "Chrome on macOS"
    assert session.is_active is True


def test_register_duplicate_email(auth_service, db_session):
    user_in = schemas.UserCreate(email="dup@example.com", password="password123")
    auth_service.register(user_in)

    with pytest.raises(HTTPException) as exc:
        auth_service.register(user_in)

    assert exc.value.status_code == 400


def test_login_success(auth_service, db_session):
    user_in = schemas.UserCreate(email="login@example.com", password="password123")
    auth_service.register(user_in)

    response = auth_service.login("login@example.com", "password123", device_info="Safari")

    assert_token_response(response)


def test_login_failure(auth_service, db_session):
    user_in = schemas.UserCreate(email="fail@example.com", password="password123")
    auth_service.register(user_in)

    with pytest.raises(HTTPException) as exc:
        auth_service.login("fail@example.com", "wrongpassword")

    assert exc.value.status_code == 401


def test_refresh_tokens_rotate_session(auth_service, db_session):
    user_in = schemas.UserCreate(email="refresh@example.com", password="password123")
    initial_tokens = auth_service.register(user_in, device_info="Initial Device")
    user = auth_service.repo.get_by_email("refresh@example.com")
    original_session_id = decode_token(initial_tokens["refresh_token"])["jti"]

    refreshed_tokens = auth_service.refresh_tokens(initial_tokens["refresh_token"], device_info="Updated Device")

    assert_token_response(refreshed_tokens)
    assert refreshed_tokens["refresh_token"] != initial_tokens["refresh_token"]

    original_session = db_session.query(RefreshToken).filter(RefreshToken.id == original_session_id).one()
    assert original_session.is_active is False
    assert original_session.revoked_at is not None

    active_sessions = auth_service.list_sessions(user.id)
    assert len(active_sessions) == 1
    assert active_sessions[0].device_info == "Updated Device"


def test_logout_revokes_refresh_token(auth_service, db_session):
    user_in = schemas.UserCreate(email="logout@example.com", password="password123")
    tokens = auth_service.register(user_in)

    response = auth_service.logout(tokens["refresh_token"])

    assert response == {"message": "Logged out successfully"}
    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens(tokens["refresh_token"])
    assert exc.value.status_code == 401


def test_list_sessions_returns_active_sessions(auth_service, db_session):
    user_in = schemas.UserCreate(email="sessions@example.com", password="password123")
    first_tokens = auth_service.register(user_in, device_info="MacBook")
    second_tokens = auth_service.login("sessions@example.com", "password123", device_info="iPhone")

    user = auth_service.repo.get_by_email("sessions@example.com")
    sessions = auth_service.list_sessions(user.id)

    session_ids = {session.id for session in sessions}
    assert len(sessions) == 2
    assert decode_token(first_tokens["refresh_token"])["jti"] in session_ids
    assert decode_token(second_tokens["refresh_token"])["jti"] in session_ids


def test_revoke_specific_session(auth_service, db_session):
    user_in = schemas.UserCreate(email="revoke@example.com", password="password123")
    first_tokens = auth_service.register(user_in, device_info="Desktop")
    second_tokens = auth_service.login("revoke@example.com", "password123", device_info="Tablet")
    user = auth_service.repo.get_by_email("revoke@example.com")
    second_session_id = decode_token(second_tokens["refresh_token"])["jti"]

    auth_service.revoke_session(user.id, second_session_id)

    sessions = auth_service.list_sessions(user.id)
    assert len(sessions) == 1
    assert sessions[0].id == decode_token(first_tokens["refresh_token"])["jti"]

    with pytest.raises(HTTPException) as exc:
        auth_service.refresh_tokens(second_tokens["refresh_token"])
    assert exc.value.status_code == 401


def test_get_current_user_accepts_access_token_and_rejects_refresh_token(auth_service, db_session):
    user_in = schemas.UserCreate(email="current@example.com", password="password123")
    tokens = auth_service.register(user_in)
    user = auth_service.repo.get_by_email("current@example.com")

    current_user = asyncio.run(get_current_user(token=tokens["access_token"], db=db_session))
    assert current_user.id == user.id

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(token=tokens["refresh_token"], db=db_session))
    assert exc.value.status_code == 401


def test_google_login_mock_success(auth_service, db_session):
    with patch("services.auth_service.settings") as mock_settings:
        mock_settings.ALLOW_MOCK_AUTH = True
        mock_settings.MOCK_TOKEN = "test-token"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

        response = auth_service.google_login("test-token", device_info="Mock Browser")

        assert_token_response(response)
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
            mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

            response = auth_service.google_login("real-google-token")

            assert_token_response(response)
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
