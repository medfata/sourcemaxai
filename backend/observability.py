"""Logging and optional error reporting setup for API and worker processes."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

STANDARD_LOG_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in STANDARD_LOG_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Configure root logging once for local or structured deployment output."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)
    log_format = os.environ.get("LOG_FORMAT", "plain").strip().lower()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def init_error_reporting() -> None:
    """Initialize optional Sentry reporting when SENTRY_DSN is configured."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return

    logger = logging.getLogger(__name__)
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("APP_ENV", "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
    )


import threading
from collections import defaultdict


class ProxyMetrics:
    """In-memory metrics for proxy transcript fetching."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, str, str], int] = defaultdict(int)
        self._histograms: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._gauges: dict[tuple[str, str], float] = {}

    def inc_proxy_fetch_total(self, provider: str, outcome: str) -> None:
        with self._lock:
            self._counters[("proxy_fetch_total", provider, outcome)] += 1

    def inc_proxy_fetch_bytes(self, provider: str, bytes_count: int) -> None:
        with self._lock:
            self._counters[("proxy_fetch_bytes", provider, "total")] += bytes_count

    def observe_proxy_fetch_duration(self, provider: str, duration_seconds: float) -> None:
        with self._lock:
            self._histograms[("proxy_fetch_duration_seconds", provider)].append(duration_seconds)

    def set_proxy_circuit_state(self, provider: str, state: int) -> None:
        with self._lock:
            self._gauges[("proxy_circuit_state", provider)] = float(state)

    def set_proxy_blocklist_size(self, provider: str, size: int) -> None:
        with self._lock:
            self._gauges[("proxy_blocklist_size", provider)] = float(size)

    def get_all(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "histograms": {k: list(v) for k, v in self._histograms.items()},
                "gauges": dict(self._gauges),
            }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()


_proxy_metrics: ProxyMetrics | None = None
_metrics_lock = threading.Lock()


def get_proxy_metrics() -> ProxyMetrics:
    global _proxy_metrics
    if _proxy_metrics is None:
        with _metrics_lock:
            if _proxy_metrics is None:
                _proxy_metrics = ProxyMetrics()
    return _proxy_metrics
