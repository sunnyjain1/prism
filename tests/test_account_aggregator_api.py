"""
Tests for the Account Aggregator (AA) bank-account auto-detection flow.

The AA provider client is faked so no real network call is made — we assert the
DB-backed consent lifecycle, that PAN/DOB are never persisted, and that FI data is
materialized into real Account rows with correct balance semantics and dedup.
"""
from datetime import datetime, timezone

import pytest

import services.account_aggregator_service as aa_service_module
from models import AAConsent, Account, Transaction
from services.aa.base import (
    AAConsentResult,
    AAConsentStatus,
    AAFiAccount,
    AAFiTransaction,
)
from user_models import User


AA_EMAIL = "aa@test.com"
AA_PASSWORD = "Password123!"


def _auth(api_client):
    r = api_client.post(
        "/api/v1/auth/register",
        json={"email": AA_EMAIL, "password": AA_PASSWORD, "full_name": "AA User"},
        headers={"user-agent": "pytest"},
    )
    assert r.status_code == 200, r.text
    login = api_client.post(
        "/api/v1/auth/login",
        data={"username": AA_EMAIL, "password": AA_PASSWORD},
        headers={"user-agent": "pytest"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _patch_orchestrator_session(monkeypatch, db_session):
    """Make the background discovery job use the test's transaction-bound session."""
    from sqlalchemy.orm import sessionmaker
    from services import financial_discovery_orchestrator as orch_module

    background_session_factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(orch_module, "SessionLocal", background_session_factory)


def _sample_fi_accounts():
    return [
        AAFiAccount(
            fi_type="DEPOSIT",
            fip_name="HDFC Bank",
            masked_account_number="XXXXXX1234",
            account_sub_type="SAVINGS",
            current_balance=124300.0,
            transactions=[
                AAFiTransaction(1500.0, "DEBIT", "Swiggy order", datetime(2026, 6, 1, tzinfo=timezone.utc)),
                AAFiTransaction(50000.0, "CREDIT", "Salary", datetime(2026, 6, 2, tzinfo=timezone.utc)),
            ],
        ),
        AAFiAccount(
            fi_type="CREDIT_CARD",
            fip_name="Axis Bank",
            masked_account_number="XXXXXX9876",
            current_balance=12400.0,
            principal=12400.0,
            credit_limit=100000.0,
        ),
    ]


class FakeAAClient:
    """Configurable in-memory AA client standing in for Setu."""

    provider_name = "fake"
    created_with = {}

    def create_consent(self, **kwargs):
        FakeAAClient.created_with = kwargs
        return AAConsentResult(
            status=AAConsentStatus.PENDING,
            consent_handle="handle-1",
            consent_id="consent-1",
            consent_url="https://aa.example/approve/handle-1",
        )

    def get_consent_status(self, consent_handle):
        return AAConsentResult(
            status=AAConsentStatus.APPROVED,
            consent_handle=consent_handle,
            consent_id="consent-1",
        )

    def create_data_session(self, consent_id, fetch_from_months=12):
        return "session-1"

    def fetch_fi_data(self, session_id):
        return _sample_fi_accounts()

    def revoke_consent(self, consent_id):
        return True


@pytest.fixture
def fake_aa(monkeypatch):
    client = FakeAAClient()
    monkeypatch.setattr(aa_service_module, "get_aa_client", lambda: client)
    return client


def test_initiate_persists_consent_and_phone_but_not_pan(api_client, fake_aa, db_session):
    headers = _auth(api_client)
    r = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT", "CREDIT_CARD"], "pan": "ABCDE1234F"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == AAConsentStatus.PENDING.value
    assert body["consent_url"].startswith("https://aa.example/")

    # Phone persisted on the user; PAN forwarded to the client but NEVER stored.
    user = db_session.query(User).filter(User.email == "aa@test.com").first()
    assert user.phone_number == "9876543210"
    assert fake_aa.created_with["pan"] == "ABCDE1234F"
    consent = db_session.query(AAConsent).filter(AAConsent.user_id == user.id).first()
    assert consent is not None
    assert "ABCDE1234F" not in (consent.fi_types_json or "")
    assert not any(c.name == "pan" for c in AAConsent.__table__.columns)


def test_status_poll_moves_to_approved(api_client, fake_aa, db_session):
    headers = _auth(api_client)
    consent_id = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT"]},
        headers=headers,
    ).json()["consent_id"]

    r = api_client.get(f"/api/v1/account-aggregator/consent/{consent_id}/status", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == AAConsentStatus.APPROVED.value


def test_fetch_materializes_real_accounts_with_balance_semantics(api_client, fake_aa, db_session):
    headers = _auth(api_client)
    consent_id = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT", "CREDIT_CARD"]},
        headers=headers,
    ).json()["consent_id"]
    # Approve via status poll, then fetch.
    api_client.get(f"/api/v1/account-aggregator/consent/{consent_id}/status", headers=headers)

    r = api_client.post(f"/api/v1/account-aggregator/consent/{consent_id}/fetch", headers=headers)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["accounts_created"] == 2
    assert summary["transactions_imported"] == 2

    user = db_session.query(User).filter(User.email == "aa@test.com").first()
    accounts = db_session.query(Account).filter(Account.owner_id == user.id).all()
    by_type = {a.type: a for a in accounts}
    # Asset account: positive balance = money in (authoritative AA balance, not txn-adjusted).
    assert by_type["savings"].balance == 124300.0
    # Liability account: positive balance = amount owed.
    assert by_type["credit"].balance == 12400.0
    assert by_type["credit"].credit_limit == 100000.0


def test_refetch_is_idempotent_no_duplicates(api_client, fake_aa, db_session):
    headers = _auth(api_client)
    consent_id = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT", "CREDIT_CARD"]},
        headers=headers,
    ).json()["consent_id"]
    api_client.get(f"/api/v1/account-aggregator/consent/{consent_id}/status", headers=headers)

    api_client.post(f"/api/v1/account-aggregator/consent/{consent_id}/fetch", headers=headers)
    second = api_client.post(
        f"/api/v1/account-aggregator/consent/{consent_id}/fetch", headers=headers
    ).json()

    # Second run updates, never duplicates.
    assert second["accounts_created"] == 0
    assert second["accounts_updated"] == 2
    assert second["transactions_imported"] == 0

    user = db_session.query(User).filter(User.email == "aa@test.com").first()
    assert db_session.query(Account).filter(Account.owner_id == user.id).count() == 2
    assert db_session.query(Transaction).filter(Transaction.owner_id == user.id).count() == 2


def test_mock_provider_completes_flow_end_to_end(api_client, monkeypatch, db_session):
    """The built-in mock provider lets the whole flow finish with no real credentials."""
    from services.aa.mock_client import MockAAClient

    monkeypatch.setattr(aa_service_module, "get_aa_client", lambda: MockAAClient())
    headers = _auth(api_client)

    init = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT", "CREDIT_CARD", "TERM_DEPOSIT", "LOAN"]},
        headers=headers,
    ).json()
    consent_id = init["consent_id"]
    # Mock initiate points the consent URL at our own approval page.
    assert init["consent_url"].endswith(f"/mock/approve/{consent_id}")

    # Opening the mock approval page (unauthenticated, like a browser) marks it approved.
    page = api_client.get(f"/api/v1/account-aggregator/mock/approve/{consent_id}")
    assert page.status_code == 200
    assert "approved" in page.text.lower()

    summary = api_client.post(
        f"/api/v1/account-aggregator/consent/{consent_id}/fetch", headers=headers
    ).json()
    assert summary["accounts_created"] == 3   # 2 deposits + 1 credit card
    assert summary["assets_created"] == 1      # FD
    assert summary["loans_created"] == 1
    assert summary["transactions_imported"] == 5


def test_fetch_rejected_when_consent_not_approved(api_client, fake_aa, db_session):
    headers = _auth(api_client)
    consent_id = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT"]},
        headers=headers,
    ).json()["consent_id"]
    # No status poll → still PENDING.
    r = api_client.post(f"/api/v1/account-aggregator/consent/{consent_id}/fetch", headers=headers)
    assert r.status_code == 409


def test_discovery_bank_phase_uses_consent_and_credit_phase_does_not_crash(
    api_client, fake_aa, db_session
):
    """Regression: orchestrator materializes via approved consent and the credit
    phase no longer crashes on a bad fetch_credit_report kwarg."""
    headers = _auth(api_client)
    consent_id = api_client.post(
        "/api/v1/account-aggregator/consent/initiate",
        json={"phone": "9876543210", "fi_types": ["DEPOSIT", "CREDIT_CARD"]},
        headers=headers,
    ).json()["consent_id"]
    api_client.get(f"/api/v1/account-aggregator/consent/{consent_id}/status", headers=headers)

    start = api_client.post(
        "/api/v1/discovery/start",
        json={"categories": ["bank_accounts", "credit_report"]},
        headers=headers,
    )
    assert start.status_code in (200, 201, 202), start.text
    session_id = start.json()["session_id"]

    status = api_client.get(f"/api/v1/discovery/status/{session_id}", headers=headers).json()
    # Job queue runs synchronously in tests, so it is already terminal.
    assert status["overall_status"] in ("completed", "partial_success")
    phases = status["phases"]
    assert phases["credit_report"]["status"] != "failed"  # the kwarg crash is fixed

    user = db_session.query(User).filter(User.email == "aa@test.com").first()
    assert db_session.query(Account).filter(Account.owner_id == user.id).count() == 2
