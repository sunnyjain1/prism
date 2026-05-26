from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, get_db
from services.mf_central_service import MfCentralService
from user_models import User

router = APIRouter(prefix="/mf-central", tags=["mf-central"])

_service = MfCentralService()


class PanOtpRequest(BaseModel):
    pan: str

    @field_validator("pan")
    @classmethod
    def validate_pan_format(cls, value: str) -> str:
        value = value.upper().strip()
        if len(value) != 10:
            raise ValueError("PAN must be exactly 10 characters")
        return value


class OtpVerifyRequest(BaseModel):
    pan: str
    otp: str

    @field_validator("pan")
    @classmethod
    def validate_pan_format(cls, value: str) -> str:
        value = value.upper().strip()
        if len(value) != 10:
            raise ValueError("PAN must be exactly 10 characters")
        return value


@router.post("/initiate-otp")
def initiate_otp(
    body: PanOtpRequest,
    current_user: User = Depends(get_current_user),
):
    return _service.initiate_otp(current_user.id, body.pan)


@router.post("/verify-otp")
def verify_otp(
    body: OtpVerifyRequest,
    current_user: User = Depends(get_current_user),
):
    return _service.verify_otp(current_user.id, body.pan, body.otp)


@router.get("/portfolio")
def get_mf_portfolio(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service.fetch_portfolio(current_user.id, "", db)
