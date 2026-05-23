import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime
from typing import Any

_REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("request_id", default=None)
_USER_ID_CONTEXT: ContextVar[str | None] = ContextVar("user_id", default=None)
_RESERVED_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            request_id = _REQUEST_ID_CONTEXT.get()
            if request_id is not None:
                record.request_id = request_id

        if not hasattr(record, "user_id"):
            user_id = _USER_ID_CONTEXT.get()
            if user_id is not None:
                record.user_id = user_id

        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            log_entry[key] = value if isinstance(value, (dict, list, str, int, float, bool)) or value is None else str(value)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        request_id = log_entry.get("request_id") or _REQUEST_ID_CONTEXT.get()
        user_id = log_entry.get("user_id") or _USER_ID_CONTEXT.get()
        if request_id:
            log_entry["request_id"] = request_id
        if user_id:
            log_entry["user_id"] = user_id

        return json.dumps(log_entry)


def set_request_id(request_id: str | None):
    return _REQUEST_ID_CONTEXT.set(request_id)


def reset_request_id(token) -> None:
    _REQUEST_ID_CONTEXT.reset(token)


def set_user_id(user_id: str | None):
    return _USER_ID_CONTEXT.set(user_id)


def reset_user_id(token) -> None:
    _USER_ID_CONTEXT.reset(token)


def setup_logging() -> None:
    from core.config import settings

    log_level = logging.DEBUG if settings.DEBUG else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    handler.setFormatter(
        JSONFormatter()
        if settings.ENVIRONMENT == "production"
        else logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(log_level)
        logger.propagate = True
