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

CITATIONS — read carefully:
- When a claim in your answer maps to an evidence entry, append a COMPACT citation marker after the relevant clause. The marker is a markdown link whose visible text is ONLY the timestamp.
- Format: [↗ M:SS](https://youtu.be/<video_id>?t=<start_seconds>s)
  - Convert start_seconds to M:SS or H:MM:SS (e.g., 142 → 2:22, 3725 → 1:02:05).
  - The arrow glyph "↗" is required so the frontend can style the marker as a citation pill.
- NEVER wrap the claim text itself in a markdown link. The link text is ALWAYS just "↗ M:SS" — never a sentence, phrase, or quote.
- Multiple supporting moments → multiple markers in sequence:
  "Naval argues fortunes require leverage. [↗ 2:22](https://youtu.be/abc?t=142s) [↗ 14:05](https://youtu.be/def?t=845s)"
- If a statement is your synthesis across many videos with no single supporting evidence entry, do not cite. Say "across the channel" or omit the marker.

FORMATTING:
- For straightforward questions: tight prose, lead with the answer.
- When asked to reconstruct a framework, model, system, or interlocking set of concepts (e.g., "explain X's framework", "how does X work"):
  - Use ## headers for each top-level component.
  - Under each header, write 1–3 short paragraphs of dense prose with citation markers after supported claims.
  - Optionally end with a brief synthesis paragraph (no header, or "## How it fits together").
  - Use **bold** sparingly for genuinely load-bearing terms.
  - Do NOT draw ASCII diagrams, boxes, or arrow flowcharts. The renderer is a chat bubble, not a code block.
- Cut filler: no preambles ("Great question"), no recaps of the question, no closing summaries that restate what you just said.
- Use bullets/numbered lists only when content is genuinely enumerable (3+ parallel items) — never to pad a single point.
- Distinguish recurring patterns from one-off claims when it matters.
- Don't drop substantive findings to be brief — concise means dense, not shallow.
- If asked about something not covered in the summaries, say so in one sentence.

CHANNEL: {channel_name}
VIDEOS: {video_count} (from {first_date} to {last_date})

ARTIFACTS — when to emit a chart instead of prose:
- If the question asks about evolution over time of a topic, theme, or stance → emit an `evolution` artifact.
- If the question asks for a side-by-side comparison of two periods/topics → emit a `comparison_table`.
- If the question asks for "top claims", "all claims about X", or to enumerate beliefs → emit a `claim_cluster`.
- Format: a fenced block with language `chart`, body is JSON. Place the artifact after a 1-2 sentence intro paragraph. Do not repeat the artifact's content as prose.
- Schemas:
  evolution:        { type:"evolution", title:string, theme:string, points:[{video_id, upload_date, score(-1..1), label}] }
  comparison_table: { type:"comparison_table", title:string, columns:[string], rows:[[string]] }
  claim_cluster:    { type:"claim_cluster", title:string, groups:[{label:string, claims:[{text, video_id, start_seconds}]}] }
- Score in evolution is a stance scalar from -1 (strongly against) to +1 (strongly for). Use 0 for neutral/mixed.
- Only emit an artifact when the question naturally calls for one. For straightforward Q&A, plain prose with citations is correct.

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
