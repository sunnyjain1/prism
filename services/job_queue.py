from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from threading import Lock
from typing import Any, Callable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    name: str
    status: str
    created_at: datetime
    user_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Any = None


class JobQueue:
    def __init__(self, max_workers: int = 3):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.jobs: dict[str, Job] = {}
        self._lock = Lock()

    def enqueue(self, name: str, func: Callable, *args, user_id: Optional[str] = None, **kwargs) -> str:
        """Submit a job and return job ID."""
        job_id = str(uuid4())
        job = Job(id=job_id, name=name, status="pending", created_at=datetime.utcnow(), user_id=user_id)
        with self._lock:
            self.jobs[job_id] = job

        def wrapper():
            job.status = "running"
            try:
                result = func(*args, **kwargs)
                job.status = "completed"
                job.result = result
                job.completed_at = datetime.utcnow()
            except Exception as exc:  # pragma: no cover - exercised via public status fields
                job.status = "failed"
                job.error = str(exc)
                job.completed_at = datetime.utcnow()
                logger.exception("Job %s (%s) failed", job_id, name)

        self.executor.submit(wrapper)
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self.jobs.get(job_id)

    def get_jobs(self, limit: int = 20, user_id: Optional[str] = None) -> list[Job]:
        with self._lock:
            jobs = list(self.jobs.values())

        if user_id is not None:
            jobs = [job for job in jobs if job.user_id == user_id]

        return sorted(jobs, key=lambda item: item.created_at, reverse=True)[:limit]

    def cleanup_old_jobs(self, max_age_hours: int = 24) -> int:
        """Remove completed jobs older than max_age_hours."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        with self._lock:
            before = len(self.jobs)
            self.jobs = {
                key: value
                for key, value in self.jobs.items()
                if value.created_at > cutoff or value.status == "running"
            }
            return before - len(self.jobs)


job_queue = JobQueue()
