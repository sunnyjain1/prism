from types import SimpleNamespace

import pytest
import requests

from services.investment_service import InvestmentService
from user_models import User


@pytest.fixture
def investment_service(db_session):
    return InvestmentService(db_session)


@pytest.fixture
def setup_user(db_session):
    user = User(id="user1", email="investor@example.com", hashed_password="hashed")
    db_session.add(user)
    db_session.commit()
    return user


def test_create_investment(investment_service, setup_user):
    investment = investment_service.create_investment(
        setup_user.id,
        {
            "name": "Reliance Industries",
            "type": "stock",
            "quantity": 10,
            "buy_price": 2500,
            "current_price": 2800,
            "invested_amount": 25000,
        },
    )

    assert investment.user_id == setup_user.id
    assert investment.current_value == 28000
    assert investment.invested_amount == 25000


def test_get_portfolio_summary(investment_service, setup_user):
    investment_service.create_investment(
        setup_user.id,
        {
            "name": "Bluechip Fund",
            "type": "mutual_fund",
            "quantity": 100,
            "buy_price": 10,
            "current_price": 12,
            "invested_amount": 1000,
        },
    )
    investment_service.create_investment(
        setup_user.id,
        {
            "name": "PPF",
            "type": "ppf",
            "invested_amount": 5000,
            "current_value": 5300,
        },
    )

    summary = investment_service.get_portfolio_summary(setup_user.id)

    assert summary["total_invested"] == 6000
    assert summary["total_current_value"] == 6500
    assert round(summary["returns_percentage"], 2) == round((500 / 6000) * 100, 2)
    assert summary["allocation_by_type"] == {"mutual_fund": 1200.0, "ppf": 5300.0}
    assert summary["top_performers"][0]["name"] == "Bluechip Fund"


def test_update_mutual_fund_nav_uses_amfi_data(investment_service, setup_user, monkeypatch):
    investment = investment_service.create_investment(
        setup_user.id,
        {
            "name": "Bluechip Fund",
            "type": "mutual_fund",
            "symbol": "123456",
            "quantity": 50,
            "buy_price": 10,
            "invested_amount": 500,
        },
    )

    def fake_get(*args, **kwargs):
        return SimpleNamespace(
            text="123456;Bluechip Fund;INF1;INF2;14.5000;23-May-2026",
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr("services.investment_service.requests.get", fake_get)
    updated = investment_service.update_mutual_fund_nav(investment.id)

    assert updated.current_price == 14.5
    assert updated.current_value == 725.0


def test_update_mutual_fund_nav_gracefully_handles_errors(investment_service, setup_user, monkeypatch):
    investment = investment_service.create_investment(
        setup_user.id,
        {
            "name": "Bluechip Fund",
            "type": "mutual_fund",
            "quantity": 50,
            "buy_price": 10,
            "invested_amount": 500,
        },
    )

    def failing_get(*args, **kwargs):
        raise requests.RequestException("network down")

    monkeypatch.setattr("services.investment_service.requests.get", failing_get)
    unchanged = investment_service.update_mutual_fund_nav(investment.id)

    assert unchanged.current_price == 10
    assert unchanged.current_value == 500



def test_portfolio_summary_cache_invalidates_on_update(investment_service, setup_user, cache_store):
    investment = investment_service.create_investment(
        setup_user.id,
        {
            "name": "Bluechip Fund",
            "type": "mutual_fund",
            "quantity": 100,
            "buy_price": 10,
            "current_price": 12,
        },
    )

    first_summary = investment_service.get_portfolio_summary(setup_user.id)
    assert cache_store[f"net_worth:{setup_user.id}"] == first_summary

    investment_service.update_investment(setup_user.id, investment.id, {"current_price": 15})
    refreshed_summary = investment_service.get_portfolio_summary(setup_user.id)

    assert refreshed_summary["total_current_value"] == 1500
    assert refreshed_summary["total_returns"] == 500
