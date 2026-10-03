"""
Map normalized AA FI data into real Prism domain rows.

Honors the project's balance semantics and dedup rules (root CLAUDE.md):
- Asset accounts (savings/current): positive balance = money in.
- Liability accounts (credit card / loan): positive balance = amount owed.
- The AA-provided ``current_balance`` is authoritative each sync, so transactions
  are inserted for history WITHOUT re-adjusting the balance (no double counting).
- Re-running a sync is idempotent: accounts/assets/loans are matched and updated,
  transactions are de-duplicated, never inserted twice.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import Account, AggregatedAsset, Loan, Transaction
from repositories.account_repository import AccountRepository
from services.aa.base import AAFiAccount
from services.smart_categorization_service import SmartCategorizationService

logger = logging.getLogger(__name__)

# AA DEPOSIT sub-type -> Prism account type.
_DEPOSIT_TYPE_MAP = {"CURRENT": "current", "SAVINGS": "savings"}
# AA LOAN sub-type -> Prism loan_type.
_LOAN_TYPE_MAP = {
    "HOME_LOAN": "home",
    "VEHICLE_LOAN": "car",
    "AUTO_LOAN": "car",
    "EDUCATION_LOAN": "education",
    "PERSONAL_LOAN": "personal",
}


def _last4(masked: str) -> str:
    digits = "".join(ch for ch in masked if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else (masked[-4:] if masked else "0000")


class AAMapper:
    """Materializes AA FI accounts into Prism entities for one user."""

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id
        self.accounts = AccountRepository(db)
        # Shared across the whole sync so the user's import profile is read once.
        self.categorizer = SmartCategorizationService()

    def materialize(self, fi_accounts: list[AAFiAccount]) -> dict[str, Any]:
        summary = {
            "accounts_created": 0,
            "accounts_updated": 0,
            "transactions_imported": 0,
            "assets_created": 0,
            "loans_created": 0,
            "skipped": 0,
        }
        for acc in fi_accounts:
            try:
                self._materialize_one(acc, summary)
            except Exception as exc:  # one bad account must not abort the whole sync
                logger.exception("Failed to materialize AA account from %s: %s", acc.fip_name, exc)
                summary["skipped"] += 1
        self.db.commit()
        return summary

    # ------------------------------------------------------------------ dispatch
    def _materialize_one(self, acc: AAFiAccount, summary: dict[str, Any]) -> None:
        fi_type = (acc.fi_type or "DEPOSIT").upper()
        if fi_type == "DEPOSIT":
            self._materialize_deposit(acc, summary)
        elif fi_type == "TERM_DEPOSIT":
            self._materialize_term_deposit(acc, summary)
        elif fi_type == "CREDIT_CARD":
            self._materialize_credit_card(acc, summary)
        elif fi_type == "LOAN":
            self._materialize_loan(acc, summary)
        else:
            logger.info("Ignoring unsupported FI type %s from %s", fi_type, acc.fip_name)
            summary["skipped"] += 1

    # ------------------------------------------------------------------ deposits
    def _materialize_deposit(self, acc: AAFiAccount, summary: dict[str, Any]) -> None:
        acc_type = _DEPOSIT_TYPE_MAP.get((acc.account_sub_type or "").upper(), "savings")
        name = f"{acc.fip_name} {acc_type.title()} ••{_last4(acc.masked_account_number)}"
        account = self._upsert_account(name, acc_type, acc.current_balance, summary)
        summary["transactions_imported"] += self._import_transactions(account, acc)

    # ------------------------------------------------------------------ credit cards
    def _materialize_credit_card(self, acc: AAFiAccount, summary: dict[str, Any]) -> None:
        name = f"{acc.fip_name} Credit Card ••{_last4(acc.masked_account_number)}"
        # Liability: positive balance = amount owed (the AA current outstanding).
        owed = acc.principal if acc.principal is not None else acc.current_balance
        account = self._upsert_account(name, "credit", owed, summary, credit_limit=acc.credit_limit)
        summary["transactions_imported"] += self._import_transactions(account, acc)

    # ------------------------------------------------------------------ term deposits
    def _materialize_term_deposit(self, acc: AAFiAccount, summary: dict[str, Any]) -> None:
        identifier = acc.masked_account_number
        name = f"{acc.fip_name} Fixed Deposit ••{_last4(identifier)}"
        value = acc.maturity_value or acc.current_balance
        existing = (
            self.db.query(AggregatedAsset)
            .filter(
                AggregatedAsset.user_id == self.user_id,
                AggregatedAsset.asset_type == "fd",
                AggregatedAsset.identifier == identifier,
            )
            .first()
        )
        if existing:
            existing.current_value = value
            existing.invested_value = acc.current_balance
            existing.last_updated = datetime.now(timezone.utc)
            return
        self.db.add(
            AggregatedAsset(
                user_id=self.user_id,
                asset_type="fd",
                source_type="auto",
                name=name,
                identifier=identifier,
                institution=acc.fip_name,
                current_value=value,
                invested_value=acc.current_balance,
                last_updated=datetime.now(timezone.utc),
            )
        )
        summary["assets_created"] += 1

    # ------------------------------------------------------------------ loans
    def _materialize_loan(self, acc: AAFiAccount, summary: dict[str, Any]) -> None:
        loan_type = _LOAN_TYPE_MAP.get((acc.account_sub_type or "").upper(), "personal")
        name = f"{acc.fip_name} {loan_type.title()} Loan ••{_last4(acc.masked_account_number)}"
        outstanding = acc.principal if acc.principal is not None else acc.current_balance
        existing = (
            self.db.query(Loan)
            .filter(Loan.user_id == self.user_id, Loan.name == name)
            .first()
        )
        if existing:
            existing.outstanding_amount = outstanding
            if acc.emi_amount is not None:
                existing.emi_amount = acc.emi_amount
            return
        self.db.add(
            Loan(
                user_id=self.user_id,
                name=name,
                loan_type=loan_type,
                principal_amount=outstanding,
                outstanding_amount=outstanding,
                interest_rate=acc.interest_rate or 0.0,
                emi_amount=acc.emi_amount,
                lender=acc.fip_name,
            )
        )
        summary["loans_created"] += 1

    # ------------------------------------------------------------------ helpers
    def _upsert_account(
        self,
        name: str,
        acc_type: str,
        balance: float,
        summary: dict[str, Any],
        credit_limit: float | None = None,
    ) -> Account:
        existing = self.accounts.get_by_name_and_owner(name, self.user_id)
        if existing and not existing.is_deleted:
            existing.balance = balance
            if credit_limit is not None:
                existing.credit_limit = credit_limit
            summary["accounts_updated"] += 1
            self.db.flush()
            return existing
        account = Account(
            id=str(uuid.uuid4()),
            name=name,
            type=acc_type,
            currency="INR",
            balance=balance,
            credit_limit=credit_limit,
            owner_id=self.user_id,
            is_deleted=False,
        )
        self.db.add(account)
        self.db.flush()
        summary["accounts_created"] += 1
        return account

    def _import_transactions(self, account: Account, acc: AAFiAccount) -> int:
        """Insert transactions for history (no balance adjustment), de-duplicated."""
        imported = 0
        for t in acc.transactions:
            tx_type = "income" if t.txn_type.upper() == "CREDIT" else "expense"
            amount = abs(t.amount)
            if amount <= 0:
                continue
            if self._is_duplicate(account.id, amount, t.value_date, t.narration):
                continue

            merchant, category_id, method, confidence = self._categorize(
                t.narration, amount, tx_type
            )
            self.db.add(
                Transaction(
                    id=str(uuid.uuid4()),
                    amount=amount,
                    type=tx_type,
                    description=t.narration,
                    merchant=merchant,
                    date=t.value_date,
                    timestamp=int(t.value_date.timestamp() * 1000),
                    owner_id=self.user_id,
                    account_id=account.id,
                    category_id=category_id,
                    categorization_method=method,
                    categorization_confidence=confidence,
                )
            )
            imported += 1
        return imported

    def _categorize(self, narration: str, amount: float, tx_type: str):
        """
        Run an AA narration through the shared categorization chain.

        AA rows used to land uncategorized, which meant a user's own rules — the
        ones that make imported entries look like their manual ones — never
        applied to their bank feed. Categorization must never fail a sync, so any
        error degrades to an uncategorized row.
        """
        try:
            suggestion = self.categorizer.categorize_transaction(
                user_id=self.user_id,
                description=narration or "",
                merchant="",
                amount=amount,
                type=tx_type,
                db=self.db,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("AA categorization failed for user %s: %s", self.user_id, exc)
            return None, None, "account_aggregator", None

        merchant = suggestion.get("normalized_merchant")
        confidence = suggestion.get("confidence", 0.0)
        if suggestion.get("category_id") and confidence >= SmartCategorizationService.AUTO_ASSIGN_CONFIDENCE:
            return merchant, suggestion["category_id"], suggestion["method"], confidence
        # Below the auto-assign bar: keep the row uncategorized but record why.
        return merchant, None, "account_aggregator", confidence or None

    def _is_duplicate(self, account_id: str, amount: float, date: datetime, description: str) -> bool:
        return (
            self.db.query(Transaction.id)
            .filter(
                Transaction.owner_id == self.user_id,
                Transaction.account_id == account_id,
                Transaction.amount == amount,
                Transaction.date == date,
                Transaction.description == description,
            )
            .first()
            is not None
        )
