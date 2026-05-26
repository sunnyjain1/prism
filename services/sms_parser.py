"""
SMS Transaction Parser Engine for Indian banks, UPI, wallets.

Supports:
- SBI, HDFC, ICICI, Axis, Kotak, IDFC First, PNB, BOB, Yes Bank
- UPI apps: Google Pay, PhonePe, Paytm, BHIM
- Credit cards: All major issuers
- Wallets: Paytm, Amazon Pay, Freecharge
- ATM withdrawals, salary credits, refunds
"""
import re
import hashlib
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class ParsedSMS:
    amount: Optional[float] = None
    transaction_type: Optional[str] = None  # debit, credit, transfer, upi, atm, refund, failed
    merchant: Optional[str] = None
    bank_name: Optional[str] = None
    masked_account: Optional[str] = None
    reference_number: Optional[str] = None
    available_balance: Optional[float] = None
    upi_id: Optional[str] = None
    card_type: Optional[str] = None  # credit_card, debit_card
    timestamp: Optional[datetime] = None
    confidence: float = 0.0
    is_transactional: bool = False


# Bank sender patterns
BANK_SENDERS = {
    r"(?i)(SBI|SBIINB|SBIPSG|ATMSBI)": "SBI",
    r"(?i)(HDFC|HDFCBK|HDFCBANK)": "HDFC",
    r"(?i)(ICICI|ICICIB)": "ICICI",
    r"(?i)(AXIS|AXISBK|AxisBk)": "Axis",
    r"(?i)(KOTAK|KotakB)": "Kotak",
    r"(?i)(IDFC|IDFCFB)": "IDFC First",
    r"(?i)(PAYTM|Paytm)": "Paytm",
    r"(?i)(GPAY|GOOGLPAY)": "Google Pay",
    r"(?i)(PHONPE|PhonePe)": "PhonePe",
    r"(?i)(PNBSMS|PNB)": "PNB",
    r"(?i)(BOBTXN|BOB)": "BOB",
    r"(?i)(YESBK|YesBank)": "Yes Bank",
    r"(?i)(INDUSIND|IDFCB)": "IndusInd",
    r"(?i)(CANBNK|CANARA)": "Canara",
    r"(?i)(UNIONB)": "Union",
    r"(?i)(FEDERAL|FEDBK)": "Federal",
    r"(?i)(CITI|CitiBank)": "Citi",
    r"(?i)(AMEX|AMEXIN)": "Amex",
    r"(?i)(RBL|RBLBANK)": "RBL",
}

# Amount extraction patterns (Indian formats: Rs, INR, Rs.)
AMOUNT_PATTERNS = [
    r"(?:Rs\.?|INR|₹)\s*([0-9,]+\.?\d*)",
    r"(?:debited|credited|paid|received|sent|transferred|withdrawn|charged)\s*(?:for\s*)?(?:Rs\.?|INR|₹)\s*([0-9,]+\.?\d*)",
    r"([0-9,]+\.?\d*)\s*(?:has been|is)\s*(?:debited|credited)",
    r"(?:amount|amt)\s*(?:of\s*)?(?:Rs\.?|INR|₹)\s*([0-9,]+\.?\d*)",
    r"(?:Rs\.?|INR|₹)\s*([0-9,]+\.?\d*)\s*(?:has been|was|is)\s*(?:debited|credited|transferred|spent|received)",
]

# Balance extraction
BALANCE_PATTERNS = [
    r"(?:Avl\.?\s*Bal|Available\s*[Bb]al(?:ance)?|Avl\s*Bal|A/c\s*bal|Bal|Balance)\s*(?:is\s*)?:?\s*(?:Rs\.?|INR|₹)\s*([0-9,]+\.?\d*)",
    r"(?:Rs\.?|INR|₹)\s*([0-9,]+\.?\d*)\s*(?:Avl|Available)",
]

# Account number patterns
ACCOUNT_PATTERNS = [
    r"(?:A/c|Ac|Acct|Account|a/c)\s*(?:no\.?\s*)?(?:ending\s*)?[Xx*]*(\d{4})",
    r"[Xx*]+(\d{4})",
    r"(?:card|Card)\s*(?:ending|no\.?)\s*(\d{4})",
]

# Reference/UPI patterns
REFERENCE_PATTERNS = [
    r"(?:Ref\.?\s*(?:No\.?|#)?|UPI\s*Ref|Txn\s*(?:ID|No)|Reference)\s*:?\s*(\w+)",
    r"UPI/(\d+)",
]

UPI_ID_PATTERN = r"([a-zA-Z0-9._-]+@[a-zA-Z]+)"

# Merchant extraction patterns
MERCHANT_PATTERNS = [
    r"(?:to|at|for|from|towards)\s+([A-Za-z0-9][\w\s&.'-]{2,30}?)(?:\s+(?:on|via|ref|upi|Ref))",
    r"(?:to|at|for|from)\s+([A-Za-z][\w\s&.'-]{2,25}?)(?:\.|,|\s+on|\s+dated|\s+Ref|\s+ref)",
    r"Info:\s*(.+?)(?:\s+Ref|\s+UPI|$)",
    r"VPA\s+([a-zA-Z0-9._-]+@[a-zA-Z]+)",
]

# Transaction type detection
DEBIT_KEYWORDS = [
    "debited", "debit", "spent", "paid", "payment", "purchase",
    "withdrawn", "withdrawal", "sent", "transferred to", "charged",
]
CREDIT_KEYWORDS = [
    "credited", "credit", "received", "deposited", "refund",
    "cashback", "reversed", "salary", "transferred from",
]
UPI_KEYWORDS = ["upi", "UPI", "google pay", "phonepe", "paytm", "bhim"]
ATM_KEYWORDS = ["atm", "ATM", "cash withdrawal", "cash withdrawn"]
REFUND_KEYWORDS = ["refund", "reversed", "cashback", "reversal"]
FAILED_KEYWORDS = ["failed", "declined", "rejected", "unsuccessful", "not processed"]

# Non-transactional SMS patterns to skip
SKIP_PATTERNS = [
    r"(?i)OTP|one.time.password|verification.code",
    r"(?i)PIN|MPIN|password",
    r"(?i)Dear Customer.*welcome",
    r"(?i)KYC|update.*details",
    r"(?i)apply.*loan|pre.?approved",
    r"(?i)EMI.*bounce|NACH.*reject",
    r"(?i)insurance.*premium|renew",
]


def detect_bank(sender: str, body: str) -> Optional[str]:
    """Detect bank name from sender or body."""
    for pattern, bank in BANK_SENDERS.items():
        if re.search(pattern, sender or ""):
            return bank
        if re.search(pattern, body[:50]):
            return bank
    return None


def extract_amount(body: str) -> Optional[float]:
    """Extract transaction amount."""
    for pattern in AMOUNT_PATTERNS:
        match = re.search(pattern, body)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                amount = float(amount_str)
                if 0.01 <= amount <= 99_99_99_999:  # Reasonable range
                    return amount
            except ValueError:
                continue
    return None


def extract_balance(body: str) -> Optional[float]:
    """Extract available balance."""
    for pattern in BALANCE_PATTERNS:
        match = re.search(pattern, body)
        if match:
            bal_str = match.group(1).replace(",", "")
            try:
                return float(bal_str)
            except ValueError:
                continue
    return None


def extract_account(body: str) -> Optional[str]:
    """Extract masked account number (last 4 digits)."""
    for pattern in ACCOUNT_PATTERNS:
        match = re.search(pattern, body)
        if match:
            return match.group(1)
    return None


def extract_reference(body: str) -> Optional[str]:
    """Extract reference/transaction ID."""
    for pattern in REFERENCE_PATTERNS:
        match = re.search(pattern, body)
        if match:
            return match.group(1)
    return None


def extract_upi_id(body: str) -> Optional[str]:
    """Extract UPI VPA."""
    match = re.search(UPI_ID_PATTERN, body)
    if match:
        vpa = match.group(1)
        # Validate it looks like a real VPA
        if "@" in vpa and len(vpa) > 5:
            return vpa
    return None


def extract_merchant(body: str) -> Optional[str]:
    """Extract merchant/payee name."""
    for pattern in MERCHANT_PATTERNS:
        match = re.search(pattern, body)
        if match:
            merchant = match.group(1).strip()
            # Clean up
            merchant = re.sub(r"\s+", " ", merchant)
            merchant = merchant.rstrip(".")
            if len(merchant) >= 2 and not merchant.isdigit():
                return merchant
    return None


def detect_transaction_type(body: str) -> Optional[str]:
    """Detect transaction type from SMS body."""
    body_lower = body.lower()

    if any(kw in body_lower for kw in FAILED_KEYWORDS):
        return "failed"
    if any(kw in body_lower for kw in REFUND_KEYWORDS):
        return "refund"
    if any(kw in body_lower for kw in ATM_KEYWORDS):
        return "atm"
    if any(kw in body_lower for kw in UPI_KEYWORDS):
        # UPI can be debit or credit
        if any(kw in body_lower for kw in ["received", "credited"]):
            return "credit"
        return "upi"  # default UPI is debit
    if any(kw in body_lower for kw in DEBIT_KEYWORDS):
        return "debit"
    if any(kw in body_lower for kw in CREDIT_KEYWORDS):
        return "credit"
    return None


def detect_card_type(body: str) -> Optional[str]:
    """Detect if transaction is on credit/debit card."""
    body_lower = body.lower()
    if "credit card" in body_lower or "cc " in body_lower:
        return "credit_card"
    if "debit card" in body_lower or "dc " in body_lower:
        return "debit_card"
    return None


def is_transactional_sms(sender: str, body: str) -> bool:
    """Check if SMS is a financial transaction message."""
    # Skip non-transactional
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, body):
            return False

    # Must have amount
    if not extract_amount(body):
        return False

    # Must have debit/credit indicator
    if not detect_transaction_type(body):
        return False

    return True


def compute_confidence(parsed: ParsedSMS) -> float:
    """Compute confidence score based on parsed data completeness."""
    score = 0.0

    if parsed.amount is not None:
        score += 0.30
    if parsed.transaction_type is not None:
        score += 0.20
    if parsed.bank_name is not None:
        score += 0.15
    if parsed.masked_account is not None:
        score += 0.10
    if parsed.merchant is not None:
        score += 0.10
    if parsed.reference_number is not None:
        score += 0.05
    if parsed.available_balance is not None:
        score += 0.05
    if parsed.upi_id is not None:
        score += 0.05

    return min(score, 1.0)


def compute_dedup_hash(user_id: str, amount: float, timestamp: Optional[datetime], reference: Optional[str]) -> str:
    """Compute deduplication hash for a parsed SMS."""
    parts = [user_id, str(amount)]
    if reference:
        parts.append(reference)
    if timestamp:
        # Round to minute for dedup tolerance
        parts.append(timestamp.strftime("%Y%m%d%H%M"))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def parse_sms(sender: str, body: str, sms_timestamp: Optional[datetime] = None) -> ParsedSMS:
    """
    Main entry point: parse a single SMS message.
    Returns ParsedSMS with extracted fields and confidence score.
    """
    result = ParsedSMS()

    # Check if transactional
    if not is_transactional_sms(sender, body):
        return result

    result.is_transactional = True
    result.bank_name = detect_bank(sender, body)
    result.amount = extract_amount(body)
    result.transaction_type = detect_transaction_type(body)
    result.masked_account = extract_account(body)
    result.available_balance = extract_balance(body)
    result.reference_number = extract_reference(body)
    result.upi_id = extract_upi_id(body)
    result.merchant = extract_merchant(body)
    result.card_type = detect_card_type(body)
    result.timestamp = sms_timestamp

    result.confidence = compute_confidence(result)

    return result


def parse_sms_batch(messages: List[dict]) -> List[ParsedSMS]:
    """
    Parse a batch of SMS messages.
    Each message dict should have: sender, body, timestamp (optional)
    """
    results = []
    for msg in messages:
        parsed = parse_sms(
            sender=msg.get("sender", ""),
            body=msg.get("body", ""),
            sms_timestamp=msg.get("timestamp"),
        )
        if parsed.is_transactional:
            results.append(parsed)
    return results


def normalize_merchant(merchant: Optional[str]) -> Optional[str]:
    """Normalize merchant name for consistent matching."""
    if not merchant:
        return None

    # Remove common suffixes
    merchant = re.sub(r"\s*(pvt|ltd|private|limited|inc|llp|corp)\s*\.?", "", merchant, flags=re.IGNORECASE)
    # Remove transaction IDs embedded in merchant
    merchant = re.sub(r"\s*\d{10,}", "", merchant)
    # Collapse whitespace
    merchant = re.sub(r"\s+", " ", merchant).strip()
    # Title case
    merchant = merchant.title()

    return merchant if len(merchant) >= 2 else None
