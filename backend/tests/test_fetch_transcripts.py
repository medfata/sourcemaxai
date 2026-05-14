"""Tests for transcript fetching behavior."""

from backend.pipeline import fetch_transcripts as fetch_transcripts_module


def test_fetch_transcripts_uses_parallel_worker_pattern(monkeypatch, tmp_path):
    channel_id = "UC_transcript_block"
    calls: list[str] = []
    progress: list[dict] = []

    monkeypatch.setattr(fetch_transcripts_module, "WORKERS", 8)
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
        return {"video_id": vid, "status": "done"}

    monkeypatch.setattr(fetch_transcripts_module, "fetch_single_transcript", fake_fetch_single)

    result = fetch_transcripts_module.fetch_transcripts(channel_id, on_progress=progress.append)

    assert set(calls) == {"vid_0", "vid_1", "vid_2"}
    assert result["total"] == 3
    assert {item["video_id"] for item in result["results"]} == {"vid_0", "vid_1", "vid_2"}
    assert all(item["status"] == "done" for item in result["results"])
    assert {item["video_id"] for item in progress} == {"vid_0", "vid_1", "vid_2"}
