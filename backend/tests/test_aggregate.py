"""Unit test for aggregator case normalization."""

import importlib
import os
import tempfile


def test_case_normalization():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATA_DIR"] = tmpdir
        # Reload storage module to pick up new DATA_DIR
        from backend import storage

        importlib.reload(storage)
        from backend.pipeline.aggregate import aggregate
        from backend.pipeline.schema_versions import (
            PROFILE_SCHEMA_VERSION,
            SUMMARY_MODEL,
            SUMMARY_SCHEMA_VERSION,
        )

        channel_id = "test_channel"
        channel_dir = storage.get_channel_dir(channel_id)

        storage.write_json(
            channel_dir / "meta.json",
            {
                "channel_id": channel_id,
                "channel_name": "Test Channel",
                "channel_handle": "@test",
                "avatar_url": "http://example.com/avatar.jpg",
            },
        )

        summaries_dir = channel_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)

        summaries = [
            {
                "video_id": "vid_0",
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "summary_schema_version": SUMMARY_SCHEMA_VERSION,
                "title": "Video 0",
                "upload_date": "20230101",
                "core_topic": "Test",
                "key_claims": [
                    {
                        "text": "claim1",
                        "evidence": [{"start_seconds": 1, "quote": "claim1"}],
                    }
                ],
                "recurring_themes": ["AI", "Technology", "Machine Learning"],
                "tone_markers": ["analytical", "Calm", "CALM"],
                "notable_opinions": [
                    {
                        "text": "op1",
                        "evidence": [{"start_seconds": 2, "quote": "op1"}],
                    }
                ],
                "people_or_things_referenced": ["OpenAI", "openai", "Python"],
                "questions_answered": ["How does AI help teams?"],
                "concepts": ["AI", "Developer Tools"],
                "tactics": ["Automate Repetitive Tasks"],
                "story_events": [],
                "audience": "software teams",
                "summary_confidence": 0.8,
                "model": SUMMARY_MODEL,
                "prompt_hash": "hash0",
                "generated_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "video_id": "vid_1",
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "summary_schema_version": SUMMARY_SCHEMA_VERSION,
                "title": "Video 1",
                "upload_date": "20230102",
                "core_topic": "Test",
                "key_claims": [
                    {
                        "text": "claim1",
                        "evidence": [{"start_seconds": 1, "quote": "claim1"}],
                    }
                ],
                "recurring_themes": ["ai", "technology", "Deep Learning"],
                "tone_markers": ["analytical", "calm"],
                "notable_opinions": [
                    {
                        "text": "op1",
                        "evidence": [{"start_seconds": 2, "quote": "op1"}],
                    }
                ],
                "people_or_things_referenced": ["OpenAI", "Python", "Guido"],
                "questions_answered": ["How does AI help teams?"],
                "concepts": ["ai", "Deep Learning"],
                "tactics": ["automate repetitive tasks"],
                "story_events": ["A team shipped a model"],
                "audience": "Software Teams",
                "summary_confidence": 0.7,
                "model": SUMMARY_MODEL,
                "prompt_hash": "hash1",
                "generated_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "video_id": "vid_2",
                "schema_version": SUMMARY_SCHEMA_VERSION,
                "summary_schema_version": SUMMARY_SCHEMA_VERSION,
                "title": "Video 2",
                "upload_date": "20230103",
                "core_topic": "Test",
                "key_claims": [
                    {
                        "text": "claim1",
                        "evidence": [{"start_seconds": 1, "quote": "claim1"}],
                    },
                    {
                        "text": "unsupported claim stays searchable but uncited",
                        "evidence": [],
                    }
                ],
                "recurring_themes": ["Ai", "TECHNOLOGY", "Neural Networks"],
                "tone_markers": ["enthusiastic"],
                "notable_opinions": [
                    {
                        "text": "op1",
                        "evidence": [{"start_seconds": 2, "quote": "op1"}],
                    }
                ],
                "people_or_things_referenced": ["Elon Musk", "OpenAI"],
                "questions_answered": ["What are neural networks?"],
                "concepts": ["Neural Networks"],
                "tactics": ["Review Model Failures"],
                "story_events": ["A demo failed live"],
                "audience": "machine learning practitioners",
                "summary_confidence": 0.6,
                "model": SUMMARY_MODEL,
                "prompt_hash": "hash2",
                "generated_at": "2026-01-01T00:00:00+00:00",
            },
        ]

        for summary in summaries:
            storage.write_json(summaries_dir / f"{summary['video_id']}.json", summary)

        profile = aggregate(channel_id)

        assert profile["schema_version"] == PROFILE_SCHEMA_VERSION
        assert profile["video_count"] == 3

        themes = {t["theme"]: t["count"] for t in profile["rollups"]["all_themes"]}
        assert themes["AI"] == 3, f"Expected AI count 3, got {themes.get('AI')}"
        assert themes["Technology"] == 3, (
            f"Expected Technology count 3, got {themes.get('Technology')}"
        )

        tones = profile["rollups"]["tone_distribution"]
        assert tones["analytical"] == 2, (
            f"Expected analytical count 2, got {tones.get('analytical')}"
        )
        assert tones["Calm"] == 3, f"Expected Calm count 3, got {tones.get('Calm')}"
        assert tones["enthusiastic"] == 1, (
            f"Expected enthusiastic count 1, got {tones.get('enthusiastic')}"
        )

        refs = {r["name"]: r["count"] for r in profile["rollups"]["all_referenced"]}
        assert refs["OpenAI"] == 4, f"Expected OpenAI count 4, got {refs.get('OpenAI')}"
        assert refs["Python"] == 2, f"Expected Python count 2, got {refs.get('Python')}"
        assert refs["Guido"] == 1
        assert refs["Elon Musk"] == 1

        concepts = {c["concept"]: c["count"] for c in profile["rollups"]["all_concepts"]}
        assert concepts["AI"] == 2
        assert concepts["Developer Tools"] == 1
        assert concepts["Deep Learning"] == 1
        assert concepts["Neural Networks"] == 1

        tactics = {t["tactic"]: t["count"] for t in profile["rollups"]["all_tactics"]}
        assert tactics["Automate Repetitive Tasks"] == 2
        assert tactics["Review Model Failures"] == 1

        questions = {
            q["question"]: q["count"]
            for q in profile["rollups"]["all_questions_answered"]
        }
        assert questions["How does AI help teams?"] == 2
        assert questions["What are neural networks?"] == 1

        assert profile["rollups"]["audience_distribution"]["software teams"] == 2
        assert profile["rollups"]["summary_quality"] == {
            "claim_count": 7,
            "supported_claim_count": 6,
            "unsupported_claim_count": 1,
            "evidence_rate": 0.857,
            "average_confidence": 0.7,
        }

        # Verify per-video arrays are canonicalized to display-label casing
        v0 = profile["videos"][0]
        v1 = profile["videos"][1]
        v2 = profile["videos"][2]

        assert v0["recurring_themes"] == ["AI", "Technology", "Machine Learning"]
        assert v1["recurring_themes"] == ["AI", "Technology", "Deep Learning"]
        assert v2["recurring_themes"] == ["AI", "Technology", "Neural Networks"]

        assert v0["tone_markers"] == ["analytical", "Calm", "Calm"]
        assert v1["tone_markers"] == ["analytical", "Calm"]
        assert v2["tone_markers"] == ["enthusiastic"]

        assert v0["people_or_things_referenced"] == ["OpenAI", "OpenAI", "Python"]
        assert v1["people_or_things_referenced"] == ["OpenAI", "Python", "Guido"]
        assert v2["people_or_things_referenced"] == ["Elon Musk", "OpenAI"]
        assert v1["concepts"] == ["AI", "Deep Learning"]
        assert v1["tactics"] == ["Automate Repetitive Tasks"]
        assert v2["key_claims"][1]["evidence"] == []
        assert "schema_version" not in v0
        assert "summary_schema_version" not in v0

        print("All case-normalization assertions passed!")


if __name__ == "__main__":
    test_case_normalization()
