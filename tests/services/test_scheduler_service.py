from unittest.mock import MagicMock

from services import scheduler_service


def test_register_jobs_adds_expected_background_tasks():
    scheduler = MagicMock()

    scheduler_service._register_jobs(scheduler)

    job_ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]
    assert job_ids == [
        "gmail_sync_check",
        "daily_net_worth_snapshot",
        "weekly_notification_cleanup",
        "hourly_job_cleanup",
    ]
