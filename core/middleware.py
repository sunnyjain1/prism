import logging
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core.logging import reset_request_id, reset_user_id, set_request_id, set_user_id

logger = logging.getLogger("prism.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        request.state.user_id = getattr(request.state, "user_id", None)

        request_token = set_request_id(request_id)
        user_token = set_user_id(getattr(request.state, "user_id", None))
        try:
            response = await call_next(request)
        finally:
            reset_user_id(user_token)
            reset_request_id(request_token)

        response.headers["X-Request-ID"] = request_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            request_id = getattr(request.state, "request_id", None)
            user_id = getattr(request.state, "user_id", None)
            self._record_metrics(request, 500, duration_ms)
            logger.exception(
                self._log_message(request.method, request.url.path, 500, duration_ms, request_id, user_id),
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "request_id": request_id,
                    "user_id": user_id,
                },
            )
            raise

        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        request_id = getattr(request.state, "request_id", None)
        user_id = getattr(request.state, "user_id", None)
        self._record_metrics(request, response.status_code, duration_ms)
        log_method = logger.warning if response.status_code >= 500 else logger.info
        log_method(
            self._log_message(request.method, request.url.path, response.status_code, duration_ms, request_id, user_id),
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
                "user_id": user_id,
            },
        )
        return response

    @staticmethod
    def _log_message(
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        request_id: str | None,
        user_id: str | None,
    ) -> str:
        message = f"{method} {path} -> {status_code} in {duration_ms}ms"
        if request_id:
            message += f" request_id={request_id}"
        if user_id:
            message += f" user_id={user_id}"
        return message

    @staticmethod
    def _record_metrics(request: Request, status_code: int, duration_ms: float) -> None:
        metrics = getattr(request.app.state, "metrics", None)
        if metrics is not None:
            metrics.record_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
