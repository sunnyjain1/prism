from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from core.config import settings
from models import Budget, Category, Transaction, TransactionType
from schemas import BudgetCreate, BudgetProgress, BudgetUpdate
from services.cache_service import cache


class BudgetService:
    WARNING_THRESHOLD = 80.0

    def __init__(self, db: Session):
        self.db = db

    def _budget_progress_cache_key(self, user_id: str, budget_id: str | None = None) -> str:
        key = f"budget_progress:{user_id}"
        return f"{key}:{budget_id}" if budget_id else key

    def _invalidate_budget_progress_cache(self, user_id: str) -> None:
        cache.delete(self._budget_progress_cache_key(user_id))
        cache.delete_pattern(f"{self._budget_progress_cache_key(user_id)}:*")

    def create_budget(self, user_id: str, data: BudgetCreate) -> dict[str, Any]:
        payload = self._normalize_payload(data.model_dump())
        self._validate_category(user_id, payload.get("category_id"))

        budget = Budget(user_id=user_id, **payload)
        self.db.add(budget)
        self.db.flush()
        budget_id = budget.id
        self.db.commit()
        self._invalidate_budget_progress_cache(user_id)
        return self.get_budget_progress(user_id, budget_id)

    def get_budgets(self, user_id: str) -> list[dict[str, Any]]:
        cache_key = self._budget_progress_cache_key(user_id)
        cached_budgets = cache.get(cache_key)
        if cached_budgets is not None:
            return [self._normalize_budget_progress(budget) for budget in cached_budgets]

        budgets = (
            self.db.query(Budget)
            .options(joinedload(Budget.category))
            .filter(Budget.user_id == user_id)
            .order_by(Budget.created_at.desc(), Budget.name.asc())
            .all()
        )
        budget_progress = [self._build_budget_progress(budget) for budget in budgets]
        cache.set(cache_key, jsonable_encoder(budget_progress), ttl=settings.CACHE_TTL_DASHBOARD)
        return budget_progress

    def get_budget_progress(self, user_id: str, budget_id: str) -> dict[str, Any]:
        cache_key = self._budget_progress_cache_key(user_id, budget_id)
        cached_progress = cache.get(cache_key)
        if cached_progress is not None:
            return self._normalize_budget_progress(cached_progress)

        budget = self._get_budget_or_404(user_id, budget_id)
        progress = self._build_budget_progress(budget)
        cache.set(cache_key, jsonable_encoder(progress), ttl=settings.CACHE_TTL_DASHBOARD)
        return progress

    def update_budget(self, user_id: str, budget_id: str, data: BudgetUpdate) -> dict[str, Any]:
        budget = self._get_budget_or_404(user_id, budget_id)
        update_data = self._normalize_payload(data.model_dump(exclude_unset=True))

        if "category_id" in update_data:
            self._validate_category(user_id, update_data.get("category_id"))

        for key, value in update_data.items():
            setattr(budget, key, value)

        self.db.commit()
        self._invalidate_budget_progress_cache(user_id)
        return self.get_budget_progress(user_id, budget_id)

    def delete_budget(self, user_id: str, budget_id: str) -> None:
        budget = self._get_budget_or_404(user_id, budget_id)
        self.db.delete(budget)
        self.db.commit()
        self._invalidate_budget_progress_cache(user_id)

    def check_budget_alerts(self, user_id: str) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []

        for budget in self.get_budgets(user_id):
            if not budget["is_active"]:
                continue
            if budget["percentage"] >= 100:
                alerts.append(
                    {
                        "budget": budget,
                        "severity": "exceeded",
                        "message": f'{budget["name"]} has exceeded its budget by {abs(budget["remaining"]):.2f}.',
                    }
                )
            elif budget["percentage"] >= self.WARNING_THRESHOLD:
                alerts.append(
                    {
                        "budget": budget,
                        "severity": "warning",
                        "message": f'{budget["name"]} is at {budget["percentage"]:.2f}% of its limit.',
                    }
                )

        return sorted(
            alerts,
            key=lambda item: (
                0 if item["severity"] == "exceeded" else 1,
                -item["budget"]["percentage"],
            ),
        )

    def _build_budget_progress(self, budget: Budget) -> dict[str, Any]:
        spent = self._calculate_spent(budget)
        remaining = round(float(budget.amount) - spent, 2)
        percentage = round((spent / float(budget.amount)) * 100, 2) if budget.amount else 0.0
        status = self._resolve_status(percentage)

        return self._normalize_budget_progress({
            "id": budget.id,
            "user_id": budget.user_id,
            "name": budget.name,
            "category_id": budget.category_id,
            "category": budget.category,
            "amount": round(float(budget.amount), 2),
            "period": budget.period,
            "start_date": budget.start_date,
            "is_active": budget.is_active,
            "created_at": budget.created_at,
            "updated_at": budget.updated_at,
            "spent": spent,
            "remaining": remaining,
            "percentage": percentage,
            "status": status,
        })

    def _normalize_budget_progress(self, progress: dict[str, Any]) -> dict[str, Any]:
        return BudgetProgress.model_validate(progress).model_dump()

    def _calculate_spent(self, budget: Budget) -> float:
        period_start, period_end = self._get_period_bounds(budget.period, budget.start_date)

        query = self.db.query(func.coalesce(func.sum(Transaction.amount), 0.0)).filter(
            Transaction.owner_id == budget.user_id,
            Transaction.type == TransactionType.expense.value,
            Transaction.date >= period_start,
            Transaction.date < period_end,
        )

        if budget.category_id:
            query = query.filter(Transaction.category_id == budget.category_id)

        spent = query.scalar() or 0.0
        return round(float(spent), 2)

    def _get_budget_or_404(self, user_id: str, budget_id: str) -> Budget:
        budget = (
            self.db.query(Budget)
            .options(joinedload(Budget.category))
            .filter(Budget.id == budget_id, Budget.user_id == user_id)
            .first()
        )
        if not budget:
            raise HTTPException(status_code=404, detail="Budget not found")
        return budget

    def _validate_category(self, user_id: str, category_id: str | None) -> None:
        if not category_id:
            return

        category = (
            self.db.query(Category)
            .filter(Category.id == category_id, Category.owner_id == user_id)
            .first()
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        if category.type != TransactionType.expense.value:
            raise HTTPException(status_code=400, detail="Budget category must be an expense category")

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        period = normalized.get("period")
        if isinstance(period, Enum):
            normalized["period"] = period.value
        return normalized

    def _get_period_bounds(self, period: str, custom_start: date | None = None) -> tuple[datetime, datetime]:
        today = datetime.now(timezone.utc).date()
        normalized_period = period.lower()

        if custom_start:
            start_date, end_date = self._get_custom_period_bounds(normalized_period, custom_start, today)
        elif normalized_period == "weekly":
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=7)
        elif normalized_period == "monthly":
            start_date = date(today.year, today.month, 1)
            end_date = self._month_boundary(*self._shift_month(today.year, today.month, 1), 1)
        elif normalized_period == "yearly":
            start_date = date(today.year, 1, 1)
            end_date = date(today.year + 1, 1, 1)
        else:
            raise HTTPException(status_code=400, detail="Invalid budget period")

        return (
            datetime.combine(start_date, time.min),
            datetime.combine(end_date, time.min),
        )

    def _get_custom_period_bounds(self, period: str, anchor: date, today: date) -> tuple[date, date]:
        if today < anchor:
            return anchor, self._advance_period(anchor, period)

        if period == "weekly":
            delta_days = (today - anchor).days
            start_date = anchor + timedelta(days=(delta_days // 7) * 7)
            return start_date, start_date + timedelta(days=7)

        if period == "monthly":
            current_boundary = self._month_boundary(today.year, today.month, anchor.day)
            if current_boundary > today:
                previous_year, previous_month = self._shift_month(today.year, today.month, -1)
                return self._month_boundary(previous_year, previous_month, anchor.day), current_boundary

            next_year, next_month = self._shift_month(today.year, today.month, 1)
            return current_boundary, self._month_boundary(next_year, next_month, anchor.day)

        if period == "yearly":
            current_boundary = self._year_boundary(today.year, anchor.month, anchor.day)
            if current_boundary > today:
                return self._year_boundary(today.year - 1, anchor.month, anchor.day), current_boundary

            return current_boundary, self._year_boundary(today.year + 1, anchor.month, anchor.day)

        raise HTTPException(status_code=400, detail="Invalid budget period")

    def _advance_period(self, start_date: date, period: str) -> date:
        if period == "weekly":
            return start_date + timedelta(days=7)
        if period == "monthly":
            year, month = self._shift_month(start_date.year, start_date.month, 1)
            return self._month_boundary(year, month, start_date.day)
        if period == "yearly":
            return self._year_boundary(start_date.year + 1, start_date.month, start_date.day)
        raise HTTPException(status_code=400, detail="Invalid budget period")

    def _shift_month(self, year: int, month: int, offset: int) -> tuple[int, int]:
        month_index = (year * 12) + (month - 1) + offset
        return month_index // 12, (month_index % 12) + 1

    def _month_boundary(self, year: int, month: int, day: int) -> date:
        return date(year, month, min(day, monthrange(year, month)[1]))

    def _year_boundary(self, year: int, month: int, day: int) -> date:
        return date(year, month, min(day, monthrange(year, month)[1]))

    def _resolve_status(self, percentage: float) -> str:
        if percentage >= 100:
            return "exceeded"
        if percentage >= self.WARNING_THRESHOLD:
            return "warning"
        return "on_track"
