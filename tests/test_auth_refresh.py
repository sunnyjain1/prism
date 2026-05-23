from datetime import timedelta
from uuid import uuid4

from auth_utils import create_access_token, decode_token
from user_models import RefreshToken, User


DEFAULT_PASSWORD = "Password123!"


def register_user(client, user_agent: str = "pytest-register") -> tuple[dict, dict]:
    payload = {
        "email": f"auth-{uuid4().hex}@example.com",
        "password": DEFAULT_PASSWORD,
        "full_name": "Auth Refresh User",
    }
    response = client.post(
        "/api/v1/auth/register",
        json=payload,
        headers={"user-agent": user_agent},
    )
    assert response.status_code == 200, response.text
    return payload, response.json()


def login_user(client, email: str, password: str, user_agent: str = "pytest-login") -> dict:
    response = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"user-agent": user_agent},
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def test_login_generates_refresh_token(api_client, db_session):
    user_payload, _ = register_user(api_client)

    login_tokens = login_user(api_client, user_payload["email"], user_payload["password"], user_agent="pytest-login-device")
    assert login_tokens["refresh_token"]

    user = db_session.query(User).filter(User.email == user_payload["email"]).one()
    active_sessions = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.is_active.is_(True))
        .all()
    )

    login_session_id = decode_token(login_tokens["refresh_token"])["jti"]
    assert login_session_id in {session.id for session in active_sessions}


def test_refresh_endpoint_rotates_refresh_tokens(api_client):
    _, tokens = register_user(api_client)

    refresh_response = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"user-agent": "pytest-refreshed-device"},
    )
    assert refresh_response.status_code == 200, refresh_response.text
    refreshed_tokens = refresh_response.json()
    assert refreshed_tokens["refresh_token"] != tokens["refresh_token"]
    assert refreshed_tokens["access_token"] != tokens["access_token"]

    old_refresh_response = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert old_refresh_response.status_code == 401
    assert old_refresh_response.json()["error"] == "unauthorized"

    me_response = api_client.get(
        "/api/v1/auth/me",
        headers=auth_headers(refreshed_tokens["access_token"]),
    )
    assert me_response.status_code == 200, me_response.text


def test_google_login_accepts_credential_payload(api_client, db_session, monkeypatch):
    monkeypatch.setattr("services.auth_service.settings.ALLOW_MOCK_AUTH", True)
    monkeypatch.setattr("services.auth_service.settings.MOCK_TOKEN", "dev-token-prism")

    response = api_client.post(
        "/api/v1/auth/google",
        json={"credential": "dev-token-prism"},
        headers={"user-agent": "pytest-google-login"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]

    user = db_session.query(User).filter(User.email == "mockuser@example.com").one()
    assert user.full_name == "Prism Developer"


def test_expired_access_token_is_rejected(api_client):
    _, tokens = register_user(api_client)
    user_id = decode_token(tokens["access_token"])["sub"]
    expired_token = create_access_token({"sub": user_id}, expires_delta=timedelta(seconds=-1))

    response = api_client.get("/api/v1/auth/me", headers=auth_headers(expired_token))

    assert response.status_code == 401
    assert response.json() == {
        "error": "unauthorized",
        "message": "Could not validate credentials",
    }


def test_sessions_endpoint_lists_active_sessions(api_client):
    user_payload, register_tokens = register_user(api_client, user_agent="Desktop Browser")
    login_tokens = login_user(api_client, user_payload["email"], user_payload["password"], user_agent="Tablet App")

    sessions_response = api_client.get(
        "/api/v1/auth/sessions",
        headers=auth_headers(login_tokens["access_token"]),
    )
    assert sessions_response.status_code == 200, sessions_response.text
    sessions = sessions_response.json()

    assert len(sessions) == 2
    assert {session["id"] for session in sessions} == {
        decode_token(register_tokens["refresh_token"])["jti"],
        decode_token(login_tokens["refresh_token"])["jti"],
    }
    assert {session["device_info"] for session in sessions} == {"Desktop Browser", "Tablet App"}


def test_session_revocation_invalidates_that_refresh_token(api_client):
    user_payload, register_tokens = register_user(api_client, user_agent="Laptop")
    login_tokens = login_user(api_client, user_payload["email"], user_payload["password"], user_agent="Phone")
    revoked_session_id = decode_token(login_tokens["refresh_token"])["jti"]

    revoke_response = api_client.delete(
        f"/api/v1/auth/sessions/{revoked_session_id}",
        headers=auth_headers(register_tokens["access_token"]),
    )
    assert revoke_response.status_code == 204, revoke_response.text

    sessions_response = api_client.get(
        "/api/v1/auth/sessions",
        headers=auth_headers(register_tokens["access_token"]),
    )
    assert sessions_response.status_code == 200, sessions_response.text
    remaining_session_ids = {session["id"] for session in sessions_response.json()}
    assert remaining_session_ids == {decode_token(register_tokens["refresh_token"])["jti"]}

    refresh_response = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_tokens["refresh_token"]},
    )
    assert refresh_response.status_code == 401
    assert refresh_response.json()["error"] == "unauthorized"


def test_logout_invalidates_refresh_token(api_client):
    _, tokens = register_user(api_client)

    logout_response = api_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert logout_response.status_code == 200, logout_response.text
    assert logout_response.json() == {"message": "Logged out successfully"}

    refresh_response = api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_response.status_code == 401
    assert refresh_response.json()["error"] == "unauthorized"
