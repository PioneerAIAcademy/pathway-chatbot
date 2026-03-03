import json
import logging
import os
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for easier parsing in production."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # Include request_id when set by RequestIDFilter
        request_id = getattr(record, "request_id", None)
        if request_id and request_id != "-":
            log_obj["request_id"] = request_id
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def init_observability():
    from app.middleware.monitoring_middleware import RequestIDFilter

    environment = os.getenv("ENVIRONMENT", "dev")
    request_id_filter = RequestIDFilter()
    if environment != "dev":
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            log = logging.getLogger(name)
            log.handlers = [handler]
            log.propagate = False
            log.addFilter(request_id_filter)
    else:
        # Install filter in dev too so request_id appears in plain-text logs
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            logging.getLogger(name).addFilter(request_id_filter)
