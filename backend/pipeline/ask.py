"""Chat against an aggregated channel profile via streaming LLM."""

import json
import os

from anthropic import AsyncAnthropic

from backend.models import ApiResponse
from backend.storage import get_channel_dir, read_json

CHAT_SYSTEM_PROMPT_TEMPLATE = """You are analyzing a YouTube channel based on structured summaries of its videos.
The summaries are listed chronologically (oldest first), so you can identify
how the creator's thinking, topics, and tone have evolved.

Data shape:
- Each summary has a video_id.
- key_claims and notable_opinions are objects with text and evidence[].
- Each evidence entry has start_seconds (an int) and quote (a verbatim substring).

When stating a claim that maps to evidence in the summaries, you MUST render it as a markdown link:
[claim text](https://youtu.be/<video_id>?t=<start_seconds>s)
Example: [He earned $80–100 per hour on client work](https://youtu.be/BaXH76BS9VA?t=137s)
Include the link inline, not as a footnote. Multiple supporting moments → multiple links.
If a statement is your synthesis across many videos (no single evidence entry matches), do not invent a link. Say "across the channel" or similar.

When asked questions:
- Be concise. Lead with the answer, then add only the supporting detail that carries information.
- Cut filler: no preambles ("Great question"), no recaps of the question, no closing summaries that restate what you just said.
- Prefer tight prose. Use bullets/lists only when the content is genuinely enumerable (3+ parallel items) — never to pad a single point.
- Distinguish recurring patterns from one-off claims when it matters.
- Don't drop substantive findings to be brief — concise means dense, not shallow.
- If asked about something not covered in the summaries, say so in one sentence.

CHANNEL: {channel_name}
VIDEOS: {video_count} (from {first_date} to {last_date})

SUMMARIES (chronological):
{serialized_summaries}
"""


def build_system_prompt(channel_id: str) -> str | None:
    """Load profile.json and build the system prompt. Returns None if profile missing."""
    channel_dir = get_channel_dir(channel_id)
    profile = read_json(channel_dir / "profile.json")
    if not profile:
        return None

    channel_name = profile.get("channel_name", "Unknown")
    video_count = profile.get("video_count", 0)
    date_range = profile.get("date_range", {})
    first_date = date_range.get("first", "unknown")
    last_date = date_range.get("last", "unknown")
    videos = profile.get("videos", [])
    serialized_summaries = json.dumps(videos, separators=(",", ":"))

    return CHAT_SYSTEM_PROMPT_TEMPLATE.format(
        channel_name=channel_name,
        video_count=video_count,
        first_date=first_date,
        last_date=last_date,
        serialized_summaries=serialized_summaries,
    )


async def chat_stream(channel_id: str, messages: list[dict]):
    """Yield SSE data frames for the chat stream."""
    system = build_system_prompt(channel_id)
    if system is None:
        yield json.dumps({"type": "error", "message": "profile_not_found"})
        return

    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        yield json.dumps({"type": "error", "message": "MINIMAX_API_KEY not configured"})
        return

    MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")

    client = AsyncAnthropic(
        api_key=api_key,
        base_url=MINIMAX_BASE_URL,
    )

    try:
        async with client.messages.stream(
            model="MiniMax-M2.7-highspeed",
            max_tokens=4000,
            system=system,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text") and delta.text:
                        yield json.dumps({"type": "delta", "text": delta.text})
                    elif hasattr(delta, "reasoning_content") and delta.reasoning_content:
                        # Drop reasoning_content deltas — do NOT leak to client
                        continue
    except Exception as exc:
        yield json.dumps({"type": "error", "message": str(exc)})
        return

    yield json.dumps({"type": "done"})
