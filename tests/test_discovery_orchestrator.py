"""
Tests for FinancialDiscoveryOrchestrator, discovery API, and discovery audit logs.
"""
from uuid import uuid4

import pytest

from models import DiscoveryAuditLog


def _make_user():
    suffix = uuid4().hex[:8]
    return {
        "email": f"discovery-{suffix}@example.com",
        "password": "Password123!",
        "full_name": "Discovery Test User",
    }


def _register_and_login(client) -> dict:
    payload = _make_user()
    r = client.post("/api/v1/auth/register", json=payload, headers={"user-agent": "pytest"})
    assert r.status_code == 200, r.text
    login = client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
        headers={"user-agent": "pytest"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _patch_orchestrator_session(monkeypatch, db_session):
    """Make sure the discovery orchestrator's background worker uses the test DB."""
    from sqlalchemy.orm import sessionmaker
    from services import financial_discovery_orchestrator as orch_module

    background_session_factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(orch_module, "SessionLocal", background_session_factory)


def test_start_discovery_creates_session(api_client):
    """POST /discovery/start returns a session with queued or running status."""
    headers = _register_and_login(api_client)
    r = api_client.post("/api/v1/discovery/start", json={}, headers=headers)
    assert r.status_code == 202, r.text
    data = r.json()
    assert "session_id" in data
    assert data["overall_status"] in ("queued", "running", "completed", "partial_success")
    assert set(data["phases"].keys()) == {
        "bank_accounts", "investments", "retirement", "credit_report", "alternative"
    }


def test_start_discovery_with_selected_categories(api_client):
    """POST /discovery/start with categories skips unselected phases."""
    headers = _register_and_login(api_client)
    r = api_client.post(
        "/api/v1/discovery/start",
        json={"categories": ["bank_accounts", "credit_report"]},
        headers=headers,
    )
    assert r.status_code == 202, r.text
    data = r.json()
    assert data["phases"]["investments"]["status"] == "skipped"
    assert data["phases"]["retirement"]["status"] == "skipped"
    assert data["phases"]["alternative"]["status"] == "skipped"


def test_get_discovery_status_returns_latest_session(api_client):
    """GET /discovery/status returns the most recent session."""
    headers = _register_and_login(api_client)
    start = api_client.post("/api/v1/discovery/start", json={}, headers=headers)
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    r = api_client.get("/api/v1/discovery/status", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["session_id"] == session_id


def test_get_discovery_status_by_id(api_client):
    """GET /discovery/status/{id} returns the specific session."""
    headers = _register_and_login(api_client)
    start = api_client.post("/api/v1/discovery/start", json={}, headers=headers)
    session_id = start.json()["session_id"]

    r = api_client.get(f"/api/v1/discovery/status/{session_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["session_id"] == session_id


def test_get_discovery_status_404_when_no_session(api_client):
    """GET /discovery/status returns 404 when the user has no session."""
    headers = _register_and_login(api_client)
    r = api_client.get("/api/v1/discovery/status", headers=headers)
    assert r.status_code == 404


def test_get_discovery_status_by_id_404_for_wrong_user(api_client):
    """GET /discovery/status/{id} returns 404 if session belongs to another user."""
    headers_a = _register_and_login(api_client)
    headers_b = _register_and_login(api_client)
    start = api_client.post("/api/v1/discovery/start", json={}, headers=headers_a)
    session_id = start.json()["session_id"]

    r = api_client.get(f"/api/v1/discovery/status/{session_id}", headers=headers_b)
    assert r.status_code == 404


def test_list_discovery_sessions(api_client):
    """GET /discovery/sessions returns up to 10 sessions."""
    headers = _register_and_login(api_client)
    api_client.post("/api/v1/discovery/start", json={}, headers=headers)
    api_client.post("/api/v1/discovery/start", json={}, headers=headers)

    r = api_client.get("/api/v1/discovery/sessions", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 2


def test_audit_log_emitted_on_discovery_start(api_client, db_session):
    """Starting a discovery session emits a discovery_started audit log."""
    headers = _register_and_login(api_client)
    start = api_client.post("/api/v1/discovery/start", json={}, headers=headers)
    session_id = start.json()["session_id"]

    log = (
        db_session.query(DiscoveryAuditLog)
        .filter(
            DiscoveryAuditLog.event_type == "discovery_started",
            DiscoveryAuditLog.entity_id == session_id,
        )
        .first()
    )
    assert log is not None, "discovery_started audit log not found"
    assert log.entity_type == "discovery_session"
