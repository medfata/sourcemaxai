"""Unit tests for the Phase 6 quota module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.quotas import (
    DEFAULT_CHAT_PER_MINUTE_LIMIT,
    DEFAULT_MAX_TRANSCRIPT_SECONDS_PER_RUN,
    DEFAULT_MONTHLY_CHAT_MESSAGES,
    DEFAULT_MONTHLY_TRANSCRIPT_SECONDS,
    ESTIMATED_BYTES_PER_TRANSCRIPT,
    LocalQuotaStore,
    MonthlyUsage,
    Quota,
    QuotaStore,
    check_chat_monthly,
    check_chat_rate,
    check_pipeline_start,
    check_transcript_fetch,
    estimate_summary_cost_usd,
    month_window_utc,
    remaining_budget,
    transcript_seconds_from_word_count,
)


class FakeQuotaStore(QuotaStore):
    """In-memory enforced store for unit tests."""

    is_enforced = True

    def __init__(
        self,
        *,
        quota: Quota | None = None,
        usage: MonthlyUsage | None = None,
        active_runs: int = 0,
        chat_window: int = 0,
        proxy_window: int = 0,
    ) -> None:
        self._quota = quota or Quota()
        self._usage = usage or MonthlyUsage()
        self._active_runs = active_runs
        self._chat_window = chat_window
        self._proxy_window = proxy_window
        self.recorded: list[dict[str, Any]] = []

    def get_quota(self, owner_id: str) -> Quota:
        return self._quota

    def get_monthly_usage(self, owner_id: str) -> MonthlyUsage:
        return self._usage

    def count_active_runs(self, owner_id: str) -> int:
        return self._active_runs

    def chat_count_in_window(self, owner_id: str, *, window_seconds: int) -> int:
        return self._chat_window

    def proxy_event_count_in_window(self, owner_id: str, *, window_seconds: int) -> int:
        return self._proxy_window

    def get_active_credit_seconds(self, owner_id: str) -> int:
        return self._quota.credit_transcript_seconds

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
    ) -> None:
        self.recorded.append(
            {
                "owner_id": owner_id,
                "event_type": event_type,
                "run_id": run_id,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "transcript_seconds": transcript_seconds,
                "chat_messages": chat_messages,
                "cost_usd": cost_usd,
            }
        )


def test_local_store_is_unenforced_and_records_nothing():
    store = LocalQuotaStore()
    assert store.is_enforced is False
    assert store.get_monthly_usage("u").videos == 0
    assert store.chat_count_in_window("u", window_seconds=60) == 0
    decision = check_pipeline_start(
        store,
        "u",
        run_transcript_seconds=10**9,
        estimated_cost_usd=999.0,
        estimated_input_tokens=10**9,
    )
    assert decision.allowed is True


def test_transcript_seconds_from_word_count_rounds_up_at_150_wpm():
    assert transcript_seconds_from_word_count(0) == 0
    assert transcript_seconds_from_word_count(1) == 1
    assert transcript_seconds_from_word_count(150) == 60
    assert transcript_seconds_from_word_count(151) == 61


def test_check_pipeline_start_blocks_on_transcript_cap():
    store = FakeQuotaStore(
        quota=Quota(monthly_transcript_seconds=150),
        usage=MonthlyUsage(transcript_seconds=120),
    )
    decision = check_pipeline_start(
        store, "u", run_transcript_seconds=45, estimated_cost_usd=0.0, estimated_input_tokens=0
    )
    assert decision.allowed is False
    assert decision.reason == "monthly_transcript_minutes_limit"
    assert decision.detail["transcript_seconds_remaining"] == 30


def test_check_pipeline_start_allows_with_active_credit():
    store = FakeQuotaStore(
        quota=Quota(monthly_transcript_seconds=150, credit_transcript_seconds=60),
        usage=MonthlyUsage(transcript_seconds=120),
    )
    decision = check_pipeline_start(
        store, "u", run_transcript_seconds=45, estimated_cost_usd=0.0, estimated_input_tokens=0
    )
    assert decision.allowed is True
    assert decision.detail["transcript_seconds_remaining"] == 45


def test_check_pipeline_start_blocks_on_run_transcript_cap():
    store = FakeQuotaStore(
        quota=Quota(max_transcript_seconds_per_run=120),
    )
    decision = check_pipeline_start(
        store, "u", run_transcript_seconds=121, estimated_cost_usd=0.0, estimated_input_tokens=0
    )
    assert decision.allowed is False
    assert decision.reason == "run_transcript_minutes_limit"


def test_check_pipeline_start_blocks_on_concurrent_runs():
    store = FakeQuotaStore(
        quota=Quota(max_concurrent_runs=1),
        active_runs=1,
    )
    decision = check_pipeline_start(
        store, "u", estimated_cost_usd=0.0, estimated_input_tokens=0
    )
    assert decision.allowed is False
    assert decision.reason == "concurrent_run_limit"


def test_check_pipeline_start_blocks_on_token_cap():
    store = FakeQuotaStore(
        quota=Quota(monthly_token_limit=1000),
        usage=MonthlyUsage(input_tokens=900, output_tokens=50),
    )
    decision = check_pipeline_start(
        store, "u", estimated_cost_usd=0.0, estimated_input_tokens=200
    )
    assert decision.allowed is False
    assert decision.reason == "monthly_token_limit"


def test_check_pipeline_start_blocks_on_cost_cap():
    store = FakeQuotaStore(
        quota=Quota(monthly_cost_limit_usd=5.0),
        usage=MonthlyUsage(cost_usd=4.5),
    )
    decision = check_pipeline_start(
        store, "u", estimated_cost_usd=1.0, estimated_input_tokens=0
    )
    assert decision.allowed is False
    assert decision.reason == "monthly_cost_limit"
    assert decision.detail["cost_remaining_usd"] == pytest.approx(0.5)


def test_check_pipeline_start_allows_within_budget():
    store = FakeQuotaStore()
    decision = check_pipeline_start(
        store,
        "u",
        run_transcript_seconds=10,
        estimated_cost_usd=0.05,
        estimated_input_tokens=10_000,
    )
    assert decision.allowed is True
    assert (
        decision.detail["transcript_seconds_remaining"]
        == DEFAULT_MONTHLY_TRANSCRIPT_SECONDS - 10
    )


def test_check_chat_rate_blocks_at_limit():
    store = FakeQuotaStore(chat_window=DEFAULT_CHAT_PER_MINUTE_LIMIT)
    decision = check_chat_rate(store, "u")
    assert decision.allowed is False
    assert decision.reason == "chat_rate_limit"


def test_check_chat_rate_allows_under_limit():
    store = FakeQuotaStore(chat_window=DEFAULT_CHAT_PER_MINUTE_LIMIT - 1)
    decision = check_chat_rate(store, "u")
    assert decision.allowed is True


def test_check_chat_rate_allows_when_limit_zero():
    store = FakeQuotaStore(quota=Quota(chat_per_minute_limit=0), chat_window=999)
    decision = check_chat_rate(store, "u")
    assert decision.allowed is True


def test_check_chat_monthly_blocks_at_limit():
    store = FakeQuotaStore(
        quota=Quota(monthly_chat_messages=20),
        usage=MonthlyUsage(chat_messages=20),
    )
    decision = check_chat_monthly(store, "u")
    assert decision.allowed is False
    assert decision.reason == "monthly_chat_message_limit"


def test_check_chat_monthly_allows_under_limit():
    store = FakeQuotaStore(
        quota=Quota(monthly_chat_messages=20),
        usage=MonthlyUsage(chat_messages=19),
    )
    decision = check_chat_monthly(store, "u")
    assert decision.allowed is True
    assert decision.detail["chat_messages_remaining"] == 1


def test_estimate_summary_cost_uses_minimax_rates():
    cost = estimate_summary_cost_usd(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(0.30 + 1.20)


def test_month_window_utc_returns_first_of_month_to_first_of_next():
    now = datetime(2026, 5, 18, 10, tzinfo=timezone.utc)
    start, end = month_window_utc(now)
    assert start == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_month_window_utc_handles_december_rollover():
    now = datetime(2026, 12, 31, 23, tzinfo=timezone.utc)
    start, end = month_window_utc(now)
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_remaining_budget_clamps_negative_values_to_zero():
    quota = Quota(
        monthly_cost_limit_usd=2.0,
        monthly_transcript_seconds=10,
        monthly_chat_messages=3,
        monthly_token_limit=100,
    )
    usage = MonthlyUsage(
        videos=20,
        transcript_seconds=20,
        chat_messages=4,
        input_tokens=200,
        output_tokens=0,
        cost_usd=5.0,
    )
    summary = remaining_budget(quota, usage)
    assert summary["transcript_seconds_remaining"] == 0
    assert summary["chat_messages_remaining"] == 0
    assert summary["tokens_remaining"] == 0
    assert summary["cost_remaining_usd"] == 0.0


def test_default_tier_constants_match_plan():
    assert DEFAULT_MONTHLY_TRANSCRIPT_SECONDS == 150 * 60
    assert DEFAULT_MONTHLY_CHAT_MESSAGES == 20
    assert DEFAULT_MAX_TRANSCRIPT_SECONDS_PER_RUN == 30 * 60


def test_check_transcript_fetch_blocks_on_proxy_bytes_limit():
    store = FakeQuotaStore(
        quota=Quota(proxy_bytes_per_month=100_000),
        usage=MonthlyUsage(proxy_bytes=90_000),
    )
    pending = 5
    decision = check_transcript_fetch(store, "u", pending_video_count=pending)
    assert decision.allowed is False
    assert decision.reason == "proxy_bytes_limit"


def test_check_transcript_fetch_allows_under_proxy_bytes_limit():
    store = FakeQuotaStore(
        quota=Quota(proxy_bytes_per_month=100_000),
        usage=MonthlyUsage(proxy_bytes=10_000),
    )
    pending = 1
    decision = check_transcript_fetch(store, "u", pending_video_count=pending)
    assert decision.allowed is True


def test_check_transcript_fetch_blocks_on_rate_limit():
    store = FakeQuotaStore(
        quota=Quota(proxy_requests_per_minute=10),
        proxy_window=10,
    )
    decision = check_transcript_fetch(store, "u", pending_video_count=1)
    assert decision.allowed is False
    assert decision.reason == "proxy_rate_limit"


def test_check_transcript_fetch_allows_under_rate_limit():
    store = FakeQuotaStore(
        quota=Quota(proxy_requests_per_minute=10),
        proxy_window=9,
    )
    decision = check_transcript_fetch(store, "u", pending_video_count=1)
    assert decision.allowed is True


def test_check_transcript_fetch_not_enforced_when_local_store():
    store = LocalQuotaStore()
    decision = check_transcript_fetch(store, "u", pending_video_count=999)
    assert decision.allowed is True


def test_remaining_budget_includes_proxy_fields():
    quota = Quota(
        proxy_bytes_per_month=500_000,
        proxy_requests_per_minute=20,
        transcript_concurrency=3,
    )
    usage = MonthlyUsage(proxy_bytes=123_456)
    summary = remaining_budget(quota, usage)
    assert summary["proxy_bytes_per_month"] == 500_000
    assert summary["proxy_bytes_used"] == 123_456
    assert summary["proxy_bytes_remaining"] == 376_544
    assert summary["proxy_requests_per_minute"] == 20
    assert summary["transcript_concurrency"] == 3
