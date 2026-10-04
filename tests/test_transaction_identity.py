"""
One real payment reaches Prism from several sources (typed in, SMS, Gmail statement).
These tests pin down that it is recorded exactly once — and that genuinely separate
payments that merely look alike are never merged.
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from models import Account, AccountSyncConfig, SMSTransaction, Transaction
from schemas import TransactionCreate, TransactionType
from services.importers.base_importer import ImportResult
from services.sms_transaction_service import SMSTransactionService
from services.sync_orchestrator import SyncOrchestrator
from services.transaction_identity import (
    IncomingTransaction,
    TransactionMatcher,
    extract_bank_reference,
)
from user_models import User

DAY = datetime(2024, 12, 2, 10, 0)


# ── Reference extraction ────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    # Narrations as they appear in HDFC statements pulled from Gmail
    ("UPI-334418094573-NA", "334418094573"),
    ("UPI-408359 191720-UPI", "408359191720"),          # PDF cell wrapped mid-number
    ("UPI-429301467239-429301467239-5020 00213", "429301467239"),
    ("UPI/412853401207/PAYTM/merchant", "412853401207"),
    ("IMPS-412345678901-SOME BANK", "412345678901"),
    ("NEFT CR-HDFCN52024010112345-MLL EXPRESS", "HDFCN52024010112345"),
    # SMS / alert e-mail wording
    ("Rs.500 debited from a/c **1234 to VPA x@ybl. UPI Ref No 412345678901.", "412345678901"),
    ("Your a/c is credited. UTR: SBIN42024123100123", "SBIN42024123100123"),
    # No reference — must not invent one from names, masks or phone numbers
    ("UPI - XXXXXX7791", None),
    ("NEFT - MLL EXPRESS SERVICESPRIVATE LIMIT", None),
    ("Paid 9876543210 for groceries", None),
    ("Salary from Mll", None),
    ("", None),
    (None, None),
])
def test_extract_bank_reference(text, expected):
    assert extract_bank_reference(text) == expected


# ── Fixtures ────────────────────────────────────────────────────────────────

def make_user(db_session) -> User:
    user = User(id=f"user-{uuid4().hex}", email=f"ident-{uuid4().hex}@example.com",
                hashed_password="x", full_name="Identity Tester")
    db_session.add(user)
    db_session.commit()
    return user


def make_account(db_session, user_id: str, name: str = "HDFC", balance: float = 0.0) -> Account:
    account = Account(id=f"acct-{uuid4().hex}", name=name, type="savings", currency="INR",
                      balance=balance, owner_id=user_id, is_deleted=False)
    db_session.add(account)
    db_session.commit()
    return account


def add_tx(db_session, user_id, account_id, amount, tx_type="expense", when=DAY,
           description="Manual entry", ref=None) -> Transaction:
    tx = Transaction(id=str(uuid4()), owner_id=user_id, account_id=account_id, amount=amount,
                     type=tx_type, description=description, date=when,
                     timestamp=int(when.timestamp()), external_ref=ref)
    db_session.add(tx)
    db_session.commit()
    return tx


def incoming(amount, tx_type="expense", when=DAY, account_id=None, ref=None):
    return IncomingTransaction(amount=amount, type=tx_type, date=when,
                               account_id=account_id, reference=ref)


# ── Matcher ─────────────────────────────────────────────────────────────────

def test_statement_row_matches_the_users_own_entry_and_learns_its_reference(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    manual = add_tx(db_session, user.id, hdfc.id, 419068.0, "income", description="Salary from Mll")

    [result] = TransactionMatcher(db_session, user.id).match(
        [incoming(419068.0, "income", account_id=hdfc.id, ref="HDFCN52024120212345")])

    assert result.existing.id == manual.id
    assert result.reason == "amount_date"
    assert result.reference_to_attach == "HDFCN52024120212345"


def test_same_reference_matches_even_outside_the_date_window(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    seen = add_tx(db_session, user.id, hdfc.id, 75000.0, ref="414012345678")

    [result] = TransactionMatcher(db_session, user.id).match(
        [incoming(75000.0, when=DAY + timedelta(days=9), account_id=hdfc.id, ref="414012345678")])

    assert result.existing.id == seen.id and result.reason == "reference"


def test_different_references_are_different_payments(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    add_tx(db_session, user.id, hdfc.id, 600.0, ref="458080135017")

    [result] = TransactionMatcher(db_session, user.id).match(
        [incoming(600.0, account_id=hdfc.id, ref="424807783222")])

    assert not result.is_duplicate


def test_repeated_identical_payments_are_matched_one_to_one(db_session):
    """Two ₹20 snacks on one day: one typed in, both on the statement → import one."""
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    add_tx(db_session, user.id, hdfc.id, 20.0, description="Snacks")

    results = TransactionMatcher(db_session, user.id).match(
        [incoming(20.0, account_id=hdfc.id), incoming(20.0, account_id=hdfc.id)])

    assert [r.is_duplicate for r in results] == [True, False]


def test_other_account_direction_or_date_is_not_a_match(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    card = make_account(db_session, user.id, name="HDFC Card")
    add_tx(db_session, user.id, hdfc.id, 3000.0)

    results = TransactionMatcher(db_session, user.id).match([
        incoming(3000.0, account_id=card.id),                       # other account
        incoming(3000.0, "income", account_id=hdfc.id),             # other direction
        incoming(3000.0, when=DAY + timedelta(days=5), account_id=hdfc.id),  # too far apart
    ])

    assert not any(r.is_duplicate for r in results)


def test_reference_match_is_not_stolen_by_a_heuristic_match(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    referenced = add_tx(db_session, user.id, hdfc.id, 500.0, ref="401258176504")

    no_ref, with_ref = TransactionMatcher(db_session, user.id).match(
        [incoming(500.0, account_id=hdfc.id), incoming(500.0, account_id=hdfc.id, ref="401258176504")])

    assert with_ref.existing.id == referenced.id
    assert not no_ref.is_duplicate


# ── Gmail statement import ──────────────────────────────────────────────────

class StubImporter:
    name = "stub"

    def __init__(self, rows):
        self.rows = rows

    def parse(self, content, filename, password=None):
        result = ImportResult()
        result.transactions = [
            TransactionCreate(id=str(uuid4()), amount=amount, type=TransactionType(tx_type),
                              description=description, date=when, timestamp=int(when.timestamp()))
            for amount, tx_type, description, when in self.rows
        ]
        return result


def run_statement(db_session, user, account, rows):
    orchestrator = SyncOrchestrator(db_session)
    orchestrator.bulk_service.importers["stub"] = StubImporter(rows)
    config = AccountSyncConfig(id=str(uuid4()), account_id=account.id, owner_id=user.id,
                               gmail_search_query="x", importer_key="stub")
    imported, skipped, _, errors = orchestrator._import_attachment(config, "s.pdf", b"", None)
    assert errors == 0
    return imported, skipped


def test_gmail_statement_skips_what_the_user_typed_in(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id, balance=1000.0)
    manual = add_tx(db_session, user.id, hdfc.id, 27000.0, description="Rent")
    statement = [
        (27000.0, "expense", "UPI-333980400819-UPI", DAY),          # already typed in as "Rent"
        (140.0, "expense", "UPI-334418094573-NA", DAY),             # new
    ]

    assert run_statement(db_session, user, hdfc, statement) == (1, 1)

    db_session.refresh(manual)
    assert manual.description == "Rent" and manual.external_ref == "333980400819"
    imported = db_session.query(Transaction).filter_by(owner_id=user.id, amount=140.0).one()
    assert (imported.source, imported.external_ref) == ("email", "334418094573")

    # Pulling the same statement again adds nothing.
    assert run_statement(db_session, user, hdfc, statement) == (0, 2)


# ── SMS ─────────────────────────────────────────────────────────────────────

HDFC_SMS = ("Rs.140.00 debited from a/c **1234 on 02-12-24 to VPA cafe@ybl. "
            "UPI Ref No 334418094573. Not you? Call 18002586161")


def test_sms_for_an_already_recorded_payment_is_not_a_draft(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id)
    manual = add_tx(db_session, user.id, hdfc.id, 140.0, description="Breakfast")

    summary = SMSTransactionService(db_session).ingest_batch(
        user.id, [{"sender": "HDFCBK", "body": HDFC_SMS, "timestamp": DAY.isoformat()}])

    assert summary["already_recorded"] == 1 and summary["ingested"] == 0
    sms = db_session.query(SMSTransaction).filter_by(user_id=user.id).one()
    assert (sms.status, sms.confirmed_transaction_id) == ("duplicate", manual.id)
    db_session.refresh(manual)
    assert manual.external_ref == "334418094573"


def test_confirmed_sms_is_recorded_once_and_the_statement_then_skips_it(db_session):
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id, balance=1000.0)
    service = SMSTransactionService(db_session)
    service.ingest_batch(user.id, [{"sender": "HDFCBK", "body": HDFC_SMS, "timestamp": DAY.isoformat()}])
    draft = db_session.query(SMSTransaction).filter_by(user_id=user.id, status="draft").one()

    tx = service.confirm_draft(user.id, draft.id, override_account_id=hdfc.id)

    assert (tx.source, tx.external_ref, tx.amount) == ("sms", "334418094573", 140.0)
    db_session.refresh(hdfc)
    assert hdfc.balance == 860.0  # confirmed SMS now moves the balance like any entry

    imported, skipped = run_statement(
        db_session, user, hdfc, [(140.0, "expense", "UPI-334418094573-NA", DAY)])
    assert (imported, skipped) == (0, 1)


def test_sms_with_ambiguous_account_still_finds_the_recorded_payment(db_session):
    """User has "HDFC" and "Papa HDFC": don't guess the account, but still dedupe."""
    user = make_user(db_session)
    hdfc = make_account(db_session, user.id, name="HDFC")
    make_account(db_session, user.id, name="Papa HDFC")
    manual = add_tx(db_session, user.id, hdfc.id, 140.0, description="Breakfast")

    summary = SMSTransactionService(db_session).ingest_batch(
        user.id, [{"sender": "HDFCBK", "body": HDFC_SMS, "timestamp": DAY.isoformat()}])

    assert summary["already_recorded"] == 1
    sms = db_session.query(SMSTransaction).filter_by(user_id=user.id).one()
    assert sms.matched_account_id is None and sms.confirmed_transaction_id == manual.id
