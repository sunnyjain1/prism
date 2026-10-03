"""
Setu (OneMoney) Account Aggregator FIU client.

Implements the provider-agnostic :class:`AAClient` contract against Setu's FIU
Data APIs. Uses synchronous ``requests`` (matching the existing pattern in
``services/investment_service.py``) — do NOT introduce asyncio here (see backend
CLAUDE.md: the DB session is sync).

Sandbox defaults (``settings.SETU_AA_BASE_URL = https://fiu-sandbox.setu.co``) work
end-to-end with Setu's mock FIP. Going live = swapping the base URL + credentials.

Reference: https://docs.setu.co/data/account-aggregator
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from core.config import settings
from services.aa.base import (
    AAClient,
    AAConsentResult,
    AAConsentStatus,
    AAError,
    AAFiAccount,
    AAFiTransaction,
)

logger = logging.getLogger(__name__)

# Setu consent statuses -> normalized statuses.
_SETU_STATUS_MAP = {
    "PENDING": AAConsentStatus.PENDING,
    "ACTIVE": AAConsentStatus.APPROVED,
    "REJECTED": AAConsentStatus.REJECTED,
    "REVOKED": AAConsentStatus.REVOKED,
    "PAUSED": AAConsentStatus.REVOKED,
    "EXPIRED": AAConsentStatus.EXPIRED,
    "FAILED": AAConsentStatus.FAILED,
}


def _parse_dt(value: Any) -> datetime:
    """Best-effort ISO-8601 parse; falls back to now() so a bad row never crashes a sync."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value[: len(fmt) + 4], fmt)
                except ValueError:
                    continue
    return datetime.now(timezone.utc)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SetuAAClient(AAClient):
    provider_name = "setu"

    def __init__(self) -> None:
        self.base_url = settings.SETU_AA_BASE_URL
        self.fiu_id = settings.AA_FIU_ID
        self.timeout = settings.AA_HTTP_TIMEOUT

    # ------------------------------------------------------------------ helpers
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-client-id": settings.SETU_AA_CLIENT_ID,
            "x-client-secret": settings.SETU_AA_CLIENT_SECRET,
            "x-product-instance-id": settings.SETU_AA_PRODUCT_INSTANCE_ID,
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise AAError(f"Setu request to {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise AAError(f"Setu {path} returned {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as exc:
            raise AAError(f"Setu request to {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise AAError(f"Setu {path} returned {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    # ------------------------------------------------------------------ consent
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
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=consent_expiry_days)
        fetch_from = now - timedelta(days=30 * fetch_from_months)

        # PAN/DOB are passed only as discovery identifiers and are never persisted by us.
        identifiers: list[dict[str, str]] = [{"type": "MOBILE", "value": phone}]
        if pan:
            identifiers.append({"type": "PAN", "value": pan})
        if dob:
            identifiers.append({"type": "DOB", "value": dob})

        payload = {
            "consentDuration": {"unit": "MONTH", "value": str(consent_expiry_days // 30 or 1)},
            "vua": f"{phone}@onemoney",
            "dataRange": {
                "from": fetch_from.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            },
            "consentMode": "STORE",
            "consentTypes": ["TRANSACTIONS", "PROFILE", "SUMMARY"],
            "fiTypes": fi_types,
            "fetchType": "PERIODIC",
            "Frequency": {"unit": "DAY", "value": 1},
            "DataLife": {"unit": "MONTH", "value": consent_expiry_days // 30 or 1},
            "purpose": {
                "code": "101",
                "text": "Wealth management / personal finance aggregation",
                "category": {"type": "Personal Finance"},
            },
            "identifiers": identifiers,
            "expireAfter": expiry.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "redirectUrl": redirect_url,
        }
        data = self._post("/v2/consents", payload)
        status = _SETU_STATUS_MAP.get(str(data.get("status", "PENDING")).upper(), AAConsentStatus.PENDING)
        return AAConsentResult(
            status=status,
            consent_handle=data.get("id"),
            consent_id=data.get("consentId") or data.get("id"),
            consent_url=data.get("url"),
            raw=data,
        )

    def get_consent_status(self, consent_handle: str) -> AAConsentResult:
        data = self._get(f"/v2/consents/{consent_handle}")
        status = _SETU_STATUS_MAP.get(str(data.get("status", "PENDING")).upper(), AAConsentStatus.PENDING)
        return AAConsentResult(
            status=status,
            consent_handle=consent_handle,
            consent_id=data.get("consentId") or consent_handle,
            consent_url=data.get("url"),
            raw=data,
        )

    def revoke_consent(self, consent_id: str) -> bool:
        self._post(f"/v2/consents/{consent_id}/revoke", {})
        return True

    # --------------------------------------------------------------- data fetch
    def create_data_session(self, consent_id: str, fetch_from_months: int = 12) -> str:
        now = datetime.now(timezone.utc)
        fetch_from = now - timedelta(days=30 * fetch_from_months)
        payload = {
            "consentId": consent_id,
            "DataRange": {
                "from": fetch_from.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "to": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            },
            "format": "json",
        }
        data = self._post("/v2/sessions", payload)
        session_id = data.get("id")
        if not session_id:
            raise AAError(f"Setu session creation returned no id: {data}")
        return session_id

    def fetch_fi_data(self, session_id: str) -> list[AAFiAccount]:
        data = self._get(f"/v2/sessions/{session_id}")
        status = str(data.get("status", "")).upper()
        if status and status not in ("COMPLETED", "PARTIAL"):
            raise AAError(f"Setu session {session_id} not ready (status={status})")
        return self._parse_fi_payload(data)

    # --------------------------------------------------------------- parsing
    def _parse_fi_payload(self, data: dict[str, Any]) -> list[AAFiAccount]:
        """Normalize Setu's decrypted FI payload into AAFiAccount objects."""
        accounts: list[AAFiAccount] = []
        for fi in data.get("fips", data.get("FIPs", [])):
            fip_name = fi.get("fipName") or fi.get("fipID") or "Bank"
            for acc in fi.get("accounts", fi.get("Accounts", [])):
                try:
                    accounts.append(self._parse_account(acc, fip_name))
                except Exception as exc:  # one bad account must not fail the whole sync
                    logger.warning("Skipping unparseable AA account from %s: %s", fip_name, exc)
        return accounts

    def _parse_account(self, acc: dict[str, Any], fip_name: str) -> AAFiAccount:
        fi_type = str(acc.get("FIType") or acc.get("fiType") or "DEPOSIT").upper()
        masked = acc.get("maskedAccNumber") or acc.get("maskedAccountNumber") or acc.get("linkRefNumber") or "XXXX"
        decrypted = acc.get("data") or acc.get("decryptedFI") or acc
        account_block = decrypted.get("Account", decrypted) if isinstance(decrypted, dict) else {}
        summary = account_block.get("Summary", {}) if isinstance(account_block, dict) else {}
        profile = account_block.get("Profile", {}) if isinstance(account_block, dict) else {}
        holders = profile.get("Holders", {}) if isinstance(profile, dict) else {}

        sub_type = (account_block.get("type") or summary.get("type") or holders.get("type"))
        result = AAFiAccount(
            fi_type=fi_type,
            fip_name=fip_name,
            masked_account_number=str(masked),
            account_sub_type=str(sub_type).upper() if sub_type else None,
            currency=str(summary.get("currency") or "INR"),
            current_balance=_to_float(summary.get("currentBalance") or summary.get("balance")),
            linked_ref_number=acc.get("linkRefNumber"),
            raw=acc,
        )
        result.credit_limit = (
            _to_float(summary.get("creditLimit")) if summary.get("creditLimit") is not None else None
        )
        result.principal = (
            _to_float(summary.get("currentOutstandingAmount") or summary.get("principalOutstanding"))
            if (summary.get("currentOutstandingAmount") or summary.get("principalOutstanding")) is not None
            else None
        )
        result.emi_amount = _to_float(summary.get("emiAmount")) if summary.get("emiAmount") is not None else None
        result.interest_rate = (
            _to_float(summary.get("interestRate")) if summary.get("interestRate") is not None else None
        )
        result.maturity_value = (
            _to_float(summary.get("maturityAmount")) if summary.get("maturityAmount") is not None else None
        )

        # Transactions
        txn_container = account_block.get("Transactions", {}) if isinstance(account_block, dict) else {}
        raw_txns = txn_container.get("Transaction", []) if isinstance(txn_container, dict) else []
        if isinstance(raw_txns, dict):
            raw_txns = [raw_txns]
        for t in raw_txns:
            result.transactions.append(
                AAFiTransaction(
                    amount=_to_float(t.get("amount")),
                    txn_type=str(t.get("type") or "DEBIT").upper(),
                    narration=str(t.get("narration") or t.get("reference") or "AA transaction"),
                    value_date=_parse_dt(t.get("valueDate") or t.get("transactionTimestamp")),
                    txn_id=t.get("txnId"),
                    mode=t.get("mode"),
                    reference=t.get("reference"),
                )
            )
        return result
