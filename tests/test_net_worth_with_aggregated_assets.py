"""Tests for the extended NetWorthService that includes AggregatedAsset values."""
from uuid import uuid4

import pytest

from models import AggregatedAsset, Investment


def _make_user():
    suffix = uuid4().hex[:8]
    return {"email": f"nw-{suffix}@example.com", "password": "Password123!", "full_name": "NW Tester"}


def _register_and_login(client):
    payload = _make_user()
    r = client.post("/api/v1/auth/register", json=payload, headers={"user-agent": "pytest"})
    assert r.status_code == 200, r.text
    login = client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
        headers={"user-agent": "pytest"},
    )
    return {
        "Authorization": f"Bearer {login.json()['access_token']}",
    }


def _get_me(client, headers):
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_net_worth_includes_aggregated_asset_value(api_client):
    """Net worth total includes AggregatedAsset.current_value."""
    headers = _register_and_login(api_client)

    r = api_client.post(
        "/api/v1/aggregation/assets/manual",
        json={"name": "Gold coins", "asset_type": "gold", "current_value": 50000.0},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    nw = api_client.get("/api/v1/net-worth", headers=headers)
    assert nw.status_code == 200, nw.text
    data = nw.json()
    assert data["total_assets"] >= 50000.0
    assert "gold" in data["asset_breakdown"]
    assert data["asset_breakdown"]["gold"] >= 50000.0


def test_net_worth_real_estate_applies_ownership_percent(api_client):
    """Real estate net worth value is scaled by ownership_percent."""
    headers = _register_and_login(api_client)

    r = api_client.post(
        "/api/v1/aggregation/assets/manual",
        json={
            "name": "Apartment",
            "asset_type": "real_estate",
            "current_value": 10_000_000.0,
            "ownership_percent": 50.0,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text

    nw = api_client.get("/api/v1/net-worth", headers=headers)
    assert nw.status_code == 200
    data = nw.json()
    assert data["asset_breakdown"].get("real_estate", 0) == pytest.approx(5_000_000.0, rel=0.01)


def test_net_worth_deduplicates_investment_and_aggregated_asset(api_client, db_session):
    """An AggregatedAsset with the same identifier as an Investment is not double-counted."""
    headers = _register_and_login(api_client)
    me = _get_me(api_client, headers)
    user_id = me["id"]

    # Insert an Investment
    inv = Investment(
        user_id=user_id,
        name="Reliance Industries",
        type="stock",
        symbol="RELIANCE",
        quantity=10.0,
        buy_price=2000.0,
        current_price=2500.0,
        invested_amount=20000.0,
        current_value=25000.0,
        is_active=True,
    )
    db_session.add(inv)

    # Inject an AggregatedAsset with the same identifier
    dup_asset = AggregatedAsset(
        user_id=user_id,
        asset_type="stock",
        name="Reliance Industries (AA)",
        identifier="RELIANCE",
        current_value=25000.0,
        invested_value=20000.0,
        source_type="auto",
    )
    db_session.add(dup_asset)
    db_session.commit()

    nw = api_client.get("/api/v1/net-worth", headers=headers)
    assert nw.status_code == 200
    data = nw.json()
    # Stock value should be 25000 (from Investment) not 50000 (double-count)
    stocks_value = (
        data["asset_breakdown"].get("stocks", 0)
        + data["asset_breakdown"].get("stock", 0)
    )
    assert stocks_value == pytest.approx(25000.0, rel=0.01)


def test_net_worth_exposes_connected_institutions_count(api_client):
    """GET /net-worth returns connected_institutions_count field."""
    headers = _register_and_login(api_client)
    r = api_client.get("/api/v1/net-worth", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "connected_institutions_count" in data
    assert isinstance(data["connected_institutions_count"], int)


def test_manual_asset_crud_full_flow(api_client):
    """Create, update, delete a manual asset."""
    headers = _register_and_login(api_client)

    # Create
    r = api_client.post(
        "/api/v1/aggregation/assets/manual",
        json={"name": "Silver bars", "asset_type": "silver", "current_value": 30000.0, "quantity": 100.0, "quantity_unit": "grams"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    asset_id = r.json()["id"]

    # Update
    upd = api_client.patch(
        f"/api/v1/aggregation/assets/{asset_id}",
        json={"current_value": 35000.0},
        headers=headers,
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["current_value"] == 35000.0

    # Delete
    dele = api_client.delete(f"/api/v1/aggregation/assets/{asset_id}", headers=headers)
    assert dele.status_code == 200, dele.text


def test_manual_asset_validation_rejects_negative_value(api_client):
    """current_value < 0 returns 422."""
    headers = _register_and_login(api_client)
    r = api_client.post(
        "/api/v1/aggregation/assets/manual",
        json={"name": "Bad", "asset_type": "gold", "current_value": -100.0},
        headers=headers,
    )
    assert r.status_code == 422


def test_manual_asset_validation_rejects_unknown_type(api_client):
    """Invalid asset_type returns 422."""
    headers = _register_and_login(api_client)
    r = api_client.post(
        "/api/v1/aggregation/assets/manual",
        json={"name": "Bad", "asset_type": "spaceship", "current_value": 100.0},
        headers=headers,
    )
    assert r.status_code == 422
