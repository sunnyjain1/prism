from time import monotonic

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import settings
from database import engine
from services.cache_service import cache
from services.search_service import SearchService

router = APIRouter(tags=["observability"])


def _uptime_seconds(request: Request) -> float:
    started_at = getattr(request.app.state, "started_at", monotonic())
    return round(monotonic() - started_at, 2)


def _database_status() -> str:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def _search_status() -> str:
    if not settings.SEARCH_ENABLED:
        return "disabled"
    return "ok" if SearchService().is_available() else "error"


def _cache_status() -> str:
    if not cache.enabled:
        return "disabled"
    try:
        return "ok" if cache.client.ping() else "error"
    except Exception:
        return "error"


@router.get("/health")
def health(request: Request):
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "uptime_seconds": _uptime_seconds(request),
    }


@router.get("/health/ready")
def readiness(request: Request):
    checks = {
        "database": _database_status(),
        "search": _search_status(),
        "cache": _cache_status(),
    }
    healthy = (
        checks["database"] == "ok"
        and checks["search"] in {"ok", "disabled"}
        and checks["cache"] in {"ok", "disabled"}
    )
    payload = {
        "status": "healthy" if healthy else "unhealthy",
        "checks": checks,
        "version": settings.APP_VERSION,
        "uptime_seconds": _uptime_seconds(request),
    }
    return JSONResponse(status_code=200 if healthy else 503, content=payload)


@router.get("/metrics")
def metrics(request: Request):
    metrics_store = getattr(request.app.state, "metrics", None)
    payload = metrics_store.snapshot() if metrics_store is not None else {
        "request_count": 0,
        "error_count": 0,
        "average_response_time_ms": 0.0,
        "max_response_time_ms": 0.0,
        "routes": {},
    }
    payload.update({
        "version": settings.APP_VERSION,
        "uptime_seconds": _uptime_seconds(request),
    })
    return payload
