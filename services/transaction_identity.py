"""
Transaction identity — decides whether an incoming auto-captured transaction (email
statement, SMS, bulk upload, AA) is one the user already has.

The same real-world payment can reach Prism up to four times: the user types it in,
the bank SMS arrives, the monthly statement is pulled from Gmail, and the AA feed
reports it. Descriptions never agree across those ("Salary from Mll" vs
"NEFT - MLL EXPRESS SERVICES"), so matching on text — what the old
DeduplicationService did — lets every one of them through.

Matching instead uses what the bank keeps stable:

1. **Bank reference** (UPI RRN / IMPS / NEFT UTR). Identical reference ⇒ same
   transaction. *Different* references ⇒ definitely different transactions, even
   when amount and date coincide.
2. **Fallback**: same direction, same amount (to the paisa), same or unknown
   account, booked within ``date_window_days``. Nearest date wins.

Every existing row can absorb at most one incoming row (1:1). Two genuine ₹20 snacks
on the same day stay two transactions; a statement that lists them twice against one
manual entry imports exactly one.

When an incoming row matches an existing one that has no reference yet, the caller
should copy the reference onto it (``MatchResult.reference_to_attach``) so later
sources match exactly instead of by heuristic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from models import Transaction

AMOUNT_TOLERANCE = 0.005

# Ordered most-specific first. Each pattern's group 1 is the reference; digits may be
# split by a stray space when the reference wraps inside a PDF table cell.
_REFERENCE_PATTERNS = [
    # UPI-334418094573-..., UPI/412853401207/..., UPI 4083 59191720
    re.compile(r"\bUPI[-/ ]?(\d[\d ]{10,14}\d)\b", re.IGNORECASE),
    # IMPS-412345678901-...
    re.compile(r"\bIMPS[-/ ]?(?:P2A[-/ ]?|P2P[-/ ]?)?(\d[\d ]{10,14}\d)\b", re.IGNORECASE),
    # NEFT/RTGS UTRs: 4-letter bank code + 12-18 alphanumerics (HDFCN52024010112345)
    re.compile(r"\b(?:NEFT|RTGS)[-/ ]?(?:CR|DR)?[-/ ]?([A-Z]{4}[A-Z0-9]{11,18})\b", re.IGNORECASE),
    # Keyed references in SMS / alert e-mails: "UPI Ref No 412345678901", "UTR: ..."
    re.compile(
        r"\b(?:UPI\s*Ref(?:erence)?|Ref(?:erence)?|UTR|RRN|Txn\s*(?:ID|No))"
        r"\.?\s*(?:No\.?|Number|#)?\s*[:.\-]?\s*([A-Z0-9]{10,22})\b",
        re.IGNORECASE,
    ),
]


def extract_bank_reference(text: Optional[str]) -> Optional[str]:
    """
    Pull the bank's transaction reference out of a narration, SMS or alert e-mail.

    Returns an upper-cased reference with internal spaces removed, or None. A UPI/IMPS
    reference must come out as exactly 12 digits (the RRN length), which keeps phone
    numbers and masked account numbers from being mistaken for references.
    """
    if not text:
        return None
    for index, pattern in enumerate(_REFERENCE_PATTERNS):
        for match in pattern.finditer(text):
            reference = re.sub(r"\s+", "", match.group(1)).upper()
            if index < 2:  # UPI / IMPS: RRN is exactly 12 digits
                if len(reference) == 12 and reference.isdigit():
                    return reference
                continue
            if any(ch.isdigit() for ch in reference):
                return reference
    return None


@dataclass
class IncomingTransaction:
    """The fields matching needs, independent of where the row came from."""

    amount: float
    type: str
    date: datetime
    account_id: Optional[str] = None
    reference: Optional[str] = None


@dataclass
class MatchResult:
    incoming: IncomingTransaction
    existing: Optional[Transaction] = None
    reason: Optional[str] = None  # "reference" | "amount_date"

    @property
    def is_duplicate(self) -> bool:
        return self.existing is not None

    @property
    def reference_to_attach(self) -> Optional[str]:
        """Reference worth copying onto the matched row (it has none yet)."""
        if self.existing is not None and self.incoming.reference and not self.existing.external_ref:
            return self.incoming.reference
        return None


def type_value(value) -> str:
    """Enum or plain string -> plain string (TransactionType vs stored str)."""
    return getattr(value, "value", value)


class TransactionMatcher:
    """Matches a batch of incoming transactions against one user's existing ones."""

    def __init__(self, db: Session, owner_id: str, date_window_days: int = 2):
        self.db = db
        self.owner_id = owner_id
        self.window = timedelta(days=date_window_days)

    def match(self, incoming: Sequence[IncomingTransaction]) -> List[MatchResult]:
        if not incoming:
            return []

        pool = self._load_pool(incoming)
        by_reference = {}
        for tx in pool:
            if tx.external_ref:
                by_reference.setdefault(tx.external_ref, tx)
        consumed: set[str] = set()

        # Reference matches first so a heuristic match can't steal their row.
        order = sorted(range(len(incoming)), key=lambda i: incoming[i].reference is None)
        resolved: dict[int, MatchResult] = {}
        for i in order:
            item = incoming[i]
            existing, reason = None, None
            if item.reference and item.reference in by_reference:
                candidate = by_reference[item.reference]
                if candidate.id not in consumed:
                    existing, reason = candidate, "reference"
            if existing is None:
                existing = self._best_fallback(item, pool, consumed)
                reason = "amount_date" if existing is not None else None
            if existing is not None:
                consumed.add(existing.id)
            resolved[i] = MatchResult(incoming=item, existing=existing, reason=reason)

        return [resolved[i] for i in range(len(incoming))]

    def _load_pool(self, incoming: Iterable[IncomingTransaction]) -> List[Transaction]:
        dates = [item.date for item in incoming if item.date]
        references = {item.reference for item in incoming if item.reference}
        if not dates:
            return []
        query = self.db.query(Transaction).filter(Transaction.owner_id == self.owner_id)
        window = query.filter(
            Transaction.date >= min(dates) - self.window,
            Transaction.date <= max(dates) + self.window,
        ).all()
        if references:
            # A reference can match outside the window (e.g. a late statement).
            seen = {tx.id for tx in window}
            window += [
                tx for tx in query.filter(Transaction.external_ref.in_(references)).all()
                if tx.id not in seen
            ]
        return window

    def _best_fallback(
        self, item: IncomingTransaction, pool: List[Transaction], consumed: set[str]
    ) -> Optional[Transaction]:
        best, best_gap = None, None
        for tx in pool:
            if tx.id in consumed:
                continue
            if type_value(tx.type) != type_value(item.type):
                continue
            if abs(tx.amount - item.amount) > AMOUNT_TOLERANCE:
                continue
            if item.account_id and tx.account_id and tx.account_id != item.account_id:
                continue
            if item.reference and tx.external_ref and tx.external_ref != item.reference:
                continue  # different bank references are different transactions
            gap = abs(tx.date - item.date)
            if gap > self.window:
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = tx, gap
        return best
