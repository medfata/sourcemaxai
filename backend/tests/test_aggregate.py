"""Unit test for aggregator case normalization."""

import json
import os
import tempfile
from pathlib import Path


def test_case_normalization():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATA_DIR"] = tmpdir
        # Reload storage module to pick up new DATA_DIR
        import importlib
        from backend import storage
        importlib.reload(storage)
        from backend.pipeline.aggregate import aggregate

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
                "title": "Video 0",
                "upload_date": "20230101",
                "core_topic": "Test",
                "key_claims": ["claim1"],
                "recurring_themes": ["AI", "Technology", "Machine Learning"],
                "tone_markers": ["analytical", "Calm", "CALM"],
                "notable_opinions": ["op1"],
                "people_or_things_referenced": ["OpenAI", "openai", "Python"],
            },
            {
                "video_id": "vid_1",
                "title": "Video 1",
                "upload_date": "20230102",
                "core_topic": "Test",
                "key_claims": ["claim1"],
                "recurring_themes": ["ai", "technology", "Deep Learning"],
                "tone_markers": ["analytical", "calm"],
                "notable_opinions": ["op1"],
                "people_or_things_referenced": ["OpenAI", "Python", "Guido"],
            },
            {
                "video_id": "vid_2",
                "title": "Video 2",
                "upload_date": "20230103",
                "core_topic": "Test",
                "key_claims": ["claim1"],
                "recurring_themes": ["Ai", "TECHNOLOGY", "Neural Networks"],
                "tone_markers": ["enthusiastic"],
                "notable_opinions": ["op1"],
                "people_or_things_referenced": ["Elon Musk", "OpenAI"],
            },
        ]

        for summary in summaries:
            storage.write_json(summaries_dir / f"{summary['video_id']}.json", summary)

        profile = aggregate(channel_id)

        assert profile["video_count"] == 3

        themes = {t["theme"]: t["count"] for t in profile["rollups"]["all_themes"]}
        assert themes["AI"] == 3, f"Expected AI count 3, got {themes.get('AI')}"
        assert themes["Technology"] == 3, f"Expected Technology count 3, got {themes.get('Technology')}"

        tones = profile["rollups"]["tone_distribution"]
        assert tones["analytical"] == 2, f"Expected analytical count 2, got {tones.get('analytical')}"
        assert tones["Calm"] == 3, f"Expected Calm count 3, got {tones.get('Calm')}"
        assert tones["enthusiastic"] == 1, f"Expected enthusiastic count 1, got {tones.get('enthusiastic')}"

        refs = {r["name"]: r["count"] for r in profile["rollups"]["all_referenced"]}
        assert refs["OpenAI"] == 4, f"Expected OpenAI count 4, got {refs.get('OpenAI')}"
        assert refs["Python"] == 2, f"Expected Python count 2, got {refs.get('Python')}"
        assert refs["Guido"] == 1
        assert refs["Elon Musk"] == 1

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

        print("All case-normalization assertions passed!")


if __name__ == "__main__":
    test_case_normalization()
