"""
Mock Account Aggregator client for local/dev testing.

Lets the full consent → approve → fetch flow run end-to-end with NO external
provider credentials, returning deterministic (non-random) sample data. This is
the auto-selected provider when no real Setu credentials are configured outside
production (see ``services.aa.factory``), mirroring the existing ``ALLOW_MOCK_AUTH``
dev pattern. Set ``AA_PROVIDER=mock`` to force it.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.aa.base import (
    AAClient,
    AAConsentResult,
    AAConsentStatus,
    AAFiAccount,
    AAFiTransaction,
)


def _txns(seed: list[tuple[float, str, str, int]]) -> list[AAFiTransaction]:
    now = datetime.now(timezone.utc)
    return [
        AAFiTransaction(
            amount=amount,
            txn_type=ttype,
            narration=narration,
            value_date=now - timedelta(days=days_ago),
        )
        for amount, ttype, narration, days_ago in seed
    ]


class MockAAClient(AAClient):
    provider_name = "mock"

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
        handle = f"mock-{secrets.token_hex(6)}"
        # consent_url is filled in by the API layer with an absolute mock approval page.
        return AAConsentResult(
            status=AAConsentStatus.PENDING,
            consent_handle=handle,
            consent_id=handle,
            consent_url=None,
        )

    def get_consent_status(self, consent_handle: str) -> AAConsentResult:
        # The mock simulates the user having approved on the AA page.
        return AAConsentResult(
            status=AAConsentStatus.APPROVED,
            consent_handle=consent_handle,
            consent_id=consent_handle,
        )

    def create_data_session(self, consent_id: str, fetch_from_months: int = 12) -> str:
        return f"mock-session-{consent_id}"

    def revoke_consent(self, consent_id: str) -> bool:
        return True

    def fetch_fi_data(self, session_id: str) -> list[AAFiAccount]:
        """Deterministic sample portfolio — stable across calls (no random values)."""
        return [
            AAFiAccount(
                fi_type="DEPOSIT",
                fip_name="HDFC Bank",
                masked_account_number="XXXXXX4321",
                account_sub_type="SAVINGS",
                current_balance=124300.0,
                transactions=_txns([
                    (52000.0, "CREDIT", "SALARY CREDIT", 28),
                    (1499.0, "DEBIT", "SWIGGY", 5),
                    (2300.0, "DEBIT", "AMAZON", 3),
                ]),
            ),
            AAFiAccount(
                fi_type="DEPOSIT",
                fip_name="ICICI Bank",
                masked_account_number="XXXXXX8899",
                account_sub_type="CURRENT",
                current_balance=58900.0,
                transactions=_txns([
                    (15000.0, "CREDIT", "UPI TRANSFER", 10),
                    (4200.0, "DEBIT", "ELECTRICITY BILL", 7),
                ]),
            ),
            AAFiAccount(
                fi_type="CREDIT_CARD",
                fip_name="Axis Bank",
                masked_account_number="XXXXXX1009",
                current_balance=12400.0,
                principal=12400.0,
                credit_limit=150000.0,
            ),
            AAFiAccount(
                fi_type="TERM_DEPOSIT",
                fip_name="SBI",
                masked_account_number="FD000123",
                current_balance=200000.0,
                maturity_value=215000.0,
            ),
            AAFiAccount(
                fi_type="LOAN",
                fip_name="HDFC Bank",
                masked_account_number="LN556677",
                account_sub_type="HOME_LOAN",
                principal=2500000.0,
                emi_amount=24000.0,
                interest_rate=8.5,
            ),
        ]
