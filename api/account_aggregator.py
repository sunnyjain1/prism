from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from core.dependencies import get_current_user
from services.account_aggregator_service import AAProvider, FIType, AccountAggregatorService
from user_models import User

router = APIRouter(prefix="/account-aggregator", tags=["account-aggregator"])

_service = AccountAggregatorService()


class ConsentRequest(BaseModel):
    phone: str
    fi_types: list[FIType]
    provider: AAProvider = AAProvider.SETU

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("Phone number must contain at least 10 digits")
        return digits

    @field_validator("fi_types")
    @classmethod
    def validate_fi_types(cls, value: list[FIType]) -> list[FIType]:
        if not value:
            raise ValueError("At least one FI type is required")
        return value


class ConsentApproveRequest(BaseModel):
    consent_id: str


class DataFetchRequest(BaseModel):
    consent_id: str
    fi_type: FIType


@router.get("/fi-types")
def get_fi_types(current_user: User = Depends(get_current_user)):
    return _service.get_supported_fi_types()


@router.post("/consent/initiate")
def initiate_consent(
    body: ConsentRequest,
    current_user: User = Depends(get_current_user),
):
    return _service.initiate_consent(
        current_user.id,
        body.phone,
        [fi_type.value for fi_type in body.fi_types],
        body.provider.value,
    )


@router.get("/consent/{consent_id}/status")
def check_consent_status(
    consent_id: str,
    current_user: User = Depends(get_current_user),
):
    return _service.check_consent_status(consent_id)


@router.post("/consent/{consent_id}/simulate-approve")
def simulate_approve(
    consent_id: str,
    current_user: User = Depends(get_current_user),
):
    """Dev/testing only — simulate consent approval."""
    return _service.simulate_consent_approval(consent_id)


@router.post("/fetch")
def fetch_data(
    body: DataFetchRequest,
    current_user: User = Depends(get_current_user),
):
    return _service.fetch_financial_data(current_user.id, body.consent_id, body.fi_type.value)


@router.post("/credit-score")
def fetch_credit_score(
    body: ConsentApproveRequest,
    current_user: User = Depends(get_current_user),
):
    return _service.fetch_credit_score(current_user.id, body.consent_id)


@router.post("/demat")
def fetch_demat(
    body: ConsentApproveRequest,
    current_user: User = Depends(get_current_user),
):
    return _service.fetch_demat_holdings(current_user.id, body.consent_id)


@router.post("/consent/{consent_id}/revoke")
def revoke_consent(
    consent_id: str,
    current_user: User = Depends(get_current_user),
):
    return _service.revoke_consent(consent_id)
