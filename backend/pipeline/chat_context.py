"""Compact retrieval-backed context builder for channel chat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend import storage
from backend.models import ChatScope
from backend.pipeline.retrieve import retrieve_context

SOURCE_LIMIT = 12
SOURCE_TEXT_MAX_CHARS = 700
SOURCE_QUOTE_MAX_CHARS = 260
HISTORY_MESSAGE_LIMIT = 8
HISTORY_CHAR_BUDGET = 5000
HISTORY_MESSAGE_MAX_CHARS = 1600
PROFILE_HINT_LIMIT = 8

CHAT_SYSTEM_PROMPT_TEMPLATE = """You answer questions about a YouTube channel using provided caption sources.

Rules:
- Use the SOURCE PACK for specific factual claims.
- Cite source IDs like [S1] after supported clauses.
- Do not cite source IDs that are not present in the SOURCE PACK.
- If the SOURCE PACK does not contain enough evidence for a specific question, say there is not enough caption evidence.
- Do not treat profile hints as caption evidence.
- Broad synthesis may use profile hints and representative sources when available; describe it as "across the channel".
- Cut filler: no preambles, no recaps of the question, and no closing summaries that restate the answer.
- Distinguish recurring patterns from one-off claims when it matters.

FORMATTING:
- For straightforward questions: tight prose, lead with the answer.
- When asked to reconstruct a framework, model, system, or interlocking set of concepts, use ## headers for each top-level component.
- Use bullets or numbered lists only when content is genuinely enumerable.

ARTIFACTS - when to emit a chart instead of prose:
- If the question asks about evolution over time of a topic, theme, or stance -> emit an `evolution` artifact.
- If the question asks for a side-by-side comparison of two periods/topics -> emit a `comparison_table`.
- If the question asks for "top claims", "all claims about X", or to enumerate beliefs -> emit a `claim_cluster`.
- Format: a fenced block with language `chart`, body is JSON. Place the artifact after a 1-2 sentence intro paragraph. Do not repeat the artifact's content as prose.
- Schemas:
  evolution:        {{ type:"evolution", title:string, theme:string, points:[{{video_id, upload_date, score(-1..1), label}}] }}
  comparison_table: {{ type:"comparison_table", title:string, columns:[string], rows:[[string]] }}
  claim_cluster:    {{ type:"claim_cluster", title:string, groups:[{{label:string, claims:[{{text, video_id, start_seconds}}]}}] }}
- Only emit an artifact when the question naturally calls for one. For straightforward Q&A, plain prose with [S1]-style citations is correct.

CHANNEL CARD:
{channel_card}

PROFILE HINTS:
{profile_hints}

LATEST USER QUESTION:
{latest_user_query}

SOURCE PACK:
{source_pack}
"""


@dataclass(frozen=True)
class ChatContext:
    """Prepared LLM inputs for a chat request."""

    system_prompt: str
    messages: list[dict[str, str]]
    sources: list[dict[str, Any]]
    latest_user_query: str
    error: str | None = None


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def extract_latest_user_query(messages: list[Any]) -> str:
    """Return the most recent non-empty user message content."""
    for message in reversed(messages):
        if _message_value(message, "role") != "user":
            continue
        content = _message_value(message, "content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _compact_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    if max_chars <= 4:
        return text[:max_chars]

    cut_at = text.rfind(" ", 0, max_chars - 4)
    if cut_at <= 0:
        cut_at = max_chars - 4
    return f"{text[:cut_at].rstrip()} ..."


def build_recent_messages(messages: list[Any]) -> list[dict[str, str]]:
    """Return recent non-empty chat messages within a fixed history budget."""
    cleaned: list[dict[str, str]] = []
    for message in messages:
        role = _message_value(message, "role")
        content = _message_value(message, "content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append({"role": role, "content": content.strip()})

    selected_reversed: list[dict[str, str]] = []
    used_chars = 0

    for message in reversed(cleaned):
        if len(selected_reversed) >= HISTORY_MESSAGE_LIMIT:
            break
        remaining_chars = HISTORY_CHAR_BUDGET - used_chars
        if remaining_chars <= 0:
            break

        content_budget = min(HISTORY_MESSAGE_MAX_CHARS, remaining_chars)
        content = _compact_text(message["content"], content_budget)
        if not content:
            continue

        selected_reversed.append({"role": message["role"], "content": content})
        used_chars += len(content)

    selected_reversed.reverse()
    while selected_reversed and selected_reversed[0]["role"] != "user":
        selected_reversed.pop(0)
    return selected_reversed


def _counted_items(items: Any, label_key: str, limit: int = PROFILE_HINT_LIMIT) -> str:
    if not isinstance(items, list):
        return "none"

    labels = []
    for item in items[:limit]:
        if isinstance(item, dict):
            label = item.get(label_key) or item.get("name") or item.get("theme")
            count = item.get("count")
            if not label:
                continue
            labels.append(f"{label} ({count})" if count is not None else str(label))
        elif isinstance(item, str):
            labels.append(item)

    return ", ".join(labels) if labels else "none"


def _tone_distribution(tones: Any, limit: int = PROFILE_HINT_LIMIT) -> str:
    if not isinstance(tones, dict):
        return "none"

    ranked = sorted(
        ((str(label), count) for label, count in tones.items()),
        key=lambda item: (-int(item[1] or 0), item[0].lower()),
    )
    labels = [f"{label} ({count})" for label, count in ranked[:limit]]
    return ", ".join(labels) if labels else "none"


def _matches_profile_scope(video: dict[str, Any], scope: ChatScope | None) -> bool:
    if scope is None:
        return True

    if scope.themes:
        wanted_themes = {theme.lower() for theme in scope.themes}
        video_themes = {
            str(theme).lower()
            for theme in video.get("recurring_themes", []) or []
            if isinstance(theme, str)
        }
        if not video_themes.intersection(wanted_themes):
            return False

    if scope.tones:
        wanted_tones = {tone.lower() for tone in scope.tones}
        video_tones = {
            str(tone).lower()
            for tone in video.get("tone_markers", []) or []
            if isinstance(tone, str)
        }
        if not video_tones.intersection(wanted_tones):
            return False

    upload_date = str(video.get("upload_date") or "")
    if scope.date_from and upload_date < scope.date_from:
        return False
    if scope.date_to and upload_date > scope.date_to:
        return False

    return True


def _scope_summary(profile: dict[str, Any], scope: ChatScope | None) -> str:
    if scope is None or not (scope.themes or scope.tones or scope.date_from or scope.date_to):
        return "none"

    videos = profile.get("videos", [])
    video_count = len(videos) if isinstance(videos, list) else 0
    matched_count = (
        sum(
            1
            for video in videos
            if isinstance(video, dict) and _matches_profile_scope(video, scope)
        )
        if isinstance(videos, list)
        else 0
    )

    parts = []
    if scope.themes:
        parts.append(f"themes={', '.join(scope.themes)}")
    if scope.tones:
        parts.append(f"tones={', '.join(scope.tones)}")
    if scope.date_from or scope.date_to:
        from_part = scope.date_from or "beginning"
        to_part = scope.date_to or "end"
        parts.append(f"dates={from_part}..{to_part}")

    return (
        f"restricted to {matched_count} of {video_count} profile videos matching "
        f"{', '.join(parts)}"
    )


def _channel_card(profile: dict[str, Any], scope: ChatScope | None) -> str:
    channel_name = profile.get("channel_name") or "Unknown"
    channel_id = profile.get("channel_id") or "unknown"
    videos = profile.get("videos", [])
    video_count = profile.get("video_count")
    if not isinstance(video_count, int):
        video_count = len(videos) if isinstance(videos, list) else 0

    date_range = profile.get("date_range", {})
    if not isinstance(date_range, dict):
        date_range = {}
    first_date = date_range.get("first") or "unknown"
    last_date = date_range.get("last") or "unknown"

    return "\n".join(
        [
            f"channel_name: {channel_name}",
            f"channel_id: {channel_id}",
            f"video_count: {video_count}",
            f"date_range: {first_date}..{last_date}",
            f"active_scope: {_scope_summary(profile, scope)}",
        ]
    )


def _profile_hints(profile: dict[str, Any]) -> str:
    rollups = profile.get("rollups")
    if not isinstance(rollups, dict):
        rollups = {}

    return "\n".join(
        [
            f"top_themes: {_counted_items(rollups.get('all_themes'), 'theme')}",
            f"top_references: {_counted_items(rollups.get('all_referenced'), 'name')}",
            f"tone_distribution: {_tone_distribution(rollups.get('tone_distribution'))}",
        ]
    )


def _format_seconds_range(source: dict[str, Any]) -> str:
    start = source.get("start_seconds")
    end = source.get("end_seconds")
    if start is None and end is None:
        return "unknown"
    if end is None:
        return str(start)
    return f"{start}-{end}"


def format_source_pack(sources: list[dict[str, Any]]) -> str:
    """Format retrieved chunks as compact [S1]-style evidence for the model."""
    if not sources:
        return (
            "(no retrieved caption sources)\n"
            "Evidence limitation: no relevant caption chunks were retrieved for this query. "
            "For specific factual questions, say there is not enough caption evidence in the "
            "source pack to answer."
        )

    lines = []
    for index, source in enumerate(sources, start=1):
        source_id = str(source.get("source_id") or f"S{index}")
        title = _compact_text(source.get("title"), 140)
        upload_date = source.get("upload_date") or "unknown"
        video_id = source.get("video_id") or "unknown"
        chunk_id = source.get("chunk_id") or "unknown"
        quote = _compact_text(source.get("quote"), SOURCE_QUOTE_MAX_CHARS)
        text = _compact_text(source.get("text"), SOURCE_TEXT_MAX_CHARS)
        if not quote:
            quote = text

        lines.extend(
            [
                (
                    f"[{source_id}] kind={source.get('kind') or 'chunk'} "
                    f"chunk_id={chunk_id} video_id={video_id} title=\"{title}\" "
                    f"date={upload_date} t={_format_seconds_range(source)}"
                ),
                f"quote: \"{quote}\"",
                f"caption: \"{text}\"",
            ]
        )
    return "\n".join(lines)


def build_chat_context(
    channel_id: str,
    messages: list[Any],
    scope: ChatScope | None = None,
    *,
    retrieval_limit: int = SOURCE_LIMIT,
) -> ChatContext:
    """Build compact system prompt, bounded history, and retrieved sources."""
    profile = storage.load_profile(channel_id)
    if not isinstance(profile, dict):
        profile = storage.read_json(storage.get_channel_dir(channel_id) / "profile.json")
    if not isinstance(profile, dict):
        return ChatContext("", [], [], "", error="profile_not_found")

    if scope and not scope.themes and not scope.tones and not scope.date_from and not scope.date_to:
        scope = None

    latest_user_query = extract_latest_user_query(messages)
    sources = retrieve_context(channel_id, latest_user_query, scope=scope, limit=retrieval_limit)
    source_pack = format_source_pack(sources)
    system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
        channel_card=_channel_card(profile, scope),
        profile_hints=_profile_hints(profile),
        latest_user_query=latest_user_query or "(none)",
        source_pack=source_pack,
    )

    return ChatContext(
        system_prompt=system_prompt,
        messages=build_recent_messages(messages),
        sources=sources,
        latest_user_query=latest_user_query,
    )
