from datetime import datetime, timezone
from pathlib import Path

from models import Account, Category, EmailReportPreference, Transaction, TransactionType
from services.report_service import ReportService
from user_models import User


def _seed_report_data(db_session):
    user = User(id="report-user", email="report@example.com", hashed_password="hashed")
    account = Account(id="report-account", name="Checking", type="checking", currency="USD", balance=1000.0, owner_id=user.id)
    category = Category(id="report-category", name="Food", type="expense", color="#ef4444", owner_id=user.id)
    db_session.add_all([user, account, category])
    db_session.flush()

    transactions = [
        Transaction(
            id="report-income",
            amount=3000.0,
            type=TransactionType.income,
            description="Salary",
            date=datetime(2025, 1, 5, tzinfo=timezone.utc),
            timestamp=1,
            owner_id=user.id,
            account_id=account.id,
        ),
        Transaction(
            id="report-expense",
            amount=250.0,
            type=TransactionType.expense,
            description="Groceries",
            date=datetime(2025, 1, 10, tzinfo=timezone.utc),
            timestamp=2,
            owner_id=user.id,
            account_id=account.id,
            category_id=category.id,
        ),
    ]
    db_session.add_all(transactions)
    db_session.commit()
    return user


def test_generate_monthly_summary_returns_totals(db_session):
    user = _seed_report_data(db_session)
    service = ReportService(db_session)

    report = service.generate_monthly_summary(user.id, 2025, 1)

    assert report["total_income"] == 3000.0
    assert report["total_expenses"] == 250.0
    assert report["savings"] == 2750.0
    assert report["transaction_count"] == 2
    assert report["top_categories"][0]["category"] == "Food"


def test_schedule_email_report_upserts_preference(db_session):
    user = _seed_report_data(db_session)
    service = ReportService(db_session)

    preference = service.schedule_email_report(user.id, "monthly_summary", "monthly")
    updated = service.schedule_email_report(user.id, "monthly_summary", "weekly")

    assert preference.user_id == user.id
    assert updated.frequency == "weekly"
    assert db_session.query(EmailReportPreference).count() == 1


def test_create_and_generate_report_job_updates_status_and_file(db_session):
    user = _seed_report_data(db_session)
    service = ReportService(db_session)

    job = service.create_report_job(
        user_id=user.id,
        report_type="monthly_summary",
        period_start=datetime(2025, 1, 1, tzinfo=timezone.utc).date(),
        period_end=datetime(2025, 1, 31, tzinfo=timezone.utc).date(),
        output_format="pdf",
    )

    assert job.status == "pending"

    completed_job = service.generate_report_job(job.id)
    assert completed_job.status == "completed"
    assert completed_job.file_path is not None
    Path(completed_job.file_path).unlink(missing_ok=True)
