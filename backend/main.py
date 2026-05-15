"""FastAPI application entrypoint."""

import logging
from time import perf_counter

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from backend.config import (  # noqa: E402
    embedded_worker_enabled,
    runtime_report,
    validate_runtime_config,
)
from backend.observability import configure_logging, init_error_reporting  # noqa: E402

configure_logging()
init_error_reporting()

from backend.routes import channel, chat, pipeline, profile, quota, videos, waitlist  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="Trace", version="0.1.0")
runtime_config = validate_runtime_config("api", strict=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=runtime_config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(channel.router)
app.include_router(videos.router)
app.include_router(pipeline.router)
app.include_router(profile.router)
app.include_router(chat.router)
app.include_router(waitlist.router)
app.include_router(quota.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Emit one structured access log entry per request."""
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((perf_counter() - start) * 1000, 2)
        logger.exception(
            "request_failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
            },
        )
        raise

    duration_ms = round((perf_counter() - start) * 1000, 2)
    logger.info(
        "request_completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.on_event("startup")
async def start_pipeline_worker() -> None:
    """Validate environment and optionally run the local embedded worker."""
    config = validate_runtime_config("api", strict=False)
    if not config.ok:
        logger.error("runtime_config_errors", extra={"errors": config.errors})
    for warning in config.warnings:
        logger.warning("runtime_config_warning", extra={"warning": warning})

    if embedded_worker_enabled():
        pipeline.requeue_interrupted_pipeline_runs()
        pipeline.ensure_pipeline_worker_started()


@app.get("/api/health")
def health_check() -> dict:
    """Return a simple health check response."""
    return {"ok": True}


@app.get("/api/ready")
def readiness_check() -> JSONResponse:
    """Return deployment readiness without exposing secret values."""
    report = runtime_report("api")
    status_code = 200 if report["ok"] else 503
    return JSONResponse(report, status_code=status_code)
