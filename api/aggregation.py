"""Financial Aggregation API — connect and sync external data sources."""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, get_db
from models import AggregatedAsset, ConnectionStatus, DataSourceConnection, DataSourceType
from user_models import User

router = APIRouter(prefix="/aggregation", tags=["aggregation"])


class ConnectionCreate(BaseModel):
    source_type: str
    provider_name: str
    display_name: Optional[str] = None
    consent_id: Optional[str] = None


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    provider_name: str
    display_name: Optional[str]
    status: str
    last_synced_at: Optional[datetime]
    error_message: Optional[str]
    created_at: Optional[datetime]


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_type: str
    name: str
    identifier: Optional[str]
    institution: Optional[str]
    current_value: float
    invested_value: float
    returns_absolute: float
    returns_percentage: float
    units: Optional[float]
    nav: Optional[float]
    last_updated: Optional[datetime]


class PortfolioSummary(BaseModel):
    total_current_value: float
    total_invested_value: float
    total_returns: float
    returns_percentage: float
    asset_count: int
    connections_count: int
    last_synced: Optional[datetime]


@router.get("/connections", response_model=List[ConnectionResponse])
def list_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all connected data sources for the user."""
    return (
        db.query(DataSourceConnection)
        .filter(DataSourceConnection.user_id == str(current_user.id))
        .order_by(DataSourceConnection.created_at.desc())
        .all()
    )


@router.post("/connections", response_model=ConnectionResponse, status_code=201)
def create_connection(
    request: ConnectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new data source connection."""
    if request.source_type not in {source_type.value for source_type in DataSourceType}:
        raise HTTPException(status_code=400, detail="Invalid source type")

    connection = DataSourceConnection(
        user_id=str(current_user.id),
        source_type=request.source_type,
        provider_name=request.provider_name,
        display_name=request.display_name or request.provider_name,
        consent_id=request.consent_id,
        status=ConnectionStatus.pending.value,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


@router.delete("/connections/{connection_id}")
def delete_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke and delete a data source connection."""
    conn = (
        db.query(DataSourceConnection)
        .filter(
            DataSourceConnection.id == connection_id,
            DataSourceConnection.user_id == str(current_user.id),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    db.query(AggregatedAsset).filter(AggregatedAsset.connection_id == connection_id).delete()
    db.delete(conn)
    db.commit()
    return {"status": "deleted"}


@router.post("/connections/{connection_id}/sync")
def trigger_sync(
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger a manual sync for a specific connection."""
    conn = (
        db.query(DataSourceConnection)
        .filter(
            DataSourceConnection.id == connection_id,
            DataSourceConnection.user_id == str(current_user.id),
        )
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    conn.status = ConnectionStatus.active.value
    conn.last_synced_at = datetime.utcnow()
    db.commit()
    return {"status": "sync_triggered", "connection_id": connection_id}


@router.get("/assets", response_model=List[AssetResponse])
def list_assets(
    asset_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all aggregated assets for the user."""
    query = db.query(AggregatedAsset).filter(AggregatedAsset.user_id == str(current_user.id))
    if asset_type:
        query = query.filter(AggregatedAsset.asset_type == asset_type)
    return query.order_by(AggregatedAsset.current_value.desc()).all()


@router.get("/portfolio", response_model=PortfolioSummary)
def get_portfolio_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregated portfolio summary across all connected sources."""
    assets = db.query(AggregatedAsset).filter(AggregatedAsset.user_id == str(current_user.id)).all()

    connections = (
        db.query(DataSourceConnection)
        .filter(
            DataSourceConnection.user_id == str(current_user.id),
            DataSourceConnection.status == ConnectionStatus.active.value,
        )
        .all()
    )

    total_current = sum(asset.current_value for asset in assets)
    total_invested = sum(asset.invested_value for asset in assets)
    total_returns = total_current - total_invested
    returns_pct = (total_returns / total_invested * 100) if total_invested > 0 else 0
    last_synced = max((conn.last_synced_at for conn in connections if conn.last_synced_at), default=None)

    return PortfolioSummary(
        total_current_value=total_current,
        total_invested_value=total_invested,
        total_returns=total_returns,
        returns_percentage=returns_pct,
        asset_count=len(assets),
        connections_count=len(connections),
        last_synced=last_synced,
    )


@router.get("/providers")
def list_available_providers():
    """List available data source providers that can be connected."""
    return {
        "providers": [
            {"id": "cams", "name": "CAMS", "type": "mutual_fund", "description": "Mutual fund holdings via CAMS"},
            {"id": "kfintech", "name": "KFintech", "type": "mutual_fund", "description": "Mutual fund holdings via KFintech"},
            {"id": "cdsl", "name": "CDSL", "type": "stock", "description": "Demat holdings via CDSL"},
            {"id": "nsdl", "name": "NSDL", "type": "stock", "description": "Demat holdings via NSDL"},
            {"id": "cibil", "name": "CIBIL", "type": "credit_bureau", "description": "Credit score and report"},
            {"id": "experian", "name": "Experian", "type": "credit_bureau", "description": "Credit score and report"},
            {"id": "epfo", "name": "EPFO", "type": "epf", "description": "Employee Provident Fund balance"},
            {"id": "nps", "name": "NPS", "type": "nps", "description": "National Pension System"},
        ]
    }
