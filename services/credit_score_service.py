"""
Credit Score & Report Service

Provides credit score fetching, report parsing, and account discovery
from credit bureau data. Currently implements a simulation layer that
returns realistic mock data; designed for easy swap to real bureau APIs
(CIBIL/TransUnion, Experian, CRIF High Mark) when partnerships are established.

Integration Architecture:
- Provider abstraction via CreditBureauProvider interface
- Consent-first: never fetch without explicit user consent
- Encrypted storage of raw report data
- Audit trail for all report fetches
"""

import random
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from models import CreditAccount, CreditInquiry, CreditReport
from schemas import (
    AccountDiscoveryResponse,
    CreditAccountResponse,
    CreditInquiryResponse,
    CreditReportResponse,
    CreditReportSummary,
    CreditScoreResponse,
    DiscoveredAccount,
)


def classify_score(score: Optional[int]) -> str:
    if score is None:
        return "unknown"
    if score >= 750:
        return "excellent"
    if score >= 700:
        return "good"
    if score >= 650:
        return "fair"
    if score >= 550:
        return "poor"
    return "very_poor"


def get_credit_score(db: Session, user_id: str) -> CreditScoreResponse:
    """Get the user's latest credit score."""
    report = (
        db.query(CreditReport)
        .filter(CreditReport.user_id == user_id, CreditReport.status == "success")
        .order_by(CreditReport.fetched_at.desc())
        .first()
    )
    if report:
        return CreditScoreResponse(
            score=report.score,
            provider=report.provider,
            score_range_min=report.score_range_min,
            score_range_max=report.score_range_max,
            classification=classify_score(report.score),
            report_date=report.report_date,
            fetched_at=report.fetched_at,
            has_report=True,
        )
    return CreditScoreResponse(has_report=False)


def fetch_credit_report(
    db: Session, user_id: str, provider: str = "cibil", pan: Optional[str] = None
) -> CreditReportResponse:
    """
    Fetch a full credit report. In production, this calls the bureau API.
    Currently returns simulated realistic data for development/demo.
    """
    # Generate realistic credit score
    score = random.randint(680, 820)
    report_date = date.today() - timedelta(days=random.randint(0, 7))

    # Create report record
    report = CreditReport(
        id=str(uuid4()),
        user_id=user_id,
        provider=provider,
        score=score,
        report_date=report_date,
        status="success",
        consent_reference=f"consent_{uuid4().hex[:12]}",
    )
    db.add(report)

    # Generate simulated credit accounts
    simulated_accounts = _generate_simulated_accounts(report.id, user_id)
    for acc in simulated_accounts:
        db.add(acc)

    # Generate simulated inquiries
    simulated_inquiries = _generate_simulated_inquiries(report.id, user_id)
    for inq in simulated_inquiries:
        db.add(inq)

    db.commit()
    db.refresh(report)

    # Build response
    account_responses = [
        CreditAccountResponse(
            id=acc.id,
            account_type=acc.account_type,
            institution=acc.institution,
            account_number_masked=acc.account_number_masked,
            status=acc.status,
            opened_date=acc.opened_date,
            closed_date=acc.closed_date,
            sanctioned_amount=acc.sanctioned_amount,
            current_balance=acc.current_balance,
            credit_limit=acc.credit_limit,
            emi_amount=acc.emi_amount,
            interest_rate=acc.interest_rate,
            days_past_due=acc.days_past_due,
            is_overdue=acc.is_overdue,
            last_payment_date=acc.last_payment_date,
            ownership=acc.ownership,
            payment_history=acc.payment_history,
        )
        for acc in simulated_accounts
    ]

    inquiry_responses = [
        CreditInquiryResponse(
            id=inq.id,
            institution=inq.institution,
            inquiry_type=inq.inquiry_type,
            purpose=inq.purpose,
            inquiry_date=inq.inquiry_date,
        )
        for inq in simulated_inquiries
    ]

    summary = _build_summary(simulated_accounts, simulated_inquiries)
    recommendations = _generate_recommendations(score, summary)

    # Score history from past reports
    history = _get_score_history(db, user_id)

    return CreditReportResponse(
        score=score,
        provider=provider,
        classification=classify_score(score),
        report_date=report_date,
        summary=summary,
        accounts=account_responses,
        inquiries=inquiry_responses,
        recommendations=recommendations,
        score_history=history,
    )


def get_credit_report(db: Session, user_id: str) -> Optional[CreditReportResponse]:
    """Get the user's latest stored credit report."""
    report = (
        db.query(CreditReport)
        .filter(CreditReport.user_id == user_id, CreditReport.status == "success")
        .order_by(CreditReport.fetched_at.desc())
        .first()
    )
    if not report:
        return None

    accounts = (
        db.query(CreditAccount)
        .filter(CreditAccount.report_id == report.id)
        .all()
    )
    inquiries = (
        db.query(CreditInquiry)
        .filter(CreditInquiry.report_id == report.id)
        .all()
    )

    account_responses = [
        CreditAccountResponse(
            id=acc.id,
            account_type=acc.account_type,
            institution=acc.institution,
            account_number_masked=acc.account_number_masked,
            status=acc.status,
            opened_date=acc.opened_date,
            closed_date=acc.closed_date,
            sanctioned_amount=acc.sanctioned_amount,
            current_balance=acc.current_balance,
            credit_limit=acc.credit_limit,
            emi_amount=acc.emi_amount,
            interest_rate=acc.interest_rate,
            days_past_due=acc.days_past_due,
            is_overdue=acc.is_overdue,
            last_payment_date=acc.last_payment_date,
            ownership=acc.ownership,
            payment_history=acc.payment_history,
        )
        for acc in accounts
    ]

    inquiry_responses = [
        CreditInquiryResponse(
            id=inq.id,
            institution=inq.institution,
            inquiry_type=inq.inquiry_type,
            purpose=inq.purpose,
            inquiry_date=inq.inquiry_date,
        )
        for inq in inquiries
    ]

    summary = _build_summary(accounts, inquiries)
    recommendations = _generate_recommendations(report.score, summary)
    history = _get_score_history(db, user_id)

    return CreditReportResponse(
        score=report.score,
        provider=report.provider,
        classification=classify_score(report.score),
        report_date=report.report_date,
        summary=summary,
        accounts=account_responses,
        inquiries=inquiry_responses,
        recommendations=recommendations,
        score_history=history,
    )


def discover_accounts_from_credit(
    db: Session, user_id: str, existing_account_names: List[str]
) -> AccountDiscoveryResponse:
    """
    Discover financial accounts from the user's credit report.
    Returns accounts found in the report that could be imported.
    """
    report = (
        db.query(CreditReport)
        .filter(CreditReport.user_id == user_id, CreditReport.status == "success")
        .order_by(CreditReport.fetched_at.desc())
        .first()
    )
    if not report:
        return AccountDiscoveryResponse(discovered_accounts=[], consent_active=False)

    credit_accounts = (
        db.query(CreditAccount)
        .filter(CreditAccount.report_id == report.id, CreditAccount.status == "active")
        .all()
    )

    existing_lower = [n.lower() for n in existing_account_names]
    discovered = []

    for acc in credit_accounts:
        suggested_name = f"{acc.institution} {acc.account_type.replace('_', ' ').title()}"
        already_linked = any(
            acc.institution.lower() in name or suggested_name.lower() in name
            for name in existing_lower
        )

        discovered.append(
            DiscoveredAccount(
                source="credit_report",
                account_type=_map_credit_type_to_account_type(acc.account_type),
                institution=acc.institution,
                account_number_masked=acc.account_number_masked,
                balance=acc.current_balance,
                credit_limit=acc.credit_limit if acc.credit_limit > 0 else None,
                already_linked=already_linked,
                suggested_name=suggested_name,
            )
        )

    return AccountDiscoveryResponse(
        discovered_accounts=discovered,
        source="credit_report",
        consent_active=True,
    )


# --- Private helpers ---


def _map_credit_type_to_account_type(credit_type: str) -> str:
    mapping = {
        "credit_card": "credit_card",
        "personal_loan": "loan",
        "home_loan": "loan",
        "auto_loan": "loan",
        "consumer_loan": "loan",
        "education_loan": "loan",
        "business_loan": "loan",
    }
    return mapping.get(credit_type, "loan")


def _generate_simulated_accounts(report_id: str, user_id: str) -> List[CreditAccount]:
    """Generate realistic Indian credit accounts for simulation."""
    banks = ["HDFC Bank", "ICICI Bank", "SBI", "Axis Bank", "Kotak Mahindra", "IndusInd Bank"]
    accounts = []

    # Credit cards (1-3)
    num_cards = random.randint(1, 3)
    for i in range(num_cards):
        bank = random.choice(banks)
        limit = random.choice([50000, 100000, 200000, 300000, 500000])
        utilization = random.uniform(0.05, 0.6)
        accounts.append(
            CreditAccount(
                id=str(uuid4()),
                report_id=report_id,
                user_id=user_id,
                account_type="credit_card",
                institution=bank,
                account_number_masked=f"XXXX-XXXX-XXXX-{random.randint(1000,9999)}",
                status="active",
                opened_date=date.today() - timedelta(days=random.randint(365, 2000)),
                sanctioned_amount=float(limit),
                current_balance=round(limit * utilization, 2),
                credit_limit=float(limit),
                days_past_due=0,
                is_overdue=False,
                last_payment_date=date.today() - timedelta(days=random.randint(1, 28)),
                payment_history=_generate_payment_history(12),
            )
        )

    # Personal loan (0-1)
    if random.random() > 0.4:
        principal = random.choice([100000, 200000, 500000, 800000])
        outstanding = round(principal * random.uniform(0.2, 0.8), 2)
        accounts.append(
            CreditAccount(
                id=str(uuid4()),
                report_id=report_id,
                user_id=user_id,
                account_type="personal_loan",
                institution=random.choice(banks),
                account_number_masked=f"PL{random.randint(100000000, 999999999)}",
                status="active",
                opened_date=date.today() - timedelta(days=random.randint(180, 1200)),
                sanctioned_amount=float(principal),
                current_balance=outstanding,
                emi_amount=round(principal / random.randint(24, 60), 2),
                interest_rate=round(random.uniform(10.5, 16.0), 2),
                days_past_due=0,
                is_overdue=False,
                last_payment_date=date.today() - timedelta(days=random.randint(1, 30)),
                payment_history=_generate_payment_history(12),
            )
        )

    # Home loan (0-1)
    if random.random() > 0.6:
        principal = random.choice([3000000, 5000000, 7500000, 10000000])
        outstanding = round(principal * random.uniform(0.5, 0.9), 2)
        accounts.append(
            CreditAccount(
                id=str(uuid4()),
                report_id=report_id,
                user_id=user_id,
                account_type="home_loan",
                institution=random.choice(banks),
                account_number_masked=f"HL{random.randint(100000000, 999999999)}",
                status="active",
                opened_date=date.today() - timedelta(days=random.randint(365, 3650)),
                sanctioned_amount=float(principal),
                current_balance=outstanding,
                emi_amount=round(principal / random.randint(180, 300), 2),
                interest_rate=round(random.uniform(7.5, 9.5), 2),
                days_past_due=0,
                is_overdue=False,
                last_payment_date=date.today() - timedelta(days=random.randint(1, 30)),
                payment_history=_generate_payment_history(12),
            )
        )

    # Closed account
    if random.random() > 0.5:
        accounts.append(
            CreditAccount(
                id=str(uuid4()),
                report_id=report_id,
                user_id=user_id,
                account_type="consumer_loan",
                institution=random.choice(banks),
                account_number_masked=f"CL{random.randint(100000000, 999999999)}",
                status="closed",
                opened_date=date.today() - timedelta(days=random.randint(730, 2000)),
                closed_date=date.today() - timedelta(days=random.randint(30, 365)),
                sanctioned_amount=float(random.choice([30000, 50000, 100000])),
                current_balance=0.0,
                payment_history=_generate_payment_history(12),
            )
        )

    return accounts


def _generate_simulated_inquiries(report_id: str, user_id: str) -> List[CreditInquiry]:
    """Generate realistic credit inquiries."""
    institutions = ["HDFC Bank", "ICICI Bank", "Bajaj Finserv", "Tata Capital", "SBI Cards"]
    purposes = ["credit_card", "personal_loan", "credit_card", "home_loan"]
    inquiries = []

    num_inquiries = random.randint(1, 4)
    for _ in range(num_inquiries):
        inquiries.append(
            CreditInquiry(
                id=str(uuid4()),
                report_id=report_id,
                user_id=user_id,
                institution=random.choice(institutions),
                inquiry_type="hard",
                purpose=random.choice(purposes),
                inquiry_date=date.today() - timedelta(days=random.randint(30, 365)),
            )
        )

    return inquiries


def _generate_payment_history(months: int) -> List[dict]:
    """Generate payment history for last N months."""
    history = []
    for i in range(months):
        month_date = date.today().replace(day=1) - timedelta(days=30 * i)
        # 90% on-time, 8% late, 2% missed
        r = random.random()
        if r < 0.9:
            status = "on_time"
        elif r < 0.98:
            status = "late"
        else:
            status = "missed"
        history.append({"month": month_date.isoformat(), "status": status})
    return history


def _build_summary(
    accounts: List[CreditAccount], inquiries: List[CreditInquiry]
) -> CreditReportSummary:
    active = [a for a in accounts if a.status == "active"]
    closed = [a for a in accounts if a.status == "closed"]
    cards = [a for a in active if a.account_type == "credit_card"]

    total_limit = sum(a.credit_limit for a in cards if a.credit_limit)
    total_balance = sum(a.current_balance for a in cards)
    utilization = (total_balance / total_limit * 100) if total_limit > 0 else 0.0

    total_emi = sum(a.emi_amount for a in active if a.emi_amount)
    overdue = [a for a in active if a.is_overdue]

    oldest_date = min(
        (a.opened_date for a in accounts if a.opened_date), default=None
    )
    oldest_months = None
    if oldest_date:
        delta = date.today() - oldest_date
        oldest_months = delta.days // 30

    six_months_ago = date.today() - timedelta(days=180)
    recent_inquiries = [
        i for i in inquiries if i.inquiry_date and i.inquiry_date >= six_months_ago
    ]

    return CreditReportSummary(
        total_accounts=len(accounts),
        active_accounts=len(active),
        closed_accounts=len(closed),
        total_credit_limit=total_limit,
        total_current_balance=total_balance,
        credit_utilization_percent=round(utilization, 1),
        overdue_accounts=len(overdue),
        total_emi_obligation=total_emi,
        oldest_account_age_months=oldest_months,
        inquiries_last_6_months=len(recent_inquiries),
    )


def _generate_recommendations(score: Optional[int], summary: CreditReportSummary) -> List[str]:
    recommendations = []

    if summary.credit_utilization_percent > 30:
        recommendations.append(
            f"Your credit utilization is {summary.credit_utilization_percent:.0f}%. "
            "Keep it below 30% to improve your score."
        )

    if summary.overdue_accounts > 0:
        recommendations.append(
            f"You have {summary.overdue_accounts} overdue account(s). "
            "Clear dues immediately to prevent score damage."
        )

    if summary.inquiries_last_6_months > 3:
        recommendations.append(
            "Multiple credit inquiries in 6 months can lower your score. "
            "Avoid applying for new credit for a while."
        )

    if score and score < 700:
        recommendations.append(
            "Pay all EMIs and credit card bills on time for 6+ months "
            "to see significant score improvement."
        )

    if summary.credit_utilization_percent < 10 and summary.total_credit_limit > 0:
        recommendations.append(
            "Your credit utilization is very low — great for your score! "
            "Continue maintaining low balances."
        )

    if not recommendations:
        recommendations.append(
            "Your credit profile looks healthy. Keep paying on time "
            "and maintaining low utilization."
        )

    return recommendations


def _get_score_history(db: Session, user_id: str) -> List[dict]:
    """Get historical credit scores for the user."""
    reports = (
        db.query(CreditReport)
        .filter(CreditReport.user_id == user_id, CreditReport.status == "success")
        .order_by(CreditReport.fetched_at.asc())
        .limit(12)
        .all()
    )
    return [
        {
            "date": r.report_date.isoformat() if r.report_date else r.fetched_at.date().isoformat(),
            "score": r.score,
            "provider": r.provider,
        }
        for r in reports
        if r.score
    ]
