"""Tests for generated-file schema version and stale detection helpers."""

from backend.pipeline.schema_versions import (
    CHUNK_INDEX_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    SUMMARY_MODEL,
    SUMMARY_SCHEMA_VERSION,
    TRANSCRIPT_SCHEMA_VERSION,
    get_chunk_index_stale_reasons,
    get_profile_stale_reasons,
    get_summary_stale_reasons,
    get_transcript_stale_reasons,
    is_chunk_index_current,
    is_profile_current,
    is_summary_current,
    is_transcript_current,
)


def _current_summary() -> dict:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        "video_id": "vid_1",
        "title": "Video 1",
        "upload_date": "20240101",
        "core_topic": "Testing schema detection",
        "key_claims": [
            {
                "text": "Claims must carry evidence metadata.",
                "evidence": [{"start_seconds": 12, "quote": "claims must carry evidence"}],
            }
        ],
        "recurring_themes": ["testing"],
        "tone_markers": ["direct"],
        "notable_opinions": [],
        "people_or_things_referenced": [],
        "questions_answered": ["What does schema detection require?"],
        "concepts": ["schema detection"],
        "tactics": ["validate generated files"],
        "story_events": [],
        "audience": "developers maintaining the pipeline",
        "summary_confidence": 0.9,
        "model": SUMMARY_MODEL,
        "prompt_hash": "abc123",
        "generated_at": "2026-01-01T00:00:00+00:00",
    }


def _current_profile() -> dict:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "channel_id": "UC_test",
        "channel_name": "Test Channel",
        "video_count": 0,
        "date_range": {"first": None, "last": None},
        "videos": [],
        "rollups": {
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
        },
        "generated_at": "2026-01-01T00:00:00+00:00",
    }


def test_transcript_current_vs_legacy_and_missing_segments():
    current = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "video_id": "vid_1",
        "segments": [{"start": 0.0, "text": "hello"}],
    }
    assert is_transcript_current(current)

    legacy = {"video_id": "vid_1", "segments": [{"start": 0.0, "text": "hello"}]}
    assert not is_transcript_current(legacy)
    assert "missing_schema_version" in get_transcript_stale_reasons(legacy)

    missing_segments = {"schema_version": TRANSCRIPT_SCHEMA_VERSION, "video_id": "vid_1"}
    assert not is_transcript_current(missing_segments)
    assert "missing_segments" in get_transcript_stale_reasons(missing_segments)


def test_summary_current_vs_legacy_without_evidence():
    current = _current_summary()
    assert is_summary_current(current)

    legacy = dict(current)
    legacy.pop("schema_version")
    assert not is_summary_current(legacy)
    assert "missing_schema_version" in get_summary_stale_reasons(legacy)

    missing_summary_schema = dict(current)
    missing_summary_schema.pop("summary_schema_version")
    assert not is_summary_current(missing_summary_schema)
    assert "missing_summary_schema_version" in get_summary_stale_reasons(
        missing_summary_schema
    )

    old_string_claims = dict(current, key_claims=["old claim shape"])
    assert not is_summary_current(old_string_claims)
    assert "key_claims_missing_evidence_metadata" in get_summary_stale_reasons(
        old_string_claims
    )

    unsupported_claim = dict(
        current,
        key_claims=[{"text": "unsupported", "evidence": []}],
        notable_opinions=[],
    )
    assert is_summary_current(unsupported_claim)

    invalid_evidence = dict(
        current,
        key_claims=[{"text": "bad evidence", "evidence": [{"start_seconds": 12}]}],
    )
    assert not is_summary_current(invalid_evidence)
    assert "key_claims_invalid_evidence_entry" in get_summary_stale_reasons(
        invalid_evidence
    )

    invalid_confidence = dict(current, summary_confidence=1.5)
    assert not is_summary_current(invalid_confidence)
    assert "invalid_summary_confidence" in get_summary_stale_reasons(invalid_confidence)


def test_profile_current_vs_legacy_missing_schema_version():
    current = _current_profile()
    assert is_profile_current(current)

    legacy = dict(current)
    legacy.pop("schema_version")
    assert not is_profile_current(legacy)
    assert "missing_schema_version" in get_profile_stale_reasons(legacy)


def test_chunk_index_current_vs_stale_shapes():
    current = {
        "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
        "channel_id": "UC_test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "chunking": {
            "target_seconds_min": 45,
            "target_seconds_max": 90,
            "target_words_min": 120,
            "target_words_max": 250,
            "overlap_seconds": 15,
        },
        "chunks": [],
    }
    assert is_chunk_index_current(current)

    legacy = {
        "channel_id": "UC_test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "chunking": {},
        "chunks": [],
    }
    assert not is_chunk_index_current(legacy)
    assert "missing_schema_version" in get_chunk_index_stale_reasons(legacy)

    missing_chunks = {
        "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
        "channel_id": "UC_test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "chunking": {},
    }
    assert not is_chunk_index_current(missing_chunks)
    assert "missing_chunks" in get_chunk_index_stale_reasons(missing_chunks)
