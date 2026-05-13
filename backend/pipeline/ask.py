"""Chat against a channel profile via retrieval-backed streaming LLM."""

import json
import os
import re
from typing import Any

from anthropic import AsyncAnthropic

from backend.models import ChatScope
from backend.pipeline.chat_context import build_chat_context
from backend.quotas import estimate_summary_cost_usd, get_quota_store
from backend.storage import current_owner_id, get_channel_dir, load_profile, read_json

CHAT_MODEL = "MiniMax-M2.7-highspeed"

CITATION_MARKER_RE = re.compile(r"\[(S\d+)\]")


def _compact_source_value(value: Any) -> str:
    return " ".join(str(value or "").split())


def _coerce_seconds(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(float(value)), 0)
        except ValueError:
            return None
    return None


def build_source_registry(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return client-safe citation metadata for retrieved sources."""
    registry = []
    for index, source in enumerate(sources, start=1):
        source_id = _compact_source_value(source.get("source_id")) or f"S{index}"
        video_id = _compact_source_value(source.get("video_id"))
        start_seconds = _coerce_seconds(source.get("start_seconds"))
        if not source_id or not video_id or start_seconds is None:
            continue

        entry: dict[str, Any] = {
            "source_id": source_id,
            "kind": _compact_source_value(source.get("kind")) or "chunk",
            "video_id": video_id,
            "title": _compact_source_value(source.get("title")),
            "upload_date": _compact_source_value(source.get("upload_date")),
            "start_seconds": start_seconds,
            "quote": _compact_source_value(source.get("quote")),
        }

        end_seconds = _coerce_seconds(source.get("end_seconds"))
        if end_seconds is not None:
            entry["end_seconds"] = end_seconds

        chunk_id = _compact_source_value(source.get("chunk_id"))
        if chunk_id:
            entry["chunk_id"] = chunk_id

        registry.append(entry)
    return registry


def unknown_citation_ids(answer_text: str, registry: list[dict[str, Any]]) -> list[str]:
    """Return cited source IDs that were not included in the backend registry."""
    known_ids = {
        source["source_id"]
        for source in registry
        if isinstance(source.get("source_id"), str)
    }
    unknown = sorted(
        {
            match.group(1)
            for match in CITATION_MARKER_RE.finditer(answer_text)
            if match.group(1) not in known_ids
        },
        key=lambda source_id: int(source_id[1:]),
    )
    return unknown


def filter_videos(videos: list[dict], scope: ChatScope | None) -> list[dict]:
    """Filter videos by scope (themes, tones, date range)."""
    if scope is None:
        return videos
    out = videos
    if scope.themes:
        wanted = {t.lower() for t in scope.themes}
        out = [v for v in out if any(t.lower() in wanted for t in v.get("recurring_themes", []))]
    if scope.tones:
        wanted = {t.lower() for t in scope.tones}
        out = [v for v in out if any(t.lower() in wanted for t in v.get("tone_markers", []))]
    if scope.date_from:
        out = [v for v in out if v.get("upload_date", "") >= scope.date_from]
    if scope.date_to:
        out = [v for v in out if v.get("upload_date", "") <= scope.date_to]
    return out


def build_system_prompt(channel_id: str, scope: ChatScope | None = None) -> str | None:
    """Build the compact chat system prompt. Returns None if profile missing."""
    context = build_chat_context(channel_id, [], scope)
    if context.error:
        return None
    return context.system_prompt


async def chat_stream(channel_id: str, messages: list[dict], scope: ChatScope | None = None):
    """Yield SSE data frames for the chat stream."""
    if scope and not scope.themes and not scope.tones and not scope.date_from and not scope.date_to:
        scope = None

    profile = load_profile(channel_id)
    if not profile:
        channel_dir = get_channel_dir(channel_id)
        profile = read_json(channel_dir / "profile.json")
    if not profile:
        yield json.dumps({"type": "error", "message": "profile_not_found"})
        return

    filtered_videos = filter_videos(profile.get("videos", []), scope)
    if scope and len(filtered_videos) == 0:
        yield json.dumps({"type": "error", "message": "scope_empty"})
        return

    context = build_chat_context(channel_id, messages, scope)
    if context.error:
        yield json.dumps({"type": "error", "message": context.error})
        return

    source_registry = build_source_registry(context.sources)

    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        yield json.dumps({"type": "error", "message": "MINIMAX_API_KEY not configured"})
        return

    MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")

    client = AsyncAnthropic(
        api_key=api_key,
        base_url=MINIMAX_BASE_URL,
    )

    yield json.dumps({"type": "sources", "sources": source_registry})

    answer_parts: list[str] = []
    final_usage: Any = None
    try:
        async with client.messages.stream(
            model=CHAT_MODEL,
            max_tokens=4000,
            system=context.system_prompt,
            messages=context.messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        answer_parts.append(delta.text)
                        yield json.dumps({"type": "delta", "text": delta.text})
                    elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        # Drop reasoning_content deltas — do NOT leak to client
                        continue
            try:
                final_message = await stream.get_final_message()
                final_usage = getattr(final_message, "usage", None)
            except Exception:  # pragma: no cover - SDK quirk
                final_usage = None
    except Exception as exc:
        yield json.dumps({"type": "error", "message": str(exc)})
        return

    _record_chat_usage(final_usage)

    unknown_ids = unknown_citation_ids("".join(answer_parts), source_registry)
    if unknown_ids:
        yield json.dumps({"type": "citation_warning", "unknown_source_ids": unknown_ids})

    yield json.dumps({"type": "done"})


def _record_chat_usage(usage: Any) -> None:
    """Best-effort usage_events insert for the active chat caller."""
    owner_id = current_owner_id()
    if not owner_id:
        return
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    cost = estimate_summary_cost_usd(input_tokens, output_tokens)
    try:
        get_quota_store().record_usage(
            owner_id,
            event_type="chat",
            model=CHAT_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            chat_messages=1,
            cost_usd=cost,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[chat] usage record failed: {exc}")
