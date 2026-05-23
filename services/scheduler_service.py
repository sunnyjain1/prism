"""
APScheduler-based scheduler for periodic background work.
Runs in-process with the FastAPI app.
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from models import Notification
from services import net_worth_service
from services.job_queue import job_queue
from services.sync_orchestrator import SyncOrchestrator
from user_models import User

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None


def _run_sync_job():
    """Background job: check for due syncs and run them."""
    logger.info("Scheduler: checking for due syncs...")
    db = SessionLocal()
    try:
        orchestrator = SyncOrchestrator(db)
        results = orchestrator.sync_all_due()
        if results:
            success = sum(1 for result in results if result["status"] == "success")
            failed = sum(1 for result in results if result["status"] == "failed")
            logger.info("Scheduler: sync complete - %s success, %s failed", success, failed)
        else:
            logger.info("Scheduler: no accounts due for sync")
    except Exception as exc:
        logger.exception("Scheduler: sync job failed: %s", exc)
    finally:
        db.close()


def _run_net_worth_snapshot_job():
    logger.info("Scheduler: taking daily net worth snapshots...")
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        processed = 0
        for user in users:
            try:
                net_worth_service.take_snapshot(user.id, db)
                processed += 1
            except Exception as exc:
                logger.exception("Scheduler: net worth snapshot failed for user %s: %s", user.id, exc)
        logger.info("Scheduler: net worth snapshot complete for %s users", processed)
    except Exception as exc:
        logger.exception("Scheduler: net worth snapshot job failed: %s", exc)
    finally:
        db.close()


def _run_notification_cleanup_job(days: int = 30):
    logger.info("Scheduler: cleaning up notifications older than %s days", days)
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted_count = (
            db.query(Notification)
            .filter(Notification.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info("Scheduler: deleted %s old notifications", deleted_count)
    except Exception as exc:
        logger.exception("Scheduler: notification cleanup failed: %s", exc)
    finally:
        db.close()


def _run_job_cleanup_job():
    removed_count = job_queue.cleanup_old_jobs()
    logger.info("Scheduler: removed %s expired background jobs", removed_count)


def _register_jobs(scheduler: BackgroundScheduler):
    scheduler.add_job(
        _run_sync_job,
        trigger=IntervalTrigger(hours=6),
        id="gmail_sync_check",
        name="Check for due Gmail syncs",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_net_worth_snapshot_job,
        trigger=IntervalTrigger(days=1),
        id="daily_net_worth_snapshot",
        name="Take daily net worth snapshots",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_notification_cleanup_job,
        trigger=IntervalTrigger(weeks=1),
        id="weekly_notification_cleanup",
        name="Clean up old notifications",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_job_cleanup_job,
        trigger=IntervalTrigger(hours=1),
        id="hourly_job_cleanup",
        name="Clean up expired background jobs",
        replace_existing=True,
    )


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("Scheduler already running")
        return

    _scheduler = BackgroundScheduler()
    _register_jobs(_scheduler)
    _scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


@asynccontextmanager
async def scheduler_lifespan(app):
    """FastAPI lifespan context manager for scheduler."""
    start_scheduler()
    yield
    stop_scheduler()
