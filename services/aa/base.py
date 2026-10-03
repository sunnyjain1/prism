"""
Provider-agnostic Account Aggregator client contract + normalized DTOs.

Every concrete AA provider (Setu, Anumati, ...) implements :class:`AAClient` and
returns these normalized structures, so the rest of the app never depends on a
specific provider's wire format.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class AAConsentStatus(str, Enum):
    """Normalized consent lifecycle, independent of provider wording."""

    PENDING = "pending"      # created, awaiting user approval on the AA page
    APPROVED = "approved"    # user approved (Setu "ACTIVE")
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"
    FAILED = "failed"


class AAError(Exception):
    """Raised when an AA provider call fails."""


@dataclass
class AAConsentResult:
    """Outcome of a create-consent / consent-status call."""

    status: AAConsentStatus
    consent_handle: Optional[str] = None   # provider handle returned at creation time
    consent_id: Optional[str] = None       # signed consent id, present once APPROVED
    consent_url: Optional[str] = None       # hosted page the user is redirected to
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AAFiTransaction:
    """A single transaction inside an FI account, normalized."""

    amount: float
    txn_type: str            # "CREDIT" or "DEBIT"
    narration: str
    value_date: datetime
    txn_id: Optional[str] = None
    mode: Optional[str] = None
    reference: Optional[str] = None


@dataclass
class AAFiAccount:
    """One discovered financial account, normalized across FI types."""

    fi_type: str                       # DEPOSIT | TERM_DEPOSIT | CREDIT_CARD | LOAN ...
    fip_name: str                      # FIP / institution display name
    masked_account_number: str
    account_sub_type: Optional[str] = None  # SAVINGS | CURRENT | ... (for DEPOSIT)
    currency: str = "INR"
    current_balance: float = 0.0       # DEPOSIT balance / card outstanding / loan outstanding
    transactions: list[AAFiTransaction] = field(default_factory=list)
    # Optional per-FI-type extras (FD maturity, card limit, loan principal/EMI, ...)
    credit_limit: Optional[float] = None
    principal: Optional[float] = None
    emi_amount: Optional[float] = None
    interest_rate: Optional[float] = None
    maturity_value: Optional[float] = None
    linked_ref_number: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


class AAClient(abc.ABC):
    """Contract every AA provider implementation fulfils."""

    provider_name: str = "base"

    @abc.abstractmethod
    def create_consent(
        self,
        *,
        phone: str,
        fi_types: list[str],
        redirect_url: str,
        pan: Optional[str] = None,
        dob: Optional[str] = None,
        consent_expiry_days: int = 365,
        fetch_from_months: int = 12,
    ) -> AAConsentResult:
        """Create a consent request and return the hosted consent URL + handle."""

    @abc.abstractmethod
    def get_consent_status(self, consent_handle: str) -> AAConsentResult:
        """Poll the current status of a consent by its handle."""

    @abc.abstractmethod
    def create_data_session(self, consent_id: str, fetch_from_months: int = 12) -> str:
        """Create a data session against an approved consent. Returns session id."""

    @abc.abstractmethod
    def fetch_fi_data(self, session_id: str) -> list[AAFiAccount]:
        """Fetch and decrypt FI data for a prepared session, normalized to accounts."""

    @abc.abstractmethod
    def revoke_consent(self, consent_id: str) -> bool:
        """Revoke an active consent. Returns True on success."""
