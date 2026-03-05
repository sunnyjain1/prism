"""
APScheduler-based scheduler for periodic Gmail sync.
Runs in-process with the FastAPI app.
"""
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from services.sync_orchestrator import SyncOrchestrator

logger = logging.getLogger(__name__)

# Single global scheduler instance
_scheduler: BackgroundScheduler = None


def _run_sync_job():
    """Background job: check for due syncs and run them."""
    logger.info("Scheduler: checking for due syncs...")
    db = SessionLocal()
    try:
        orchestrator = SyncOrchestrator(db)
        results = orchestrator.sync_all_due()
        if results:
            success = sum(1 for r in results if r["status"] == "success")
            failed = sum(1 for r in results if r["status"] == "failed")
            logger.info(f"Scheduler: sync complete - {success} success, {failed} failed")
        else:
            logger.info("Scheduler: no accounts due for sync")
    except Exception as e:
        logger.exception(f"Scheduler: sync job failed: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("Scheduler already running")
        return

    _scheduler = BackgroundScheduler()
    # Check every 6 hours for due syncs
    _scheduler.add_job(
        _run_sync_job,
        trigger=IntervalTrigger(hours=6),
        id="gmail_sync_check",
        name="Check for due Gmail syncs",
        replace_existing=True
    )
    _scheduler.start()
    logger.info("Scheduler started: checking for due syncs every 6 hours")


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
