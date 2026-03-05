"""
Category inference service for auto-categorizing transactions based on description keywords.

Used as a fallback when importers don't provide explicit category information
(e.g., bank PDF importers, credit card PDF importers).
"""
import re
import logging
from typing import Optional, List, Tuple
from schemas import TransactionType

logger = logging.getLogger(__name__)


class CategoryInferenceService:
    """
    Infers transaction category from description using keyword matching.
    
    Stateless service — no DB dependency. Returns category name strings
    that can be passed to ImportEntityService.get_or_create_category().
    
    Keywords are checked in priority order (most specific first).
    """
    
    # Each entry: (keywords, category_name, transaction_type, color)
    # More specific keywords should come before generic ones.
    CATEGORY_RULES: List[Tuple[List[str], str, str, str]] = [
        # ── Food & Dining ────────────────────────────────────────
        (
            [
                "swiggy", "zomato", "dominos", "pizza hut", "burger king",
                "mcdonalds", "kfc", "starbucks", "cafe coffee day", "ccd",
                "restaurant", "cafe", "food", "dining", "barbeque", "biryani",
                "bakery", "eat", "kitchen", "dhaba", "mess", "canteen",
                "dunkin", "baskin robbins", "subway", "haldiram", "blinkit",
                "zepto", "bigbasket", "grofers", "instamart",
            ],
            "Food & Dining", "expense", "#ef4444",
        ),
        # ── Groceries ────────────────────────────────────────────
        (
            [
                "grocery", "supermarket", "dmart", "reliance fresh",
                "more supermarket", "spar", "nature basket", "spencers",
                "ratnadeep", "star bazaar",
            ],
            "Groceries", "expense", "#f97316",
        ),
        # ── Transportation ───────────────────────────────────────
        (
            [
                "uber", "ola", "rapido", "metro", "irctc", "railway",
                "fuel", "petrol", "diesel", "indian oil", "hp petrol",
                "bharat petroleum", "bpcl", "iocl", "hpcl", "parking",
                "toll", "fastag", "grab", "lyft", "taxi", "auto",
                "makemytrip", "redbus", "goibibo", "yatra",
            ],
            "Transportation", "expense", "#f59e0b",
        ),
        # ── Shopping ─────────────────────────────────────────────
        (
            [
                "amazon", "flipkart", "myntra", "ajio", "meesho",
                "nykaa", "tata cliq", "snapdeal", "shopping", "mall",
                "croma", "reliance digital", "vijay sales",
            ],
            "Shopping", "expense", "#3b82f6",
        ),
        # ── Entertainment ────────────────────────────────────────
        (
            [
                "netflix", "spotify", "hotstar", "disney", "prime video",
                "youtube premium", "apple music", "jio cinema",
                "movie", "cinema", "pvr", "inox", "bookmyshow",
                "gaming", "playstation", "xbox", "steam",
            ],
            "Entertainment", "expense", "#8b5cf6",
        ),
        # ── Utilities ────────────────────────────────────────────
        (
            [
                "electricity", "power", "bescom", "tata power", "adani electricity",
                "water", "gas", "piped gas", "broadband", "internet",
                "jio", "airtel", "vodafone", "vi ", "bsnl",
                "act fibernet", "hathway", "tata sky", "d2h",
                "mobile recharge", "postpaid",
            ],
            "Utilities", "expense", "#06b6d4",
        ),
        # ── Housing / Rent ───────────────────────────────────────
        (
            [
                "rent", "housing", "maintenance", "society",
                "apartment", "flat", "lease", "nobroker",
            ],
            "Housing", "expense", "#ec4899",
        ),
        # ── Healthcare ───────────────────────────────────────────
        (
            [
                "hospital", "pharmacy", "pharma", "apollo", "medplus",
                "netmeds", "1mg", "pharmeasy", "doctor", "clinic",
                "dental", "diagnostic", "pathology", "lab test",
                "medical", "health", "fortis", "max hospital",
            ],
            "Healthcare", "expense", "#10b981",
        ),
        # ── Insurance ────────────────────────────────────────────
        (
            [
                "insurance", "lic", "premium", "policy",
                "icici prudential", "hdfc life", "sbi life",
                "max life", "bajaj allianz", "acko",
            ],
            "Insurance", "expense", "#0ea5e9",
        ),
        # ── Loan & EMI ───────────────────────────────────────────
        (
            [
                "emi", "loan", "hdfc ltd", "bajaj finance",
                "home credit", "lending", "credit line",
            ],
            "Loan & EMI", "expense", "#dc2626",
        ),
        # ── Education ────────────────────────────────────────────
        (
            [
                "school", "college", "university", "education",
                "course", "udemy", "coursera", "unacademy",
                "byju", "tuition", "coaching",
            ],
            "Education", "expense", "#7c3aed",
        ),
        # ── Fitness ──────────────────────────────────────────────
        (
            [
                "gym", "fitness", "cult.fit", "cultfit",
                "yoga", "crossfit",
            ],
            "Fitness", "expense", "#14b8a6",
        ),
        # ── Subscriptions ────────────────────────────────────────
        (
            [
                "subscription", "membership", "cred",
                "patreon", "notion", "chatgpt", "openai",
                "icloud", "google one", "dropbox",
            ],
            "Subscriptions", "expense", "#a855f7",
        ),
        # ── Investments ──────────────────────────────────────────
        (
            [
                "mutual fund", "sip", "zerodha", "groww",
                "upstox", "angel", "smallcase", "nps",
                "ppf", "fixed deposit", "fd ",
            ],
            "Investments", "expense", "#6366f1",
        ),
        # ── Income: Salary ───────────────────────────────────────
        (
            ["salary", "payroll"],
            "Salary", "income", "#10b981",
        ),
        # ── Income: Investment Returns ───────────────────────────
        (
            ["interest", "dividend", "capital gain", "maturity"],
            "Investments", "income", "#6366f1",
        ),
        # ── Income: Freelance / Business ─────────────────────────
        (
            ["freelance", "consulting", "invoice", "client payment"],
            "Freelance", "income", "#34d399",
        ),
        # ── Income: Refunds ──────────────────────────────────────
        (
            ["refund", "cashback", "reversal"],
            "Refunds", "income", "#84cc16",
        ),
    ]

    def infer_category(
        self,
        description: str,
        tx_type: TransactionType,
    ) -> Optional[str]:
        """
        Infer category name from transaction description.
        
        Args:
            description: Cleaned transaction description
            tx_type: Transaction type (income/expense/transfer)
            
        Returns:
            Category name string or None if no match
        """
        if not description or tx_type == TransactionType.transfer:
            return None
        
        desc_lower = description.lower()
        
        for keywords, category_name, rule_type, _color in self.CATEGORY_RULES:
            # Only match rules that align with the transaction type
            if rule_type != tx_type.value:
                continue
            
            for keyword in keywords:
                if keyword in desc_lower:
                    logger.debug(
                        f"Inferred category '{category_name}' for "
                        f"description '{description}' (matched '{keyword}')"
                    )
                    return category_name
        
        return None

    def get_category_color(self, category_name: str) -> Optional[str]:
        """Get the default color for an inferred category."""
        for _keywords, name, _rule_type, color in self.CATEGORY_RULES:
            if name.lower() == category_name.lower():
                return color
        return None
