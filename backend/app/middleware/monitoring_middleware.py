"""
Middleware for automatic request monitoring.
Captures all requests and sends metrics to the monitoring service.
"""

import time
import uuid
import sys
import traceback
import psutil
from contextvars import ContextVar
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging

from app.monitoring import get_monitoring_service

logger = logging.getLogger("uvicorn")

# Stores the active request ID for the current async context.
# Default "-" means "no active request" (e.g. startup logs).
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    """Injects the current request_id into every log record it touches."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class MonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware that automatically tracks all HTTP requests."""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.monitoring_service = get_monitoring_service()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique request ID and bind it to the current async context
        request_id = str(uuid.uuid4())
        token = request_id_ctx.set(request_id)

        # LoggerAdapter so every log from this middleware carries request_id
        log = logging.LoggerAdapter(logger, {"request_id": request_id})

        # Extract request info
        endpoint = request.url.path
        method = request.method

        # Record request start
        start_time = self.monitoring_service.metrics_collector.record_request_start(
            request_id=request_id,
            endpoint=endpoint,
            method=method
        )

        # Initialize metadata
        metadata = {
            "user_agent": request.headers.get("user-agent", "unknown"),
            "client_ip": self._get_client_ip(request),
        }

        error = None
        status_code = 500  # Default to error

        try:
            # Process request
            response = await call_next(request)
            status_code = response.status_code

            # Add response headers for tracing
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            error = str(e)

            # Enhanced error context for crash diagnosis
            error_context = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "traceback": traceback.format_exc(),
            }

            # Capture memory state at crash time
            try:
                process = psutil.Process()
                mem_info = process.memory_info()
                error_context.update({
                    "crash_memory_rss_mb": mem_info.rss / 1024 / 1024,
                    "crash_memory_vms_mb": mem_info.vms / 1024 / 1024,
                    "crash_memory_percent": process.memory_percent(),
                    "crash_num_threads": process.num_threads(),
                })
            except Exception as mem_error:
                log.warning(f"Could not capture crash memory state: {mem_error}")

            # Add to metadata for detailed logging
            metadata.update(error_context)

            log.error(
                f"Request crashed: {error_context['error_type']} - {error}\n"
                f"Memory at crash: {error_context.get('crash_memory_rss_mb', 'N/A')} MB\n"
                f"Traceback:\n{error_context['traceback']}"
            )
            raise

        finally:
            # Reset request ID context var and record request end
            request_id_ctx.reset(token)
            self.monitoring_service.metrics_collector.record_request_end(
                request_id=request_id,
                endpoint=endpoint,
                method=method,
                start_time=start_time,
                status_code=status_code,
                error=error,
                metadata=metadata
            )
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract real client IP from headers (handles proxies/load balancers)."""
        # Check X-Forwarded-For header first (set by proxies/load balancers)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs, get the first (original client)
            return forwarded_for.split(",")[0].strip()
        
        # Fallback to direct client host
        return request.client.host if request.client else "unknown"
