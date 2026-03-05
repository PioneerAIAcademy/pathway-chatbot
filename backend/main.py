# flake8: noqa: E402
from dotenv import load_dotenv

from app.config import DATA_DIR

load_dotenv()

import logging
import os

import uvicorn
from app.api.routers.chat import chat_router
from app.api.routers.chat_config import config_router
from app.api.routers.upload import file_upload_router
from app.api.routers.health import health_router
from app.observability import init_observability
from app.settings import init_settings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

CHAT_MAX_BODY_SIZE = 512 * 1024         # 512KB for full conversation payload
FEEDBACK_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10MB for feedback screenshots


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            size = int(content_length)
            path = request.url.path
            if path.startswith("/api/chat/feedback"):
                limit = FEEDBACK_MAX_BODY_SIZE
                label = "10MB"
            else:
                limit = CHAT_MAX_BODY_SIZE
                label = "10KB"
            if size > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Maximum size is {label}."},
                )
        return await call_next(request)

app = FastAPI()

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Enforce size limits: 10KB for chat, 10MB for feedback/screenshots
app.add_middleware(RequestSizeLimitMiddleware)

init_settings()
init_observability()

# Initialize monitoring
from app.middleware.monitoring_middleware import MonitoringMiddleware
from app.scheduler import get_monitoring_scheduler

# Add monitoring middleware
app.add_middleware(MonitoringMiddleware)

# Start monitoring scheduler
monitoring_scheduler = get_monitoring_scheduler()

environment = os.getenv("ENVIRONMENT", "dev")  # Default to 'development' if not set
logger = logging.getLogger("uvicorn")

if environment == "dev":
    logger.warning("Running in development mode - allowing CORS for all origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Redirect to documentation page when accessing base URL
    @app.get("/")
    async def redirect_to_docs():
        return RedirectResponse(url="/docs")
else:
    raw_origins = os.getenv("ALLOWED_ORIGINS", "")
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    if not allowed_origins:
        logger.error("ALLOWED_ORIGINS is not set in production! CORS will block all frontend requests.")
    logger.info(f"Production CORS allowed origins: {allowed_origins}")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Session-ID", "X-Device-ID"],
    )


def mount_static_files(directory, path):
    if os.path.exists(directory):
        logger.info(f"Mounting static files '{directory}' at '{path}'")
        app.mount(
            path,
            StaticFiles(directory=directory, check_dir=False),
            name=f"{directory}-static",
        )


# Mount the data files to serve the file viewer
mount_static_files(DATA_DIR, "/api/files/data")
# Mount the output files from tools
mount_static_files("output", "/api/files/output")

app.include_router(chat_router, prefix="/api/chat")
app.include_router(config_router, prefix="/api/chat/config")
app.include_router(file_upload_router, prefix="/api/chat/upload")
app.include_router(health_router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    # Start malloc_trim to return freed memory to OS (Step 2)
    from app.memory_trim import start_malloc_trimmer
    start_malloc_trimmer(period_sec=300)  # Every 5 minutes
    
    # Disabled monitoring for now - relying on Render's memory tracking instead
    # logger.info("Starting monitoring scheduler...")
    # monitoring_scheduler.start()
    
    # # Run startup recovery to upload any unsaved reports from previous session
    # logger.info("Running monitoring startup recovery...")
    # await monitoring_scheduler.monitoring_service.startup_recovery()
    
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    # Disabled monitoring for now - relying on Render's memory tracking instead
    # logger.info("Shutting down monitoring scheduler...")
    # await monitoring_scheduler.shutdown()
    
    # Close shared HTTP client
    from app.http_client import close_http_client
    await close_http_client()
    
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    app_host = os.getenv("APP_HOST", "0.0.0.0")
    app_port = int(os.getenv("APP_PORT", "8000"))
    reload = True if environment == "dev" else False

    uvicorn.run(app="main:app", host=app_host, port=app_port, reload=reload)
