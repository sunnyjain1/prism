from contextlib import asynccontextmanager
from time import monotonic

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

import database
import models
import user_models
from api import accounts, auth, budgets, bulk_upload, categorize, categorization_rules, categories, health, health_score, investments, jobs, loans, net_worth, notifications, reports, search, subscriptions, sync, transactions
from core.config import settings
from core.exceptions import (
    global_exception_handler,
    http_exception_handler,
    rate_limit_exception_handler,
    validation_exception_handler,
)
from core.logging import setup_logging
from core.metrics import APIMetrics
from core.middleware import RequestContextMiddleware, RequestLoggingMiddleware
from core.rate_limit import limiter
from core.sentry import init_sentry
from services.scheduler_service import scheduler_lifespan

# Database initialization is now handled by Alembic migrations in start.sh


def _run_migrations() -> None:
    """Run Alembic migrations at startup so the DB schema is always current."""
    import logging
    log = logging.getLogger("alembic.startup")
    try:
        from alembic import command
        from alembic.config import Config
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        log.info("Database migrations applied successfully.")
    except Exception:
        log.exception(
            "Alembic migration failed at startup — the app will still start "
            "but some features may be unavailable until migrations succeed."
        )


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    setup_logging()
    init_sentry()
    _run_migrations()
    app.state.started_at = monotonic()
    app.state.metrics = APIMetrics()

    async with scheduler_lifespan(app):
        yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    redirect_slashes=False,
    lifespan=app_lifespan,
)
app.state.limiter = limiter

# Exception Handling
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestContextMiddleware)

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth.router)
api_v1_router.include_router(transactions.v1_router)
api_v1_router.include_router(accounts.router)
api_v1_router.include_router(categories.router)
api_v1_router.include_router(bulk_upload.router)
api_v1_router.include_router(sync.router)
api_v1_router.include_router(categorization_rules.router)
api_v1_router.include_router(categorize.router)
api_v1_router.include_router(notifications.v1_router)
api_v1_router.include_router(search.router)
api_v1_router.include_router(reports.v1_router)
api_v1_router.include_router(jobs.router)
api_v1_router.include_router(budgets.router)
api_v1_router.include_router(subscriptions.v1_router)
api_v1_router.include_router(investments.router)
api_v1_router.include_router(net_worth.router)
api_v1_router.include_router(health_score.router)
api_v1_router.include_router(loans.v1_router)
app.include_router(api_v1_router)
app.include_router(health.router)

# Legacy routes kept for backward compatibility.
app.include_router(auth.router, include_in_schema=False)
app.include_router(transactions.router, prefix="/api", include_in_schema=False)
app.include_router(accounts.router, prefix="/api", include_in_schema=False)
app.include_router(categories.router, prefix="/api", include_in_schema=False)
app.include_router(bulk_upload.router, prefix="/api", include_in_schema=False)
app.include_router(sync.router, prefix="/api", include_in_schema=False)
app.include_router(categorization_rules.router, prefix="/api", include_in_schema=False)
app.include_router(categorize.router, prefix="/api", include_in_schema=False)
app.include_router(notifications.router, prefix="/api", include_in_schema=False)
app.include_router(reports.router, prefix="/api", include_in_schema=False)
app.include_router(jobs.router, prefix="/api", include_in_schema=False)
app.include_router(budgets.router, prefix="/api", include_in_schema=False)
app.include_router(subscriptions.router, prefix="/api", include_in_schema=False)
app.include_router(investments.router, prefix="/api", include_in_schema=False)
app.include_router(net_worth.router, prefix="/api", include_in_schema=False)
app.include_router(health_score.router, prefix="/api", include_in_schema=False)
app.include_router(loans.router, prefix="/api", include_in_schema=False)


@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}"}
