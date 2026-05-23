from datetime import datetime

import pytest

from models import Account, Category, CategorizationRule, MerchantCategoryMapping
from schemas import TransactionCreate, TransactionType, TransactionUpdate
from services.smart_categorization_service import SmartCategorizationService
from services.transaction_service import TransactionService
from user_models import User


@pytest.fixture
def categorization_setup(db_session):
    user = User(id="smart-user", email="smart@example.com", hashed_password="hashed")
    db_session.add(user)

    account = Account(
        id="smart-account",
        name="Primary",
        type="checking",
        currency="INR",
        balance=5000.0,
        owner_id=user.id,
    )
    db_session.add(account)

    categories = {
        "food": Category(id="cat-food", name="Food & Dining", type="expense", color="#ef4444", owner_id=user.id),
        "groceries": Category(id="cat-groceries", name="Groceries", type="expense", color="#f97316", owner_id=user.id),
        "general-expense": Category(id="cat-general-expense", name="General", type="expense", color="#6b7280", owner_id=user.id),
        "salary": Category(id="cat-salary", name="Salary", type="income", color="#22c55e", owner_id=user.id),
    }
    db_session.add_all(categories.values())
    db_session.commit()
    return user, account, categories


def test_normalize_merchant_recognizes_indian_upi_patterns(db_session):
    service = SmartCategorizationService()

    assert service.normalize_merchant("UPI-SWIGGY-123456") == "Swiggy"
    assert service.normalize_merchant("POS 1234 AMAZON SELLER SERVICES") == "Amazon"
    assert service.normalize_merchant("UPI/LOCAL KIRANA/998877") == "Local Kirana"


def test_categorize_transaction_prefers_user_rule_over_history(db_session, categorization_setup):
    user, _, categories = categorization_setup
    service = SmartCategorizationService()

    db_session.add(
        MerchantCategoryMapping(
            user_id=user.id,
            merchant_pattern="Swiggy",
            category_id=categories["food"].id,
            confidence=0.9,
            usage_count=4,
        )
    )
    db_session.add(
        CategorizationRule(
            id="rule-swiggy",
            pattern="swiggy",
            category_id=categories["groceries"].id,
            priority=100,
            owner_id=user.id,
            is_regex=False,
        )
    )
    db_session.commit()

    result = service.categorize_transaction(
        user_id=user.id,
        description="UPI-SWIGGY-ORDER",
        merchant="",
        amount=450,
        type=TransactionType.expense,
        db=db_session,
    )

    assert result["category_id"] == categories["groceries"].id
    assert result["method"] == "pattern_match"
    assert result["confidence"] == pytest.approx(0.95)


def test_transaction_creation_auto_assigns_smart_category(db_session, categorization_setup):
    user, account, categories = categorization_setup
    service = TransactionService(db_session)

    transaction = service.create_transaction(
        TransactionCreate(
            id="tx-smart-auto",
            amount=320.0,
            type=TransactionType.expense,
            description="UPI-SWIGGY-ORDER-4433",
            date=datetime.now(),
            timestamp=1,
            account_id=account.id,
        ),
        user.id,
    )

    assert transaction.category_id == categories["food"].id
    assert transaction.categorization_method == "keyword"
    assert transaction.categorization_confidence >= SmartCategorizationService.AUTO_ASSIGN_CONFIDENCE
    assert transaction.merchant == "Swiggy"


def test_manual_category_change_learns_pattern_for_future_transactions(db_session, categorization_setup):
    user, account, categories = categorization_setup
    service = TransactionService(db_session)

    first_tx = service.create_transaction(
        TransactionCreate(
            id="tx-manual-1",
            amount=150.0,
            type=TransactionType.expense,
            description="UPI/FRESH BASKET/1111",
            date=datetime.now(),
            timestamp=1,
            account_id=account.id,
        ),
        user.id,
    )
    assert first_tx.category_id is None

    updated_tx = service.update_transaction(
        first_tx.id,
        TransactionUpdate(category_id=categories["groceries"].id),
        user.id,
    )
    assert updated_tx.category_id == categories["groceries"].id
    assert updated_tx.categorization_method == "manual"

    mapping = db_session.query(MerchantCategoryMapping).filter(MerchantCategoryMapping.user_id == user.id).one()
    assert mapping.merchant_pattern == "Fresh Basket"
    assert mapping.category_id == categories["groceries"].id

    second_tx = service.create_transaction(
        TransactionCreate(
            id="tx-manual-2",
            amount=220.0,
            type=TransactionType.expense,
            description="UPI/FRESH BASKET/2222",
            date=datetime.now(),
            timestamp=2,
            account_id=account.id,
        ),
        user.id,
    )

    assert second_tx.category_id == categories["groceries"].id
    assert second_tx.categorization_method == "user_history"
    assert second_tx.categorization_confidence >= SmartCategorizationService.AUTO_ASSIGN_CONFIDENCE
