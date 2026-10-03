"""Discovery API — start and poll multi-phase financial discovery sessions."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from core.dependencies import get_current_user, get_db
from models import DiscoverySession
from services.financial_discovery_orchestrator import FinancialDiscoveryOrchestrator
from user_models import User

router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryStartRequest(BaseModel):
    categories: Optional[List[str]] = None  # None means all phases


class DiscoveryCategoryStatusOut(BaseModel):
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    requires_manual_setup: bool = False


class DiscoverySessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    overall_status: str
    job_id: Optional[str]
    phases: Dict[str, DiscoveryCategoryStatusOut]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: Optional[datetime]


def _session_to_out(session: DiscoverySession) -> DiscoverySessionOut:
    import json
    phases_raw = json.loads(session.phases_json or "{}")
    phases = {
        k: DiscoveryCategoryStatusOut(**v) if isinstance(v, dict) else DiscoveryCategoryStatusOut()
        for k, v in phases_raw.items()
    }
    return DiscoverySessionOut(
        session_id=session.id,
        overall_status=session.status,
        job_id=session.job_id,
        phases=phases,
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
    )


@router.post("/start", response_model=DiscoverySessionOut, status_code=202)
def start_discovery(
    request: DiscoveryStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Start a new financial discovery session.
    Runs asynchronously. Poll GET /discovery/status for progress.
    """
    orchestrator = FinancialDiscoveryOrchestrator(db)
    session = orchestrator.start_discovery(
        user_id=str(current_user.id),
        categories=request.categories,
    )
    return _session_to_out(session)


@router.get("/status", response_model=DiscoverySessionOut)
def get_latest_discovery_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the most recent discovery session status for the current user."""
    orchestrator = FinancialDiscoveryOrchestrator(db)
    session = orchestrator.get_latest_session(user_id=str(current_user.id))
    if not session:
        raise HTTPException(status_code=404, detail="No discovery session found")
    return _session_to_out(session)


@router.get("/status/{session_id}", response_model=DiscoverySessionOut)
def get_discovery_status_by_id(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific discovery session by ID."""
    orchestrator = FinancialDiscoveryOrchestrator(db)
    session = orchestrator.get_session_status(session_id=session_id, user_id=str(current_user.id))
    if not session:
        raise HTTPException(status_code=404, detail="Discovery session not found")
    return _session_to_out(session)


@router.get("/sessions", response_model=List[DiscoverySessionOut])
def list_discovery_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List last 10 discovery sessions for the current user."""
    orchestrator = FinancialDiscoveryOrchestrator(db)
    sessions = orchestrator.get_sessions(user_id=str(current_user.id), limit=10)
    return [_session_to_out(s) for s in sessions]
