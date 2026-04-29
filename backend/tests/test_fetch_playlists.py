"""Unit tests for playlist fetch functions."""

import json
from unittest.mock import patch

from backend.pipeline.fetch_videos import fetch_channel_playlists, fetch_playlist_video_ids


def _mock_stdout(lines: list[dict]) -> str:
    return "\n".join(json.dumps(v) for v in lines)


def test_fetch_channel_playlists_basic():
    """Parse playlists from yt-dlp output with playlist_count."""
    mock = _mock_stdout([
        {"id": "PL1", "title": "My Playlist", "playlist_count": 15, "thumbnails": [{"url": "https://example.com/thumb.jpg"}]},
        {"id": "PL2", "title": "Another", "playlist_count": 3, "thumbnails": []},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert len(result) == 2
    assert result[0]["id"] == "PL1"
    assert result[0]["title"] == "My Playlist"
    assert result[0]["video_count"] == 15
    assert result[0]["thumbnail"] == "https://example.com/thumb.jpg"
    assert result[1]["id"] == "PL2"
    assert result[1]["thumbnail"] is None


def test_fetch_channel_playlists_fallback_video_count():
    """Fall back to video_count when playlist_count is absent."""
    mock = _mock_stdout([
        {"id": "PL1", "title": "Test", "video_count": 7},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert result[0]["video_count"] == 7


def test_fetch_channel_playlists_fallback_n_entries():
    """Fall back to n_entries when both playlist_count and video_count are absent."""
    mock = _mock_stdout([
        {"id": "PL1", "title": "Test", "n_entries": 4},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert result[0]["video_count"] == 4


def test_fetch_channel_playlists_default_zero():
    """Default to 0 when no count field is present."""
    mock = _mock_stdout([
        {"id": "PL1", "title": "Test"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert result[0]["video_count"] == 0


def test_fetch_channel_playlists_skip_missing_id():
    """Skip entries without an id."""
    mock = _mock_stdout([
        {"title": "No ID"},
        {"id": "PL1", "title": "Valid", "playlist_count": 5},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert len(result) == 1
    assert result[0]["id"] == "PL1"


def test_fetch_channel_playlists_empty():
    """Empty output yields empty list."""
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=""):
        result = fetch_channel_playlists("https://www.youtube.com/@test")
    assert result == []


def test_fetch_playlist_video_ids():
    """Parse video IDs from --print output."""
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value="v1\nv2\nv3\n"):
        result = fetch_playlist_video_ids("PL1")
    assert result == ["v1", "v2", "v3"]


def test_fetch_playlist_video_ids_empty():
    """Empty playlist returns empty list."""
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=""):
        result = fetch_playlist_video_ids("PL_empty")
    assert result == []
