import logging
import re
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models import Category, CategorizationRule, MerchantCategoryMapping, Transaction
from schemas import TransactionType
from services.import_entity_service import ImportEntityService

logger = logging.getLogger(__name__)


class SmartCategorizationService:
    AUTO_ASSIGN_CONFIDENCE = 0.7

    MERCHANT_PATTERNS = {
        r"swiggy|swigy": "Swiggy",
        r"zomato": "Zomato",
        r"amazon|amzn": "Amazon",
        r"flipkart|fkrt": "Flipkart",
        r"uber|ola|rapido": "Ride",
        r"petrol|fuel|hp\s|bp\s|iocl|bharat\spetro|indian\soil": "Petrol",
        r"bigbasket|blinkit|zepto|instamart|dmart|bbnow": "Groceries",
        r"netflix|hotstar|prime\svideo|spotify|jiocinema": "Entertainment",
        r"airtel|jio|vodafone|vi\b|bsnl": "Telecom",
        r"electricity|bescom|tata\spower|adani\selectricity|torrent\spower": "Electricity",
        r"rent|rental": "Rent",
        r"salary|stipend|payroll": "Salary",
        r"apollo|pharmacy|medplus|hospital|clinic": "Healthcare",
        r"lic|insurance|policy": "Insurance",
        r"zerodha|groww|upstox|mutual\sfund|sip": "Investments",
        r"refund|cashback|reversal": "Refund",
    }

    CATEGORY_RULES = [
        (r"swiggy|swigy|zomato|restaurant|domino'?s|pizza\s*hut|faasos|eatsure", "Food & Dining", TransactionType.expense, "#ef4444", 0.84),
        (r"bigbasket|blinkit|zepto|instamart|dmart|bbnow|grocery|kirana|supermarket", "Groceries", TransactionType.expense, "#f97316", 0.82),
        (r"uber|ola|rapido|metro|irctc|ride|petrol|fuel|hp\s|bp\s|iocl|bharat\spetro", "Transportation", TransactionType.expense, "#f59e0b", 0.82),
        (r"amazon|amzn|flipkart|fkrt|myntra|meesho|nykaa", "Shopping", TransactionType.expense, "#3b82f6", 0.81),
        (r"netflix|spotify|hotstar|prime\svideo|jiocinema", "Entertainment", TransactionType.expense, "#8b5cf6", 0.8),
        (r"electricity|bescom|tata\spower|torrent\spower|airtel|jio|vodafone|vi\b|bsnl|recharge|broadband", "Utilities", TransactionType.expense, "#06b6d4", 0.79),
        (r"rent|rental|maintenance", "Housing", TransactionType.expense, "#ec4899", 0.78),
        (r"apollo|pharmacy|medplus|hospital|clinic|medical", "Healthcare", TransactionType.expense, "#14b8a6", 0.78),
        (r"lic|insurance|policy|premium", "Insurance", TransactionType.expense, "#64748b", 0.78),
        (r"emi|loan", "Loan & EMI", TransactionType.expense, "#dc2626", 0.78),
        (r"udemy|coursera|tuition|byju'?s|unacademy", "Education", TransactionType.expense, "#7c3aed", 0.78),
        (r"gym|fitness|cult\.?fit", "Fitness", TransactionType.expense, "#059669", 0.77),
        (r"subscription|membership|annual\splan|cred", "Subscriptions", TransactionType.expense, "#d97706", 0.76),
        (r"zerodha|groww|upstox|mutual\sfund|sip|demat", "Investments", TransactionType.expense, "#0ea5e9", 0.76),
        (r"salary|stipend|payroll", "Salary", TransactionType.income, "#22c55e", 0.86),
        (r"interest|dividend|returns|maturity", "Investments", TransactionType.income, "#16a34a", 0.8),
        (r"refund|cashback|reversal", "Refunds", TransactionType.income, "#84cc16", 0.8),
        (r"consulting|freelance|client\spayment", "Freelance", TransactionType.income, "#0891b2", 0.8),
    ]

    NOISE_WORDS = {
        "upi", "imps", "neft", "rtgs", "ach", "debit", "credit", "pos", "ecom", "atm", "bank", "txn",
        "tx", "utr", "ref", "rrn", "id", "paid", "payment", "collect", "collection", "transfer", "to", "from",
        "via", "vpa", "dr", "cr", "bill", "purchase", "india", "pvt", "ltd", "private", "limited", "the",
        "online", "pay", "merchant", "transaction", "card", "acct", "account", "upiqr", "qr",
    }

    def _coerce_transaction_type(self, tx_type: Any) -> Optional[TransactionType]:
        if tx_type is None:
            return None
        if isinstance(tx_type, TransactionType):
            return tx_type
        raw_value = getattr(tx_type, "value", tx_type)
        try:
            return TransactionType(str(raw_value))
        except ValueError:
            return None

    def _get_or_create_category_id(
        self,
        user_id: str,
        category_name: str,
        tx_type: TransactionType,
        db: Session,
        color: Optional[str] = None,
    ) -> Optional[str]:
        entity_service = ImportEntityService(db, user_id)
        return entity_service.get_or_create_category(category_name, tx_type, color=color)

    def normalize_merchant(self, description: str) -> str:
        if not description:
            return ""

        lowered = description.lower().strip()
        lowered = re.sub(r"[|:_/\\-]+", " ", lowered)
        lowered = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", lowered)
        lowered = re.sub(r"\b\d{6,}\b", " ", lowered)
        lowered = re.sub(r"\b[a-z]*\d[a-z\d]{3,}\b", " ", lowered)

        for pattern, canonical in self.MERCHANT_PATTERNS.items():
            if re.search(pattern, lowered):
                return canonical

        cleaned = re.sub(r"[^a-z\s]", " ", lowered)
        tokens = [
            token
            for token in cleaned.split()
            if len(token) > 1 and token not in self.NOISE_WORDS
        ]
        if not tokens:
            return ""

        merchant_tokens = []
        for token in tokens:
            merchant_tokens.append(token)
            if len(merchant_tokens) == 3:
                break

        return " ".join(merchant_tokens).title()

    def _match_user_rule(
        self,
        user_id: str,
        description: str,
        merchant: str,
        tx_type: TransactionType,
        db: Session,
    ) -> Optional[str]:
        rules = (
            db.query(CategorizationRule)
            .join(Category, Category.id == CategorizationRule.category_id)
            .filter(
                CategorizationRule.owner_id == user_id,
                Category.type == tx_type.value,
            )
            .order_by(CategorizationRule.priority.desc(), CategorizationRule.updated_at.desc())
            .all()
        )
        searchable_text = " ".join(part for part in [description or "", merchant or ""] if part).strip()
        if not searchable_text:
            return None

        for rule in rules:
            if rule.is_regex:
                try:
                    if re.search(rule.pattern, searchable_text, re.IGNORECASE):
                        return rule.category_id
                except re.error:
                    logger.warning("Skipping invalid categorization rule %s", rule.id)
                    continue
            elif rule.pattern.lower() in searchable_text.lower():
                return rule.category_id

        return None

    def _get_history_match(
        self,
        user_id: str,
        merchant: str,
        tx_type: TransactionType,
        db: Session,
    ) -> tuple[Optional[str], float]:
        if not merchant:
            return None, 0.0

        mapping = (
            db.query(MerchantCategoryMapping)
            .join(Category, Category.id == MerchantCategoryMapping.category_id)
            .filter(
                MerchantCategoryMapping.user_id == user_id,
                func.lower(MerchantCategoryMapping.merchant_pattern) == merchant.lower(),
                Category.type == tx_type.value,
            )
            .order_by(MerchantCategoryMapping.usage_count.desc(), MerchantCategoryMapping.updated_at.desc())
            .first()
        )
        if mapping:
            confidence = min(0.97, 0.78 + min(mapping.usage_count, 6) * 0.03)
            return mapping.category_id, confidence

        history_rows = (
            db.query(
                Transaction.category_id,
                func.count(Transaction.id).label("match_count"),
            )
            .join(Category, Category.id == Transaction.category_id)
            .filter(
                Transaction.owner_id == user_id,
                Transaction.category_id.isnot(None),
                Category.type == tx_type.value,
                or_(
                    func.lower(func.coalesce(Transaction.merchant, "")) == merchant.lower(),
                    Transaction.description.ilike(f"%{merchant}%"),
                ),
            )
            .group_by(Transaction.category_id)
            .order_by(func.count(Transaction.id).desc())
            .all()
        )
        if not history_rows:
            return None, 0.0

        top_match = history_rows[0]
        total_matches = sum(row.match_count for row in history_rows)
        dominant_ratio = (top_match.match_count / total_matches) if total_matches else 0.0
        confidence = min(0.92, 0.58 + dominant_ratio * 0.22 + min(top_match.match_count, 5) * 0.03)
        return top_match.category_id, confidence

    def get_category_from_history(self, user_id: str, merchant: str, db: Session) -> Optional[str]:
        category_id, _ = self._get_history_match(user_id, merchant, TransactionType.expense, db)
        return category_id

    def _match_keyword_category(
        self,
        user_id: str,
        description: str,
        merchant: str,
        tx_type: TransactionType,
        db: Session,
    ) -> tuple[Optional[str], float]:
        searchable_text = " ".join(part for part in [description or "", merchant or ""] if part).lower()
        if not searchable_text:
            return None, 0.0

        for pattern, category_name, rule_tx_type, color, confidence in self.CATEGORY_RULES:
            if rule_tx_type != tx_type:
                continue
            if re.search(pattern, searchable_text):
                category_id = self._get_or_create_category_id(user_id, category_name, tx_type, db, color=color)
                return category_id, confidence if category_id else 0.0

        return None, 0.0

    def _apply_amount_heuristic(
        self,
        user_id: str,
        amount: float,
        tx_type: TransactionType,
        db: Session,
    ) -> tuple[Optional[str], float]:
        try:
            normalized_amount = float(amount or 0)
        except (TypeError, ValueError):
            normalized_amount = 0.0

        if tx_type == TransactionType.income and normalized_amount >= 10000:
            category_id = self._get_or_create_category_id(user_id, "Salary", tx_type, db, color="#22c55e")
            return category_id, 0.72 if category_id else 0.0

        if tx_type == TransactionType.expense and 0 < normalized_amount <= 250:
            category_id = self._get_or_create_category_id(user_id, "Food & Dining", tx_type, db, color="#ef4444")
            return category_id, 0.52 if category_id else 0.0

        return None, 0.0

    def _get_default_category(
        self,
        user_id: str,
        tx_type: TransactionType,
        db: Session,
    ) -> Optional[str]:
        return self._get_or_create_category_id(user_id, "General", tx_type, db, color="#6b7280")

    def categorize_transaction(
        self,
        user_id: str,
        description: str,
        merchant: str,
        amount: float,
        type: Any,
        db: Session,
    ) -> dict:
        tx_type = self._coerce_transaction_type(type)
        normalized_merchant = self.normalize_merchant(merchant or description)

        if not db or not user_id or not tx_type or tx_type == TransactionType.transfer:
            return {
                "category_id": None,
                "confidence": 0.0,
                "method": "default",
                "normalized_merchant": normalized_merchant or None,
            }

        category_id = self._match_user_rule(user_id, description, normalized_merchant or merchant, tx_type, db)
        if category_id:
            return {
                "category_id": category_id,
                "confidence": 0.95,
                "method": "pattern_match",
                "normalized_merchant": normalized_merchant or None,
            }

        category_id, confidence = self._get_history_match(user_id, normalized_merchant, tx_type, db)
        if category_id:
            return {
                "category_id": category_id,
                "confidence": confidence,
                "method": "user_history",
                "normalized_merchant": normalized_merchant or None,
            }

        category_id, confidence = self._match_keyword_category(user_id, description, normalized_merchant or merchant, tx_type, db)
        if category_id:
            return {
                "category_id": category_id,
                "confidence": confidence,
                "method": "keyword",
                "normalized_merchant": normalized_merchant or None,
            }

        category_id, confidence = self._apply_amount_heuristic(user_id, amount, tx_type, db)
        if category_id:
            return {
                "category_id": category_id,
                "confidence": confidence,
                "method": "default",
                "normalized_merchant": normalized_merchant or None,
            }

        return {
            "category_id": self._get_default_category(user_id, tx_type, db),
            "confidence": 0.35,
            "method": "default",
            "normalized_merchant": normalized_merchant or None,
        }

    def learn_from_transaction(
        self,
        user_id: str,
        description: str,
        merchant: str,
        category_id: Optional[str],
        db: Session,
    ) -> Optional[MerchantCategoryMapping]:
        if not db or not user_id or not category_id:
            return None

        normalized_merchant = self.normalize_merchant(merchant or description)
        if not normalized_merchant:
            return None

        mapping = (
            db.query(MerchantCategoryMapping)
            .filter(
                MerchantCategoryMapping.user_id == user_id,
                func.lower(MerchantCategoryMapping.merchant_pattern) == normalized_merchant.lower(),
            )
            .first()
        )
        if mapping:
            mapping.category_id = category_id
            mapping.usage_count += 1
            mapping.confidence = min(1.0, 0.7 + min(mapping.usage_count, 5) * 0.06)
            return mapping

        mapping = MerchantCategoryMapping(
            user_id=user_id,
            merchant_pattern=normalized_merchant,
            category_id=category_id,
            confidence=0.82,
            usage_count=1,
        )
        db.add(mapping)
        return mapping

    def get_learned_patterns(self, user_id: str, db: Session) -> list[MerchantCategoryMapping]:
        return (
            db.query(MerchantCategoryMapping)
            .filter(MerchantCategoryMapping.user_id == user_id)
            .order_by(MerchantCategoryMapping.usage_count.desc(), MerchantCategoryMapping.updated_at.desc())
            .all()
        )
