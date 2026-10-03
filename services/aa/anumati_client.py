"""
Anumati (Perfios) Account Aggregator FIU client — scaffold.

Anumati is the AA that powers the IDFC FIRST Bank app and has the widest live
FIP coverage, so it is the natural production swap. The integration shape mirrors
:class:`SetuAAClient`; wire the concrete HTTP calls once Anumati FIU credentials
and the signed contract are in place, then set ``AA_PROVIDER=anumati``.
"""
from __future__ import annotations

from typing import Optional

from services.aa.base import AAClient, AAConsentResult, AAFiAccount

_NOT_CONFIGURED = (
    "Anumati AA integration is not configured. Provide Anumati FIU credentials and "
    "implement the HTTP calls, or set AA_PROVIDER=setu."
)


class AnumatiAAClient(AAClient):
    provider_name = "anumati"

    def create_consent(self, **kwargs) -> AAConsentResult:  # noqa: D401
        raise NotImplementedError(_NOT_CONFIGURED)

    def get_consent_status(self, consent_handle: str) -> AAConsentResult:
        raise NotImplementedError(_NOT_CONFIGURED)

    def create_data_session(self, consent_id: str, fetch_from_months: int = 12) -> str:
        raise NotImplementedError(_NOT_CONFIGURED)

    def fetch_fi_data(self, session_id: str) -> list[AAFiAccount]:
        raise NotImplementedError(_NOT_CONFIGURED)

    def revoke_consent(self, consent_id: str) -> bool:
        raise NotImplementedError(_NOT_CONFIGURED)
