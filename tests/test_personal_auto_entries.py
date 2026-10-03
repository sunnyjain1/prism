"""
Auto-created entries must follow the user's OWN categorization patterns.

Covers the path from a learned import profile through to every ingestion route:
SMS, Account Aggregator, and the shared TransactionService.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from models import Account, Category, Transaction, UserImportProfile
from schemas import TransactionCreate, TransactionType
from services.aa.base import AAFiAccount, AAFiTransaction
from services.aa.mapper import AAMapper
from services.import_profile_service import ImportProfileService
from services.smart_categorization_service import SmartCategorizationService
from services.transaction_service import TransactionService
from user_models import User


def make_user(db_session) -> User:
    user = User(
        id=f"user-{uuid4().hex}",
        email=f"personal-{uuid4().hex}@example.com",
        hashed_password="x",
        full_name="Personal Patterns User",
    )
    db_session.add(user)
    db_session.commit()
    return user


def make_account(db_session, user_id: str) -> Account:
    account = Account(
        id=f"acct-{uuid4().hex}",
        name="HDFC",
        type="savings",
        currency="INR",
        balance=10000.0,
        owner_id=user_id,
        is_deleted=False,
    )
    db_session.add(account)
    db_session.commit()
    return account


def save_profile(db_session, user_id: str, rules=None, vocabulary=None) -> ImportProfileService:
    svc = ImportProfileService(db_session, user_id)
    svc.save_profile({
        "version": 1,
        "note_rules": rules or [],
        "account_mappings": {},
        "category_mappings": {},
        "category_vocabulary": vocabulary or {},
        "skip_categories": ["Modified Bal."],
        "skip_notes": [],
    })
    return svc


def note_rule(pattern, category, **overrides):
    rule = {
        "pattern": pattern,
        "match": "exact",
        "category": category,
        "type": "expense",
        "frequency": 50,
        "confidence": 1.0,
    }
    rule.update(overrides)
    return rule


# The real vocabulary from the Money Manager export: personal names that do not
# match the built-in category names.
SUNNY_VOCABULARY = {
    "Sukoon": {"count": 1456, "type": "expense"},
    "Food": {"count": 812, "type": "expense"},
    "Transportation": {"count": 732, "type": "expense"},
    "Household": {"count": 452, "type": "expense"},
    "Health": {"count": 63, "type": "expense"},
    "Insurance": {"count": 51, "type": "expense"},
    "Salary": {"count": 43, "type": "income"},
}


# ---------------------------------------------------------------------------
# Runtime note matching — narrow by design
# ---------------------------------------------------------------------------
def test_single_word_note_never_fires_on_a_narration(db_session):
    """
    The critical false-positive guard. "auto" is a real learned note (5 uses,
    Transportation) but it appears in "ACH AUTO DEBIT MANDATE" on every standing
    instruction. One bare word cannot bridge the user's vocabulary and the bank's.
    """
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("auto", "Transportation", frequency=5),
        note_rule("snacks", "Sukoon", frequency=1306),
        note_rule("gst", "Other", frequency=10),
    ])

    assert svc.match_note_rule("ACH AUTO DEBIT MANDATE HDFC", TransactionType.expense) is None
    assert svc.match_note_rule("UPI/P2M/998/PAYTM QR/SNACKS BAR", TransactionType.expense) is None
    assert svc.match_note_rule("GST ON CARD FEES JAN26", TransactionType.expense) is None


def test_distinctive_phrase_still_matches(db_session):
    """Multi-word phrases carry enough signal to be safe."""
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("lic policy premium", "Insurance", frequency=50),
    ])

    rule = svc.match_note_rule("NEFT-LIC POLICY PREMIUM-N26011", TransactionType.expense)

    assert rule is not None
    assert rule["category"] == "Insurance"


def test_boilerplate_phrase_is_rejected_even_when_multi_word(db_session):
    """"card payment" is two words but both are narration noise."""
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("card payment", "Other", frequency=28),
    ])

    assert svc.match_note_rule("UPI/P2M/998877/CRED CLUB CARD PAYMENT", TransactionType.expense) is None


def test_phrase_must_be_contiguous(db_session):
    """Scattered words are a coincidence, not a match."""
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("bank interest", "Interest", type="income", frequency=111),
    ])

    assert svc.match_note_rule("BANK INTEREST CREDITED", TransactionType.income) is not None
    assert svc.match_note_rule("INTEREST PAID BY BANK", TransactionType.income) is None


def test_longer_pattern_wins_over_shorter(db_session):
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("cab to flat", "Transportation", frequency=116),
        note_rule("cab to office pool", "Social Life", frequency=21),
    ])

    rule = svc.match_note_rule("PAYTM CAB TO OFFICE POOL", TransactionType.expense)

    assert rule["category"] == "Social Life"


def test_low_frequency_rule_is_not_trusted_for_auto_entries(db_session):
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("lic policy premium", "Insurance", frequency=2),
    ])

    assert svc.match_note_rule("NEFT-LIC POLICY PREMIUM", TransactionType.expense) is None


def test_rule_type_guards_against_wrong_direction(db_session):
    user = make_user(db_session)
    svc = save_profile(db_session, user.id, rules=[
        note_rule("bank interest", "Interest", type="income", frequency=111),
    ])

    assert svc.match_note_rule("BANK INTEREST CR", TransactionType.income) is not None
    assert svc.match_note_rule("BANK INTEREST CR", TransactionType.expense) is None


# ---------------------------------------------------------------------------
# The shared categorization chain
# ---------------------------------------------------------------------------
def test_generic_detection_lands_in_the_users_own_category(db_session):
    """
    The real personalization for bank feeds. Swiggy is detected generically as
    "Food & Dining", but this user's history calls it "Food" — the entry must
    join that category rather than forking a near-duplicate.
    """
    user = make_user(db_session)
    save_profile(db_session, user.id, vocabulary=SUNNY_VOCABULARY)

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="POS 4375XXXX1234 SWIGGY BANGALORE",
        merchant="", amount=450.0, type=TransactionType.expense, db=db_session,
    )

    category = db_session.query(Category).filter(Category.id == result["category_id"]).first()
    assert category.name == "Food"
    assert db_session.query(Category).filter(
        Category.owner_id == user.id, Category.name == "Food & Dining"
    ).first() is None


def test_vocabulary_mapping_handles_prefix_names(db_session):
    """"Healthcare" (generic) -> "Health" (this user's name for it)."""
    user = make_user(db_session)
    save_profile(db_session, user.id, vocabulary=SUNNY_VOCABULARY)

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="APOLLO PHARMACY SEC18", merchant="",
        amount=340.0, type=TransactionType.expense, db=db_session,
    )

    category = db_session.query(Category).filter(Category.id == result["category_id"]).first()
    assert category.name == "Health"


def test_unmatched_concept_keeps_the_generic_name(db_session):
    """No equivalent in the user's vocabulary means no forced mapping."""
    user = make_user(db_session)
    save_profile(db_session, user.id, vocabulary=SUNNY_VOCABULARY)

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="NETFLIX SUBSCRIPTION", merchant="",
        amount=649.0, type=TransactionType.expense, db=db_session,
    )

    category = db_session.query(Category).filter(Category.id == result["category_id"]).first()
    assert category.name == "Entertainment"


def test_ride_narration_does_not_guess_a_specific_personal_category(db_session):
    """
    An Uber narration cannot tell you whether this was "cab to flat" or
    "cab to home" — in the user's own history that split is 71/30. It must land
    in the broad category, never guess one of the specific ones.
    """
    user = make_user(db_session)
    save_profile(
        db_session, user.id,
        rules=[note_rule("cab to flat", "Relationship", frequency=116)],
        vocabulary=SUNNY_VOCABULARY,
    )

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="UPI-UBERINDIASYSTEMS-UBER@AXISBANK-412",
        merchant="", amount=180.0, type=TransactionType.expense, db=db_session,
    )

    category = db_session.query(Category).filter(Category.id == result["category_id"]).first()
    assert category.name == "Transportation"
    assert result["method"] == "keyword"


def test_explicit_user_rule_still_outranks_learned_profile(db_session):
    """Profile rules are learned; a rule the user typed by hand must win."""
    user = make_user(db_session)
    save_profile(db_session, user.id, rules=[
        note_rule("lic policy premium", "Insurance", frequency=50),
    ])

    manual_category = Category(
        id=f"cat-{uuid4().hex}", name="Manual Override", type="expense", owner_id=user.id
    )
    db_session.add(manual_category)
    db_session.flush()

    from models import CategorizationRule
    db_session.add(CategorizationRule(
        id=f"rule-{uuid4().hex}", pattern="lic policy premium", category_id=manual_category.id,
        priority=10, owner_id=user.id, is_regex=False,
    ))
    db_session.commit()

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="NEFT-LIC POLICY PREMIUM", merchant="",
        amount=7788.0, type=TransactionType.expense, db=db_session,
    )

    assert result["method"] == "pattern_match"
    assert result["category_id"] == manual_category.id


def test_no_profile_falls_back_to_generic_rules(db_session):
    """Users without a profile must be unaffected."""
    user = make_user(db_session)

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="SWIGGY ORDER 8821", merchant="",
        amount=450.0, type=TransactionType.expense, db=db_session,
    )

    assert result["method"] == "keyword"
    category = db_session.query(Category).filter(Category.id == result["category_id"]).first()
    assert category.name == "Food & Dining"


# ---------------------------------------------------------------------------
# Ingestion routes
# ---------------------------------------------------------------------------
def test_account_aggregator_rows_get_personal_categories(db_session):
    """AA rows used to land completely uncategorized."""
    user = make_user(db_session)
    save_profile(db_session, user.id, vocabulary=SUNNY_VOCABULARY)

    fi_account = AAFiAccount(
        fi_type="DEPOSIT",
        fip_name="HDFC Bank",
        masked_account_number="XXXXXX4321",
        account_sub_type="SAVINGS",
        current_balance=5000.0,
        transactions=[
            AAFiTransaction(
                amount=450.0,
                txn_type="DEBIT",
                narration="POS 4375XXXX1234 SWIGGY BANGALORE",
                value_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            )
        ],
    )

    summary = AAMapper(db_session, user.id).materialize([fi_account])
    db_session.commit()

    assert summary["transactions_imported"] == 1
    tx = db_session.query(Transaction).filter(Transaction.owner_id == user.id).one()
    assert tx.category_id is not None
    category = db_session.query(Category).filter(Category.id == tx.category_id).first()
    assert category.name == "Food"


def test_account_aggregator_leaves_unknown_rows_uncategorized(db_session):
    """Below the auto-assign bar, an AA row must stay uncategorized for review."""
    user = make_user(db_session)
    save_profile(db_session, user.id, vocabulary=SUNNY_VOCABULARY)

    fi_account = AAFiAccount(
        fi_type="DEPOSIT", fip_name="HDFC Bank", masked_account_number="XXXXXX4321",
        account_sub_type="SAVINGS", current_balance=5000.0,
        transactions=[
            AAFiTransaction(
                amount=2400.0, txn_type="DEBIT",
                narration="UPI/P2M/412345678901/QR9982211",
                value_date=datetime(2026, 1, 11, tzinfo=timezone.utc),
            )
        ],
    )

    AAMapper(db_session, user.id).materialize([fi_account])
    db_session.commit()

    tx = db_session.query(Transaction).filter(Transaction.owner_id == user.id).one()
    assert tx.category_id is None
    assert tx.categorization_method == "account_aggregator"


def test_transaction_service_applies_profile_on_create(db_session):
    user = make_user(db_session)
    account = make_account(db_session, user.id)
    save_profile(db_session, user.id, vocabulary=SUNNY_VOCABULARY)

    tx = TransactionService(db_session).create_transaction(
        TransactionCreate(
            id=f"tx-{uuid4().hex}",
            amount=450.0,
            type=TransactionType.expense,
            description="POS 4375XXXX1234 SWIGGY BANGALORE",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            timestamp=1767000000000,
            account_id=account.id,
        ),
        user.id,
    )

    category = db_session.query(Category).filter(Category.id == tx.category_id).first()
    assert category.name == "Food"


# ---------------------------------------------------------------------------
# Bootstrapping + learning
# ---------------------------------------------------------------------------
def test_generate_from_history_learns_dominant_mapping(db_session):
    user = make_user(db_session)
    account = make_account(db_session, user.id)
    category = Category(
        id=f"cat-{uuid4().hex}", name="Sukoon", type="expense", owner_id=user.id
    )
    db_session.add(category)
    db_session.flush()

    for i in range(5):
        db_session.add(Transaction(
            id=f"tx-{uuid4().hex}", amount=36.0, type="expense", description="Snacks",
            date=datetime(2026, 1, 10, tzinfo=timezone.utc), owner_id=user.id,
            account_id=account.id, category_id=category.id,
        ))
    db_session.commit()

    config = ImportProfileService(db_session, user.id).generate_from_history()

    rules = {r["pattern"]: r for r in config["note_rules"]}
    assert rules["snacks"]["category"] == "Sukoon"
    assert rules["snacks"]["frequency"] == 5
    assert rules["snacks"]["type"] == "expense"


def test_manual_recategorization_teaches_future_entries(db_session):
    """
    Correcting one entry must change how the NEXT auto entry is categorized.
    This is the feedback loop that keeps auto entries looking like the user's.
    """
    user = make_user(db_session)
    account = make_account(db_session, user.id)
    service = TransactionService(db_session)

    chaap = Category(id=f"cat-{uuid4().hex}", name="Chaap", type="expense", owner_id=user.id)
    db_session.add(chaap)
    db_session.commit()

    tx = service.create_transaction(
        TransactionCreate(
            id=f"tx-{uuid4().hex}", amount=60.0, type=TransactionType.expense,
            description="MOJO CHAAP CORNER", date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            timestamp=1767000000000, account_id=account.id,
        ),
        user.id,
    )

    from schemas import TransactionUpdate
    service.update_transaction(tx.id, TransactionUpdate(category_id=chaap.id), user.id)

    profile = db_session.query(UserImportProfile).filter(
        UserImportProfile.user_id == user.id
    ).first()
    assert profile is not None
    patterns = {r["pattern"]: r["category"] for r in profile.config["note_rules"]}
    assert patterns.get("mojo chaap corner") == "Chaap"

    # A later entry with the same narration now categorizes itself.
    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="MOJO CHAAP CORNER", merchant="",
        amount=60.0, type=TransactionType.expense, db=db_session,
    )
    assert result["category_id"] == chaap.id
    assert result["method"] == "import_profile"


def test_explicit_category_alias_overrides_the_heuristic(db_session):
    """
    "Groceries" has no token overlap with "Household", so the heuristic leaves it
    alone. The user can state the equivalence themselves and it must be honoured.
    """
    user = make_user(db_session)
    svc = ImportProfileService(db_session, user.id)
    svc.save_profile({
        "version": 1,
        "note_rules": [],
        "account_mappings": {},
        "category_mappings": {"Groceries": "Household"},
        "category_vocabulary": SUNNY_VOCABULARY,
        "skip_categories": [],
        "skip_notes": [],
    })

    result = SmartCategorizationService().categorize_transaction(
        user_id=user.id, description="BIGBASKET ORDER 7781", merchant="",
        amount=1200.0, type=TransactionType.expense, db=db_session,
    )

    category = db_session.query(Category).filter(Category.id == result["category_id"]).first()
    assert category.name == "Household"
