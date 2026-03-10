"""
Category inference service for auto-categorizing transactions based on description keywords.

Used as a fallback when importers don't provide explicit category information
(e.g., bank PDF importers, credit card PDF importers).
"""
import re
import logging
from typing import Optional, List, Tuple, Dict
from sqlalchemy.orm import Session
from models import CategorizationRule, Category
from schemas import TransactionType

logger = logging.getLogger(__name__)


class CategoryInferenceService:
    """
    Infers transaction category from description using user-defined rules in the database.
    When no database session is provided, falls back to built-in DEFAULT_RULES for
    stateless (e.g. test) usage.

    Keywords and regex patterns are checked in priority order.
    """

    def __init__(self, db: Optional[Session] = None, owner_id: Optional[str] = None):
        self.db = db
        self.owner_id = owner_id

    # Each entry: (keywords, category_name, transaction_type, color)
    # Order matters: earlier entries take priority when multiple keywords match.
    DEFAULT_RULES = [
        (["swiggy", "zomato", "blinkit", "zepto", "restaurant"], "Food & Dining", "expense", "#ef4444"),
        (["dmart", "bigbasket", "supermarket"], "Groceries", "expense", "#f97316"),
        (["uber", "ola", "metro", "irctc", "petrol", "fuel", "rapido"], "Transportation", "expense", "#f59e0b"),
        (["amazon", "flipkart", "myntra", "meesho", "nykaa"], "Shopping", "expense", "#3b82f6"),
        (["netflix", "spotify", "hotstar"], "Entertainment", "expense", "#8b5cf6"),
        (["electricity", "jio", "airtel", "recharge", "broadband"], "Utilities", "expense", "#06b6d4"),
        (["rent", "housing", "maintenance"], "Housing", "expense", "#ec4899"),
        (["apollo", "pharmacy", "hospital", "clinic", "medical"], "Healthcare", "expense", "#14b8a6"),
        (["lic", "insurance", "policy"], "Insurance", "expense", "#64748b"),
        (["emi"], "Loan & EMI", "expense", "#dc2626"),
        (["udemy", "coursera", "tuition"], "Education", "expense", "#7c3aed"),
        (["gym", "fitness", "cult.fit"], "Fitness", "expense", "#059669"),
        (["cred", "subscription", "annual plan"], "Subscriptions", "expense", "#d97706"),
        (["zerodha", "groww", "mutual fund", "sip", "demat"], "Investments", "expense", "#0ea5e9"),
        (["salary", "payroll", "stipend"], "Salary", "income", "#22c55e"),
        (["interest", "dividend", "returns", "maturity"], "Investments", "income", "#16a34a"),
        (["refund", "cashback", "reversal"], "Refunds", "income", "#84cc16"),
        (["consulting", "freelance", "client payment"], "Freelance", "income", "#0891b2"),
    ]

    # Class-level color lookup built lazily from DEFAULT_RULES
    _DEFAULT_COLORS: Dict[str, str] = {}

    @classmethod
    def _get_default_colors(cls) -> Dict[str, str]:
        if not cls._DEFAULT_COLORS:
            for _, category, _, color in cls.DEFAULT_RULES:
                cls._DEFAULT_COLORS[category.lower()] = color
        return cls._DEFAULT_COLORS

    # ------------------------------------------------------------------
    # Static (no-DB) inference using DEFAULT_RULES
    # ------------------------------------------------------------------

    def _static_infer_category(self, description: str, tx_type: TransactionType) -> Optional[str]:
        """Infer category using hardcoded DEFAULT_RULES without a database."""
        if not description or tx_type == TransactionType.transfer:
            return None
        desc_lower = description.lower()
        for keywords, category, rule_tx_type, _ in self.DEFAULT_RULES:
            if rule_tx_type != tx_type.value:
                continue
            for keyword in keywords:
                if keyword in desc_lower:
                    return category
        return None

    # ------------------------------------------------------------------
    # DB seeding
    # ------------------------------------------------------------------

    def seed_default_rules(self):
        """Seed default rules for the user if they don't have any."""
        if not self.db or not self.owner_id:
            return

        from services.import_entity_service import ImportEntityService

        existing_rules = self.db.query(CategorizationRule).filter(
            CategorizationRule.owner_id == self.owner_id
        ).first()

        if existing_rules:
            return  # Already has rules

        entity_service = ImportEntityService(self.db, self.owner_id)

        for idx, (keywords, cat_name, tx_type, color) in enumerate(self.DEFAULT_RULES):
            category_id = entity_service.get_or_create_category(
                cat_name, TransactionType(tx_type), color=color
            )

            if not category_id:
                continue

            for keyword in keywords:
                import uuid
                rule = CategorizationRule(
                    id=str(uuid.uuid4()),
                    pattern=keyword,
                    category_id=category_id,
                    priority=100 - idx,  # Higher priority for earlier categories
                    owner_id=self.owner_id,
                    is_regex=False
                )
                self.db.add(rule)

        self.db.commit()

    # ------------------------------------------------------------------
    # Public inference API
    # ------------------------------------------------------------------

    def infer_category(
        self,
        description: str,
        tx_type: TransactionType,
    ) -> Optional[str]:
        """
        Infer category name from transaction description.

        Uses database rules when a db session is available; otherwise falls
        back to the built-in DEFAULT_RULES.
        """
        if not self.db or not self.owner_id:
            return self._static_infer_category(description, tx_type)

        if not description or tx_type == TransactionType.transfer:
            return None

        desc_lower = description.lower()

        # Fetch rules for this user, ordered by priority
        rules = self.db.query(CategorizationRule).filter(
            CategorizationRule.owner_id == self.owner_id
        ).order_by(CategorizationRule.priority.desc()).all()

        for rule in rules:
            # Check if category matches transaction type
            if rule.category.type != tx_type.value:
                continue

            if rule.is_regex:
                try:
                    if re.search(rule.pattern, description, re.IGNORECASE):
                        logger.debug(f"Inferred category '{rule.category.name}' via regex '{rule.pattern}'")
                        return rule.category.name
                except re.error:
                    logger.error(f"Invalid regex pattern in rule {rule.id}: {rule.pattern}")
                    continue
            else:
                # Simple keyword match
                if rule.pattern.lower() in desc_lower:
                    logger.debug(f"Inferred category '{rule.category.name}' via keyword '{rule.pattern}'")
                    return rule.category.name

        return None

    def get_category_color(self, category_name: str) -> Optional[str]:
        """Get the color for a category."""
        if not self.db or not self.owner_id:
            return self._get_default_colors().get(category_name.lower())

        category = self.db.query(Category).filter(
            Category.owner_id == self.owner_id,
            Category.name.ilike(category_name)
        ).first()
        return category.color if category else None
