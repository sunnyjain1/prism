"""
Unit tests for the AA service metadata and the FI-data mapper.

The full consent/fetch lifecycle (HTTP + DB-backed consent) is covered in
tests/test_account_aggregator_api.py. Here we cover the pure pieces: the supported
FI-type catalogue and the mapper's materialization (balance semantics + dedup).
"""
from datetime import datetime, timezone

import pytest

from models import Account, AggregatedAsset, Loan, Transaction
from services.aa.base import AAFiAccount, AAFiTransaction
from services.aa.mapper import AAMapper
from user_models import User


def _make_user(db_session) -> str:
    user = User(email="mapper@test.com", hashed_password="x", full_name="Mapper")
    db_session.add(user)
    db_session.commit()
    return user.id


def test_get_fi_types_lists_supported_scope():
    from services.account_aggregator_service import AccountAggregatorService

    # Instantiated without touching the network — get_aa_client builds a client lazily.
    types = AccountAggregatorService.get_supported_fi_types(object.__new__(AccountAggregatorService))
    codes = {t["type"] for t in types}
    assert codes == {"DEPOSIT", "TERM_DEPOSIT", "CREDIT_CARD", "LOAN"}


def test_mapper_materializes_deposit_credit_fd_and_loan(db_session):
    user_id = _make_user(db_session)
    fi_accounts = [
        AAFiAccount(
            fi_type="DEPOSIT",
            fip_name="HDFC Bank",
            masked_account_number="XXXX1234",
            account_sub_type="SAVINGS",
            current_balance=100000.0,
            transactions=[
                AAFiTransaction(2000.0, "DEBIT", "Groceries", datetime(2026, 6, 1, tzinfo=timezone.utc)),
            ],
        ),
        AAFiAccount(
            fi_type="CREDIT_CARD",
            fip_name="Axis Bank",
            masked_account_number="XXXX5678",
            principal=8000.0,
            credit_limit=50000.0,
        ),
        AAFiAccount(
            fi_type="TERM_DEPOSIT",
            fip_name="SBI",
            masked_account_number="FD0001",
            current_balance=200000.0,
            maturity_value=215000.0,
        ),
        AAFiAccount(
            fi_type="LOAN",
            fip_name="HDFC Bank",
            masked_account_number="LN0009",
            account_sub_type="HOME_LOAN",
            principal=2500000.0,
            emi_amount=24000.0,
            interest_rate=8.5,
        ),
    ]

    summary = AAMapper(db_session, user_id).materialize(fi_accounts)

    assert summary["accounts_created"] == 2          # deposit + credit card
    assert summary["assets_created"] == 1            # FD
    assert summary["loans_created"] == 1
    assert summary["transactions_imported"] == 1

    accounts = {a.type: a for a in db_session.query(Account).filter(Account.owner_id == user_id)}
    assert accounts["savings"].balance == 100000.0   # asset: positive = money in
    assert accounts["credit"].balance == 8000.0      # liability: positive = owed
    assert accounts["credit"].credit_limit == 50000.0

    fd = db_session.query(AggregatedAsset).filter(AggregatedAsset.user_id == user_id).one()
    assert fd.asset_type == "fd"
    assert fd.current_value == 215000.0

    loan = db_session.query(Loan).filter(Loan.user_id == user_id).one()
    assert loan.loan_type == "home"
    assert loan.outstanding_amount == 2500000.0
    assert loan.emi_amount == 24000.0


def test_mapper_is_idempotent_on_rerun(db_session):
    user_id = _make_user(db_session)
    fi_accounts = [
        AAFiAccount(
            fi_type="DEPOSIT",
            fip_name="HDFC Bank",
            masked_account_number="XXXX1234",
            account_sub_type="SAVINGS",
            current_balance=100000.0,
            transactions=[
                AAFiTransaction(2000.0, "DEBIT", "Groceries", datetime(2026, 6, 1, tzinfo=timezone.utc)),
            ],
        ),
    ]
    AAMapper(db_session, user_id).materialize(fi_accounts)
    # Balance changes on the next sync; transaction is unchanged.
    fi_accounts[0].current_balance = 95000.0
    summary = AAMapper(db_session, user_id).materialize(fi_accounts)

    assert summary["accounts_created"] == 0
    assert summary["accounts_updated"] == 1
    assert summary["transactions_imported"] == 0
    account = db_session.query(Account).filter(Account.owner_id == user_id).one()
    assert account.balance == 95000.0
    assert db_session.query(Transaction).filter(Transaction.owner_id == user_id).count() == 1
