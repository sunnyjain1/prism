"""Factory that returns the configured AA provider client."""
from __future__ import annotations

import logging
from functools import lru_cache

from core.config import settings
from services.aa.base import AAClient, AAError

logger = logging.getLogger(__name__)


def resolve_provider() -> str:
    """
    Resolve the effective AA provider.

    Falls back to the built-in ``mock`` provider when the selected real provider
    has no credentials configured AND we're not in production — so the consent
    flow is fully testable out of the box without external sign-up. Set
    ``AA_PROVIDER=mock`` to force it, or configure credentials to use the real one.
    """
    provider = settings.AA_PROVIDER
    if provider == "setu" and not settings.SETU_AA_CLIENT_ID:
        if settings.ENVIRONMENT != "production":
            logger.warning(
                "Setu AA credentials are not configured — falling back to the mock AA "
                "provider for testing. Set SETU_AA_CLIENT_ID/SECRET or AA_PROVIDER=mock."
            )
            return "mock"
    return provider


@lru_cache(maxsize=4)
def _build(provider: str) -> AAClient:
    if provider == "setu":
        from services.aa.setu_client import SetuAAClient

        return SetuAAClient()
    if provider == "anumati":
        from services.aa.anumati_client import AnumatiAAClient

        return AnumatiAAClient()
    if provider == "mock":
        from services.aa.mock_client import MockAAClient

        return MockAAClient()
    raise AAError(f"Unknown AA_PROVIDER '{provider}'. Supported: setu, anumati, mock.")


def get_aa_client() -> AAClient:
    """Return the AA client selected by ``settings.AA_PROVIDER`` (with mock fallback)."""
    return _build(resolve_provider())
