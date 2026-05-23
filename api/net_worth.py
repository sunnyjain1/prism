from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services import net_worth_service
from user_models import User

router = APIRouter(prefix="/net-worth", tags=["net-worth"])


@router.get("", response_model=schemas.NetWorthSummary)
def get_current_net_worth(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return net_worth_service.calculate_current_net_worth(current_user.id, db)


@router.get("/history", response_model=List[schemas.NetWorthHistoryPoint])
def get_net_worth_history(
    months: int = Query(default=12, ge=1, le=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return net_worth_service.get_net_worth_history(current_user.id, db, months=months)


@router.get("/allocation", response_model=schemas.AssetAllocationResponse)
def get_asset_allocation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return net_worth_service.get_asset_allocation(current_user.id, db)


@router.post("/snapshot", response_model=schemas.NetWorthSnapshotResponse)
def create_net_worth_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return net_worth_service.take_snapshot(current_user.id, db)
