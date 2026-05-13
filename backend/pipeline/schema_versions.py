"""Schema versions and stale-detection helpers for generated pipeline files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend import storage

TRANSCRIPT_SCHEMA_VERSION = 2
SUMMARY_SCHEMA_VERSION = 3
PROFILE_SCHEMA_VERSION = 3
CHUNK_INDEX_SCHEMA_VERSION = 1

SUMMARY_MODEL = "MiniMax-M2.7"

SUMMARY_REQUIRED_FIELDS = {
    "video_id",
    "title",
    "upload_date",
    "core_topic",
    "key_claims",
    "recurring_themes",
    "tone_markers",
    "notable_opinions",
    "people_or_things_referenced",
    "questions_answered",
    "concepts",
    "tactics",
    "story_events",
    "audience",
    "summary_confidence",
}

PROFILE_REQUIRED_FIELDS = {
    "channel_id",
    "channel_name",
    "video_count",
    "date_range",
    "videos",
    "rollups",
    "generated_at",
}

PROFILE_ROLLUP_REQUIRED_FIELDS = {
    "all_themes",
    "all_referenced",
    "tone_distribution",
    "all_concepts",
    "all_tactics",
    "all_questions_answered",
    "audience_distribution",
    "summary_quality",
}

PROFILE_VIDEO_REQUIRED_FIELDS = SUMMARY_REQUIRED_FIELDS.difference(
    {"summary_schema_version"}
)

CHUNK_INDEX_REQUIRED_FIELDS = {
    "channel_id",
    "generated_at",
    "chunking",
}

CHUNK_REQUIRED_FIELDS = {
    "chunk_id",
    "video_id",
    "title",
    "upload_date",
    "start_seconds",
    "end_seconds",
    "text",
    "word_count",
}


def _schema_reasons(data: Any, expected_version: int) -> list[str]:
    if not isinstance(data, dict):
        return ["invalid_json_shape"]
    reasons = []
    if "schema_version" not in data:
        reasons.append("missing_schema_version")
    elif data.get("schema_version") != expected_version:
        reasons.append("schema_version_mismatch")
    return reasons


def _summary_schema_reasons(data: Any) -> list[str]:
    reasons = _schema_reasons(data, SUMMARY_SCHEMA_VERSION)
    if not isinstance(data, dict):
        return reasons

    if "summary_schema_version" not in data:
        reasons.append("missing_summary_schema_version")
    elif data.get("summary_schema_version") != SUMMARY_SCHEMA_VERSION:
        reasons.append("summary_schema_version_mismatch")
    return reasons


def get_transcript_stale_reasons(data: Any) -> list[str]:
    """Return reasons a transcript JSON object is stale, or an empty list."""
    reasons = _schema_reasons(data, TRANSCRIPT_SCHEMA_VERSION)
    if not isinstance(data, dict):
        return reasons
    if "segments" not in data:
        reasons.append("missing_segments")
    elif not isinstance(data.get("segments"), list):
        reasons.append("invalid_segments")
    return reasons


def is_transcript_current(data: Any) -> bool:
    """Return True when transcript JSON matches the current generated schema."""
    return not get_transcript_stale_reasons(data)


def _evidence_entry_is_valid(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    start_seconds = entry.get("start_seconds")
    quote = entry.get("quote")
    return isinstance(start_seconds, int | float) and isinstance(quote, str) and bool(quote)


def _summary_claim_reasons(data: dict[str, Any]) -> list[str]:
    reasons = []

    for field in ("key_claims", "notable_opinions"):
        if field not in data:
            continue
        items = data.get(field)
        if not isinstance(items, list):
            reasons.append(f"invalid_{field}")
            continue
        for item in items:
            if not isinstance(item, dict):
                reasons.append(f"{field}_missing_evidence_metadata")
                continue
            if not isinstance(item.get("text"), str) or not item.get("text", "").strip():
                reasons.append(f"{field}_invalid_text")
            if "evidence" not in item:
                reasons.append(f"{field}_missing_evidence_metadata")
                continue
            evidence = item.get("evidence")
            if not isinstance(evidence, list):
                reasons.append(f"{field}_invalid_evidence")
                continue
            for entry in evidence:
                if not _evidence_entry_is_valid(entry):
                    reasons.append(f"{field}_invalid_evidence_entry")
                    break

    return reasons


def _summary_metadata_reasons(data: dict[str, Any]) -> list[str]:
    reasons = []
    for field in (
        "recurring_themes",
        "tone_markers",
        "people_or_things_referenced",
        "questions_answered",
        "concepts",
        "tactics",
        "story_events",
    ):
        if field not in data:
            continue
        value = data.get(field)
        if not isinstance(value, list):
            reasons.append(f"invalid_{field}")
            continue
        if any(not isinstance(item, str) for item in value):
            reasons.append(f"invalid_{field}_item")

    audience = data.get("audience")
    if "audience" in data and not isinstance(audience, str):
        reasons.append("invalid_audience")

    confidence = data.get("summary_confidence")
    if "summary_confidence" in data and (
        not isinstance(confidence, int | float) or not 0 <= float(confidence) <= 1
    ):
        reasons.append("invalid_summary_confidence")

    return reasons


def get_summary_stale_reasons(data: Any) -> list[str]:
    """Return reasons a per-video summary JSON object is stale, or an empty list."""
    reasons = _summary_schema_reasons(data)
    if not isinstance(data, dict):
        return reasons

    for field in SUMMARY_REQUIRED_FIELDS:
        if field not in data:
            reasons.append(f"missing_{field}")

    for field in ("model", "prompt_hash", "generated_at"):
        if not data.get(field):
            reasons.append(f"missing_{field}")

    reasons.extend(_summary_claim_reasons(data))
    reasons.extend(_summary_metadata_reasons(data))
    return reasons


def is_summary_current(data: Any) -> bool:
    """Return True when summary JSON matches the current generated schema."""
    return not get_summary_stale_reasons(data)


def get_profile_stale_reasons(data: Any) -> list[str]:
    """Return reasons profile JSON is stale, or an empty list."""
    reasons = _schema_reasons(data, PROFILE_SCHEMA_VERSION)
    if not isinstance(data, dict):
        return reasons

    for field in PROFILE_REQUIRED_FIELDS:
        if field not in data:
            reasons.append(f"missing_{field}")

    if "videos" in data and not isinstance(data.get("videos"), list):
        reasons.append("invalid_videos")
    elif isinstance(data.get("videos"), list):
        for video in data.get("videos", []):
            if not isinstance(video, dict):
                reasons.append("invalid_video_shape")
                break
            missing = PROFILE_VIDEO_REQUIRED_FIELDS.difference(video.keys())
            if missing:
                reasons.append("invalid_video_shape")
                break
    if "rollups" in data and not isinstance(data.get("rollups"), dict):
        reasons.append("invalid_rollups")
    elif isinstance(data.get("rollups"), dict):
        for field in PROFILE_ROLLUP_REQUIRED_FIELDS:
            if field not in data["rollups"]:
                reasons.append(f"missing_rollup_{field}")
    return reasons


def is_profile_current(data: Any) -> bool:
    """Return True when profile JSON matches the current generated schema."""
    return not get_profile_stale_reasons(data)


def get_chunk_index_stale_reasons(data: Any) -> list[str]:
    """Return reasons a chunk index object is stale, or an empty list."""
    reasons = _schema_reasons(data, CHUNK_INDEX_SCHEMA_VERSION)
    if not isinstance(data, dict):
        return reasons

    for field in CHUNK_INDEX_REQUIRED_FIELDS:
        if field not in data:
            reasons.append(f"missing_{field}")

    if "generated_at" in data and not data.get("generated_at"):
        reasons.append("missing_generated_at")
    if "chunking" in data and not isinstance(data.get("chunking"), dict):
        reasons.append("invalid_chunking")

    if "chunks" not in data:
        reasons.append("missing_chunks")
    elif not isinstance(data.get("chunks"), list):
        reasons.append("invalid_chunks")
    else:
        for chunk in data.get("chunks", []):
            if not isinstance(chunk, dict):
                reasons.append("invalid_chunk_shape")
                break
            missing = CHUNK_REQUIRED_FIELDS.difference(chunk.keys())
            if missing:
                reasons.append("invalid_chunk_shape")
                break
    return reasons


def is_chunk_index_current(data: Any) -> bool:
    """Return True when chunk-index JSON matches the current generated schema."""
    return not get_chunk_index_stale_reasons(data)


def _file_status(path: Path, stale_reasons: list[str]) -> dict[str, Any]:
    status = "current" if not stale_reasons else "stale"
    return {
        "path": str(path),
        "status": status,
        "current": status == "current",
        "stale": status == "stale",
        "stale_reasons": stale_reasons,
    }


def _selected_video_ids(channel_id: str) -> list[str]:
    selection = storage.load_selection(channel_id)
    if selection is not None:
        return selection
    videos = storage.load_videos(channel_id) or []
    return [video.get("id", "") for video in videos if video.get("id")]


def _inspect_video_files(
    channel_dir: Path,
    video_ids: list[str],
    dirname: str,
    reason_fn: Callable[[Any], list[str]],
) -> dict[str, Any]:
    items = {}
    counts = {"current": 0, "stale": 0, "missing": 0}
    for video_id in video_ids:
        path = channel_dir / dirname / f"{video_id}.json"
        if not path.exists():
            items[video_id] = {
                "path": str(path),
                "status": "missing",
                "current": False,
                "stale": False,
                "stale_reasons": [],
            }
            counts["missing"] += 1
            continue
        data = storage.read_json(path)
        file_status = _file_status(path, reason_fn(data))
        items[video_id] = file_status
        counts[file_status["status"]] += 1
    return {"counts": counts, "items": items}


def get_generated_file_report(channel_id: str) -> dict[str, Any]:
    """Inspect generated files for a channel without mutating or regenerating them."""
    channel_dir = storage.get_channel_dir(channel_id)
    video_ids = _selected_video_ids(channel_id)

    profile_path = channel_dir / "profile.json"
    if profile_path.exists():
        profile = _file_status(
            profile_path,
            get_profile_stale_reasons(storage.read_json(profile_path)),
        )
    else:
        profile = {
            "path": str(profile_path),
            "status": "missing",
            "current": False,
            "stale": False,
            "stale_reasons": [],
        }

    chunk_index_path = channel_dir / "chunk_index.json"
    if chunk_index_path.exists():
        chunk_index = _file_status(
            chunk_index_path,
            get_chunk_index_stale_reasons(storage.read_json(chunk_index_path)),
        )
    else:
        chunk_index = {
            "path": str(chunk_index_path),
            "status": "missing",
            "current": False,
            "stale": False,
            "stale_reasons": [],
        }

    report = {
        "schema_versions": {
            "transcript": TRANSCRIPT_SCHEMA_VERSION,
            "summary": SUMMARY_SCHEMA_VERSION,
            "profile": PROFILE_SCHEMA_VERSION,
            "chunk_index": CHUNK_INDEX_SCHEMA_VERSION,
        },
        "transcripts": _inspect_video_files(
            channel_dir,
            video_ids,
            "transcripts",
            get_transcript_stale_reasons,
        ),
        "summaries": _inspect_video_files(
            channel_dir,
            video_ids,
            "summaries",
            get_summary_stale_reasons,
        ),
        "profile": profile,
        "chunk_index": chunk_index,
    }
    report["has_stale"] = (
        report["transcripts"]["counts"]["stale"] > 0
        or report["summaries"]["counts"]["stale"] > 0
        or report["profile"]["stale"]
        or report["chunk_index"]["stale"]
    )
    return report
