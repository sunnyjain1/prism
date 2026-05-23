from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from math import ceil, log
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Account, Loan


class LoanService:
    def __init__(self, db: Session):
        self.db = db

    def create_loan(self, user_id: str, data: Any) -> dict[str, Any]:
        payload = self._normalize_payload(user_id, data)
        payload["id"] = payload.get("id") or str(uuid4())
        payload["user_id"] = user_id

        loan = Loan(**payload)
        self.db.add(loan)
        self.db.commit()
        self.db.refresh(loan)
        return self._serialize_loan(loan)

    def get_loans(self, user_id: str, active_only: bool = True) -> list[dict[str, Any]]:
        query = self.db.query(Loan).filter(Loan.user_id == user_id)
        if active_only:
            query = query.filter(Loan.is_active.is_(True))

        loans = query.order_by(Loan.is_active.desc(), Loan.updated_at.desc(), Loan.name.asc()).all()
        return [self._serialize_loan(loan) for loan in loans]

    def update_loan(self, user_id: str, loan_id: str, data: Any) -> dict[str, Any]:
        loan = self._get_loan(user_id, loan_id)
        payload = self._normalize_payload(user_id, data, existing=loan)
        for key, value in payload.items():
            setattr(loan, key, value)

        self.db.commit()
        self.db.refresh(loan)
        return self._serialize_loan(loan)

    def close_loan(self, user_id: str, loan_id: str) -> dict[str, Any]:
        loan = self._get_loan(user_id, loan_id)
        loan.is_active = False
        if loan.outstanding_amount <= 0:
            loan.outstanding_amount = 0.0
            loan.end_date = loan.end_date or date.today()
        self.db.commit()
        self.db.refresh(loan)
        return self._serialize_loan(loan)

    def calculate_amortization(self, principal: float, rate: float, tenure_months: int) -> list[dict[str, Any]]:
        return self._build_amortization(principal, rate, tenure_months)["schedule"]

    def get_loan_summary(self, user_id: str) -> dict[str, Any]:
        loans = self.db.query(Loan).filter(Loan.user_id == user_id, Loan.is_active.is_(True)).all()
        serialized_loans = [self._serialize_loan(loan) for loan in loans]
        return {
            "total_outstanding": round(sum(item["outstanding_amount"] for item in serialized_loans), 2),
            "monthly_emi_burden": round(sum(item["emi_amount"] or 0 for item in serialized_loans), 2),
            "total_interest_payable": round(sum(item["total_interest_remaining"] for item in serialized_loans), 2),
            "active_count": len(serialized_loans),
        }

    def get_upcoming_emis(self, user_id: str, days: int = 30) -> list[dict[str, Any]]:
        today = date.today()
        end_date = today + timedelta(days=days)
        upcoming: list[dict[str, Any]] = []

        loans = self.db.query(Loan).filter(Loan.user_id == user_id, Loan.is_active.is_(True)).all()
        for loan in loans:
            next_due_date = self._calculate_next_due_date(loan)
            emi_amount = self._effective_emi_amount(loan)
            if not next_due_date or not emi_amount:
                continue
            if today <= next_due_date <= end_date:
                upcoming.append(
                    {
                        "loan_id": loan.id,
                        "name": loan.name,
                        "lender": loan.lender,
                        "due_date": next_due_date,
                        "emi_amount": round(emi_amount, 2),
                        "outstanding_amount": round(float(loan.outstanding_amount or 0), 2),
                    }
                )

        return sorted(upcoming, key=lambda item: (item["due_date"], item["name"].lower()))

    def record_emi_payment(self, user_id: str, loan_id: str, amount: float, payment_date: date) -> dict[str, Any]:
        loan = self._get_loan(user_id, loan_id)
        if not loan.is_active or loan.outstanding_amount <= 0:
            raise HTTPException(status_code=400, detail="Loan is already closed")
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")

        monthly_rate = float(loan.interest_rate or 0) / 1200
        interest_component = round(float(loan.outstanding_amount) * monthly_rate, 2) if monthly_rate else 0.0
        principal_component = round(max(float(amount) - interest_component, 0.0), 2)
        principal_component = min(principal_component, round(float(loan.outstanding_amount), 2))

        loan.outstanding_amount = round(max(float(loan.outstanding_amount) - principal_component, 0.0), 2)
        if loan.outstanding_amount <= 0.01:
            loan.outstanding_amount = 0.0
            loan.is_active = False
            loan.end_date = payment_date

        self.db.commit()
        self.db.refresh(loan)

        return {
            "loan": self._serialize_loan(loan),
            "amount": round(float(amount), 2),
            "payment_date": payment_date,
            "principal_component": principal_component,
            "interest_component": interest_component,
            "outstanding_amount": loan.outstanding_amount,
            "is_closed": not loan.is_active,
        }

    def get_amortization_details(self, user_id: str, loan_id: str) -> dict[str, Any]:
        loan = self._get_loan(user_id, loan_id)
        total_tenure = self._resolve_total_tenure(loan)
        if not total_tenure:
            raise HTTPException(status_code=400, detail="Loan tenure could not be determined for amortization")

        full_schedule = self._build_amortization(
            principal=float(loan.principal_amount),
            rate=float(loan.interest_rate),
            tenure_months=total_tenure,
            emi_amount=loan.emi_amount,
            start_date=loan.start_date,
            emi_day=loan.emi_day,
        )

        remaining_tenure = self._resolve_remaining_tenure(loan)
        next_due_date = self._calculate_next_due_date(loan)
        remaining_schedule = self._build_amortization(
            principal=float(loan.outstanding_amount),
            rate=float(loan.interest_rate),
            tenure_months=remaining_tenure,
            emi_amount=self._effective_emi_amount(loan),
            start_date=next_due_date,
            emi_day=loan.emi_day,
        ) if loan.outstanding_amount > 0 and remaining_tenure > 0 else {"schedule": [], "total_interest": 0.0}

        total_interest_payable = round(full_schedule["total_interest"], 2)
        total_interest_remaining = round(remaining_schedule["total_interest"], 2)
        total_interest_paid = round(max(total_interest_payable - total_interest_remaining, 0.0), 2)

        return {
            "loan": self._serialize_loan(loan),
            "schedule": full_schedule["schedule"],
            "monthly_emi": round(full_schedule["emi_amount"], 2),
            "total_interest_payable": total_interest_payable,
            "total_interest_paid": total_interest_paid,
            "total_interest_remaining": total_interest_remaining,
            "remaining_tenure_months": remaining_tenure,
        }

    def _get_loan(self, user_id: str, loan_id: str) -> Loan:
        loan = self.db.query(Loan).filter(Loan.id == loan_id, Loan.user_id == user_id).first()
        if not loan:
            raise HTTPException(status_code=404, detail="Loan not found")
        return loan

    def _serialize_loan(self, loan: Loan) -> dict[str, Any]:
        total_tenure = self._resolve_total_tenure(loan)
        remaining_tenure = self._resolve_remaining_tenure(loan)
        emi_amount = self._effective_emi_amount(loan)
        total_interest_remaining = 0.0
        if emi_amount and remaining_tenure > 0 and loan.outstanding_amount > 0:
            total_interest_remaining = self._build_amortization(
                principal=float(loan.outstanding_amount),
                rate=float(loan.interest_rate),
                tenure_months=remaining_tenure,
                emi_amount=emi_amount,
                start_date=self._calculate_next_due_date(loan),
                emi_day=loan.emi_day,
            )["total_interest"]

        principal_amount = round(float(loan.principal_amount or 0), 2)
        outstanding_amount = round(float(loan.outstanding_amount or 0), 2)
        paid_amount = round(max(principal_amount - outstanding_amount, 0.0), 2)
        progress_percentage = round(min(max((paid_amount / principal_amount * 100) if principal_amount else 0.0, 0.0), 100.0), 2)

        return {
            "id": loan.id,
            "user_id": loan.user_id,
            "name": loan.name,
            "loan_type": loan.loan_type,
            "principal_amount": principal_amount,
            "outstanding_amount": outstanding_amount,
            "interest_rate": round(float(loan.interest_rate or 0), 2),
            "emi_amount": round(emi_amount, 2) if emi_amount else None,
            "tenure_months": total_tenure,
            "start_date": loan.start_date,
            "end_date": loan.end_date,
            "emi_day": loan.emi_day,
            "lender": loan.lender,
            "account_id": loan.account_id,
            "is_active": loan.is_active,
            "notes": loan.notes,
            "created_at": loan.created_at,
            "updated_at": loan.updated_at,
            "next_due_date": self._calculate_next_due_date(loan),
            "progress_percentage": progress_percentage,
            "paid_amount": paid_amount,
            "total_interest_remaining": round(total_interest_remaining, 2),
            "remaining_tenure_months": remaining_tenure,
        }

    def _normalize_payload(self, user_id: str, data: Any, existing: Loan | None = None) -> dict[str, Any]:
        payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)

        for field in ("name", "lender", "notes"):
            if field in payload and isinstance(payload[field], str):
                payload[field] = payload[field].strip() or None
        if "name" in payload and payload["name"] is None:
            raise HTTPException(status_code=400, detail="Loan name cannot be empty")

        if "account_id" in payload:
            self._validate_account(payload.get("account_id"), user_id)

        principal_amount = payload.get("principal_amount", existing.principal_amount if existing else None)
        outstanding_amount = payload.get("outstanding_amount", existing.outstanding_amount if existing else None)
        interest_rate = payload.get("interest_rate", existing.interest_rate if existing else None)
        emi_amount = payload.get("emi_amount", existing.emi_amount if existing else None)
        tenure_months = payload.get("tenure_months", existing.tenure_months if existing else None)
        start_date = payload.get("start_date", existing.start_date if existing else None)
        end_date = payload.get("end_date", existing.end_date if existing else None)

        if principal_amount is not None:
            principal_amount = float(principal_amount)
            if principal_amount <= 0:
                raise HTTPException(status_code=400, detail="Principal amount must be greater than zero")
            payload["principal_amount"] = principal_amount

        if outstanding_amount is None and not existing and principal_amount is not None:
            outstanding_amount = principal_amount
            payload["outstanding_amount"] = outstanding_amount
        elif (
            existing
            and "principal_amount" in payload
            and "outstanding_amount" not in payload
            and float(existing.outstanding_amount or 0) == float(existing.principal_amount or 0)
        ):
            outstanding_amount = principal_amount
            payload["outstanding_amount"] = outstanding_amount

        if outstanding_amount is not None:
            outstanding_amount = float(outstanding_amount)
            if outstanding_amount < 0:
                raise HTTPException(status_code=400, detail="Outstanding amount cannot be negative")
            payload["outstanding_amount"] = outstanding_amount

        if principal_amount is not None and outstanding_amount is not None and outstanding_amount > principal_amount:
            raise HTTPException(status_code=400, detail="Outstanding amount cannot exceed principal amount")

        if interest_rate is not None:
            interest_rate = float(interest_rate)
            if interest_rate < 0:
                raise HTTPException(status_code=400, detail="Interest rate cannot be negative")
            payload["interest_rate"] = interest_rate

        if emi_amount is not None:
            emi_amount = float(emi_amount)
            if emi_amount <= 0:
                raise HTTPException(status_code=400, detail="EMI amount must be greater than zero")
            payload["emi_amount"] = emi_amount

        if tenure_months is not None:
            tenure_months = int(tenure_months)
            if tenure_months <= 0:
                raise HTTPException(status_code=400, detail="Loan tenure must be at least one month")
            payload["tenure_months"] = tenure_months

        if start_date and end_date and end_date < start_date:
            raise HTTPException(status_code=400, detail="Loan end date cannot be before start date")

        if payload.get("emi_day") is None and start_date:
            payload["emi_day"] = start_date.day

        reference_principal = principal_amount
        if reference_principal is None and existing and existing.principal_amount is not None:
            reference_principal = float(existing.principal_amount)

        reference_rate = interest_rate
        if reference_rate is None and existing and existing.interest_rate is not None:
            reference_rate = float(existing.interest_rate)

        reference_emi = emi_amount
        if reference_emi is None and existing and existing.emi_amount is not None:
            reference_emi = float(existing.emi_amount)

        reference_tenure = tenure_months if tenure_months is not None else existing.tenure_months if existing else None

        if reference_tenure is None and reference_emi is None:
            raise HTTPException(status_code=400, detail="Provide tenure_months or emi_amount for the loan")

        if reference_principal and reference_rate is not None and reference_emi and reference_rate > 0:
            minimum_interest = reference_principal * (reference_rate / 1200)
            if reference_emi <= minimum_interest:
                raise HTTPException(status_code=400, detail="EMI amount is too low to cover monthly interest")

        if reference_tenure is None and reference_principal and reference_rate is not None and reference_emi:
            estimated_tenure = self._estimate_tenure_from_emi(reference_principal, reference_rate, reference_emi)
            if estimated_tenure:
                payload["tenure_months"] = estimated_tenure
                reference_tenure = estimated_tenure

        if reference_emi is None and reference_principal and reference_rate is not None and reference_tenure:
            payload["emi_amount"] = self._calculate_emi(reference_principal, reference_rate, reference_tenure)

        if start_date and reference_tenure and "end_date" not in payload:
            payload["end_date"] = self._add_months(start_date, reference_tenure - 1, payload.get("emi_day") or start_date.day)

        if payload.get("outstanding_amount") == 0 and payload.get("is_active") is None:
            payload["is_active"] = False
            payload.setdefault("end_date", date.today())

        return payload

    def _validate_account(self, account_id: str | None, user_id: str) -> None:
        if not account_id:
            return
        account = self.db.query(Account).filter(
            Account.id == account_id,
            Account.owner_id == user_id,
            Account.is_deleted.is_(False),
        ).first()
        if not account:
            raise HTTPException(status_code=400, detail="Linked account not found")

    def _resolve_total_tenure(self, loan: Loan) -> int:
        if loan.tenure_months:
            return int(loan.tenure_months)
        if loan.emi_amount:
            estimated = self._estimate_tenure_from_emi(float(loan.principal_amount), float(loan.interest_rate), float(loan.emi_amount))
            if estimated:
                return estimated
        return 0

    def _resolve_remaining_tenure(self, loan: Loan) -> int:
        if not loan.is_active or float(loan.outstanding_amount or 0) <= 0:
            return 0
        if loan.emi_amount:
            estimated = self._estimate_tenure_from_emi(float(loan.outstanding_amount), float(loan.interest_rate), float(loan.emi_amount))
            if estimated:
                return estimated
        total_tenure = self._resolve_total_tenure(loan)
        if total_tenure and loan.start_date:
            elapsed = self._months_elapsed(loan.start_date, date.today(), loan.emi_day)
            return max(total_tenure - elapsed, 0)
        return total_tenure

    def _effective_emi_amount(self, loan: Loan) -> float | None:
        if loan.emi_amount:
            return float(loan.emi_amount)
        total_tenure = self._resolve_total_tenure(loan)
        if total_tenure > 0:
            return self._calculate_emi(float(loan.principal_amount), float(loan.interest_rate), total_tenure)
        return None

    def _build_amortization(
        self,
        principal: float,
        rate: float,
        tenure_months: int,
        emi_amount: float | None = None,
        start_date: date | None = None,
        emi_day: int | None = None,
    ) -> dict[str, Any]:
        if principal <= 0 or tenure_months <= 0:
            return {"schedule": [], "emi_amount": 0.0, "total_interest": 0.0}

        resolved_emi = float(emi_amount) if emi_amount else self._calculate_emi(principal, rate, tenure_months)
        monthly_rate = rate / 1200
        balance = float(principal)
        total_interest = 0.0
        schedule: list[dict[str, Any]] = []
        today = date.today()

        for month_number in range(1, tenure_months + 1):
            interest_component = balance * monthly_rate if monthly_rate else 0.0
            principal_component = resolved_emi - interest_component
            current_emi = resolved_emi

            if month_number == tenure_months or principal_component >= balance:
                principal_component = balance
                current_emi = balance + interest_component

            balance = max(balance - principal_component, 0.0)
            due_date = self._build_due_date(start_date, month_number, emi_day)
            total_interest += interest_component
            schedule.append(
                {
                    "month_number": month_number,
                    "due_date": due_date,
                    "emi_amount": round(current_emi, 2),
                    "principal_component": round(principal_component, 2),
                    "interest_component": round(interest_component, 2),
                    "outstanding_balance": round(balance, 2),
                    "is_current": bool(due_date and due_date.year == today.year and due_date.month == today.month),
                }
            )

        return {
            "schedule": schedule,
            "emi_amount": resolved_emi,
            "total_interest": round(total_interest, 2),
        }

    def _calculate_emi(self, principal: float, rate: float, tenure_months: int) -> float:
        if tenure_months <= 0:
            raise HTTPException(status_code=400, detail="Loan tenure must be at least one month")
        if rate == 0:
            return round(principal / tenure_months, 2)

        monthly_rate = rate / 1200
        multiplier = (1 + monthly_rate) ** tenure_months
        emi = principal * monthly_rate * multiplier / (multiplier - 1)
        return round(emi, 2)

    def _estimate_tenure_from_emi(self, principal: float, rate: float, emi_amount: float) -> int:
        if principal <= 0 or emi_amount <= 0:
            return 0
        if rate == 0:
            return max(1, ceil(principal / emi_amount))

        monthly_rate = rate / 1200
        denominator = emi_amount - (principal * monthly_rate)
        if denominator <= 0:
            return 0
        months = log(emi_amount / denominator) / log(1 + monthly_rate)
        return max(1, ceil(months))

    def _calculate_next_due_date(self, loan: Loan) -> date | None:
        if not loan.is_active or not loan.start_date or float(loan.outstanding_amount or 0) <= 0:
            return None

        due_day = loan.emi_day or loan.start_date.day
        next_due = self._align_date(loan.start_date.year, loan.start_date.month, due_day)
        if next_due < loan.start_date:
            next_due = self._add_months(next_due, 1, due_day)

        today = date.today()
        while next_due < today:
            next_due = self._add_months(next_due, 1, due_day)

        if loan.end_date and next_due > loan.end_date:
            return None
        return next_due

    def _build_due_date(self, start_date: date | None, month_number: int, emi_day: int | None) -> date | None:
        if not start_date:
            return None
        due_day = emi_day or start_date.day
        due_date = self._align_date(start_date.year, start_date.month, due_day)
        if due_date < start_date:
            due_date = self._add_months(due_date, 1, due_day)
        return self._add_months(due_date, month_number - 1, due_day)

    def _months_elapsed(self, start_date: date, as_of: date, emi_day: int | None) -> int:
        due_day = emi_day or start_date.day
        months = (as_of.year - start_date.year) * 12 + (as_of.month - start_date.month)
        if as_of.day < due_day:
            months -= 1
        return max(months, 0)

    def _add_months(self, value: date, months: int, due_day: int | None = None) -> date:
        month_index = value.month - 1 + months
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(due_day or value.day, monthrange(year, month)[1])
        return date(year, month, day)

    def _align_date(self, year: int, month: int, due_day: int) -> date:
        day = min(due_day, monthrange(year, month)[1])
        return date(year, month, day)
