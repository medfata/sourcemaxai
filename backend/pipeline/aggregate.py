"""Pure-Python aggregation of per-video summaries into a channel profile."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.storage import get_channel_dir, read_json, write_json

REQUIRED_SUMMARY_FIELDS = {
    "video_id",
    "title",
    "upload_date",
    "core_topic",
    "key_claims",
    "recurring_themes",
    "tone_markers",
    "notable_opinions",
    "people_or_things_referenced",
}


def _load_summaries(channel_dir: Path) -> list[dict]:
    """Load all valid summary JSON files for a channel."""
    summaries_dir = channel_dir / "summaries"
    if not summaries_dir.exists():
        return []

    summaries = []
    for path in summaries_dir.glob("*.json"):
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if not REQUIRED_SUMMARY_FIELDS.issubset(data.keys()):
            continue
        summaries.append(data)
    return summaries


def _sort_summaries(summaries: list[dict]) -> list[dict]:
    """Sort summaries ascending by upload_date (YYYYMMDD string sort)."""
    return sorted(summaries, key=lambda s: s.get("upload_date", ""))


def _compute_rollups(summaries: list[dict]) -> dict:
    """Compute aggregated counters from summary objects.

    Casing is normalized (lower-cased) when counting, but the display label
    preserves the first-seen casing.
    """
    theme_counter: Counter = Counter()
    referenced_counter: Counter = Counter()
    tone_counter: Counter = Counter()

    theme_display: dict[str, str] = {}
    referenced_display: dict[str, str] = {}
    tone_display: dict[str, str] = {}

    for summary in summaries:
        for theme in summary.get("recurring_themes", []) or []:
            if isinstance(theme, str):
                key = theme.lower()
                theme_counter[key] += 1
                if key not in theme_display:
                    theme_display[key] = theme
        for ref in summary.get("people_or_things_referenced", []) or []:
            if isinstance(ref, str):
                key = ref.lower()
                referenced_counter[key] += 1
                if key not in referenced_display:
                    referenced_display[key] = ref
        for tone in summary.get("tone_markers", []) or []:
            if isinstance(tone, str):
                key = tone.lower()
                tone_counter[key] += 1
                if key not in tone_display:
                    tone_display[key] = tone

    all_themes = [
        {"theme": theme_display[key], "count": count}
        for key, count in theme_counter.most_common()
    ]
    # most_common returns count desc; for ties we want alphabetical asc by display label
    all_themes.sort(key=lambda x: (-x["count"], x["theme"].lower()))

    all_referenced = [
        {"name": referenced_display[key], "count": count}
        for key, count in referenced_counter.most_common(50)
    ]
    all_referenced.sort(key=lambda x: (-x["count"], x["name"].lower()))

    tone_distribution = {tone_display[key]: count for key, count in tone_counter.items()}

    return {
        "all_themes": all_themes,
        "all_referenced": all_referenced,
        "tone_distribution": tone_distribution,
        "theme_display": theme_display,
        "referenced_display": referenced_display,
        "tone_display": tone_display,
    }


def aggregate(channel_id: str) -> dict:
    """Aggregate all video summaries for a channel into a profile digest.

    Returns the profile dict and writes it to disk.
    """
    channel_dir = get_channel_dir(channel_id)
    meta = read_json(channel_dir / "meta.json") or {}

    summaries = _load_summaries(channel_dir)
    sorted_summaries = _sort_summaries(summaries)

    video_count = len(sorted_summaries)

    if video_count > 0:
        date_range = {
            "first": sorted_summaries[0].get("upload_date"),
            "last": sorted_summaries[-1].get("upload_date"),
        }
    else:
        date_range = {"first": None, "last": None}

    rollups = _compute_rollups(sorted_summaries) if video_count > 0 else {
        "all_themes": [],
        "all_referenced": [],
        "tone_distribution": {},
        "theme_display": {},
        "referenced_display": {},
        "tone_display": {},
    }

    theme_display = rollups.get("theme_display", {})
    referenced_display = rollups.get("referenced_display", {})
    tone_display = rollups.get("tone_display", {})

    videos = []
    for summary in sorted_summaries:
        video = dict(summary)
        if "recurring_themes" in video:
            video["recurring_themes"] = [
                theme_display.get(theme.lower(), theme) if isinstance(theme, str) else theme
                for theme in video["recurring_themes"]
            ]
        if "tone_markers" in video:
            video["tone_markers"] = [
                tone_display.get(tone.lower(), tone) if isinstance(tone, str) else tone
                for tone in video["tone_markers"]
            ]
        if "people_or_things_referenced" in video:
            video["people_or_things_referenced"] = [
                referenced_display.get(ref.lower(), ref) if isinstance(ref, str) else ref
                for ref in video["people_or_things_referenced"]
            ]
        videos.append(video)

    # Remove internal display maps from the public rollups payload
    public_rollups = {
        k: v for k, v in rollups.items()
        if k not in {"theme_display", "referenced_display", "tone_display"}
    }

    profile = {
        "channel_id": channel_id,
        "channel_name": meta.get("channel_name", ""),
        "channel_handle": meta.get("channel_handle"),
        "avatar_url": meta.get("avatar_url"),
        "video_count": video_count,
        "date_range": date_range,
        "videos": videos,
        "rollups": public_rollups,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    write_json(channel_dir / "profile.json", profile)
    return profile
