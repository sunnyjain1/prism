"""Account Aggregator (AA) API — consent handshake + real data fetch.

Flow: initiate → redirect user to ``consent_url`` (mobile OTP + pick accounts on the
AA hosted page) → poll status → fetch (materializes real accounts). The optional
webhook lets the AA notify us the moment data is ready instead of polling.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from core.config import settings
from core.dependencies import get_current_user, get_db
from models import AAConsent
from services.account_aggregator_service import AccountAggregatorService, FIType
from services.aa.base import AAConsentStatus
from user_models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account-aggregator", tags=["account-aggregator"])


class ConsentRequest(BaseModel):
    phone: str
    fi_types: list[FIType]
    pan: Optional[str] = None
    dob: Optional[str] = None  # YYYY-MM-DD, discovery hint only — never stored

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("Phone number must contain at least 10 digits")
        return digits[-10:]

    @field_validator("fi_types")
    @classmethod
    def validate_fi_types(cls, value: list[FIType]) -> list[FIType]:
        if not value:
            raise ValueError("At least one FI type is required")
        return value

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        pan = value.strip().upper()
        if len(pan) != 10 or not (pan[:5].isalpha() and pan[5:9].isdigit() and pan[9].isalpha()):
            raise ValueError("PAN must be in the format ABCDE1234F")
        return pan


@router.get("/fi-types")
def get_fi_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AccountAggregatorService(db).get_supported_fi_types()


@router.post("/consent/initiate")
def initiate_consent(
    body: ConsentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AccountAggregatorService(db)
    result = service.initiate_consent(
        user=current_user,
        phone=body.phone,
        fi_types=[fi_type.value for fi_type in body.fi_types],
        pan=body.pan,
        dob=body.dob,
    )
    # The mock provider has no hosted page — point it at our own approval page so the
    # redirect step shows a real "approve" screen and the flow completes end-to-end.
    if service.client.provider_name == "mock":
        base = str(request.base_url).rstrip("/")
        mock_url = f"{base}/api/v1/account-aggregator/mock/approve/{result['consent_id']}"
        service.set_consent_url(result["consent_id"], current_user.id, mock_url)
        result["consent_url"] = mock_url
    return result


@router.get("/consent/{consent_id}/status")
def check_consent_status(
    consent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AccountAggregatorService(db).get_consent_status(consent_id, current_user.id)


@router.post("/consent/{consent_id}/fetch")
def fetch_accounts(
    consent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Open a data session against an approved consent and import real accounts."""
    return AccountAggregatorService(db).fetch_and_materialize(consent_id, current_user.id)


@router.post("/consent/{consent_id}/revoke")
def revoke_consent(
    consent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AccountAggregatorService(db).revoke_consent(consent_id, current_user.id)


@router.post("/webhook")
async def aa_webhook(request: Request, db: Session = Depends(get_db)):
    """
    AA data-ready / consent-status notification. Optional optimization over polling.
    Verifies an HMAC-SHA256 signature over the raw body using AA_WEBHOOK_SECRET.
    """
    raw = await request.body()
    if settings.AA_WEBHOOK_SECRET:
        signature = request.headers.get("x-setu-signature", "")
        expected = hmac.new(settings.AA_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("AA webhook signature mismatch")
            return {"ok": False, "error": "invalid signature"}

    payload = await request.json()
    consent_ref = payload.get("consentId") or payload.get("consentHandle")
    if not consent_ref:
        return {"ok": True, "note": "no consent reference in payload"}

    consent = (
        db.query(AAConsent)
        .filter((AAConsent.consent_id == consent_ref) | (AAConsent.consent_handle == consent_ref))
        .first()
    )
    if not consent:
        return {"ok": True, "note": "unknown consent reference"}

    # On a data-ready notification for an approved consent, pull immediately.
    if consent.status == AAConsentStatus.APPROVED.value:
        try:
            AccountAggregatorService(db).fetch_and_materialize(consent.id, consent.user_id)
        except Exception as exc:  # webhook must always 200 so the AA stops retrying
            logger.error("AA webhook fetch failed for consent %s: %s", consent.id, exc)
    return {"ok": True}


@router.get("/mock/approve/{consent_id}", response_class=HTMLResponse, include_in_schema=False)
def mock_approve_page(consent_id: str, db: Session = Depends(get_db)):
    """
    Dev-only stand-in for an AA hosted consent page. Marks the mock consent approved
    and tells the user to return to the app. Only meaningful when the mock provider
    is active (no real Setu credentials configured outside production).
    """
    approved = AccountAggregatorService(db).mark_mock_approved(consent_id)
    body = (
        "<h2>✓ Consent approved (demo)</h2>"
        "<p>This is a simulated Account Aggregator approval because no live AA "
        "credentials are configured.</p>"
        "<p><b>Return to the Prism app and tap “I've approved — continue”.</b></p>"
        if approved
        else "<h2>Consent not found</h2><p>Return to the app and try again.</p>"
    )
    html = (
        "<!doctype html><html><head><meta name='viewport' "
        "content='width=device-width, initial-scale=1'><title>Account Aggregator</title>"
        "<style>body{font-family:-apple-system,system-ui,sans-serif;max-width:480px;"
        "margin:40px auto;padding:0 20px;color:#111}h2{color:#10B981}</style></head>"
        f"<body>{body}</body></html>"
    )
    return HTMLResponse(content=html)
