"""Standalone durable pipeline worker process."""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from backend.config import validate_runtime_config
from backend.observability import configure_logging, init_error_reporting
from backend.routes import pipeline

logger = logging.getLogger(__name__)


async def run_worker_loop() -> None:
    """Poll for queued pipeline runs until the process is stopped."""
    config = validate_runtime_config("worker")
    for warning in config.warnings:
        logger.warning("runtime_config_warning", extra={"warning": warning})

    pipeline.requeue_interrupted_pipeline_runs()

    poll_seconds = float(os.environ.get("PIPELINE_WORKER_POLL_SECONDS", "2.0"))
    logger.info(
        "pipeline_worker_started",
        extra={
            "storage_backend": config.storage_backend,
            "poll_seconds": poll_seconds,
        },
    )
    while True:
        try:
            await pipeline.process_queued_runs_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pipeline_worker_iteration_failed")
        await asyncio.sleep(poll_seconds)


def main() -> None:
    """CLI entrypoint for `python -m backend.worker`."""
    load_dotenv()
    configure_logging()
    init_error_reporting()
    asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
