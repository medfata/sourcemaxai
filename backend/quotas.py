"""Per-user quota and usage ledger for Phase 6 abuse controls."""

from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any
from uuid import UUID

from backend import storage

DEFAULT_TIER_KEY = "free"
DEFAULT_TIER_DISPLAY_NAME = "Free"
TRANSCRIPT_WORDS_PER_MINUTE = 150
DEFAULT_MONTHLY_TRANSCRIPT_SECONDS = 150 * 60
DEFAULT_MONTHLY_CHAT_MESSAGES = 20
DEFAULT_MAX_TRANSCRIPT_SECONDS_PER_RUN = 30 * 60
DEFAULT_MONTHLY_TOKEN_LIMIT = 1_000_000
DEFAULT_MONTHLY_COST_LIMIT_USD = 5.0
DEFAULT_MAX_CONCURRENT_RUNS = 1
DEFAULT_CHAT_PER_MINUTE_LIMIT = 10
DEFAULT_PROXY_BYTES_PER_MONTH = 524_288_000
DEFAULT_PROXY_REQUESTS_PER_MINUTE = 30
DEFAULT_TRANSCRIPT_CONCURRENCY = 2

SUMMARY_INPUT_USD_PER_M_TOKENS = 0.30
SUMMARY_OUTPUT_USD_PER_M_TOKENS = 1.20

ACTIVE_RUN_STATUSES = ("queued", "running", "awaiting_confirm_summaries", "cancel_requested")


@dataclass(frozen=True)
class Quota:
    """Per-user enforcement ceilings loaded from user_quotas."""

    tier_key: str = DEFAULT_TIER_KEY
    display_name: str = DEFAULT_TIER_DISPLAY_NAME
    monthly_transcript_seconds: int = DEFAULT_MONTHLY_TRANSCRIPT_SECONDS
    monthly_chat_messages: int = DEFAULT_MONTHLY_CHAT_MESSAGES
    max_transcript_seconds_per_run: int = DEFAULT_MAX_TRANSCRIPT_SECONDS_PER_RUN
    monthly_token_limit: int = DEFAULT_MONTHLY_TOKEN_LIMIT
    monthly_cost_limit_usd: float = DEFAULT_MONTHLY_COST_LIMIT_USD
    max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS
    chat_per_minute_limit: int = DEFAULT_CHAT_PER_MINUTE_LIMIT
    credit_transcript_seconds: int = 0
    proxy_bytes_per_month: int = DEFAULT_PROXY_BYTES_PER_MONTH
    proxy_requests_per_minute: int = DEFAULT_PROXY_REQUESTS_PER_MINUTE
    transcript_concurrency: int = DEFAULT_TRANSCRIPT_CONCURRENCY


@dataclass
class MonthlyUsage:
    """Aggregated usage for the current calendar month."""

    videos: int = 0
    transcript_seconds: int = 0
    chat_messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    proxy_bytes: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class QuotaDecision:
    """Outcome of a guard check, returned to API callers."""

    allowed: bool
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def estimate_summary_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Estimate model spend for a summarization call in USD."""
    input_cost = input_tokens / 1_000_000 * SUMMARY_INPUT_USD_PER_M_TOKENS
    output_cost = output_tokens / 1_000_000 * SUMMARY_OUTPUT_USD_PER_M_TOKENS
    return round(input_cost + output_cost, 6)


def transcript_seconds_from_word_count(word_count: int) -> int:
    """Convert transcript words into billable transcript seconds."""
    words = int(max(word_count, 0))
    if words == 0:
        return 0
    return int(ceil(words * 60 / TRANSCRIPT_WORDS_PER_MINUTE))


def transcript_seconds_from_transcript(transcript: dict[str, Any] | None) -> int:
    """Return billable transcript seconds for a fetched transcript payload."""
    if not isinstance(transcript, dict):
        return 0
    if transcript.get("source") in ("", "unavailable"):
        return 0
    word_count = transcript.get("word_count")
    if isinstance(word_count, int | float):
        return transcript_seconds_from_word_count(int(word_count))
    text = transcript.get("transcript_text")
    if isinstance(text, str):
        return transcript_seconds_from_word_count(len(text.split()))
    return 0


def month_window_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return [start, end) of the current UTC calendar month."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


class QuotaStore(ABC):
    """Persistence API for quotas and usage events."""

    is_enforced = False

    @abstractmethod
    def get_quota(self, owner_id: str) -> Quota:
        """Return the per-user quota row, defaults if missing."""

    @abstractmethod
    def get_monthly_usage(self, owner_id: str) -> MonthlyUsage:
        """Return aggregated usage for the current calendar month."""

    @abstractmethod
    def count_active_runs(self, owner_id: str) -> int:
        """Return the number of pipeline runs currently consuming a slot."""

    @abstractmethod
    def chat_count_in_window(self, owner_id: str, *, window_seconds: int) -> int:
        """Return chat events recorded in the last ``window_seconds`` seconds."""

    @abstractmethod
    def get_active_credit_seconds(self, owner_id: str) -> int:
        """Return unexpired unused transcript-second credits."""

    @abstractmethod
    def record_usage(
        self,
        owner_id: str,
        *,
        event_type: str,
        run_id: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        transcript_seconds: int = 0,
        chat_messages: int = 0,
        cost_usd: float = 0.0,
        proxy_bytes: int = 0,
        proxy_provider: str | None = None,
    ) -> None:
        """Persist a usage_events row for billing + rate limiting."""


class LocalQuotaStore(QuotaStore):
    """Dev-only quota store: returns defaults and never enforces."""

    is_enforced = False

    def get_quota(self, owner_id: str) -> Quota:
        return Quota()

    def get_monthly_usage(self, owner_id: str) -> MonthlyUsage:
        return MonthlyUsage()

    def count_active_runs(self, owner_id: str) -> int:
        return 0

    def chat_count_in_window(self, owner_id: str, *, window_seconds: int) -> int:
        return 0

    def get_active_credit_seconds(self, owner_id: str) -> int:
        return 0

    def record_usage(
        self,
        owner_id: str,
        *,
        event_type: str,
        run_id: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        transcript_seconds: int = 0,
        chat_messages: int = 0,
        cost_usd: float = 0.0,
        proxy_bytes: int = 0,
        proxy_provider: str | None = None,
    ) -> None:
        return None


class SupabaseQuotaStore(QuotaStore):
    """Supabase-backed quota store using service-role PostgREST."""

    is_enforced = True

    def __init__(self, backend: storage.SupabaseStorageBackend) -> None:
        self.backend = backend

    @staticmethod
    def _eq(value: str) -> str:
        return f"eq.{value}"

    def get_quota(self, owner_id: str) -> Quota:
        quota_rows = self.backend._select(
            "user_quotas",
            select="tier_key",
            filters={"owner_id": self._eq(owner_id)},
            limit=1,
        )
        tier_key = DEFAULT_TIER_KEY
        if quota_rows:
            tier_key = str(quota_rows[0].get("tier_key") or DEFAULT_TIER_KEY)

        tier_rows = self.backend._select(
            "plan_tiers",
            filters={"tier_key": self._eq(tier_key)},
            limit=1,
        )
        if not tier_rows and tier_key != DEFAULT_TIER_KEY:
            tier_key = DEFAULT_TIER_KEY
            tier_rows = self.backend._select(
                "plan_tiers",
                filters={"tier_key": self._eq(DEFAULT_TIER_KEY)},
                limit=1,
            )

        if not tier_rows:
            return Quota()
        row = tier_rows[0]
        return Quota(
            tier_key=str(row.get("tier_key") or DEFAULT_TIER_KEY),
            display_name=str(row.get("display_name") or DEFAULT_TIER_DISPLAY_NAME),
            monthly_transcript_seconds=int(
                row.get("monthly_transcript_seconds", DEFAULT_MONTHLY_TRANSCRIPT_SECONDS)
            ),
            monthly_chat_messages=int(
                row.get("monthly_chat_messages", DEFAULT_MONTHLY_CHAT_MESSAGES)
            ),
            max_transcript_seconds_per_run=int(
                row.get(
                    "max_transcript_seconds_per_run",
                    DEFAULT_MAX_TRANSCRIPT_SECONDS_PER_RUN,
                )
            ),
            monthly_token_limit=int(row.get("monthly_token_limit", DEFAULT_MONTHLY_TOKEN_LIMIT)),
            monthly_cost_limit_usd=float(
                row.get("monthly_cost_limit_usd", DEFAULT_MONTHLY_COST_LIMIT_USD)
            ),
            max_concurrent_runs=int(row.get("max_concurrent_runs", DEFAULT_MAX_CONCURRENT_RUNS)),
            chat_per_minute_limit=int(
                row.get("chat_per_minute_limit", DEFAULT_CHAT_PER_MINUTE_LIMIT)
            ),
            credit_transcript_seconds=self.get_active_credit_seconds(owner_id),
            proxy_bytes_per_month=int(
                row.get("proxy_bytes_per_month", DEFAULT_PROXY_BYTES_PER_MONTH)
            ),
            proxy_requests_per_minute=int(
                row.get("proxy_requests_per_minute", DEFAULT_PROXY_REQUESTS_PER_MINUTE)
            ),
            transcript_concurrency=int(
                row.get("transcript_concurrency", DEFAULT_TRANSCRIPT_CONCURRENCY)
            ),
        )

    def get_monthly_usage(self, owner_id: str) -> MonthlyUsage:
        start, _ = month_window_utc()
        rows = self.backend._select(
            "usage_events",
            select=(
                "event_type,input_tokens,output_tokens,cost_usd,"
                "transcript_seconds,chat_messages,proxy_bytes"
            ),
            filters={
                "owner_id": self._eq(owner_id),
                "created_at": f"gte.{start.isoformat()}",
            },
            limit=10000,
        )
        usage = MonthlyUsage()
        for row in rows:
            usage.input_tokens += int(row.get("input_tokens") or 0)
            usage.output_tokens += int(row.get("output_tokens") or 0)
            usage.transcript_seconds += int(row.get("transcript_seconds") or 0)
            usage.chat_messages += int(row.get("chat_messages") or 0)
            usage.cost_usd += float(row.get("cost_usd") or 0)
            usage.proxy_bytes += int(row.get("proxy_bytes") or 0)
            if int(row.get("transcript_seconds") or 0) > 0:
                usage.videos += 1
        usage.cost_usd = round(usage.cost_usd, 6)
        return usage

    def count_active_runs(self, owner_id: str) -> int:
        in_clause = ",".join(ACTIVE_RUN_STATUSES)
        rows = self.backend._select(
            "pipeline_runs",
            select="id",
            filters={
                "owner_id": self._eq(owner_id),
                "status": f"in.({in_clause})",
            },
            limit=100,
        )
        return len(rows)

    def chat_count_in_window(self, owner_id: str, *, window_seconds: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        rows = self.backend._select(
            "usage_events",
            select="id",
            filters={
                "owner_id": self._eq(owner_id),
                "event_type": self._eq("chat"),
                "created_at": f"gte.{cutoff.isoformat()}",
            },
            limit=500,
        )
        return len(rows)

    def get_active_credit_seconds(self, owner_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        rows = self.backend._select(
            "user_credit_grants",
            select="remaining_transcript_seconds",
            filters={
                "owner_id": self._eq(owner_id),
                "remaining_transcript_seconds": "gt.0",
                "expires_at": f"gt.{now}",
            },
            limit=1000,
        )
        return sum(int(row.get("remaining_transcript_seconds") or 0) for row in rows)

    def _consume_transcript_credits(self, owner_id: str, seconds: int) -> None:
        remaining = int(max(seconds, 0))
        if remaining <= 0:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = self.backend._select(
            "user_credit_grants",
            select="id,remaining_transcript_seconds",
            filters={
                "owner_id": self._eq(owner_id),
                "remaining_transcript_seconds": "gt.0",
                "expires_at": f"gt.{now}",
            },
            order="expires_at.asc,created_at.asc",
            limit=1000,
        )
        for row in rows:
            if remaining <= 0:
                break
            grant_id = str(row.get("id") or "")
            grant_remaining = int(row.get("remaining_transcript_seconds") or 0)
            if not grant_id or grant_remaining <= 0:
                continue
            used = min(grant_remaining, remaining)
            self.backend._update(
                "user_credit_grants",
                {"remaining_transcript_seconds": grant_remaining - used},
                filters={"id": self._eq(grant_id)},
            )
            remaining -= used

    def record_usage(
        self,
        owner_id: str,
        *,
        event_type: str,
        run_id: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        transcript_seconds: int = 0,
        chat_messages: int = 0,
        cost_usd: float = 0.0,
        proxy_bytes: int = 0,
        proxy_provider: str | None = None,
    ) -> None:
        transcript_seconds = int(max(transcript_seconds, 0))
        chat_messages = int(max(chat_messages, 0))
        usage_before = self.get_monthly_usage(owner_id) if transcript_seconds > 0 else None
        quota_before = self.get_quota(owner_id) if transcript_seconds > 0 else None
        row: dict[str, Any] = {
            "owner_id": owner_id,
            "event_type": event_type,
            "input_tokens": int(max(input_tokens, 0)),
            "output_tokens": int(max(output_tokens, 0)),
            "transcript_seconds": transcript_seconds,
            "chat_messages": chat_messages,
            "cost_usd": round(float(max(cost_usd, 0.0)), 6),
            "proxy_bytes": int(max(proxy_bytes, 0)),
        }
        if model:
            row["model"] = model
        if _is_uuid(run_id):
            row["run_id"] = run_id
        if proxy_provider:
            row["proxy_provider"] = proxy_provider
        try:
            self.backend._insert("usage_events", row)
        except storage.SupabaseStorageError:
            # Usage logging is best-effort; never break the request path.
            return None

        if usage_before is not None and quota_before is not None:
            before_overage = max(
                usage_before.transcript_seconds - quota_before.monthly_transcript_seconds,
                0,
            )
            after_overage = max(
                usage_before.transcript_seconds
                + transcript_seconds
                - quota_before.monthly_transcript_seconds,
                0,
            )
            self._consume_transcript_credits(owner_id, after_overage - before_overage)


def get_quota_store() -> QuotaStore:
    """Return the quota store matching the configured storage backend."""
    backend = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
    if backend == "supabase":
        return SupabaseQuotaStore(storage.SupabaseStorageBackend.from_env())
    return LocalQuotaStore()


class OwnerConcurrencyGate:
    """Per-owner semaphore tracked in-process. Works for single-worker deployment."""

    _instance: "OwnerConcurrencyGate | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._semaphores: dict[str, threading.Semaphore] = {}

    @classmethod
    def get(cls) -> "OwnerConcurrencyGate":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def acquire(self, owner_id: str, concurrency: int) -> threading.Semaphore:
        if owner_id not in self._semaphores:
            self._semaphores[owner_id] = threading.Semaphore(concurrency)
        return self._semaphores[owner_id]


def check_pipeline_start(
    store: QuotaStore,
    owner_id: str,
    *,
    run_transcript_seconds: int = 0,
    estimated_cost_usd: float = 0.0,
    estimated_input_tokens: int = 0,
    check_concurrent: bool = True,
) -> QuotaDecision:
    """Block expensive pipeline runs that would exceed monthly ceilings."""
    if not store.is_enforced:
        return QuotaDecision(allowed=True)

    quota = store.get_quota(owner_id)

    active_runs = store.count_active_runs(owner_id) if check_concurrent else 0
    if check_concurrent and active_runs >= quota.max_concurrent_runs:
        return QuotaDecision(
            allowed=False,
            reason="concurrent_run_limit",
            detail={
                "active_runs": active_runs,
                "max_concurrent_runs": quota.max_concurrent_runs,
            },
        )

    run_transcript_seconds = int(max(run_transcript_seconds, 0))
    if (
        quota.max_transcript_seconds_per_run > 0
        and run_transcript_seconds > quota.max_transcript_seconds_per_run
    ):
        return QuotaDecision(
            allowed=False,
            reason="run_transcript_minutes_limit",
            detail={
                "run_transcript_seconds": run_transcript_seconds,
                "max_transcript_seconds_per_run": quota.max_transcript_seconds_per_run,
            },
        )

    usage = store.get_monthly_usage(owner_id)

    transcript_limit = quota.monthly_transcript_seconds + quota.credit_transcript_seconds
    projected_transcript_seconds = usage.transcript_seconds + run_transcript_seconds
    if projected_transcript_seconds > transcript_limit:
        return QuotaDecision(
            allowed=False,
            reason="monthly_transcript_minutes_limit",
            detail={
                "run_transcript_seconds": run_transcript_seconds,
                "monthly_transcript_seconds": quota.monthly_transcript_seconds,
                "credit_transcript_seconds": quota.credit_transcript_seconds,
                "transcript_seconds_used": usage.transcript_seconds,
                "transcript_seconds_remaining": max(
                    transcript_limit - usage.transcript_seconds,
                    0,
                ),
            },
        )

    projected_tokens = usage.total_tokens + max(estimated_input_tokens, 0)
    if projected_tokens > quota.monthly_token_limit:
        return QuotaDecision(
            allowed=False,
            reason="monthly_token_limit",
            detail={
                "estimated_input_tokens": estimated_input_tokens,
                "monthly_token_limit": quota.monthly_token_limit,
                "tokens_used": usage.total_tokens,
                "tokens_remaining": max(quota.monthly_token_limit - usage.total_tokens, 0),
            },
        )

    projected_cost = round(usage.cost_usd + max(estimated_cost_usd, 0.0), 6)
    if projected_cost > quota.monthly_cost_limit_usd:
        return QuotaDecision(
            allowed=False,
            reason="monthly_cost_limit",
            detail={
                "estimated_cost_usd": round(estimated_cost_usd, 6),
                "monthly_cost_limit_usd": quota.monthly_cost_limit_usd,
                "cost_used_usd": round(usage.cost_usd, 6),
                "cost_remaining_usd": round(
                    max(quota.monthly_cost_limit_usd - usage.cost_usd, 0.0), 6
                ),
            },
        )

    return QuotaDecision(
        allowed=True,
        detail={
            "tier_key": quota.tier_key,
            "monthly_transcript_seconds": quota.monthly_transcript_seconds,
            "credit_transcript_seconds": quota.credit_transcript_seconds,
            "transcript_seconds_remaining": max(
                transcript_limit - projected_transcript_seconds,
                0,
            ),
            "monthly_cost_limit_usd": quota.monthly_cost_limit_usd,
            "cost_remaining_usd": round(
                max(quota.monthly_cost_limit_usd - projected_cost, 0.0), 6
            ),
        },
    )


def check_chat_rate(
    store: QuotaStore,
    owner_id: str,
    *,
    window_seconds: int = 60,
) -> QuotaDecision:
    """Reject chat requests that exceed the per-minute sliding window."""
    if not store.is_enforced:
        return QuotaDecision(allowed=True)

    quota = store.get_quota(owner_id)
    if quota.chat_per_minute_limit <= 0:
        return QuotaDecision(allowed=True)

    recent = store.chat_count_in_window(owner_id, window_seconds=window_seconds)
    if recent >= quota.chat_per_minute_limit:
        return QuotaDecision(
            allowed=False,
            reason="chat_rate_limit",
            detail={
                "limit": quota.chat_per_minute_limit,
                "window_seconds": window_seconds,
                "recent": recent,
            },
        )
    return QuotaDecision(
        allowed=True,
        detail={
            "limit": quota.chat_per_minute_limit,
            "window_seconds": window_seconds,
            "recent": recent,
        },
    )


def check_chat_monthly(store: QuotaStore, owner_id: str) -> QuotaDecision:
    """Reject chat requests that exceed the user's monthly chat-message quota."""
    if not store.is_enforced:
        return QuotaDecision(allowed=True)

    quota = store.get_quota(owner_id)
    if quota.monthly_chat_messages <= 0:
        return QuotaDecision(allowed=True)

    usage = store.get_monthly_usage(owner_id)
    if usage.chat_messages >= quota.monthly_chat_messages:
        return QuotaDecision(
            allowed=False,
            reason="monthly_chat_message_limit",
            detail={
                "monthly_chat_messages": quota.monthly_chat_messages,
                "chat_messages_used": usage.chat_messages,
                "chat_messages_remaining": 0,
            },
        )
    return QuotaDecision(
        allowed=True,
        detail={
            "monthly_chat_messages": quota.monthly_chat_messages,
            "chat_messages_used": usage.chat_messages,
            "chat_messages_remaining": quota.monthly_chat_messages - usage.chat_messages,
        },
    )


def remaining_budget(quota: Quota, usage: MonthlyUsage) -> dict[str, Any]:
    """Return a UI-friendly summary of remaining monthly headroom."""
    transcript_limit = quota.monthly_transcript_seconds + quota.credit_transcript_seconds
    return {
        "tier_key": quota.tier_key,
        "display_name": quota.display_name,
        "monthly_transcript_seconds": quota.monthly_transcript_seconds,
        "credit_transcript_seconds": quota.credit_transcript_seconds,
        "transcript_seconds_used": usage.transcript_seconds,
        "transcript_seconds_remaining": max(transcript_limit - usage.transcript_seconds, 0),
        "monthly_chat_messages": quota.monthly_chat_messages,
        "chat_messages_used": usage.chat_messages,
        "chat_messages_remaining": max(
            quota.monthly_chat_messages - usage.chat_messages,
            0,
        ),
        "max_transcript_seconds_per_run": quota.max_transcript_seconds_per_run,
        "videos_used": usage.videos,
        "monthly_token_limit": quota.monthly_token_limit,
        "tokens_used": usage.total_tokens,
        "tokens_remaining": max(quota.monthly_token_limit - usage.total_tokens, 0),
        "monthly_cost_limit_usd": quota.monthly_cost_limit_usd,
        "cost_used_usd": round(usage.cost_usd, 6),
        "cost_remaining_usd": round(
            max(quota.monthly_cost_limit_usd - usage.cost_usd, 0.0), 6
        ),
        "proxy_bytes_per_month": quota.proxy_bytes_per_month,
        "proxy_bytes_used": usage.proxy_bytes,
        "proxy_bytes_remaining": max(quota.proxy_bytes_per_month - usage.proxy_bytes, 0),
        "proxy_requests_per_minute": quota.proxy_requests_per_minute,
        "transcript_concurrency": quota.transcript_concurrency,
    }
