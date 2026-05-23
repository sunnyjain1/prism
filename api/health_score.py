from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.health_score_service import HealthScoreService
from user_models import User

router = APIRouter(prefix="/health-score", tags=["health-score"])


@router.get("", response_model=schemas.HealthScoreResponse)
def get_health_score(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return HealthScoreService().get_current_score(current_user.id, db)


@router.get("/history", response_model=List[schemas.HealthScoreHistoryPoint])
def get_health_score_history(
    months: int = Query(default=12, ge=1, le=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return HealthScoreService().get_health_score_history(current_user.id, db, months=months)
