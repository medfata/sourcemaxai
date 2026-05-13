"""Build deterministic caption chunk indexes from existing transcript files."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend import storage
from backend.pipeline.schema_versions import (
    CHUNK_INDEX_SCHEMA_VERSION,
    TRANSCRIPT_SCHEMA_VERSION,
    get_transcript_stale_reasons,
    is_chunk_index_current,
)

CHUNKING_CONFIG = {
    "target_seconds_min": 45,
    "target_seconds_max": 90,
    "target_words_min": 120,
    "target_words_max": 250,
    "overlap_seconds": 15,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _selected_video_ids(channel_id: str) -> list[str]:
    selection = storage.load_selection(channel_id)
    if selection is not None:
        return selection
    videos = storage.load_videos(channel_id) or []
    return [video.get("id", "") for video in videos if video.get("id")]


def _word_count(text: str) -> int:
    return len(text.split())


def _json_seconds(value: float) -> int | float:
    numeric = float(value)
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _normalize_segments(raw_segments: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_segments, list):
        return []

    segments = []
    for order, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            continue
        try:
            start = float(segment.get("start"))
        except (TypeError, ValueError):
            continue
        text = " ".join(str(segment.get("text", "")).split())
        if not text:
            continue
        segments.append({"start": start, "text": text, "_order": order})

    return sorted(segments, key=lambda segment: (segment["start"], segment["_order"]))


def _make_chunk(
    video_id: str,
    title: str,
    upload_date: str,
    chunk_number: int,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    text = " ".join(segment["text"] for segment in segments)
    return {
        "chunk_id": f"{video_id}:{chunk_number:04d}",
        "video_id": video_id,
        "title": title,
        "upload_date": upload_date,
        "start_seconds": _json_seconds(segments[0]["start"]),
        "end_seconds": _json_seconds(segments[-1]["start"]),
        "text": text,
        "word_count": _word_count(text),
    }


def chunk_segments(
    video_id: str,
    title: str,
    upload_date: str,
    raw_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert timestamped transcript segments into stable overlapping chunks."""
    segments = _normalize_segments(raw_segments)
    if not segments:
        return []

    chunks = []
    start_index = 0

    while start_index < len(segments):
        chunk_start_seconds = segments[start_index]["start"]
        end_index = start_index
        word_total = 0

        while end_index < len(segments):
            current = segments[end_index]
            word_total += _word_count(current["text"])
            span_seconds = current["start"] - chunk_start_seconds

            next_index = end_index + 1
            if next_index >= len(segments):
                break

            next_span_seconds = segments[next_index]["start"] - chunk_start_seconds
            next_word_total = word_total + _word_count(segments[next_index]["text"])

            has_min_seconds = span_seconds >= CHUNKING_CONFIG["target_seconds_min"]
            has_min_words = word_total >= CHUNKING_CONFIG["target_words_min"]

            if has_min_seconds and has_min_words:
                break
            if has_min_seconds and next_span_seconds > CHUNKING_CONFIG["target_seconds_max"]:
                break
            if (
                has_min_seconds
                and has_min_words
                and next_word_total > CHUNKING_CONFIG["target_words_max"]
            ):
                break

            end_index = next_index

        chunks.append(
            _make_chunk(
                video_id,
                title,
                upload_date,
                len(chunks),
                segments[start_index : end_index + 1],
            )
        )

        if end_index >= len(segments) - 1:
            break

        next_start_index = end_index + 1
        overlap_start = segments[end_index]["start"] - CHUNKING_CONFIG["overlap_seconds"]
        for candidate_index in range(start_index + 1, end_index + 1):
            if segments[candidate_index]["start"] >= overlap_start:
                next_start_index = candidate_index
                break

        if next_start_index <= start_index:
            next_start_index = end_index + 1
        start_index = next_start_index

    return chunks


def _skip_result(
    video_id: str,
    reasons: list[str],
    *,
    stale: bool = False,
    schema_current: bool | None = None,
) -> dict[str, Any]:
    result = {
        "video_id": video_id,
        "status": "skipped",
        "chunk_count": 0,
        "stale": stale,
        "stale_reasons": reasons,
    }
    if schema_current is not None:
        result["schema_current"] = schema_current
    return result


def _index_without_generated_at(index: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in index.items() if key != "generated_at"}


def build_chunk_index(
    channel_id: str,
    on_progress=None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build data/channels/{channel_id}/chunk_index.json from current transcripts only."""
    channel_dir = storage.get_channel_dir(channel_id)
    index_path = channel_dir / "chunk_index.json"

    video_ids = _selected_video_ids(channel_id)
    videos = storage.load_videos(channel_id) or []
    video_map = {video.get("id", ""): video for video in videos}
    video_order = {video_id: order for order, video_id in enumerate(video_ids)}

    chunks = []
    skipped = []
    results = []

    for video_id in video_ids:
        transcript_path = channel_dir / "transcripts" / f"{video_id}.json"
        if not transcript_path.exists():
            result = _skip_result(video_id, ["missing_transcript_file"])
            skipped.append({"video_id": video_id, "reasons": result["stale_reasons"]})
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        transcript = storage.read_json(transcript_path)
        stale_reasons = get_transcript_stale_reasons(transcript)
        if stale_reasons:
            result = _skip_result(
                video_id,
                stale_reasons,
                stale=True,
                schema_current=False,
            )
            skipped.append({"video_id": video_id, "reasons": stale_reasons})
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        if not isinstance(transcript, dict):
            result = _skip_result(
                video_id,
                ["invalid_json_shape"],
                stale=True,
                schema_current=False,
            )
            skipped.append({"video_id": video_id, "reasons": result["stale_reasons"]})
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        if transcript.get("source") == "unavailable":
            result = _skip_result(video_id, ["unavailable"], schema_current=True)
            skipped.append({"video_id": video_id, "reasons": result["stale_reasons"]})
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        segments = _normalize_segments(transcript.get("segments"))
        if not segments:
            reasons = ["missing_timestamped_segments"]
            result = _skip_result(video_id, reasons, stale=True, schema_current=True)
            skipped.append({"video_id": video_id, "reasons": reasons})
            results.append(result)
            if on_progress:
                on_progress(result)
            continue

        video_info = video_map.get(video_id, {})
        title = transcript.get("title") or video_info.get("title") or "Untitled"
        upload_date = transcript.get("upload_date") or video_info.get("upload_date") or ""
        video_chunks = chunk_segments(video_id, title, upload_date, segments)
        chunks.extend(video_chunks)

        result = {
            "video_id": video_id,
            "status": "done",
            "chunk_count": len(video_chunks),
            "schema_current": True,
            "stale": False,
            "stale_reasons": [],
        }
        results.append(result)
        if on_progress:
            on_progress(result)

    chunks.sort(
        key=lambda chunk: (
            chunk.get("upload_date", ""),
            video_order.get(chunk.get("video_id", ""), len(video_order)),
            chunk.get("video_id", ""),
            float(chunk.get("start_seconds", 0)),
        )
    )

    index = {
        "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
        "channel_id": channel_id,
        "generated_at": generated_at or _utc_now_iso(),
        "chunking": dict(CHUNKING_CONFIG),
        "source": {
            "transcript_schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "selected_video_ids": video_ids,
        },
        "stats": {
            "selected_videos": len(video_ids),
            "indexed_videos": sum(1 for result in results if result["status"] == "done"),
            "skipped_videos": len(skipped),
            "chunks": len(chunks),
        },
        "skipped": skipped,
        "chunks": chunks,
    }

    existing = storage.read_json(index_path)
    if isinstance(existing, dict) and is_chunk_index_current(existing):
        if _index_without_generated_at(existing) == _index_without_generated_at(index):
            return {
                "total": len(video_ids),
                "results": results,
                "chunk_count": len(existing.get("chunks", [])),
                "path": str(index_path),
                "data": existing,
            }

    storage.write_json(index_path, index)
    return {
        "total": len(video_ids),
        "results": results,
        "chunk_count": len(chunks),
        "path": str(index_path),
        "data": index,
    }
