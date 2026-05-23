from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import requests
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from core.config import settings
from models import Account, Investment
from services.cache_service import cache


class InvestmentService:
    AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

    def __init__(self, db: Session):
        self.db = db

    def _net_worth_cache_key(self, user_id: str) -> str:
        return f"net_worth:{user_id}"

    def _invalidate_net_worth_cache(self, user_id: str) -> None:
        cache.delete(self._net_worth_cache_key(user_id))

    def create_investment(self, user_id: str, data: dict[str, Any]) -> Investment:
        payload = dict(data)
        self._validate_account(payload.get("account_id"), user_id)
        payload["id"] = payload.get("id") or str(uuid4())
        payload["user_id"] = user_id
        investment = Investment(**payload)
        self._apply_derived_values(investment)
        self.db.add(investment)
        self.db.commit()
        self.db.refresh(investment)
        self._invalidate_net_worth_cache(user_id)
        return investment

    def get_investments(self, user_id: str, type_filter: Optional[str] = None) -> list[Investment]:
        query = self.db.query(Investment).filter(
            Investment.user_id == user_id,
            Investment.is_active.is_(True),
        )
        if type_filter:
            query = query.filter(Investment.type == type_filter)
        return query.order_by(Investment.type.asc(), Investment.updated_at.desc()).all()

    def get_investment(self, user_id: str, investment_id: str) -> Investment:
        investment = self.db.query(Investment).filter(
            Investment.id == investment_id,
            Investment.user_id == user_id,
        ).first()
        if not investment:
            raise HTTPException(status_code=404, detail="Investment not found")
        return investment

    def update_investment(self, user_id: str, investment_id: str, data: dict[str, Any]) -> Investment:
        investment = self.get_investment(user_id, investment_id)
        payload = dict(data)
        if "account_id" in payload:
            self._validate_account(payload.get("account_id"), user_id)

        for field, value in payload.items():
            if hasattr(investment, field):
                setattr(investment, field, value)

        self._apply_derived_values(investment)
        self.db.commit()
        self.db.refresh(investment)
        self._invalidate_net_worth_cache(user_id)
        return investment

    def delete_investment(self, user_id: str, investment_id: str) -> None:
        investment = self.get_investment(user_id, investment_id)
        self.db.delete(investment)
        self.db.commit()
        self._invalidate_net_worth_cache(user_id)

    def get_portfolio_summary(self, user_id: str) -> dict[str, Any]:
        cache_key = self._net_worth_cache_key(user_id)
        cached_summary = cache.get(cache_key)
        if cached_summary is not None:
            return cached_summary

        investments = self.get_investments(user_id)
        total_invested = sum(investment.invested_amount or 0 for investment in investments)
        total_current_value = sum(self._resolved_current_value(investment) for investment in investments)
        total_returns = total_current_value - total_invested
        returns_percentage = (total_returns / total_invested * 100) if total_invested else 0.0

        allocation_by_type: dict[str, float] = {}
        performers = []
        for investment in investments:
            current_value = self._resolved_current_value(investment)
            allocation_by_type[investment.type] = allocation_by_type.get(investment.type, 0.0) + current_value
            total_return = current_value - (investment.invested_amount or 0)
            return_pct = (total_return / investment.invested_amount * 100) if investment.invested_amount else 0.0
            performers.append({
                "id": investment.id,
                "name": investment.name,
                "type": investment.type,
                "invested_amount": investment.invested_amount or 0.0,
                "current_value": current_value,
                "total_returns": total_return,
                "returns_percentage": return_pct,
            })

        top_performers = sorted(performers, key=lambda item: item["returns_percentage"], reverse=True)[:3]
        worst_performers = sorted(performers, key=lambda item: item["returns_percentage"])[:3]

        summary = {
            "total_invested": total_invested,
            "total_current_value": total_current_value,
            "total_returns": total_returns,
            "returns_percentage": returns_percentage,
            "allocation_by_type": allocation_by_type,
            "top_performers": top_performers,
            "worst_performers": worst_performers,
        }
        cache.set(cache_key, jsonable_encoder(summary), ttl=settings.CACHE_TTL_SUMMARY)
        return summary

    def update_mutual_fund_nav(self, investment_id: str) -> Investment:
        investment = self.db.query(Investment).filter(Investment.id == investment_id).first()
        if not investment:
            raise HTTPException(status_code=404, detail="Investment not found")

        if investment.type != "mutual_fund":
            self._apply_derived_values(investment)
            self.db.commit()
            self.db.refresh(investment)
            self._invalidate_net_worth_cache(investment.user_id)
            return investment

        try:
            response = requests.get(self.AMFI_NAV_URL, timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            return investment

        nav_data = self._find_nav_value(response.text, investment)
        if nav_data is None:
            return investment

        investment.current_price = nav_data
        self._apply_derived_values(investment)
        self.db.commit()
        self.db.refresh(investment)
        self._invalidate_net_worth_cache(investment.user_id)
        return investment

    def _validate_account(self, account_id: Optional[str], user_id: str) -> None:
        if not account_id:
            return
        account = self.db.query(Account).filter(
            Account.id == account_id,
            Account.owner_id == user_id,
            Account.is_deleted.is_(False),
        ).first()
        if not account:
            raise HTTPException(status_code=400, detail="Linked account not found")

    def _apply_derived_values(self, investment: Investment) -> None:
        if investment.quantity is not None and investment.buy_price is not None:
            investment.invested_amount = investment.quantity * investment.buy_price

        if investment.quantity is not None:
            reference_price = investment.current_price
            if reference_price is None and investment.buy_price is not None:
                reference_price = investment.buy_price
                investment.current_price = investment.buy_price
            if reference_price is not None:
                investment.current_value = investment.quantity * reference_price

        if investment.current_price is None and investment.current_value is not None and investment.quantity:
            investment.current_price = investment.current_value / investment.quantity

        if investment.current_value is None:
            investment.current_value = investment.invested_amount

        investment.currency = (investment.currency or "INR").upper()
        investment.last_updated = datetime.now(timezone.utc)

    def _resolved_current_value(self, investment: Investment) -> float:
        if investment.current_value is not None:
            return investment.current_value
        if investment.quantity is not None and investment.current_price is not None:
            return investment.quantity * investment.current_price
        return investment.invested_amount or 0.0

    def _find_nav_value(self, payload: str, investment: Investment) -> Optional[float]:
        symbol = (investment.symbol or "").strip().lower()
        name = investment.name.strip().lower()
        partial_matches: list[float] = []

        for raw_line in payload.splitlines():
            parts = [part.strip() for part in raw_line.split(";")]
            if len(parts) < 6 or not parts[0].isdigit():
                continue

            scheme_code, scheme_name, isin_growth, isin_reinvest, nav_value = parts[0], parts[1], parts[2], parts[3], parts[4]
            try:
                nav = float(nav_value)
            except ValueError:
                continue

            if symbol and symbol in {scheme_code.lower(), isin_growth.lower(), isin_reinvest.lower()}:
                return nav
            if scheme_name.strip().lower() == name:
                return nav
            if symbol and symbol in scheme_name.lower():
                partial_matches.append(nav)
            elif name and name in scheme_name.lower():
                partial_matches.append(nav)

        return partial_matches[0] if partial_matches else None
