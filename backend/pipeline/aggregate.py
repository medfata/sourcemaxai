"""Pure-Python aggregation of per-video summaries into a channel profile."""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.pipeline.schema_versions import (
    PROFILE_SCHEMA_VERSION,
    SUMMARY_REQUIRED_FIELDS,
    is_summary_current,
)
from backend.storage import get_channel_dir, load_channel_meta, read_json, save_profile, write_json


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
        if not SUMMARY_REQUIRED_FIELDS.issubset(data.keys()):
            continue
        if not is_summary_current(data):
            continue
        summaries.append(data)
    return summaries


def _sort_summaries(summaries: list[dict]) -> list[dict]:
    """Sort summaries ascending by upload_date (YYYYMMDD string sort)."""
    return sorted(summaries, key=lambda s: s.get("upload_date", ""))


def _add_string_counts(
    counter: Counter,
    display: dict[str, str],
    values: list | None,
) -> None:
    for value in values or []:
        if isinstance(value, str) and value.strip():
            label = value.strip()
            key = label.lower()
            counter[key] += 1
            if key not in display:
                display[key] = label


def _ranked_items(
    counter: Counter,
    display: dict[str, str],
    label_key: str,
    limit: int | None = None,
) -> list[dict]:
    items = [
        {label_key: display[key], "count": count}
        for key, count in counter.most_common(limit)
    ]
    items.sort(key=lambda item: (-item["count"], str(item[label_key]).lower()))
    return items


def _summary_claim_metrics(summary: dict) -> dict:
    claim_count = 0
    supported_claim_count = 0
    for field in ("key_claims", "notable_opinions"):
        claims = summary.get(field, [])
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_count += 1
            if claim.get("evidence"):
                supported_claim_count += 1
    unsupported_claim_count = claim_count - supported_claim_count
    return {
        "claim_count": claim_count,
        "supported_claim_count": supported_claim_count,
        "unsupported_claim_count": unsupported_claim_count,
    }


def _compute_rollups(summaries: list[dict]) -> dict:
    """Compute aggregated counters from summary objects.

    Casing is normalized (lower-cased) when counting, but the display label
    preserves the first-seen casing.
    """
    theme_counter: Counter = Counter()
    referenced_counter: Counter = Counter()
    tone_counter: Counter = Counter()
    concept_counter: Counter = Counter()
    tactic_counter: Counter = Counter()
    question_counter: Counter = Counter()
    audience_counter: Counter = Counter()

    theme_display: dict[str, str] = {}
    referenced_display: dict[str, str] = {}
    tone_display: dict[str, str] = {}
    concept_display: dict[str, str] = {}
    tactic_display: dict[str, str] = {}
    question_display: dict[str, str] = {}
    audience_display: dict[str, str] = {}

    claim_count = 0
    supported_claim_count = 0
    unsupported_claim_count = 0
    confidence_total = 0.0
    confidence_count = 0

    for summary in summaries:
        _add_string_counts(theme_counter, theme_display, summary.get("recurring_themes"))
        _add_string_counts(
            referenced_counter,
            referenced_display,
            summary.get("people_or_things_referenced"),
        )
        _add_string_counts(tone_counter, tone_display, summary.get("tone_markers"))
        _add_string_counts(concept_counter, concept_display, summary.get("concepts"))
        _add_string_counts(tactic_counter, tactic_display, summary.get("tactics"))
        _add_string_counts(
            question_counter,
            question_display,
            summary.get("questions_answered"),
        )

        audience = summary.get("audience")
        if isinstance(audience, str) and audience.strip():
            _add_string_counts(audience_counter, audience_display, [audience])

        metrics = _summary_claim_metrics(summary)
        claim_count += metrics["claim_count"]
        supported_claim_count += metrics["supported_claim_count"]
        unsupported_claim_count += metrics["unsupported_claim_count"]

        confidence = summary.get("summary_confidence")
        if isinstance(confidence, int | float):
            confidence_total += float(confidence)
            confidence_count += 1

    all_themes = _ranked_items(theme_counter, theme_display, "theme")
    all_referenced = _ranked_items(referenced_counter, referenced_display, "name", 50)
    all_concepts = _ranked_items(concept_counter, concept_display, "concept", 50)
    all_tactics = _ranked_items(tactic_counter, tactic_display, "tactic", 50)
    all_questions_answered = _ranked_items(
        question_counter,
        question_display,
        "question",
        50,
    )

    tone_distribution = {tone_display[key]: count for key, count in tone_counter.items()}
    audience_distribution = {
        audience_display[key]: count for key, count in audience_counter.items()
    }
    evidence_rate = supported_claim_count / claim_count if claim_count else 1.0

    return {
        "all_themes": all_themes,
        "all_referenced": all_referenced,
        "tone_distribution": tone_distribution,
        "all_concepts": all_concepts,
        "all_tactics": all_tactics,
        "all_questions_answered": all_questions_answered,
        "audience_distribution": audience_distribution,
        "summary_quality": {
            "claim_count": claim_count,
            "supported_claim_count": supported_claim_count,
            "unsupported_claim_count": unsupported_claim_count,
            "evidence_rate": round(evidence_rate, 3),
            "average_confidence": (
                round(confidence_total / confidence_count, 3)
                if confidence_count
                else 0.0
            ),
        },
        "theme_display": theme_display,
        "referenced_display": referenced_display,
        "tone_display": tone_display,
        "concept_display": concept_display,
        "tactic_display": tactic_display,
    }


def aggregate(channel_id: str) -> dict:
    """Aggregate all video summaries for a channel into a profile digest.

    Returns the profile dict and writes it to disk.
    """
    channel_dir = get_channel_dir(channel_id)
    meta = load_channel_meta(channel_id) or read_json(channel_dir / "meta.json") or {}

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
        "all_concepts": [],
        "all_tactics": [],
        "all_questions_answered": [],
        "audience_distribution": {},
        "summary_quality": {
            "claim_count": 0,
            "supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "evidence_rate": 1.0,
            "average_confidence": 0.0,
        },
        "theme_display": {},
        "referenced_display": {},
        "tone_display": {},
        "concept_display": {},
        "tactic_display": {},
    }

    theme_display = rollups.get("theme_display", {})
    referenced_display = rollups.get("referenced_display", {})
    tone_display = rollups.get("tone_display", {})
    concept_display = rollups.get("concept_display", {})
    tactic_display = rollups.get("tactic_display", {})

    videos = []
    for summary in sorted_summaries:
        video = {
            key: value
            for key, value in summary.items()
            if key not in {
                "schema_version",
                "summary_schema_version",
                "model",
                "prompt_hash",
                "generated_at",
            }
        }
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
        if "concepts" in video:
            video["concepts"] = [
                (
                    concept_display.get(concept.lower(), concept)
                    if isinstance(concept, str)
                    else concept
                )
                for concept in video["concepts"]
            ]
        if "tactics" in video:
            video["tactics"] = [
                tactic_display.get(tactic.lower(), tactic) if isinstance(tactic, str) else tactic
                for tactic in video["tactics"]
            ]
        videos.append(video)

    # Remove internal display maps from the public rollups payload
    public_rollups = {
        k: v for k, v in rollups.items()
        if k not in {
            "theme_display",
            "referenced_display",
            "tone_display",
            "concept_display",
            "tactic_display",
        }
    }

    profile = {
        "schema_version": PROFILE_SCHEMA_VERSION,
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
    save_profile(channel_id, "manual", profile)
    return profile
