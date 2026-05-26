"""
Smart Notification Intelligence — proactive financial alerts and insights.

Generates:
- Budget threshold warnings (80%, 100%)
- Unusual spending alerts
- Weekly spending summaries
- Bill due reminders
- Savings milestones
- Financial streak notifications
"""
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from models import Transaction, Budget, Account, TransactionType


class NotificationIntelligenceService:
    def __init__(self, db: Session):
        self.db = db

    def generate_insights(self, user_id: str) -> List[dict]:
        """Generate all pending intelligent notifications for a user."""
        insights = []
        insights.extend(self._check_budget_thresholds(user_id))
        insights.extend(self._check_unusual_spending(user_id))
        insights.extend(self._generate_weekly_summary(user_id))
        insights.extend(self._check_savings_milestones(user_id))
        return insights

    def _check_budget_thresholds(self, user_id: str) -> List[dict]:
        """Check if any budgets are approaching or exceeding limits."""
        insights = []
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        budgets = self.db.query(Budget).filter(
            Budget.user_id == user_id,
        ).all()

        for budget in budgets:
            # Sum expenses in this budget's category for current month
            spent = self.db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
                and_(
                    Transaction.owner_id == user_id,
                    Transaction.type == TransactionType.expense.value,
                    Transaction.category_id == budget.category_id,
                    Transaction.date >= month_start,
                )
            ).scalar() or 0

            if budget.amount <= 0:
                continue

            usage_pct = (spent / budget.amount) * 100

            if usage_pct >= 100:
                insights.append({
                    "type": "budget_exceeded",
                    "title": f"Budget exceeded: {budget.name}",
                    "body": f"You've spent ₹{spent:,.0f} of your ₹{budget.amount:,.0f} {budget.name} budget this month.",
                    "severity": "high",
                    "category": "budget",
                    "metadata": {"budget_id": budget.id, "spent": spent, "limit": budget.amount},
                })
            elif usage_pct >= 80:
                insights.append({
                    "type": "budget_warning",
                    "title": f"Budget alert: {budget.name}",
                    "body": f"You've used {usage_pct:.0f}% of your {budget.name} budget (₹{spent:,.0f} of ₹{budget.amount:,.0f}).",
                    "severity": "medium",
                    "category": "budget",
                    "metadata": {"budget_id": budget.id, "spent": spent, "limit": budget.amount},
                })

        return insights

    def _check_unusual_spending(self, user_id: str) -> List[dict]:
        """Detect transactions significantly above category average."""
        insights = []
        now = datetime.utcnow()
        lookback = now - timedelta(days=90)

        # Get recent transactions (last 7 days)
        recent = self.db.query(Transaction).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.expense.value,
                Transaction.date >= now - timedelta(days=7),
            )
        ).all()

        # Get category averages over 90 days
        category_stats = {}
        hist_txns = self.db.query(Transaction).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.expense.value,
                Transaction.date >= lookback,
                Transaction.date < now - timedelta(days=7),
            )
        ).all()

        for txn in hist_txns:
            cat_id = txn.category_id or "uncategorized"
            if cat_id not in category_stats:
                category_stats[cat_id] = []
            category_stats[cat_id].append(txn.amount)

        # Find outliers
        for txn in recent:
            cat_id = txn.category_id or "uncategorized"
            history = category_stats.get(cat_id, [])
            if len(history) < 3:
                continue
            avg = sum(history) / len(history)
            if avg > 0 and txn.amount > avg * 2.5:
                insights.append({
                    "type": "unusual_spending",
                    "title": "Unusual transaction detected",
                    "body": f"₹{txn.amount:,.0f} at {txn.merchant or txn.description or 'Unknown'} is {txn.amount/avg:.1f}x your typical spend in this category.",
                    "severity": "medium",
                    "category": "anomaly",
                    "metadata": {
                        "transaction_id": txn.id,
                        "amount": txn.amount,
                        "average": avg,
                        "multiplier": txn.amount / avg,
                    },
                })

        return insights[:3]  # Cap at 3 anomalies

    def _generate_weekly_summary(self, user_id: str) -> List[dict]:
        """Generate a weekly spending summary insight."""
        now = datetime.utcnow()
        week_start = now - timedelta(days=7)

        weekly_expense = self.db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.expense.value,
                Transaction.date >= week_start,
            )
        ).scalar() or 0

        weekly_income = self.db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.income.value,
                Transaction.date >= week_start,
            )
        ).scalar() or 0

        # Compare to previous week
        prev_week_start = week_start - timedelta(days=7)
        prev_expense = self.db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.expense.value,
                Transaction.date >= prev_week_start,
                Transaction.date < week_start,
            )
        ).scalar() or 0

        if weekly_expense == 0 and weekly_income == 0:
            return []

        change_pct = ((weekly_expense - prev_expense) / prev_expense * 100) if prev_expense > 0 else 0
        direction = "more" if change_pct > 0 else "less"
        tone = "📈" if change_pct > 10 else "📉" if change_pct < -10 else "➡️"

        return [{
            "type": "weekly_summary",
            "title": f"{tone} Weekly spending summary",
            "body": f"You spent ₹{weekly_expense:,.0f} this week — {abs(change_pct):.0f}% {direction} than last week.",
            "severity": "low",
            "category": "summary",
            "metadata": {
                "weekly_expense": weekly_expense,
                "weekly_income": weekly_income,
                "prev_expense": prev_expense,
                "change_pct": change_pct,
            },
        }]

    def _check_savings_milestones(self, user_id: str) -> List[dict]:
        """Check if user hit savings milestones."""
        insights = []
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        monthly_income = self.db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.income.value,
                Transaction.date >= month_start,
            )
        ).scalar() or 0

        monthly_expense = self.db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.expense.value,
                Transaction.date >= month_start,
            )
        ).scalar() or 0

        savings = monthly_income - monthly_expense
        savings_rate = (savings / monthly_income * 100) if monthly_income > 0 else 0

        milestones = [
            (50, "🏆 Incredible savings!", "You've saved over 50% of your income this month!"),
            (30, "🎉 Great savings rate!", "You're saving 30%+ of your income this month. Keep it up!"),
            (20, "💪 Solid progress!", "20% savings rate this month — you're building good habits."),
        ]

        for threshold, title, body in milestones:
            if savings_rate >= threshold:
                insights.append({
                    "type": "savings_milestone",
                    "title": title,
                    "body": f"{body} (₹{savings:,.0f} saved so far)",
                    "severity": "positive",
                    "category": "milestone",
                    "metadata": {"savings": savings, "savings_rate": savings_rate},
                })
                break  # Only the highest milestone

        return insights
