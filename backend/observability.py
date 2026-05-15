"""Logging and optional error reporting setup for API and worker processes."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

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


def log_daily_proxy_summary(quota_store: Any) -> dict[str, Any]:
    """Log daily proxy usage summary: bytes per provider, per tier, top-10 users."""
    from backend.quotas import LocalQuotaStore, SupabaseQuotaStore

    if isinstance(quota_store, LocalQuotaStore):
        return {}

    if not isinstance(quota_store, SupabaseQuotaStore):
        return {}

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    backend = quota_store.backend

    rows = backend._select(
        "usage_events",
        select="owner_id,proxy_provider,proxy_bytes",
        filters={
            "event_type": quota_store._eq("transcript_fetch"),
            "created_at": f"gte.{cutoff}",
            "proxy_bytes": "gt.0",
        },
        limit=10000,
    )

    by_provider: dict[str, int] = {}
    by_user: dict[str, int] = {}
    total_bytes = 0

    for row in rows:
        provider = str(row.get("proxy_provider") or "unknown")
        owner = str(row.get("owner_id") or "unknown")
        b = int(row.get("proxy_bytes") or 0)
        by_provider[provider] = by_provider.get(provider, 0) + b
        by_user[owner] = by_user.get(owner, 0) + b
        total_bytes += b

    tier_rows = backend._select("user_quotas", select="owner_id,tier_key", limit=10000)
    tier_map = {str(r["owner_id"]): str(r["tier_key"]) for r in tier_rows if r.get("owner_id")}

    by_tier: dict[str, int] = {}
    for owner, b in by_user.items():
        tier = tier_map.get(owner, "unknown")
        by_tier[tier] = by_tier.get(tier, 0) + b

    top_users = sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:10]

    summary = {
        "period": "last_24h",
        "total_proxy_bytes": total_bytes,
        "by_provider": by_provider,
        "by_tier": by_tier,
        "top_users": [{"owner_id": u, "proxy_bytes": b} for u, b in top_users],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info("daily_proxy_summary: %s", json.dumps(summary, default=str))
    return summary
