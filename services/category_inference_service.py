"""
Category inference service for auto-categorizing transactions based on description keywords.

Used as a fallback when importers don't provide explicit category information
(e.g., bank PDF importers, credit card PDF importers).
"""
import re
import logging
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from models import CategorizationRule, Category
from schemas import TransactionType

logger = logging.getLogger(__name__)


class CategoryInferenceService:
    """
    Infers transaction category from description using user-defined rules in the database.
    
    Keywords and regex patterns are checked in priority order.
    """
    
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    # Each entry: (keywords, category_name, transaction_type, color)
    DEFAULT_RULES = [
        (["swiggy", "zomato", "blinkit", "zepto"], "Food & Dining", "expense", "#ef4444"),
        (["uber", "ola", "metro", "irctc"], "Transportation", "expense", "#f59e0b"),
        (["amazon", "flipkart", "myntra"], "Shopping", "expense", "#3b82f6"),
        (["netflix", "spotify", "hotstar"], "Entertainment", "expense", "#8b5cf6"),
        (["rent", "housing", "maintenance"], "Housing", "expense", "#ec4899"),
        (["salary", "payroll"], "Salary", "income", "#10b981"),
        (["refund", "cashback"], "Refunds", "income", "#84cc16"),
    ]

    def seed_default_rules(self):
        """Seed default rules for the user if they don't have any."""
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

    def infer_category(
        self,
        description: str,
        tx_type: TransactionType,
    ) -> Optional[str]:
        """
        Infer category name from transaction description using database rules.
        """
        if not description or tx_type == TransactionType.transfer:
            return None
        
        desc_lower = description.lower()
        
        # Fetch rules for this user, ordered by priority
        rules = self.db.query(CategorizationRule).filter(
            CategorizationRule.owner_id == self.owner_id
        ).order_by(CategorizationRule.priority.desc()).all()
        
        for rule in rules:
            # Check if category matches transaction type? 
            # Actually, the rule points to a category, and categories have a type.
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
        """Get the default color for a category."""
        category = self.db.query(Category).filter(
            Category.owner_id == self.owner_id,
            Category.name.ilike(category_name)
        ).first()
        return category.color if category else None
