"""
Account Aggregator (AA) Integration Service.

The AA framework (India Stack) enables consent-based financial data sharing.
Flow: FIU (us) → AA (Setu/OneMoney/Anumati) → FIP (bank/NBFC) → data back to FIU.

This service is DB-backed and provider-agnostic: it persists the consent lifecycle
in ``aa_consents`` and delegates the wire protocol to a :class:`services.aa.AAClient`
(Setu by default; Anumati pluggable). The user is redirected to the AA's hosted
consent page; on approval we open a data session and materialize real accounts.

Supported FI types (this build): DEPOSIT, TERM_DEPOSIT, CREDIT_CARD, LOAN.
PAN/DOB are accepted only as discovery hints and are NEVER persisted.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.config import settings
from models import AAConsent
from services.aa import AAError, AAConsentStatus, get_aa_client
from services.aa.mapper import AAMapper
from user_models import User

logger = logging.getLogger(__name__)


class AAProvider(str, Enum):
    SETU = "setu"
    FINVU = "finvu"
    ONEMONEY = "onemoney"
    ANUMATI = "anumati"


class FIType(str, Enum):
    DEPOSIT = "DEPOSIT"
    TERM_DEPOSIT = "TERM_DEPOSIT"
    CREDIT_CARD = "CREDIT_CARD"
    LOAN = "LOAN"
    INSURANCE = "INSURANCE"
    MUTUAL_FUND = "MUTUAL_FUND"
    SECURITIES = "SECURITIES"
    CREDIT_SCORE = "CREDIT_SCORE"


class AccountAggregatorService:
    """Handles the real AA consent + data-fetch flow, persisted in the DB."""

    def __init__(self, db: Session):
        self.db = db
        self.client = get_aa_client()

    # ------------------------------------------------------------------ metadata
    def get_supported_fi_types(self) -> list[dict[str, str]]:
        """Return the FI types this build can discover and materialize."""
        return [
            {
                "type": FIType.DEPOSIT.value,
                "label": "Bank Accounts",
                "description": "Savings & current account balances and transactions",
            },
            {
                "type": FIType.TERM_DEPOSIT.value,
                "label": "Fixed Deposits",
                "description": "FD details, maturity dates, interest rates",
            },
            {
                "type": FIType.CREDIT_CARD.value,
                "label": "Credit Cards",
                "description": "Credit card outstanding and statements",
            },
            {
                "type": FIType.LOAN.value,
                "label": "Loans",
                "description": "Personal, home, auto, education loans",
            },
        ]

    # ------------------------------------------------------------------ consent
    def initiate_consent(
        self,
        user: User,
        phone: str,
        fi_types: list[str],
        pan: Optional[str] = None,
        dob: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Create a consent request with the AA and persist it. Returns the hosted
        ``consent_url`` to redirect the user to. PAN/DOB are forwarded as discovery
        hints only and are never stored.
        """
        try:
            result = self.client.create_consent(
                phone=phone,
                fi_types=fi_types,
                redirect_url=settings.AA_REDIRECT_URL,
                pan=pan,
                dob=dob,
                consent_expiry_days=settings.AA_CONSENT_EXPIRY_DAYS,
                fetch_from_months=settings.AA_FETCH_FROM_MONTHS,
            )
        except AAError as exc:
            logger.error("AA create_consent failed for user %s: %s", user.id, exc)
            raise HTTPException(status_code=502, detail=f"Account Aggregator error: {exc}")

        consent = AAConsent(
            user_id=user.id,
            provider=settings.AA_PROVIDER,
            consent_handle=result.consent_handle,
            consent_id=result.consent_id,
            status=result.status.value,
            fi_types_json=json.dumps(fi_types),
            consent_url=result.consent_url,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.AA_CONSENT_EXPIRY_DAYS),
        )
        self.db.add(consent)

        # Persist the verified mobile number for reuse on later syncs (PAN/DOB are NOT stored).
        if phone and getattr(user, "phone_number", None) != phone:
            db_user = self.db.query(User).filter(User.id == user.id).first()
            if db_user:
                db_user.phone_number = phone

        self.db.commit()
        self.db.refresh(consent)
        return {
            "success": True,
            "consent_id": consent.id,
            "status": consent.status,
            "consent_url": consent.consent_url,
            "fi_types": fi_types,
        }

    def get_consent_status(self, consent_id: str, user_id: str) -> dict[str, Any]:
        """Poll the AA for the latest status and update the persisted row."""
        consent = self._get_owned_consent(consent_id, user_id)
        # Terminal states need no further polling.
        if consent.status not in (AAConsentStatus.PENDING.value,):
            return self._consent_payload(consent)
        try:
            result = self.client.get_consent_status(consent.consent_handle)
        except AAError as exc:
            logger.warning("AA status poll failed for consent %s: %s", consent.id, exc)
            return self._consent_payload(consent)

        consent.status = result.status.value
        if result.consent_id:
            consent.consent_id = result.consent_id
        self.db.commit()
        self.db.refresh(consent)
        return self._consent_payload(consent)

    def fetch_and_materialize(self, consent_id: str, user_id: str) -> dict[str, Any]:
        """Open a data session against an approved consent and import real accounts."""
        consent = self._get_owned_consent(consent_id, user_id)
        if consent.status != AAConsentStatus.APPROVED.value:
            raise HTTPException(
                status_code=409,
                detail=f"Consent is not approved (status: {consent.status}).",
            )
        try:
            session_id = self.client.create_data_session(
                consent.consent_id, fetch_from_months=settings.AA_FETCH_FROM_MONTHS
            )
            consent.data_session_id = session_id
            self.db.commit()
            fi_accounts = self.client.fetch_fi_data(session_id)
        except AAError as exc:
            logger.error("AA data fetch failed for consent %s: %s", consent.id, exc)
            raise HTTPException(status_code=502, detail=f"Account Aggregator error: {exc}")

        summary = AAMapper(self.db, user_id).materialize(fi_accounts)
        consent.last_fetched_at = datetime.now(timezone.utc)
        self.db.commit()
        return {"success": True, "consent_id": consent.id, **summary}

    def revoke_consent(self, consent_id: str, user_id: str) -> dict[str, Any]:
        consent = self._get_owned_consent(consent_id, user_id)
        try:
            if consent.consent_id:
                self.client.revoke_consent(consent.consent_id)
        except AAError as exc:
            logger.warning("AA revoke failed for consent %s: %s", consent.id, exc)
        consent.status = AAConsentStatus.REVOKED.value
        self.db.commit()
        return {"success": True, "status": consent.status}

    def set_consent_url(self, consent_id: str, user_id: str, url: str) -> None:
        """Override the stored consent URL (used to point the mock provider at its approval page)."""
        consent = self._get_owned_consent(consent_id, user_id)
        consent.consent_url = url
        self.db.commit()

    def mark_mock_approved(self, consent_id: str) -> bool:
        """Dev-only: mark a mock consent approved (called when the mock approval page is opened)."""
        consent = self.db.query(AAConsent).filter(AAConsent.id == consent_id).first()
        if not consent:
            return False
        consent.status = AAConsentStatus.APPROVED.value
        self.db.commit()
        return True

    def get_latest_approved_consent(self, user_id: str) -> Optional[AAConsent]:
        """Used by the discovery orchestrator to fetch without re-prompting consent."""
        return (
            self.db.query(AAConsent)
            .filter(
                AAConsent.user_id == user_id,
                AAConsent.status == AAConsentStatus.APPROVED.value,
            )
            .order_by(AAConsent.created_at.desc())
            .first()
        )

    # ------------------------------------------------------------------ helpers
    def _get_owned_consent(self, consent_id: str, user_id: str) -> AAConsent:
        consent = (
            self.db.query(AAConsent)
            .filter(AAConsent.id == consent_id, AAConsent.user_id == user_id)
            .first()
        )
        if not consent:
            raise HTTPException(status_code=404, detail="Consent not found")
        return consent

    @staticmethod
    def _consent_payload(consent: AAConsent) -> dict[str, Any]:
        return {
            "success": True,
            "consent_id": consent.id,
            "status": consent.status,
            "consent_url": consent.consent_url,
            "fi_types": json.loads(consent.fi_types_json or "[]"),
        }
