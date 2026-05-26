"""
MF Central Integration Service (stub for future API integration).

MF Central (mfcentral.com) is a joint CAMS+KFintech platform that provides
consolidated mutual fund portfolio data using PAN + OTP verification.

Integration flow:
1. User submits PAN number
2. OTP sent to registered mobile/email
3. User verifies OTP
4. CAS (Consolidated Account Statement) is fetched
5. Holdings are parsed and imported as investments

Currently: placeholder implementation that validates PAN format and simulates OTP.
Future: Replace with actual CAMS/KFintech API calls once partnership is established.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session


class MfCentralService:
    """Handles MF Central PAN+OTP flow and portfolio fetch."""

    PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    OTP_EXPIRY_MINUTES = 10

    # In-memory OTP store (replace with Redis in production)
    _otp_store: dict[str, dict[str, Any]] = {}

    def validate_pan(self, pan: str) -> bool:
        """Validate PAN format (ABCDE1234F pattern)."""
        return bool(self.PAN_REGEX.fullmatch(pan.upper().strip()))

    def _build_key(self, user_id: str, pan: str) -> str:
        return f"{user_id}:{pan}"

    def initiate_otp(self, user_id: str, pan: str) -> dict[str, Any]:
        """Initiate OTP verification for MF Central access."""
        pan = pan.upper().strip()
        if not self.validate_pan(pan):
            return {"success": False, "error": "Invalid PAN format. Expected: ABCDE1234F"}

        otp = f"{secrets.randbelow(900000) + 100000}"
        self._otp_store[self._build_key(str(user_id), pan)] = {
            "otp": otp,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=self.OTP_EXPIRY_MINUTES),
            "pan": pan,
            "attempts": 0,
        }

        return {
            "success": True,
            "message": "OTP sent to registered mobile number",
            "pan_masked": f"{pan[:2]}***{pan[-1]}",
            "expires_in_seconds": self.OTP_EXPIRY_MINUTES * 60,
        }

    def verify_otp(self, user_id: str, pan: str, otp: str) -> dict[str, Any]:
        """Verify OTP and fetch portfolio (stub)."""
        pan = pan.upper().strip()
        key = self._build_key(str(user_id), pan)
        record = self._otp_store.get(key)

        if not record:
            return {"success": False, "error": "No OTP request found. Please initiate again."}

        if datetime.now(timezone.utc) > record["expires_at"]:
            del self._otp_store[key]
            return {"success": False, "error": "OTP expired. Please request a new one."}

        if record["attempts"] >= 3:
            del self._otp_store[key]
            return {"success": False, "error": "Too many attempts. Please try again."}

        record["attempts"] += 1
        if record["otp"] != otp.strip():
            remaining_attempts = 3 - record["attempts"]
            if remaining_attempts <= 0:
                del self._otp_store[key]
                return {"success": False, "error": "Too many attempts. Please try again."}
            return {"success": False, "error": f"Incorrect OTP. {remaining_attempts} attempts remaining."}

        del self._otp_store[key]
        return {
            "success": True,
            "message": "PAN verified successfully. Portfolio fetch is not yet available — please add holdings manually.",
            "holdings": [],
            "pan": pan,
            "status": "pending_integration",
        }

    def fetch_portfolio(self, user_id: str, pan: str, db: Session) -> dict[str, Any]:
        """Fetch mutual fund portfolio from MF Central (stub)."""
        _ = (user_id, pan, db)
        return {
            "status": "not_available",
            "message": "MF Central API integration pending. Add mutual fund holdings manually.",
            "holdings": [],
        }
