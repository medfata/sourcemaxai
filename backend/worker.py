"""Standalone durable pipeline worker process."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

from backend import storage
from backend.config import load_runtime_config, validate_runtime_config
from backend.observability import configure_logging, init_error_reporting
from backend.pipeline.proxy_pool import BlocklistStore, CircuitBreaker
from backend.routes import pipeline

logger = logging.getLogger(__name__)

BLOCKLIST_CLEANUP_INTERVAL = 600  # 10 min
CIRCUIT_PROBE_INTERVAL = 300  # 5 min


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
    last_blocklist_cleanup = 0.0
    last_circuit_probe = 0.0
    while True:
        try:
            await pipeline.process_queued_runs_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pipeline_worker_iteration_failed")

        now = time.monotonic()

        if now - last_blocklist_cleanup >= BLOCKLIST_CLEANUP_INTERVAL:
            try:
                blocklist = BlocklistStore(storage.SupabaseStorageBackend.from_env())
                cleaned = blocklist.cleanup_expired()
                if cleaned > 0:
                    logger.info("proxy_blocklist_cleanup", extra={"cleaned": cleaned})
            except Exception:
                logger.exception("proxy_blocklist_cleanup_failed")
            last_blocklist_cleanup = now

        if now - last_circuit_probe >= CIRCUIT_PROBE_INTERVAL:
            try:
                breaker = CircuitBreaker(storage.SupabaseStorageBackend.from_env())
                cfg = load_runtime_config()
                providers = []
                if cfg.proxy.iproyal_enabled:
                    providers.append("iproyal")
                if cfg.proxy.webshare_enabled:
                    providers.append("webshare")
                for provider_name in providers:
                    if breaker.should_probe(provider_name):
                        logger.info("circuit_breaker_probe", extra={"provider": provider_name, "status": "half_open"})
            except Exception:
                logger.exception("circuit_breaker_probe_failed")
            last_circuit_probe = now

        await asyncio.sleep(poll_seconds)


def main() -> None:
    """CLI entrypoint for `python -m backend.worker`."""
    load_dotenv()
    configure_logging()
    init_error_reporting()
    asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
