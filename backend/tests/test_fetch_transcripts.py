"""Tests for transcript queue pacing and block handling."""

from backend.pipeline import fetch_transcripts as fetch_transcripts_module


def test_fetch_transcripts_stops_queue_after_youtube_block(monkeypatch, tmp_path):
    channel_id = "UC_transcript_block"
    calls: list[str] = []
    progress: list[dict] = []

    monkeypatch.setattr(fetch_transcripts_module, "STOP_ON_BLOCK", True)
    monkeypatch.setattr(fetch_transcripts_module, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetch_transcripts_module, "BATCH_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetch_transcripts_module, "DELAY_JITTER_SECONDS", 0)
    monkeypatch.setattr(fetch_transcripts_module, "load_selection", lambda _channel_id: [
        "vid_0",
        "vid_1",
        "vid_2",
    ])
    monkeypatch.setattr(fetch_transcripts_module, "load_videos", lambda _channel_id: [
        {"id": "vid_0", "title": "Video 0"},
        {"id": "vid_1", "title": "Video 1"},
        {"id": "vid_2", "title": "Video 2"},
    ])
    monkeypatch.setattr(fetch_transcripts_module, "get_channel_dir", lambda _channel_id: tmp_path)

    def fake_fetch_single(vid, *_args, **_kwargs):
        calls.append(vid)
        return {
            "video_id": vid,
            "status": "failed",
            "error": "YouTube is blocking requests from your IP",
            "rate_limited": True,
        }

    monkeypatch.setattr(fetch_transcripts_module, "fetch_single_transcript", fake_fetch_single)

    result = fetch_transcripts_module.fetch_transcripts(channel_id, on_progress=progress.append)

    assert calls == ["vid_0"]
    assert result["total"] == 3
    assert [item["video_id"] for item in result["results"]] == ["vid_0", "vid_1", "vid_2"]
    assert all(item["status"] == "failed" for item in result["results"])
    assert all(item["rate_limited"] is True for item in result["results"])
    assert [item["video_id"] for item in progress] == ["vid_0", "vid_1", "vid_2"]
