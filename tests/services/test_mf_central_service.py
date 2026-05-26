from services.mf_central_service import MfCentralService


def setup_function() -> None:
    MfCentralService._otp_store.clear()


def test_validate_pan_format() -> None:
    service = MfCentralService()

    assert service.validate_pan("ABCDE1234F") is True
    assert service.validate_pan("abcde1234f") is True
    assert service.validate_pan("INVALID123") is False


def test_initiate_otp_rejects_invalid_pan() -> None:
    service = MfCentralService()

    response = service.initiate_otp("user-1", "BADPAN")

    assert response["success"] is False
    assert "Invalid PAN format" in response["error"]


def test_verify_otp_returns_pending_integration_result() -> None:
    service = MfCentralService()

    initiate_response = service.initiate_otp("user-1", "ABCDE1234F")
    assert initiate_response["success"] is True

    otp = service._otp_store["user-1:ABCDE1234F"]["otp"]
    verify_response = service.verify_otp("user-1", "ABCDE1234F", otp)

    assert verify_response["success"] is True
    assert verify_response["status"] == "pending_integration"
    assert verify_response["holdings"] == []
