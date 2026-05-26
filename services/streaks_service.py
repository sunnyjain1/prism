"""
Financial Streaks & Achievements Service.

Tracks user engagement patterns and generates achievement milestones:
- Transaction logging streaks (consecutive days)
- Under-budget streaks
- Savings milestones
- Activity badges
"""
from datetime import datetime, timedelta, date
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, distinct, cast, Date

from models import Transaction, Budget, TransactionType


class StreaksService:
    def __init__(self, db: Session):
        self.db = db

    def get_user_streaks(self, user_id: str) -> dict:
        """Get all streak and achievement data for a user."""
        return {
            "logging_streak": self._get_logging_streak(user_id),
            "budget_streak": self._get_budget_streak(user_id),
            "achievements": self._get_achievements(user_id),
            "stats": self._get_engagement_stats(user_id),
        }

    def _get_logging_streak(self, user_id: str) -> dict:
        """Calculate consecutive days of transaction logging."""
        # Get distinct dates when user logged transactions (last 180 days)
        cutoff = datetime.utcnow() - timedelta(days=180)
        dates_result = self.db.query(
            distinct(func.date(Transaction.date))
        ).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.date >= cutoff,
            )
        ).all()

        active_dates = sorted([row[0] for row in dates_result], reverse=True)
        if not active_dates:
            return {"current": 0, "longest": 0, "last_active": None}

        # Calculate current streak (consecutive days ending today or yesterday)
        today = date.today()
        current_streak = 0
        check_date = today

        for d in active_dates:
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if d == check_date or d == check_date - timedelta(days=1):
                if d == check_date:
                    current_streak += 1
                    check_date = d - timedelta(days=1)
                elif d == check_date - timedelta(days=1):
                    current_streak += 1
                    check_date = d - timedelta(days=1)
            else:
                break

        # Calculate longest streak
        longest_streak = 0
        streak = 1
        for i in range(1, len(active_dates)):
            prev = active_dates[i-1]
            curr = active_dates[i]
            if isinstance(prev, str):
                prev = date.fromisoformat(prev)
            if isinstance(curr, str):
                curr = date.fromisoformat(curr)
            if (prev - curr).days == 1:
                streak += 1
            else:
                longest_streak = max(longest_streak, streak)
                streak = 1
        longest_streak = max(longest_streak, streak)

        return {
            "current": current_streak,
            "longest": longest_streak,
            "last_active": str(active_dates[0]) if active_dates else None,
        }

    def _get_budget_streak(self, user_id: str) -> dict:
        """Calculate consecutive months where user stayed under budget overall."""
        budgets = self.db.query(Budget).filter(Budget.user_id == user_id).all()
        if not budgets:
            return {"current_months": 0}

        now = datetime.utcnow()
        under_budget_months = 0

        for month_offset in range(12):
            check_month = now - timedelta(days=30 * month_offset)
            month_start = check_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1)

            total_budget = sum(b.amount for b in budgets if b.amount > 0)
            if total_budget == 0:
                break

            total_spent = self.db.query(
                func.coalesce(func.sum(Transaction.amount), 0)
            ).filter(
                and_(
                    Transaction.owner_id == user_id,
                    Transaction.type == TransactionType.expense.value,
                    Transaction.date >= month_start,
                    Transaction.date < month_end,
                )
            ).scalar() or 0

            if total_spent <= total_budget:
                under_budget_months += 1
            else:
                break

        return {"current_months": under_budget_months}

    def _get_achievements(self, user_id: str) -> List[dict]:
        """Generate achievements based on user activity."""
        achievements = []
        now = datetime.utcnow()

        # Total transactions logged
        total_txns = self.db.query(func.count(Transaction.id)).filter(
            Transaction.owner_id == user_id
        ).scalar() or 0

        txn_milestones = [
            (1000, "💎 Finance Master", "Logged 1,000+ transactions"),
            (500, "🏆 Dedicated Tracker", "Logged 500+ transactions"),
            (100, "⭐ Getting Serious", "Logged 100+ transactions"),
            (50, "📊 Building Habits", "Logged 50+ transactions"),
            (10, "🚀 First Steps", "Logged 10+ transactions"),
            (1, "👋 Welcome!", "Logged your first transaction"),
        ]

        for threshold, title, description in txn_milestones:
            if total_txns >= threshold:
                achievements.append({
                    "id": f"txn_{threshold}",
                    "title": title,
                    "description": description,
                    "earned": True,
                    "category": "activity",
                })
                break

        # Savings achievements
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_income = self.db.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.income.value,
                Transaction.date >= month_start,
            )
        ).scalar() or 0

        monthly_expense = self.db.query(
            func.coalesce(func.sum(Transaction.amount), 0)
        ).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.type == TransactionType.expense.value,
                Transaction.date >= month_start,
            )
        ).scalar() or 0

        if monthly_income > 0:
            savings_rate = ((monthly_income - monthly_expense) / monthly_income) * 100
            if savings_rate >= 50:
                achievements.append({"id": "save_50", "title": "🏦 Super Saver", "description": "50%+ savings rate this month", "earned": True, "category": "savings"})
            elif savings_rate >= 30:
                achievements.append({"id": "save_30", "title": "💰 Smart Saver", "description": "30%+ savings rate this month", "earned": True, "category": "savings"})
            elif savings_rate >= 20:
                achievements.append({"id": "save_20", "title": "📈 On Track", "description": "20%+ savings rate this month", "earned": True, "category": "savings"})

        return achievements

    def _get_engagement_stats(self, user_id: str) -> dict:
        """Basic engagement statistics."""
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)

        txns_this_month = self.db.query(func.count(Transaction.id)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.date >= month_start,
            )
        ).scalar() or 0

        txns_this_week = self.db.query(func.count(Transaction.id)).filter(
            and_(
                Transaction.owner_id == user_id,
                Transaction.date >= week_start,
            )
        ).scalar() or 0

        total_txns = self.db.query(func.count(Transaction.id)).filter(
            Transaction.owner_id == user_id
        ).scalar() or 0

        return {
            "total_transactions": total_txns,
            "transactions_this_month": txns_this_month,
            "transactions_this_week": txns_this_week,
        }
