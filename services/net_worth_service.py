from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from models import Account, Investment, Loan, NetWorthSnapshot

ASSET_ACCOUNT_TYPES = {"checking", "current", "savings", "investment", "cash"}
LIABILITY_ACCOUNT_TYPES = {"credit", "credit_card", "loan"}
ACCOUNT_BREAKDOWN_MAP = {
    "checking": "checking",
    "current": "current",
    "savings": "savings",
    "cash": "cash",
    "investment": "investment_accounts",
}
LIABILITY_BREAKDOWN_MAP = {
    "credit": "credit_cards",
    "credit_card": "credit_cards",
    "loan": "loans",
}


def _to_float(value: float | None) -> float:
    return float(value or 0.0)



def _resolved_investment_value(investment: Investment) -> float:
    if investment.current_value is not None:
        return float(investment.current_value)
    if investment.quantity is not None and investment.current_price is not None:
        return float(investment.quantity * investment.current_price)
    return float(investment.invested_amount or 0.0)



def _start_months_ago(reference_date: date, months: int) -> date:
    month_index = reference_date.year * 12 + reference_date.month - 1 - max(months - 1, 0)
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)



def calculate_current_net_worth(user_id: str, db: Session) -> dict[str, Any]:
    accounts = db.query(Account).filter(
        Account.owner_id == user_id,
        Account.is_deleted.is_(False),
    ).all()
    investments = db.query(Investment).filter(
        Investment.user_id == user_id,
        Investment.is_active.is_(True),
    ).all()
    loans = db.query(Loan).filter(
        Loan.user_id == user_id,
        Loan.is_active.is_(True),
    ).all()

    asset_breakdown: defaultdict[str, float] = defaultdict(float)
    liability_breakdown: defaultdict[str, float] = defaultdict(float)
    total_assets = 0.0
    total_liabilities = 0.0

    for account in accounts:
        balance = _to_float(account.balance)
        if account.type in ASSET_ACCOUNT_TYPES:
            total_assets += balance
            asset_breakdown[ACCOUNT_BREAKDOWN_MAP.get(account.type, account.type)] += balance
        elif account.type in LIABILITY_ACCOUNT_TYPES:
            liability_value = abs(balance)
            total_liabilities += liability_value
            liability_breakdown[LIABILITY_BREAKDOWN_MAP.get(account.type, account.type)] += liability_value

    for investment in investments:
        current_value = _resolved_investment_value(investment)
        total_assets += current_value
        asset_breakdown[investment.type or "other"] += current_value

    for loan in loans:
        if loan.account_id:
            continue
        liability_value = _to_float(loan.outstanding_amount)
        total_liabilities += liability_value
        liability_breakdown["loans"] += liability_value

    asset_breakdown_dict = dict(sorted(asset_breakdown.items(), key=lambda item: item[0]))
    liability_breakdown_dict = dict(sorted(liability_breakdown.items(), key=lambda item: item[0]))
    breakdown = {
        **asset_breakdown_dict,
        **liability_breakdown_dict,
    }
    net_worth = total_assets - total_liabilities

    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": net_worth,
        "breakdown": breakdown,
        "asset_breakdown": asset_breakdown_dict,
        "liability_breakdown": liability_breakdown_dict,
        "debt_to_asset_ratio": (total_liabilities / total_assets) if total_assets else 0.0,
        "snapshot_date": date.today(),
    }



def take_snapshot(user_id: str, db: Session) -> NetWorthSnapshot:
    today = date.today()
    current = calculate_current_net_worth(user_id, db)
    snapshot = db.query(NetWorthSnapshot).filter(
        NetWorthSnapshot.user_id == user_id,
        NetWorthSnapshot.snapshot_date == today,
    ).first()

    if snapshot is None:
        snapshot = NetWorthSnapshot(
            user_id=user_id,
            snapshot_date=today,
        )
        db.add(snapshot)

    snapshot.total_assets = current["total_assets"]
    snapshot.total_liabilities = current["total_liabilities"]
    snapshot.net_worth = current["net_worth"]
    snapshot.breakdown = current["breakdown"]

    db.commit()
    db.refresh(snapshot)
    return snapshot



def get_net_worth_history(user_id: str, db: Session, months: int = 12) -> list[dict[str, Any]]:
    today = date.today()
    start_date = _start_months_ago(today, months)
    snapshots = db.query(NetWorthSnapshot).filter(
        NetWorthSnapshot.user_id == user_id,
        NetWorthSnapshot.snapshot_date >= start_date,
    ).order_by(NetWorthSnapshot.snapshot_date.asc()).all()

    history = [
        {
            "id": snapshot.id,
            "snapshot_date": snapshot.snapshot_date,
            "total_assets": snapshot.total_assets,
            "total_liabilities": snapshot.total_liabilities,
            "net_worth": snapshot.net_worth,
            "breakdown": snapshot.breakdown or {},
            "created_at": snapshot.created_at,
        }
        for snapshot in snapshots
    ]

    if not history or history[-1]["snapshot_date"] != today:
        current = calculate_current_net_worth(user_id, db)
        history.append(
            {
                "id": None,
                "snapshot_date": current["snapshot_date"],
                "total_assets": current["total_assets"],
                "total_liabilities": current["total_liabilities"],
                "net_worth": current["net_worth"],
                "breakdown": current["breakdown"],
                "created_at": None,
            }
        )

    return history



def get_asset_allocation(user_id: str, db: Session) -> dict[str, Any]:
    current = calculate_current_net_worth(user_id, db)
    total_assets = current["total_assets"]
    allocation = [
        {
            "type": asset_type,
            "value": value,
            "percentage": (value / total_assets * 100) if total_assets else 0.0,
        }
        for asset_type, value in current["asset_breakdown"].items()
        if value != 0
    ]
    allocation.sort(key=lambda item: item["value"], reverse=True)
    return {
        "total_assets": total_assets,
        "allocation": allocation,
    }



def get_debt_to_asset_ratio(user_id: str, db: Session) -> float:
    current = calculate_current_net_worth(user_id, db)
    return current["debt_to_asset_ratio"]
