from __future__ import annotations

import re
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha1
from statistics import median
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from models import Account, Category, Subscription, Transaction, TransactionType

ALLOWED_FREQUENCIES = {"weekly", "monthly", "quarterly", "yearly"}
FREQUENCY_INTERVALS = {
    "weekly": (5, 9),
    "monthly": (27, 34),
    "quarterly": (86, 96),
    "yearly": (350, 380),
}
MONTHLY_MULTIPLIERS = {
    "weekly": 52 / 12,
    "monthly": 1,
    "quarterly": 1 / 3,
    "yearly": 1 / 12,
}
DESCRIPTOR_STOP_WORDS = {
    "upi",
    "debit",
    "credit",
    "payment",
    "subscription",
    "recurring",
    "mandate",
    "card",
    "purchase",
    "bill",
    "autopay",
    "txn",
}


class SubscriptionService:
    def __init__(self, db: Session):
        self.db = db

    def create_subscription(self, user_id: str, data: Any) -> Subscription:
        payload = self._normalize_payload(user_id, data)
        subscription = Subscription(user_id=user_id, **payload)
        self.db.add(subscription)
        self.db.commit()
        self.db.refresh(subscription)
        return subscription

    def get_subscriptions(self, user_id: str, active_only: bool = True) -> list[Subscription]:
        query = self.db.query(Subscription).filter(Subscription.user_id == user_id)
        if active_only:
            query = query.filter(Subscription.is_active.is_(True))
        return (
            query.order_by(Subscription.next_due_date.is_(None), Subscription.next_due_date.asc(), Subscription.name.asc())
            .all()
        )

    def update_subscription(self, user_id: str, sub_id: str, data: Any) -> Subscription:
        subscription = self._get_subscription(user_id, sub_id)
        payload = self._normalize_payload(user_id, data, existing=subscription)
        for key, value in payload.items():
            setattr(subscription, key, value)
        self.db.commit()
        self.db.refresh(subscription)
        return subscription

    def cancel_subscription(self, user_id: str, sub_id: str) -> Subscription:
        subscription = self._get_subscription(user_id, sub_id)
        subscription.is_active = False
        self.db.commit()
        self.db.refresh(subscription)
        return subscription

    def detect_recurring_transactions(self, user_id: str) -> list[dict[str, Any]]:
        transactions = (
            self.db.query(Transaction)
            .options(joinedload(Transaction.account))
            .filter(Transaction.owner_id == user_id, Transaction.type == TransactionType.expense.value)
            .order_by(Transaction.date.asc())
            .all()
        )

        grouped_transactions: dict[str, list[Transaction]] = defaultdict(list)
        for transaction in transactions:
            descriptor = self._normalize_descriptor(transaction.merchant or transaction.description or "")
            if descriptor:
                grouped_transactions[descriptor].append(transaction)

        existing_subscriptions = self.get_subscriptions(user_id, active_only=True)
        suggestions: list[dict[str, Any]] = []

        for descriptor, descriptor_transactions in grouped_transactions.items():
            if len(descriptor_transactions) < 2:
                continue

            candidate_transactions = self._largest_amount_cluster(descriptor_transactions)
            if len(candidate_transactions) < 2:
                continue

            frequency, interval_score = self._detect_frequency(candidate_transactions)
            if not frequency or interval_score < 0.75:
                continue

            amount_values = [float(transaction.amount) for transaction in candidate_transactions]
            median_amount = float(median(amount_values))
            tolerance = max(median_amount * 0.05, 1.0)
            max_deviation = max(abs(amount - median_amount) for amount in amount_values)
            amount_score = max(0.0, 1 - (max_deviation / tolerance if tolerance else 0.0))

            name = self._display_name(candidate_transactions)
            if self._matches_existing_subscription(existing_subscriptions, name, median_amount, frequency):
                continue

            currency = self._most_common_value(
                [transaction.account.currency for transaction in candidate_transactions if transaction.account and transaction.account.currency],
                default="INR",
            )
            category_id = self._most_common_value(
                [transaction.category_id for transaction in candidate_transactions if transaction.category_id],
                default=None,
            )
            account_id = self._most_common_value(
                [transaction.account_id for transaction in candidate_transactions if transaction.account_id],
                default=None,
            )
            last_paid_date = candidate_transactions[-1].date.date()
            next_due_date = self._calculate_next_due_date(last_paid_date, frequency)
            coverage_score = len(candidate_transactions) / len(descriptor_transactions)
            confidence = round(min(0.99, (interval_score * 0.45) + (amount_score * 0.35) + (coverage_score * 0.20)), 2)
            amount = round(median_amount, 2)
            suggestion_id = sha1(f"{descriptor}|{frequency}|{amount:.2f}".encode("utf-8")).hexdigest()[:12]

            suggestions.append(
                {
                    "id": suggestion_id,
                    "name": name,
                    "amount": amount,
                    "currency": currency,
                    "frequency": frequency,
                    "category_id": category_id,
                    "account_id": account_id,
                    "next_due_date": next_due_date,
                    "last_paid_date": last_paid_date,
                    "occurrences": len(candidate_transactions),
                    "confidence": confidence,
                    "auto_detected": True,
                    "notes": f"Auto-detected from {len(candidate_transactions)} similar transactions.",
                }
            )

        return sorted(suggestions, key=lambda item: (-item["confidence"], -item["occurrences"], item["name"].lower()))

    def confirm_detected_subscription(self, user_id: str, suggestion_id: str) -> Subscription:
        suggestion = next((item for item in self.detect_recurring_transactions(user_id) if item["id"] == suggestion_id), None)
        if not suggestion:
            raise HTTPException(status_code=404, detail="Detected subscription suggestion not found")

        existing_subscription = next(
            (
                subscription
                for subscription in self.get_subscriptions(user_id, active_only=True)
                if self._normalize_descriptor(subscription.name) == self._normalize_descriptor(suggestion["name"])
                and subscription.frequency == suggestion["frequency"]
                and self._amounts_similar(float(subscription.amount), float(suggestion["amount"]))
            ),
            None,
        )
        if existing_subscription:
            return existing_subscription

        return self.create_subscription(
            user_id,
            {
                "name": suggestion["name"],
                "amount": suggestion["amount"],
                "currency": suggestion["currency"],
                "frequency": suggestion["frequency"],
                "category_id": suggestion["category_id"],
                "account_id": suggestion["account_id"],
                "next_due_date": suggestion["next_due_date"],
                "last_paid_date": suggestion["last_paid_date"],
                "auto_detected": True,
                "notes": suggestion["notes"],
            },
        )

    def get_monthly_subscription_cost(self, user_id: str) -> float:
        subscriptions = self.get_subscriptions(user_id, active_only=True)
        return round(sum(self._to_monthly_cost(subscription.amount, subscription.frequency) for subscription in subscriptions), 2)

    def get_monthly_subscription_breakdown(self, user_id: str) -> list[dict[str, Any]]:
        totals: dict[str, float] = defaultdict(float)
        for subscription in self.get_subscriptions(user_id, active_only=True):
            totals[(subscription.currency or "INR").upper()] += self._to_monthly_cost(subscription.amount, subscription.frequency)
        return [
            {"currency": currency, "monthly_cost": round(amount, 2)}
            for currency, amount in sorted(totals.items())
        ]

    def get_upcoming_renewals(self, user_id: str, days: int = 7) -> list[Subscription]:
        today = date.today()
        end_date = today + timedelta(days=days)
        return (
            self.db.query(Subscription)
            .filter(
                Subscription.user_id == user_id,
                Subscription.is_active.is_(True),
                Subscription.next_due_date.is_not(None),
                Subscription.next_due_date >= today,
                Subscription.next_due_date <= end_date,
            )
            .order_by(Subscription.next_due_date.asc(), Subscription.name.asc())
            .all()
        )

    def _get_subscription(self, user_id: str, sub_id: str) -> Subscription:
        subscription = (
            self.db.query(Subscription)
            .filter(Subscription.id == sub_id, Subscription.user_id == user_id)
            .first()
        )
        if not subscription:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return subscription

    def _normalize_payload(self, user_id: str, data: Any, existing: Subscription | None = None) -> dict[str, Any]:
        payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)

        if "name" in payload and payload["name"] is not None:
            payload["name"] = payload["name"].strip()
        if "currency" in payload and payload["currency"] is not None:
            payload["currency"] = payload["currency"].strip().upper()
        if "notes" in payload and payload["notes"] is not None:
            payload["notes"] = payload["notes"].strip() or None
        if "amount" in payload and float(payload["amount"]) <= 0:
            raise HTTPException(status_code=400, detail="Subscription amount must be greater than zero")

        frequency = payload.get("frequency", existing.frequency if existing else None)
        if frequency and frequency not in ALLOWED_FREQUENCIES:
            raise HTTPException(status_code=400, detail="Unsupported subscription frequency")

        category_id = payload.get("category_id")
        if category_id:
            category = self.db.query(Category).filter(Category.id == category_id, Category.owner_id == user_id).first()
            if not category:
                raise HTTPException(status_code=404, detail="Category not found")

        account_id = payload.get("account_id")
        if account_id:
            account = self.db.query(Account).filter(Account.id == account_id, Account.owner_id == user_id).first()
            if not account:
                raise HTTPException(status_code=404, detail="Account not found")

        resolved_last_paid_date = payload.get("last_paid_date", existing.last_paid_date if existing else None)
        if ("last_paid_date" in payload or "frequency" in payload) and "next_due_date" not in payload and resolved_last_paid_date and frequency:
            payload["next_due_date"] = self._calculate_next_due_date(resolved_last_paid_date, frequency)

        payload.setdefault("currency", existing.currency if existing else "INR")
        return payload

    def _normalize_descriptor(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value.lower()).strip()
        cleaned = re.sub(r"\d+", " ", cleaned)
        cleaned = re.sub(r"[^a-z\s]", " ", cleaned)
        tokens = [token for token in cleaned.split() if len(token) > 1 and token not in DESCRIPTOR_STOP_WORDS]
        if not tokens:
            tokens = [token for token in cleaned.split() if len(token) > 1]
        return " ".join(tokens[:4])

    def _display_name(self, transactions: list[Transaction]) -> str:
        for transaction in reversed(transactions):
            for value in (transaction.merchant, transaction.description):
                if value and value.strip():
                    return re.sub(r"\s+", " ", value.strip())[:80]
        return "Recurring payment"

    def _largest_amount_cluster(self, transactions: list[Transaction]) -> list[Transaction]:
        best_cluster: list[Transaction] = []
        for transaction in transactions:
            cluster = [candidate for candidate in transactions if self._amounts_similar(float(transaction.amount), float(candidate.amount))]
            if len(cluster) > len(best_cluster):
                best_cluster = cluster
        return sorted(best_cluster, key=lambda item: item.date)

    def _detect_frequency(self, transactions: list[Transaction]) -> tuple[str | None, float]:
        if len(transactions) < 2:
            return None, 0.0

        intervals = [
            (transactions[index].date.date() - transactions[index - 1].date.date()).days
            for index in range(1, len(transactions))
        ]
        best_frequency = None
        best_score = 0.0
        for frequency, (lower_bound, upper_bound) in FREQUENCY_INTERVALS.items():
            matches = sum(1 for interval in intervals if lower_bound <= interval <= upper_bound)
            score = matches / len(intervals)
            if score > best_score:
                best_frequency = frequency
                best_score = score
        return best_frequency, best_score

    def _matches_existing_subscription(
        self,
        subscriptions: list[Subscription],
        name: str,
        amount: float,
        frequency: str,
    ) -> bool:
        normalized_name = self._normalize_descriptor(name)
        for subscription in subscriptions:
            if self._normalize_descriptor(subscription.name) != normalized_name:
                continue
            if subscription.frequency != frequency:
                continue
            if self._amounts_similar(float(subscription.amount), float(amount)):
                return True
        return False

    def _amounts_similar(self, left: float, right: float) -> bool:
        baseline = max(abs(left), abs(right), 1.0)
        return abs(left - right) <= baseline * 0.05

    def _most_common_value(self, values: list[Any], default: Any) -> Any:
        if not values:
            return default
        return Counter(values).most_common(1)[0][0]

    def _to_monthly_cost(self, amount: float, frequency: str) -> float:
        return float(amount) * MONTHLY_MULTIPLIERS.get(frequency, 1)

    def _calculate_next_due_date(self, paid_date: date, frequency: str) -> date:
        if frequency == "weekly":
            return paid_date + timedelta(days=7)
        if frequency == "monthly":
            return self._add_months(paid_date, 1)
        if frequency == "quarterly":
            return self._add_months(paid_date, 3)
        if frequency == "yearly":
            return self._add_months(paid_date, 12)
        raise HTTPException(status_code=400, detail="Unsupported subscription frequency")

    def _add_months(self, value: date, months: int) -> date:
        month_index = value.month - 1 + months
        year = value.year + month_index // 12
        month = month_index % 12 + 1
        day = min(value.day, monthrange(year, month)[1])
        return date(year, month, day)
