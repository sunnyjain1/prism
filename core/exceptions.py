import logging
from typing import Any, Optional

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from core.config import settings
from schemas import ErrorResponse

logger = logging.getLogger(__name__)

HTTP_422_VALIDATION = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


def _apply_cors_headers(request: Request, response: JSONResponse) -> JSONResponse:
    origin = request.headers.get("origin")
    if origin and any(origin.startswith(o) for o in settings.ALLOWED_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response


def _error_code_for_status(status_code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "unauthorized",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_409_CONFLICT: "conflict",
        HTTP_422_VALIDATION: "validation_error",
        status.HTTP_429_TOO_MANY_REQUESTS: "rate_limit_exceeded",
    }.get(status_code, "error")


def _build_error_response(
    request: Request,
    *,
    status_code: int,
    error: str,
    message: str,
    details: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    payload = ErrorResponse(error=error, message=message, details=details)
    response = JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
        headers=headers,
    )
    return _apply_cors_headers(request, response)


async def http_exception_handler(request: Request, exc: HTTPException):
    details: Optional[dict[str, Any]] = None
    message = "Request failed"

    if isinstance(exc.detail, str):
        message = exc.detail
    elif isinstance(exc.detail, dict):
        details = exc.detail
        message = exc.detail.get("message") or exc.detail.get("detail") or message
    elif isinstance(exc.detail, list):
        details = {"errors": exc.detail}
        message = "Request validation failed"

    return _build_error_response(
        request,
        status_code=exc.status_code,
        error=_error_code_for_status(exc.status_code),
        message=message,
        details=details,
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _build_error_response(
        request,
        status_code=HTTP_422_VALIDATION,
        error="validation_error",
        message="Request validation failed",
        details={"errors": exc.errors()},
    )


async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    return _build_error_response(
        request,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        error="rate_limit_exceeded",
        message=str(exc.detail),
    )


async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    logger.error(
        "Unhandled exception during request",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={
            "method": request.method,
            "path": request.url.path,
            "request_id": getattr(request.state, "request_id", None),
            "user_id": getattr(request.state, "user_id", None),
        },
    )

    details = None
    if settings.DEBUG and settings.ENVIRONMENT != "production":
        details = {
            "error_type": type(exc).__name__,
            "error_message": error_msg,
        }

    return _build_error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error="internal_server_error",
        message="Internal Server Error",
        details=details,
    )
