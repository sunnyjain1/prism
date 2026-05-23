from datetime import datetime, timedelta
from time import sleep, time

from services.job_queue import Job, JobQueue


def _wait_for_completion(queue: JobQueue, job_id: str, timeout: float = 2.0):
    deadline = time() + timeout
    while time() < deadline:
        job = queue.get_job(job_id)
        if job is not None and job.status in {"completed", "failed"}:
            return job
        sleep(0.01)
    raise AssertionError("job did not complete in time")


def test_job_queue_completes_and_records_result():
    queue = JobQueue(max_workers=1)
    try:
        job_id = queue.enqueue("double_value", lambda value: {"value": value * 2}, 4, user_id="user-1")
        job = _wait_for_completion(queue, job_id)

        assert job.status == "completed"
        assert job.result == {"value": 8}
        assert [item.id for item in queue.get_jobs(user_id="user-1")] == [job_id]
    finally:
        queue.executor.shutdown(wait=True)


def test_job_queue_cleanup_removes_old_completed_jobs():
    queue = JobQueue(max_workers=1)
    try:
        old_job = Job(
            id="old-job",
            name="finished_job",
            status="completed",
            created_at=datetime.utcnow() - timedelta(hours=30),
            user_id="user-1",
            completed_at=datetime.utcnow() - timedelta(hours=29),
        )
        running_job = Job(
            id="running-job",
            name="active_job",
            status="running",
            created_at=datetime.utcnow() - timedelta(hours=30),
            user_id="user-1",
        )
        queue.jobs = {old_job.id: old_job, running_job.id: running_job}

        removed = queue.cleanup_old_jobs(max_age_hours=24)

        assert removed == 1
        assert queue.get_job("old-job") is None
        assert queue.get_job("running-job") is running_job
    finally:
        queue.executor.shutdown(wait=True)
