"""
SMS Transaction Service — ingestion, account matching, confirmation workflow.
"""
from typing import List, Optional
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from models import SMSTransaction, SMSTransactionStatus, Account, Transaction, TransactionType
from services.sms_parser import parse_sms, compute_dedup_hash, normalize_merchant, ParsedSMS
from services.smart_categorization_service import SmartCategorizationService


class SMSTransactionService:
    def __init__(self, db: Session):
        self.db = db

    def ingest_batch(self, user_id: str, messages: List[dict], device_id: Optional[str] = None) -> dict:
        """
        Ingest a batch of raw SMS messages.
        Returns summary: { ingested, duplicates, non_transactional }
        """
        ingested = 0
        duplicates = 0
        non_transactional = 0

        for msg in messages:
            sender = msg.get("sender", "")
            body = msg.get("body", "")
            sms_ts = msg.get("timestamp")
            if isinstance(sms_ts, str):
                try:
                    sms_ts = datetime.fromisoformat(sms_ts)
                except (ValueError, TypeError):
                    sms_ts = None

            parsed = parse_sms(sender, body, sms_ts)

            if not parsed.is_transactional:
                non_transactional += 1
                continue

            # Deduplication
            dedup_hash = compute_dedup_hash(
                user_id,
                parsed.amount or 0,
                parsed.timestamp,
                parsed.reference_number
            )
            existing = self.db.query(SMSTransaction).filter(
                and_(
                    SMSTransaction.user_id == user_id,
                    SMSTransaction.dedup_hash == dedup_hash
                )
            ).first()
            if existing:
                duplicates += 1
                continue

            # Match account
            matched_account_id = self._match_account(user_id, parsed)

            # Suggest category
            suggested_category_id = self._suggest_category(user_id, parsed)

            # Normalize merchant
            merchant = normalize_merchant(parsed.merchant) or parsed.merchant

            sms_txn = SMSTransaction(
                id=str(uuid4()),
                user_id=user_id,
                raw_body=body,
                sender=sender,
                sms_timestamp=sms_ts,
                device_id=device_id,
                amount=parsed.amount,
                transaction_type=parsed.transaction_type,
                merchant=merchant,
                bank_name=parsed.bank_name,
                masked_account=parsed.masked_account,
                reference_number=parsed.reference_number,
                available_balance=parsed.available_balance,
                upi_id=parsed.upi_id,
                card_type=parsed.card_type,
                matched_account_id=matched_account_id,
                suggested_category_id=suggested_category_id,
                confidence=parsed.confidence,
                status=SMSTransactionStatus.draft.value,
                dedup_hash=dedup_hash,
            )
            self.db.add(sms_txn)
            ingested += 1

        self.db.commit()
        return {
            "ingested": ingested,
            "duplicates": duplicates,
            "non_transactional": non_transactional,
            "total_processed": ingested + duplicates + non_transactional,
        }

    def get_drafts(self, user_id: str, limit: int = 50, offset: int = 0) -> List[SMSTransaction]:
        """Get pending draft SMS transactions for review."""
        return (
            self.db.query(SMSTransaction)
            .filter(
                and_(
                    SMSTransaction.user_id == user_id,
                    SMSTransaction.status == SMSTransactionStatus.draft.value
                )
            )
            .order_by(desc(SMSTransaction.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_draft_count(self, user_id: str) -> int:
        """Count pending drafts."""
        return (
            self.db.query(SMSTransaction)
            .filter(
                and_(
                    SMSTransaction.user_id == user_id,
                    SMSTransaction.status == SMSTransactionStatus.draft.value
                )
            )
            .count()
        )

    def confirm_draft(
        self,
        user_id: str,
        sms_txn_id: str,
        override_amount: Optional[float] = None,
        override_category_id: Optional[str] = None,
        override_account_id: Optional[str] = None,
        override_description: Optional[str] = None,
    ) -> Optional[Transaction]:
        """Confirm a draft SMS transaction → create a real Transaction."""
        sms_txn = self.db.query(SMSTransaction).filter(
            and_(
                SMSTransaction.id == sms_txn_id,
                SMSTransaction.user_id == user_id,
                SMSTransaction.status == SMSTransactionStatus.draft.value,
            )
        ).first()

        if not sms_txn:
            return None

        # Map SMS type to transaction type
        txn_type = self._map_transaction_type(sms_txn.transaction_type)
        amount = override_amount or sms_txn.amount or 0
        category_id = override_category_id or sms_txn.suggested_category_id
        account_id = override_account_id or sms_txn.matched_account_id
        description = override_description or sms_txn.merchant or sms_txn.raw_body[:80]

        # Create real transaction
        transaction = Transaction(
            id=str(uuid4()),
            amount=abs(amount),
            type=txn_type,
            description=description,
            merchant=sms_txn.merchant,
            date=sms_txn.sms_timestamp or datetime.utcnow(),
            owner_id=user_id,
            category_id=category_id,
            account_id=account_id,
            categorization_method="sms_auto" if not override_category_id else "manual",
            categorization_confidence=sms_txn.confidence if not override_category_id else 1.0,
        )
        self.db.add(transaction)

        # Update SMS transaction status
        sms_txn.status = SMSTransactionStatus.confirmed.value
        sms_txn.confirmed_transaction_id = transaction.id

        self.db.commit()
        return transaction

    def batch_confirm(self, user_id: str, sms_txn_ids: List[str]) -> dict:
        """Bulk confirm multiple draft SMS transactions."""
        confirmed = 0
        failed = 0
        for txn_id in sms_txn_ids:
            result = self.confirm_draft(user_id, txn_id)
            if result:
                confirmed += 1
            else:
                failed += 1
        return {"confirmed": confirmed, "failed": failed}

    def reject_draft(self, user_id: str, sms_txn_id: str) -> bool:
        """Reject a draft SMS transaction."""
        sms_txn = self.db.query(SMSTransaction).filter(
            and_(
                SMSTransaction.id == sms_txn_id,
                SMSTransaction.user_id == user_id,
                SMSTransaction.status == SMSTransactionStatus.draft.value,
            )
        ).first()
        if not sms_txn:
            return False
        sms_txn.status = SMSTransactionStatus.rejected.value
        self.db.commit()
        return True

    def batch_reject(self, user_id: str, sms_txn_ids: List[str]) -> dict:
        """Bulk reject multiple draft SMS transactions."""
        rejected = 0
        for txn_id in sms_txn_ids:
            if self.reject_draft(user_id, txn_id):
                rejected += 1
        return {"rejected": rejected}

    def _match_account(self, user_id: str, parsed: ParsedSMS) -> Optional[str]:
        """Match parsed SMS to a user's account."""
        accounts = self.db.query(Account).filter(
            Account.owner_id == user_id,
            Account.is_deleted == False,
        ).all()

        if not accounts:
            return None

        best_match = None
        best_score = 0

        for account in accounts:
            score = 0
            acc_name_lower = (account.name or "").lower()
            acc_institution_lower = (account.institution or "").lower()

            # Bank name match
            if parsed.bank_name:
                bank_lower = parsed.bank_name.lower()
                if bank_lower in acc_name_lower or bank_lower in acc_institution_lower:
                    score += 3

            # Masked account number match
            if parsed.masked_account and account.account_number:
                if account.account_number.endswith(parsed.masked_account):
                    score += 5  # Strong match

            # Card type match
            if parsed.card_type == "credit_card" and account.account_type in ("credit", "credit_card"):
                score += 2
            elif parsed.card_type == "debit_card" and account.account_type in ("savings", "checking"):
                score += 2

            if score > best_score:
                best_score = score
                best_match = account.id

        # Only return if we have reasonable confidence
        return best_match if best_score >= 2 else None

    def _suggest_category(self, user_id: str, parsed: ParsedSMS) -> Optional[str]:
        """Suggest category based on merchant/description."""
        if not parsed.merchant:
            return None
        try:
            service = SmartCategorizationService(self.db)
            suggestion = service.categorize_transaction(
                user_id=user_id,
                description=parsed.merchant,
                amount=parsed.amount,
            )
            if suggestion and suggestion.get("confidence", 0) > 0.5:
                return suggestion.get("category_id")
        except Exception:
            pass
        return None

    def _map_transaction_type(self, sms_type: Optional[str]) -> str:
        """Map SMS transaction type to Transaction model type."""
        if sms_type in ("credit", "refund"):
            return TransactionType.income.value
        if sms_type == "transfer":
            return TransactionType.transfer.value
        # debit, upi, atm → expense
        return TransactionType.expense.value
