"""Deterministic lexical retrieval over the generated caption chunk index."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from backend import storage
from backend.models import ChatScope
from backend.pipeline.schema_versions import get_chunk_index_stale_reasons

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
QUOTE_MAX_CHARS = 220

QueryMode = Literal["lexical", "opening", "closing", "lexical_global"]

DEFAULT_OPENING_WINDOW_SECONDS = 30
DEFAULT_CLOSING_WINDOW_SECONDS = 60


# Substring patterns drive intent classification. The lists below are the
# authoritative rule set (R2.2); keep them in sync with PLAN_RAG_CHAT.md.
#
# Opening-mode triggers (any one is sufficient):
#   - "hook"               structural noun used in YouTube parlance
#   - "intro"              short for introduction
#   - "outset"             unambiguous opening phrase
#   - "start of"           phrase form anchors the bare verb "start"
#   - "first N seconds"    regex below picks up a numeric window
#   - "how do videos start", "how does ... begin", "begin with",
#     "how does it begin", "begin the video", "kick(s|ing) off"
#   The bare verbs "start", "begin", "open" are NOT triggers on their own
#   (false positive risk: "I want to start using Feastables").
_OPENING_SUBSTRINGS: tuple[str, ...] = (
    "hook",
    "intro",
    "outset",
    "start of",
    "how do videos start",
    "how do the videos start",
    "how do his videos start",
    "how do her videos start",
    "how do they start",
    "begin with",
    "how does it begin",
    "how does the video begin",
    "how does each video begin",
    "how does every video begin",
    "begin the video",
    "kick off",
    "kicks off",
    "kicking off",
)

# Closing-mode triggers:
#   - "outro"
#   - "closing"
#   - "end of"
#   - "last N seconds"      regex below picks up the numeric window
#   - "how do videos end", "how does ... end", "end the video",
#     "wrap up", "wraps up", "wrapping up", "sign off", "signs off"
_CLOSING_SUBSTRINGS: tuple[str, ...] = (
    "outro",
    "closing",
    "end of",
    "how do videos end",
    "how do the videos end",
    "how do his videos end",
    "how do her videos end",
    "how do they end",
    "how does it end",
    "how does the video end",
    "how does each video end",
    "how does every video end",
    "end the video",
    "wrap up",
    "wraps up",
    "wrapping up",
    "sign off",
    "signs off",
)

# Cross-video / "global" phrasing. When present and no structural keyword
# fires, we return lexical_global so the dispatcher (Wave 2) can widen the
# chunk budget for cross-video synthesis.
_GLOBAL_SUBSTRINGS: tuple[str, ...] = (
    "every video",
    "every episode",
    "across all",
    "across every",
    "each video",
    "each episode",
    "all 50",
    "all of the videos",
    "in all the videos",
    "in all videos",
)

_OPENING_NUMERIC_RE = re.compile(
    r"first\s+(\d{1,3})\s*(?:s\b|sec\b|secs\b|second\b|seconds\b)",
    re.IGNORECASE,
)
_CLOSING_NUMERIC_RE = re.compile(
    r"last\s+(\d{1,3})\s*(?:s\b|sec\b|secs\b|second\b|seconds\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryIntent:
    mode: QueryMode
    seconds_window: int | None


def _extract_window(query_lc: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(query_lc)
    if match is None:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def classify_query(query: str) -> QueryIntent:
    """Classify a chat query into a retrieval intent.

    Returns a `QueryIntent` describing how the dispatcher (Wave 2) should
    pull chunks. Structural modes (`opening`, `closing`) bypass lexical
    scoring; `lexical_global` keeps lexical scoring but signals the caller
    to widen the chunk budget for cross-video synthesis.
    """
    if not query or not isinstance(query, str):
        return QueryIntent(mode="lexical", seconds_window=None)

    query_lc = query.casefold()

    opening_window = _extract_window(query_lc, _OPENING_NUMERIC_RE)
    closing_window = _extract_window(query_lc, _CLOSING_NUMERIC_RE)

    opening_match = opening_window is not None or any(
        token in query_lc for token in _OPENING_SUBSTRINGS
    )
    closing_match = closing_window is not None or any(
        token in query_lc for token in _CLOSING_SUBSTRINGS
    )

    if opening_match and not closing_match:
        window = opening_window if opening_window is not None else DEFAULT_OPENING_WINDOW_SECONDS
        return QueryIntent(mode="opening", seconds_window=window)

    if closing_match and not opening_match:
        window = closing_window if closing_window is not None else DEFAULT_CLOSING_WINDOW_SECONDS
        return QueryIntent(mode="closing", seconds_window=window)

    if opening_match and closing_match:
        if opening_window is not None and closing_window is None:
            return QueryIntent(mode="opening", seconds_window=opening_window)
        if closing_window is not None and opening_window is None:
            return QueryIntent(mode="closing", seconds_window=closing_window)
        return QueryIntent(
            mode="opening",
            seconds_window=opening_window or DEFAULT_OPENING_WINDOW_SECONDS,
        )

    if any(token in query_lc for token in _GLOBAL_SUBSTRINGS):
        return QueryIntent(mode="lexical_global", seconds_window=None)

    return QueryIntent(mode="lexical", seconds_window=None)

STOP_WORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "doing",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "has",
    "have",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "say",
    "says",
    "she",
    "should",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}


def _tokenize(value: Any) -> list[str]:
    return [match.group(0).casefold() for match in TOKEN_RE.finditer(str(value or ""))]


def _query_tokens(query: str) -> list[str]:
    tokens = _tokenize(query)
    filtered = [token for token in tokens if token not in STOP_WORDS]
    return filtered or tokens


def _unique_preserving_order(tokens: list[str]) -> list[str]:
    seen = set()
    unique = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _load_current_chunk_index(channel_id: str) -> dict[str, Any] | None:
    index_path = storage.get_channel_dir(channel_id) / "chunk_index.json"
    try:
        data = storage.read_json(index_path)
    except (OSError, TypeError, ValueError):
        return None

    if get_chunk_index_stale_reasons(data):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("channel_id") != channel_id:
        return None
    return data


def _indexed_video_ids(index: dict[str, Any]) -> set[str]:
    source = index.get("source")
    if not isinstance(source, dict):
        return set()
    selected_video_ids = source.get("selected_video_ids")
    if not isinstance(selected_video_ids, list):
        return set()
    return {video_id for video_id in selected_video_ids if isinstance(video_id, str)}


def _metadata_values(chunk: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw = chunk.get(key)
        if isinstance(raw, str):
            values.add(raw.casefold())
        elif isinstance(raw, list):
            values.update(item.casefold() for item in raw if isinstance(item, str))
    return values


def _matches_scope(chunk: dict[str, Any], scope: ChatScope | None) -> bool:
    if scope is None:
        return True

    upload_date = str(chunk.get("upload_date") or "")
    if (scope.date_from or scope.date_to) and not upload_date:
        return False
    if scope.date_from and upload_date < scope.date_from:
        return False
    if scope.date_to and upload_date > scope.date_to:
        return False

    # Phase 2 chunks do not currently include theme/tone metadata. If future
    # chunk indexes add it, honor those filters here; otherwise leave them as
    # no-ops so retrieval remains available from caption-only indexes.
    if scope.themes:
        chunk_themes = _metadata_values(chunk, ("recurring_themes", "themes"))
        wanted_themes = {theme.casefold() for theme in scope.themes}
        if chunk_themes and not chunk_themes.intersection(wanted_themes):
            return False
    if scope.tones:
        chunk_tones = _metadata_values(chunk, ("tone_markers", "tones"))
        wanted_tones = {tone.casefold() for tone in scope.tones}
        if chunk_tones and not chunk_tones.intersection(wanted_tones):
            return False

    return True


def _is_retrievable_chunk(chunk: Any) -> bool:
    if not isinstance(chunk, dict):
        return False
    for field in (
        "chunk_id",
        "video_id",
        "title",
        "upload_date",
        "start_seconds",
        "end_seconds",
        "text",
    ):
        if field not in chunk:
            return False
    if not isinstance(chunk.get("chunk_id"), str) or not chunk.get("chunk_id"):
        return False
    if not isinstance(chunk.get("video_id"), str) or not chunk.get("video_id"):
        return False
    if not isinstance(chunk.get("text"), str) or not chunk.get("text").strip():
        return False
    if not isinstance(chunk.get("start_seconds"), int | float):
        return False
    return isinstance(chunk.get("end_seconds"), int | float)


def _score_chunk(chunk: dict[str, Any], tokens: list[str]) -> float:
    unique_tokens = _unique_preserving_order(tokens)
    if not unique_tokens:
        return 0.0

    text_tokens = _tokenize(chunk.get("text", ""))
    title_tokens = _tokenize(chunk.get("title", ""))
    if not text_tokens and not title_tokens:
        return 0.0

    text_counts = Counter(text_tokens)
    title_counts = Counter(title_tokens)
    phrase = " ".join(unique_tokens)
    text_phrase = " ".join(text_tokens)
    title_phrase = " ".join(title_tokens)

    score = 0.0
    matched_tokens = 0

    for token in unique_tokens:
        text_count = text_counts.get(token, 0)
        title_count = title_counts.get(token, 0)
        if text_count or title_count:
            matched_tokens += 1
        if text_count:
            score += 1.0 + min(text_count, 5) * 0.2
        if title_count:
            score += 0.6 + min(title_count, 3) * 0.15

    if matched_tokens == 0:
        return 0.0

    score += (matched_tokens / len(unique_tokens)) * 1.5

    if len(unique_tokens) >= 2:
        if phrase in text_phrase:
            score += 8.0 + len(unique_tokens) * 0.4
        if phrase in title_phrase:
            score += 2.0 + len(unique_tokens) * 0.2

    return score


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    return [
        (match.group(0).casefold(), match.start(), match.end())
        for match in TOKEN_RE.finditer(text)
    ]


def _matched_span(text: str, tokens: list[str]) -> tuple[int, int] | None:
    unique_tokens = _unique_preserving_order(tokens)
    if not unique_tokens:
        return None

    spans = _token_spans(text)
    if not spans:
        return None

    phrase_length = len(unique_tokens)
    if phrase_length >= 2:
        for index in range(0, len(spans) - phrase_length + 1):
            window = [token for token, _, _ in spans[index : index + phrase_length]]
            if window == unique_tokens:
                return spans[index][1], spans[index + phrase_length - 1][2]

    wanted = set(unique_tokens)
    for token, start, end in spans:
        if token in wanted:
            return start, end

    return None


def _trim_to_word_boundaries(
    text: str,
    start: int,
    end: int,
    anchor: tuple[int, int],
) -> tuple[int, int]:
    anchor_start, anchor_end = anchor
    if start > 0:
        next_space = text.find(" ", start)
        if next_space != -1 and next_space < anchor_start:
            start = next_space + 1
    if end < len(text):
        previous_space = text.rfind(" ", anchor_end, end)
        if previous_space != -1 and previous_space > anchor_end:
            end = previous_space
    return start, end


def _quote_from_span(text: str, span: tuple[int, int]) -> str:
    if len(text) <= QUOTE_MAX_CHARS:
        return text

    span_start, span_end = span
    span_width = span_end - span_start
    before = max((QUOTE_MAX_CHARS - span_width) // 2, 0)
    start = max(0, span_start - before)
    end = min(len(text), start + QUOTE_MAX_CHARS)
    if end - start < QUOTE_MAX_CHARS:
        start = max(0, end - QUOTE_MAX_CHARS)

    start, end = _trim_to_word_boundaries(text, start, end, span)
    quote = text[start:end].strip()
    if start > 0:
        quote = f"... {quote}"
    if end < len(text):
        quote = f"{quote} ..."
    return quote


def _beginning_quote(text: str) -> str:
    if len(text) <= QUOTE_MAX_CHARS:
        return text
    end = text.rfind(" ", 0, QUOTE_MAX_CHARS)
    if end <= 0:
        end = QUOTE_MAX_CHARS
    return f"{text[:end].strip()} ..."


def _make_quote(text: str, tokens: list[str]) -> str:
    compact = " ".join(str(text or "").split())
    if not compact:
        return ""

    span = _matched_span(compact, tokens)
    if span is not None:
        return _quote_from_span(compact, span)
    return _beginning_quote(compact)


def _sort_key(source: dict[str, Any]) -> tuple[float, str, str, float, str]:
    return (
        -float(source["score"]),
        str(source.get("upload_date") or ""),
        str(source.get("video_id") or ""),
        float(source.get("start_seconds") or 0),
        str(source.get("chunk_id") or ""),
    )


def retrieve_context(
    channel_id: str,
    query: str,
    scope: ChatScope | None = None,
    limit: int = 12,
) -> list[dict]:
    """Return ranked caption chunks from data/channels/{channel_id}/chunk_index.json.

    The retrieval backend is intentionally lexical and deterministic. It does
    not refetch transcripts, read raw transcript files, build embeddings, or
    mutate the chat prompt/citation pipeline.
    """
    if limit <= 0:
        return []

    tokens = _query_tokens(query)
    if not tokens:
        return []

    index = _load_current_chunk_index(channel_id)
    if index is None:
        return []

    chunks = index.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return []

    scored_sources = []
    seen_chunk_ids = set()
    indexed_video_ids = _indexed_video_ids(index)

    for chunk in chunks:
        if not _is_retrievable_chunk(chunk):
            continue
        if indexed_video_ids and chunk["video_id"] not in indexed_video_ids:
            continue
        chunk_id = chunk["chunk_id"]
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        if not _matches_scope(chunk, scope):
            continue

        score = _score_chunk(chunk, tokens)
        if score <= 0:
            continue

        text = chunk["text"]
        scored_sources.append(
            {
                "kind": "chunk",
                "chunk_id": chunk_id,
                "video_id": chunk["video_id"],
                "title": str(chunk.get("title") or ""),
                "upload_date": str(chunk.get("upload_date") or ""),
                "start_seconds": chunk["start_seconds"],
                "end_seconds": chunk["end_seconds"],
                "quote": _make_quote(text, tokens),
                "text": text,
                "score": round(score, 6),
            }
        )

    scored_sources.sort(key=_sort_key)
    limited_sources = scored_sources[:limit]
    for index, source in enumerate(limited_sources, start=1):
        source["source_id"] = f"S{index}"
    return limited_sources
