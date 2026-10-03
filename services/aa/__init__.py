"""
Account Aggregator (AA) provider-agnostic integration package.

Public surface:
    from services.aa import get_aa_client
    from services.aa.base import (
        AAClient, AAConsentResult, AAConsentStatus, AAFiAccount, AAFiTransaction,
    )
"""
from services.aa.base import (
    AAClient,
    AAConsentResult,
    AAConsentStatus,
    AAError,
    AAFiAccount,
    AAFiTransaction,
)
from services.aa.factory import get_aa_client

__all__ = [
    "AAClient",
    "AAConsentResult",
    "AAConsentStatus",
    "AAError",
    "AAFiAccount",
    "AAFiTransaction",
    "get_aa_client",
]
