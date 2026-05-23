from datetime import date

import pytest

from schemas import LoanCreate
from services.loan_service import LoanService
from user_models import User


@pytest.fixture
def loan_service(db_session):
    return LoanService(db_session)


@pytest.fixture
def setup_loan_user(db_session):
    user = User(id="loan-user", email="loan@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.commit()
    return user


def test_calculate_amortization_splits_principal_and_interest(loan_service):
    schedule = loan_service.calculate_amortization(120000, 12, 12)

    assert len(schedule) == 12
    assert schedule[0]["interest_component"] == pytest.approx(1200.0, rel=1e-3)
    assert schedule[0]["principal_component"] == pytest.approx(9461.86, rel=1e-3)
    assert schedule[-1]["outstanding_balance"] == 0.0


def test_create_loan_summary_and_upcoming_emis(loan_service, setup_loan_user):
    today = date.today()
    created = loan_service.create_loan(
        setup_loan_user.id,
        LoanCreate(
            name="Home Loan - SBI",
            loan_type="home",
            principal_amount=120000.0,
            interest_rate=8.5,
            tenure_months=24,
            start_date=today,
            emi_day=today.day,
            lender="SBI",
        ),
    )

    assert created["emi_amount"] == pytest.approx(5456.25, rel=1e-3)
    assert created["outstanding_amount"] == 120000.0
    assert created["next_due_date"] == today
    assert created["remaining_tenure_months"] >= 1

    summary = loan_service.get_loan_summary(setup_loan_user.id)
    upcoming = loan_service.get_upcoming_emis(setup_loan_user.id, days=30)

    assert summary["active_count"] == 1
    assert summary["total_outstanding"] == 120000.0
    assert summary["monthly_emi_burden"] == pytest.approx(5456.25, rel=1e-3)
    assert len(upcoming) == 1
    assert upcoming[0]["name"] == "Home Loan - SBI"


def test_record_emi_payment_can_close_zero_interest_loan(loan_service, setup_loan_user):
    created = loan_service.create_loan(
        setup_loan_user.id,
        {
            "name": "Phone Loan",
            "loan_type": "personal",
            "principal_amount": 1000.0,
            "outstanding_amount": 1000.0,
            "interest_rate": 0.0,
            "tenure_months": 1,
            "start_date": date.today(),
        },
    )

    payment = loan_service.record_emi_payment(setup_loan_user.id, created["id"], 1000.0, date.today())

    assert payment["principal_component"] == 1000.0
    assert payment["interest_component"] == 0.0
    assert payment["outstanding_amount"] == 0.0
    assert payment["is_closed"] is True

    summary = loan_service.get_loan_summary(setup_loan_user.id)
    assert summary["active_count"] == 0
