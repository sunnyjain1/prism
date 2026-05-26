"""
Account Aggregator (AA) Integration Service.

The AA framework (India Stack) enables consent-based financial data sharing.
Flow: FIU (us) → AA (Setu/Finvu) → FIP (bank/NBFC) → data back to FIU.

Supported FI types:
- DEPOSIT (savings/current accounts)
- TERM_DEPOSIT (FDs)
- CREDIT_CARD
- LOAN (personal, home, auto, education)
- INSURANCE (life, health, motor)
- MUTUAL_FUND
- SECURITIES (demat holdings - NSDL/CDSL)
- CREDIT_SCORE (CIBIL/Experian/CRIF)

Integration partners (future):
- Setu AA (setu.co)
- Finvu (finvu.in)
- OneMoney (onemoney.in)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class AAProvider(str, Enum):
    SETU = "setu"
    FINVU = "finvu"
    ONEMONEY = "onemoney"


class FIType(str, Enum):
    DEPOSIT = "DEPOSIT"
    TERM_DEPOSIT = "TERM_DEPOSIT"
    CREDIT_CARD = "CREDIT_CARD"
    LOAN = "LOAN"
    INSURANCE = "INSURANCE"
    MUTUAL_FUND = "MUTUAL_FUND"
    SECURITIES = "SECURITIES"
    CREDIT_SCORE = "CREDIT_SCORE"


class ConsentStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AccountAggregatorService:
    """Handles AA consent flow and data fetch (stub for future integration)."""

    # In-memory consent store (replace with DB in production)
    _consent_store: dict[str, dict[str, Any]] = {}

    def get_supported_fi_types(self) -> list[dict[str, str]]:
        """Return list of supported financial information types."""
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
                "description": "Credit card balances and statements",
            },
            {
                "type": FIType.LOAN.value,
                "label": "Loans",
                "description": "Personal, home, auto, education loans",
            },
            {
                "type": FIType.INSURANCE.value,
                "label": "Insurance",
                "description": "Life, health, and motor insurance policies",
            },
            {
                "type": FIType.MUTUAL_FUND.value,
                "label": "Mutual Funds",
                "description": "MF holdings and NAV",
            },
            {
                "type": FIType.SECURITIES.value,
                "label": "Stocks & Demat",
                "description": "Equity holdings from NSDL/CDSL",
            },
            {
                "type": FIType.CREDIT_SCORE.value,
                "label": "Credit Score",
                "description": "CIBIL/Experian/CRIF score and report",
            },
        ]

    def initiate_consent(
        self,
        user_id: str,
        phone: str,
        fi_types: list[str],
        provider: str = AAProvider.SETU.value,
    ) -> dict[str, Any]:
        """Initiate AA consent request (stub)."""
        consent_id = f"consent_{secrets.token_hex(8)}"
        normalized_fi_types = [fi_type.value if isinstance(fi_type, FIType) else str(fi_type) for fi_type in fi_types]
        normalized_provider = provider.value if isinstance(provider, AAProvider) else str(provider).lower()
        redirect_url = f"https://aa-sandbox.example.com/consent/{consent_id}"
        now = datetime.now(timezone.utc)

        self._consent_store[consent_id] = {
            "user_id": user_id,
            "phone": phone,
            "fi_types": normalized_fi_types,
            "provider": normalized_provider,
            "status": ConsentStatus.PENDING,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=365)).isoformat(),
            "redirect_url": redirect_url,
        }

        # In production: call AA provider API to generate consent artifact.
        # User gets redirected to AA app for approval.
        return {
            "success": True,
            "consent_id": consent_id,
            "status": ConsentStatus.PENDING.value,
            "message": "Consent request created. In production, user will be redirected to AA app for approval.",
            "redirect_url": redirect_url,
            "fi_types_requested": normalized_fi_types,
            "provider": normalized_provider,
            "note": "Account Aggregator integration requires FIU registration with Sahamati. This is a development stub.",
        }

    def check_consent_status(self, consent_id: str) -> dict[str, Any]:
        """Check status of a consent request."""
        record = self._consent_store.get(consent_id)
        if not record:
            return {"success": False, "error": "Consent not found"}
        return {
            "success": True,
            "consent_id": consent_id,
            "status": record["status"],
            "fi_types": record["fi_types"],
            "created_at": record["created_at"],
        }

    def simulate_consent_approval(self, consent_id: str) -> dict[str, Any]:
        """Simulate consent approval (dev/testing only)."""
        record = self._consent_store.get(consent_id)
        if not record:
            return {"success": False, "error": "Consent not found"}
        record["status"] = ConsentStatus.APPROVED
        return {"success": True, "status": ConsentStatus.APPROVED.value, "message": "Consent approved (simulated)"}

    def fetch_financial_data(self, user_id: str, consent_id: str, fi_type: str) -> dict[str, Any]:
        """Fetch financial data for approved consent (stub)."""
        record = self._consent_store.get(consent_id)
        requested_fi_type = fi_type.value if isinstance(fi_type, FIType) else str(fi_type)
        if not record:
            return {"success": False, "error": "Consent not found"}
        if record["user_id"] != user_id:
            return {"success": False, "error": "Consent does not belong to user"}
        if record["status"] != ConsentStatus.APPROVED:
            return {"success": False, "error": f"Consent not approved (status: {record['status']})"}
        if requested_fi_type not in record["fi_types"]:
            return {"success": False, "error": f"FI type {requested_fi_type} not in consent scope"}

        return {
            "success": True,
            "fi_type": requested_fi_type,
            "status": "pending_integration",
            "message": f"AA data fetch for {requested_fi_type} is not yet available. Integration pending.",
            "data": [],
        }

    def fetch_credit_score(self, user_id: str, consent_id: str) -> dict[str, Any]:
        """Fetch credit score via AA (stub)."""
        return self.fetch_financial_data(user_id, consent_id, FIType.CREDIT_SCORE)

    def fetch_demat_holdings(self, user_id: str, consent_id: str) -> dict[str, Any]:
        """Fetch demat/securities holdings via AA (stub)."""
        return self.fetch_financial_data(user_id, consent_id, FIType.SECURITIES)

    def revoke_consent(self, consent_id: str) -> dict[str, Any]:
        """Revoke an existing consent."""
        record = self._consent_store.get(consent_id)
        if not record:
            return {"success": False, "error": "Consent not found"}
        record["status"] = ConsentStatus.REVOKED
        return {"success": True, "message": "Consent revoked successfully"}
