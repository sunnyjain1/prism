from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

import schemas
from core.dependencies import get_current_user
from services.job_queue import Job, job_queue
from user_models import User

router = APIRouter(prefix="/jobs", tags=["jobs"])


def serialize_job(job: Job) -> schemas.JobStatusResponse:
    result = job.result if isinstance(job.result, dict) or job.result is None else {"value": job.result}
    return schemas.JobStatusResponse(
        id=job.id,
        name=job.name,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error=job.error,
        result=result,
    )


@router.get("", response_model=list[schemas.JobStatusResponse])
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    return [serialize_job(job) for job in job_queue.get_jobs(limit=limit, user_id=current_user.id)]


@router.get("/{job_id}", response_model=schemas.JobStatusResponse)
def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    job = job_queue.get_job(job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return serialize_job(job)
