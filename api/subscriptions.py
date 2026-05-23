from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import schemas
from core.dependencies import get_current_user, get_db
from services.subscription_service import SubscriptionService
from user_models import User

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
v1_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@v1_router.get("", response_model=List[schemas.Subscription])
@router.get("", response_model=List[schemas.Subscription])
def read_subscriptions(
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    return service.get_subscriptions(current_user.id, active_only=active_only)


@v1_router.get("/detect", response_model=List[schemas.SubscriptionDetectionSuggestion])
@router.get("/detect", response_model=List[schemas.SubscriptionDetectionSuggestion])
def detect_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    return service.detect_recurring_transactions(current_user.id)


@v1_router.get("/summary", response_model=schemas.SubscriptionSummaryResponse)
@router.get("/summary", response_model=schemas.SubscriptionSummaryResponse)
def get_subscription_summary(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    active_subscriptions = service.get_subscriptions(current_user.id, active_only=True)
    return {
        "monthly_cost": service.get_monthly_subscription_cost(current_user.id),
        "active_count": len(active_subscriptions),
        "upcoming_renewals": service.get_upcoming_renewals(current_user.id, days=days),
        "currency_breakdown": service.get_monthly_subscription_breakdown(current_user.id),
    }


@v1_router.post("", response_model=schemas.Subscription)
@router.post("", response_model=schemas.Subscription)
def create_subscription(
    subscription: schemas.SubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    return service.create_subscription(current_user.id, subscription)


@v1_router.post("/{subscription_id}/confirm", response_model=schemas.Subscription)
@router.post("/{subscription_id}/confirm", response_model=schemas.Subscription)
def confirm_detected_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    return service.confirm_detected_subscription(current_user.id, subscription_id)


@v1_router.put("/{subscription_id}", response_model=schemas.Subscription)
@router.put("/{subscription_id}", response_model=schemas.Subscription)
def update_subscription(
    subscription_id: str,
    subscription: schemas.SubscriptionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    return service.update_subscription(current_user.id, subscription_id, subscription)


@v1_router.delete("/{subscription_id}", response_model=schemas.MessageResponse)
@router.delete("/{subscription_id}", response_model=schemas.MessageResponse)
def cancel_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SubscriptionService(db)
    service.cancel_subscription(current_user.id, subscription_id)
    return {"message": "Subscription cancelled successfully"}
