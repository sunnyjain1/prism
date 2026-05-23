from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from models import HealthScoreSnapshot
from services import net_worth_service
from services.budget_service import BudgetService
from services.investment_service import InvestmentService
from services.loan_service import LoanService
from services.transaction_service import TransactionService


class HealthScoreService:
    COMPONENT_WEIGHTS = {
        "savings_rate": 0.25,
        "debt_ratio": 0.25,
        "emergency_fund": 0.20,
        "diversification": 0.15,
        "budget_adherence": 0.15,
    }
    LIQUID_RESERVE_TYPES = ("savings", "checking", "current", "cash")
    LOW_SCORE_THRESHOLD = 60

    def calculate_health_score(self, user_id: str, db: Session) -> dict[str, Any]:
        today = date.today()
        snapshot_date = date(today.year, today.month, 1)

        transaction_summary = TransactionService(db).aggregate_transactions(
            user_id,
            month=today.month,
            year=today.year,
        )
        monthly_income = float(transaction_summary["total_income"] or 0.0)
        monthly_expenses = float(transaction_summary["total_expense"] or 0.0)
        monthly_savings = monthly_income - monthly_expenses

        net_worth = net_worth_service.calculate_current_net_worth(user_id, db)
        liquid_reserves = sum(
            float(net_worth["asset_breakdown"].get(account_type, 0.0))
            for account_type in self.LIQUID_RESERVE_TYPES
        )

        loan_summary = LoanService(db).get_loan_summary(user_id)
        monthly_emi = float(loan_summary["monthly_emi_burden"] or 0.0)

        investments = InvestmentService(db).get_investments(user_id)
        investment_types = len({investment.type for investment in investments if getattr(investment, "is_active", True)})

        active_budgets = [budget for budget in BudgetService(db).get_budgets(user_id) if budget["is_active"]]
        budget_adherence = None
        if active_budgets:
            budgets_on_track = sum(1 for budget in active_budgets if float(budget["percentage"]) <= 100)
            budget_adherence = budgets_on_track / len(active_budgets)

        components = {
            "savings_rate": self._build_component(
                value=(monthly_savings / monthly_income) if monthly_income > 0 else None,
                score_fn=self._score_savings_rate,
                formatter=lambda value: f"Savings Rate: {self._format_percent(value)}",
                missing_label="Add income transactions to calculate your savings rate",
            ),
            "debt_ratio": self._build_component(
                value=(monthly_emi / monthly_income) if monthly_income > 0 else None,
                score_fn=self._score_debt_ratio,
                formatter=lambda value: f"Debt-to-Income: {self._format_percent(value)}",
                missing_label="Add income transactions to calculate your debt ratio",
            ),
            "emergency_fund": self._build_component(
                value=(liquid_reserves / monthly_expenses) if monthly_expenses > 0 else None,
                score_fn=self._score_emergency_fund,
                formatter=lambda value: f"Emergency Fund: {self._format_months(value)}",
                missing_label="Add expense transactions to estimate your emergency fund coverage",
            ),
            "diversification": self._build_component(
                value=float(investment_types),
                score_fn=lambda value: self._score_diversification(int(value)),
                formatter=lambda value: self._format_investment_types(int(value)),
            ),
            "budget_adherence": self._build_component(
                value=budget_adherence,
                score_fn=self._score_budget_adherence,
                formatter=lambda value: f"{self._format_percent(value)} budgets on track",
                missing_label="Create active budgets to track adherence",
            ),
        }

        available_components = [
            name for name, component in components.items() if component["has_data"]
        ]
        if len(available_components) < 2:
            return {
                "score": None,
                "grade": None,
                "components": components,
                "recommendations": [],
                "has_enough_data": False,
                "message": "Not enough data",
                "snapshot_date": snapshot_date,
            }

        total_weight = sum(self.COMPONENT_WEIGHTS[name] for name in available_components)
        weighted_score = sum(
            int(components[name]["score"]) * self.COMPONENT_WEIGHTS[name]
            for name in available_components
        )
        score = max(0, min(100, round(weighted_score / total_weight)))

        return {
            "score": score,
            "grade": self._resolve_grade(score),
            "components": components,
            "recommendations": self._build_recommendations(components),
            "has_enough_data": True,
            "message": None,
            "snapshot_date": snapshot_date,
        }

    def get_current_score(self, user_id: str, db: Session) -> dict[str, Any]:
        payload = self.calculate_health_score(user_id, db)
        if payload["has_enough_data"]:
            self._upsert_snapshot(user_id, payload, db)
        return payload

    def get_health_score_history(self, user_id: str, db: Session, months: int = 12) -> list[dict[str, Any]]:
        current_score = self.get_current_score(user_id, db)
        start_date = self._start_months_ago(date.today(), months)
        snapshots = (
            db.query(HealthScoreSnapshot)
            .filter(
                HealthScoreSnapshot.user_id == user_id,
                HealthScoreSnapshot.snapshot_date >= start_date,
            )
            .order_by(HealthScoreSnapshot.snapshot_date.asc())
            .all()
        )

        history = [
            {
                "score": snapshot.score,
                "grade": snapshot.grade,
                "snapshot_date": snapshot.snapshot_date,
                "created_at": snapshot.created_at,
            }
            for snapshot in snapshots
        ]

        if current_score["has_enough_data"] and not history:
            history.append(
                {
                    "score": current_score["score"],
                    "grade": current_score["grade"],
                    "snapshot_date": current_score["snapshot_date"],
                    "created_at": None,
                }
            )

        return history

    def _upsert_snapshot(self, user_id: str, payload: dict[str, Any], db: Session) -> HealthScoreSnapshot:
        snapshot = (
            db.query(HealthScoreSnapshot)
            .filter(
                HealthScoreSnapshot.user_id == user_id,
                HealthScoreSnapshot.snapshot_date == payload["snapshot_date"],
            )
            .first()
        )

        if snapshot is None:
            snapshot = HealthScoreSnapshot(
                user_id=user_id,
                snapshot_date=payload["snapshot_date"],
            )
            db.add(snapshot)

        snapshot.score = int(payload["score"])
        snapshot.grade = str(payload["grade"])
        snapshot.components = payload["components"]
        snapshot.recommendations = payload["recommendations"]

        db.commit()
        db.refresh(snapshot)
        return snapshot

    def _build_component(
        self,
        value: float | None,
        score_fn,
        formatter,
        missing_label: str | None = None,
    ) -> dict[str, Any]:
        if value is None:
            return {
                "score": None,
                "value": None,
                "label": missing_label or "Not enough data",
                "has_data": False,
            }

        return {
            "score": score_fn(value),
            "value": round(float(value), 4),
            "label": formatter(value),
            "has_data": True,
        }

    def _build_recommendations(self, components: dict[str, dict[str, Any]]) -> list[str]:
        recommendations: list[str] = []

        if self._is_low_score(components["savings_rate"]):
            recommendations.append("Try to save at least 20% of your income")
        if self._is_low_score(components["debt_ratio"]):
            recommendations.append("Consider paying off high-interest debt first")
        if self._is_low_score(components["emergency_fund"]):
            recommendations.append("Build an emergency fund covering 3-6 months of expenses")
        if self._is_low_score(components["diversification"]):
            recommendations.append("Consider diversifying across mutual funds, stocks, and fixed deposits")
        if self._is_low_score(components["budget_adherence"]):
            recommendations.append("Review and adjust your budgets to be more realistic")

        return recommendations

    def _is_low_score(self, component: dict[str, Any]) -> bool:
        return component["has_data"] and int(component["score"]) <= self.LOW_SCORE_THRESHOLD

    def _score_savings_rate(self, value: float) -> int:
        if value >= 0.30:
            return 100
        if value >= 0.20:
            return 80
        if value >= 0.10:
            return 60
        if value >= 0.05:
            return 40
        return 20

    def _score_debt_ratio(self, value: float) -> int:
        if value < 0.20:
            return 100
        if value < 0.30:
            return 80
        if value < 0.40:
            return 60
        if value <= 0.50:
            return 40
        return 20

    def _score_emergency_fund(self, value: float) -> int:
        if value > 6:
            return 100
        if value >= 3:
            return 80
        if value >= 1:
            return 60
        return 30

    def _score_diversification(self, value: int) -> int:
        if value >= 5:
            return 100
        if value >= 3:
            return 80
        if value == 2:
            return 60
        if value == 1:
            return 40
        return 20

    def _score_budget_adherence(self, value: float) -> int:
        if value > 0.90:
            return 100
        if value >= 0.70:
            return 80
        if value >= 0.50:
            return 60
        return 40

    def _resolve_grade(self, score: int) -> str:
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B+"
        if score >= 60:
            return "B"
        if score >= 50:
            return "C+"
        if score >= 40:
            return "C"
        if score >= 30:
            return "D"
        return "F"

    def _format_percent(self, value: float) -> str:
        return f"{round(value * 100)}%"

    def _format_months(self, value: float) -> str:
        rounded = round(value, 1)
        if float(rounded).is_integer():
            rounded = int(rounded)
        return f"{rounded} months"

    def _format_investment_types(self, count: int) -> str:
        return f"{count} investment type{'s' if count != 1 else ''}"

    def _start_months_ago(self, reference_date: date, months: int) -> date:
        month_index = reference_date.year * 12 + reference_date.month - 1 - max(months - 1, 0)
        year = month_index // 12
        month = month_index % 12 + 1
        return date(year, month, 1)
