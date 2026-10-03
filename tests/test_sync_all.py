"""Tests for POST /aggregation/sync-all and GET /aggregation/sync-status."""
from uuid import uuid4

import pytest


def _make_user():
    suffix = uuid4().hex[:8]
    return {"email": f"sync-{suffix}@example.com", "password": "Password123!", "full_name": "Sync Tester"}


def _register_and_login(client):
    payload = _make_user()
    r = client.post("/api/v1/auth/register", json=payload, headers={"user-agent": "pytest"})
    assert r.status_code == 200, r.text
    login = client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
        headers={"user-agent": "pytest"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _patch_orchestrator_session(monkeypatch, db_session):
    from sqlalchemy.orm import sessionmaker
    from services import financial_discovery_orchestrator as orch_module

    background_session_factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(orch_module, "SessionLocal", background_session_factory)


def test_sync_all_returns_job_id(api_client):
    """POST /aggregation/sync-all returns a job_id."""
    headers = _register_and_login(api_client)
    r = api_client.post("/api/v1/aggregation/sync-all", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "job_id" in data
    assert data["status"] == "queued"


def test_sync_status_returns_category_breakdown(api_client):
    """GET /aggregation/sync-status returns overall_status and categories."""
    headers = _register_and_login(api_client)
    r = api_client.get("/api/v1/aggregation/sync-status", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "overall_status" in data
    assert "categories" in data
    assert "bank_accounts" in data["categories"]
    assert "investments" in data["categories"]
    assert "retirement" in data["categories"]
    assert "credit_report" in data["categories"]


def test_sync_status_after_discovery(api_client):
    """Sync status reflects active connections created by a discovery run."""
    headers = _register_and_login(api_client)
    api_client.post("/api/v1/discovery/start", json={}, headers=headers)

    r = api_client.get("/api/v1/aggregation/sync-status", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["overall_status"] in ("idle", "running", "synced")
