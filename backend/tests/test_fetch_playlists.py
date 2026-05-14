"""Unit tests for playlist fetch functions."""

import json
from unittest.mock import patch

from backend.pipeline.fetch_videos import fetch_channel_playlists, fetch_playlist_video_ids


def _mock_stdout(lines: list[dict]) -> str:
    return "\n".join(json.dumps(v) for v in lines)


def test_fetch_channel_playlists_resolves_per_playlist_count():
    """playlist_count on the /playlists listing is unreliable. fetch_channel_playlists
    must resolve each playlist's video_count with a dedicated yt-dlp call."""
    mock_listing = _mock_stdout([
        {"id": "PL1", "title": "My Playlist", "playlist_count": 99, "thumbnails": [{"url": "https://example.com/thumb.jpg"}]},
        {"id": "PL2", "title": "Another", "thumbnails": []},
    ])
    counts = {"PL1": 15, "PL2": 3}
    with patch(
        "backend.pipeline.fetch_videos._run_ytdlp", return_value=mock_listing
    ), patch(
        "backend.pipeline.fetch_videos.fetch_playlist_count",
        side_effect=lambda plid: counts[plid],
    ):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    by_id = {row["id"]: row for row in result}
    assert by_id["PL1"]["title"] == "My Playlist"
    assert by_id["PL1"]["video_count"] == 15
    assert by_id["PL1"]["thumbnail"] == "https://example.com/thumb.jpg"
    assert by_id["PL2"]["video_count"] == 3
    assert by_id["PL2"]["thumbnail"] is None


def test_fetch_channel_playlists_defaults_to_zero_on_count_error():
    """If per-playlist count resolution raises, default to 0 rather than crashing."""
    mock_listing = _mock_stdout([{"id": "PL1", "title": "Test"}])
    with patch(
        "backend.pipeline.fetch_videos._run_ytdlp", return_value=mock_listing
    ), patch(
        "backend.pipeline.fetch_videos.fetch_playlist_count",
        side_effect=RuntimeError("boom"),
    ):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert result[0]["video_count"] == 0


def test_fetch_channel_playlists_skip_missing_id():
    mock = _mock_stdout([
        {"title": "No ID"},
        {"id": "PL1", "title": "Valid"},
    ])
    with patch(
        "backend.pipeline.fetch_videos._run_ytdlp", return_value=mock
    ), patch(
        "backend.pipeline.fetch_videos.fetch_playlist_count",
        return_value=5,
    ):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert len(result) == 1
    assert result[0]["id"] == "PL1"


def test_fetch_channel_playlists_empty():
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=""):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert result == []


def test_fetch_playlist_video_ids():
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value="v1\nv2\nv3\n"):
        result = fetch_playlist_video_ids("PL1")
    assert result == ["v1", "v2", "v3"]


def test_fetch_playlist_video_ids_empty():
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=""):
        result = fetch_playlist_video_ids("PL_empty")
    assert result == []
