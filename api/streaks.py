"""Financial Streaks & Achievements API."""
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, get_db
from services.streaks_service import StreaksService
from user_models import User


router = APIRouter(prefix="/streaks", tags=["streaks"])


class LoggingStreak(BaseModel):
    current: int
    longest: int
    last_active: Optional[str] = None


class BudgetStreak(BaseModel):
    current_months: int


class Achievement(BaseModel):
    id: str
    title: str
    description: str
    earned: bool
    category: str


class EngagementStats(BaseModel):
    total_transactions: int
    transactions_this_month: int
    transactions_this_week: int


class StreaksResponse(BaseModel):
    logging_streak: LoggingStreak
    budget_streak: BudgetStreak
    achievements: List[Achievement]
    stats: EngagementStats


@router.get("", response_model=StreaksResponse)
def get_streaks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get user's financial streaks, achievements, and engagement stats."""
    service = StreaksService(db)
    data = service.get_user_streaks(str(current_user.id))
    return StreaksResponse(**data)
